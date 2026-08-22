"""Embedding generation, routed through the gateway.

Two invariants this module exists to hold:

* **Dimension.** pgvector's HNSW index caps at 2,000 dimensions, so the vectors
  must come back at the configured width. A provider that quietly returns the
  model's native 3,072 would produce an index that cannot be built and a column
  that rejects every insert — better to fail here, naming the cause.
* **Order.** Batching is an optimization, not a semantic change. Vectors are
  reordered by the index the provider reports, never assumed to arrive in the
  order they were sent.

Requests go to the gateway rather than to the provider directly: retries,
backoff, and provider fallback are its job, and pointing this module straight at
a provider would quietly lose all three.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import httpx

from src.core.config import Settings, get_settings
from src.core.errors import ErrorCode, RescueError
from src.core.logging import get_logger
from src.core.tracing import opik_span

logger = get_logger(__name__)

#: Verified against the gateway container: an OpenAI-compatible provider is
#: addressed by naming `openai` as the protocol and the real base URL as the
#: custom host. Matching on the protocol rather than the vendor is what lets the
#: fallback provider be a different company entirely.
PROVIDER_HEADER = "x-portkey-provider"
CUSTOM_HOST_HEADER = "x-portkey-custom-host"
PROVIDER_PROTOCOL = "openai"

#: Retried: the request may succeed unchanged. Anything else — a malformed
#: request, a bad key — will fail identically every time, and retrying it only
#: delays the error.
_RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
_MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = (1.0, 3.0)


@dataclass(frozen=True, slots=True)
class EmbeddingBatch:
    """Vectors for one request, with the usage that makes cost attributable."""

    vectors: list[list[float]]
    model: str
    prompt_tokens: int
    total_tokens: int


def _batched(values: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


def _retry_after_seconds(response: httpx.Response, attempt: int) -> float:
    """Honor a server-supplied delay over our own backoff."""
    header = response.headers.get("retry-after")
    if header:
        try:
            return min(float(header), 30.0)
        except ValueError:
            pass
    return _BACKOFF_SECONDS[min(attempt, len(_BACKOFF_SECONDS) - 1)]


class EmbeddingClient:
    """Generates embeddings at the configured dimensionality via the gateway."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client or httpx.Client(timeout=self._settings.embedding_timeout_seconds)
        self._owns_client = client is None

    def __enter__(self) -> EmbeddingClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    @property
    def dimensions(self) -> int:
        return self._settings.embedding_dimensions

    @property
    def model(self) -> str:
        return self._settings.embedding_model

    def _headers(self) -> dict[str, str]:
        settings = self._settings
        return {
            "Authorization": f"Bearer {settings.embedding_api_key}",
            "Content-Type": "application/json",
            PROVIDER_HEADER: PROVIDER_PROTOCOL,
            CUSTOM_HOST_HEADER: settings.embedding_base_url.rstrip("/"),
        }

    def _post(self, payload: dict[str, object]) -> httpx.Response:
        url = f"{self._settings.portkey_base_url.rstrip('/')}/v1/embeddings"
        last_status: int | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                response = self._client.post(url, headers=self._headers(), json=payload)
            except httpx.TimeoutException as err:
                if attempt == _MAX_ATTEMPTS - 1:
                    raise RescueError(
                        ErrorCode.UPSTREAM_TIMEOUT,
                        detail=f"embedding request timed out after {_MAX_ATTEMPTS} attempts",
                    ) from err
                time.sleep(_BACKOFF_SECONDS[min(attempt, len(_BACKOFF_SECONDS) - 1)])
                continue
            except httpx.HTTPError as err:
                raise RescueError(
                    ErrorCode.ALL_PROVIDERS_UNAVAILABLE,
                    detail=f"gateway unreachable at {url}: {err}",
                ) from err

            if response.status_code < 400:
                return response

            last_status = response.status_code
            if response.status_code in {401, 403}:
                # Never retried, and never echoed: the body of an auth failure
                # can contain the key that was rejected.
                raise RescueError(
                    ErrorCode.UNAUTHORIZED,
                    detail=f"provider rejected the embedding credential ({last_status})",
                )
            if response.status_code not in _RETRYABLE_STATUS:
                raise RescueError(
                    ErrorCode.EMBEDDING_FAILED,
                    detail=f"provider returned {last_status}: {response.text[:300]}",
                )
            if attempt < _MAX_ATTEMPTS - 1:
                time.sleep(_retry_after_seconds(response, attempt))

        raise RescueError(
            ErrorCode.EMBEDDING_FAILED,
            detail=f"provider returned {last_status} on every one of {_MAX_ATTEMPTS} attempts",
        )

    def embed_batch(self, texts: Sequence[str]) -> EmbeddingBatch:
        """Embed one batch. Prefer `embed` unless you are managing batching."""
        if not texts:
            raise RescueError(ErrorCode.INVALID_REQUEST, detail="embed_batch called with no inputs")

        with opik_span("embeddings.batch", kind="llm") as span:
            span.metadata(
                model=self.model,
                dimensions=self.dimensions,
                input_count=len(texts),
                input_chars=sum(len(text) for text in texts),
            )
            batch = self._embed_batch(texts)
            span.usage(
                model=batch.model,
                prompt_tokens=batch.prompt_tokens,
                total_tokens=batch.total_tokens,
            )
            return batch

    def _embed_batch(self, texts: Sequence[str]) -> EmbeddingBatch:
        response = self._post(
            {
                "model": self.model,
                "input": list(texts),
                # The whole reason 1536 is achievable: the model is natively
                # 3072 and honors this parameter. See docs/deployment.md §2.
                "dimensions": self.dimensions,
            }
        )
        try:
            body = response.json()
            rows = sorted(body["data"], key=lambda row: row["index"])
            vectors = [list(row["embedding"]) for row in rows]
        except (KeyError, TypeError, ValueError) as err:
            raise RescueError(
                ErrorCode.EMBEDDING_FAILED,
                detail=f"unreadable embedding response: {response.text[:300]}",
            ) from err

        if len(vectors) != len(texts):
            raise RescueError(
                ErrorCode.EMBEDDING_FAILED,
                detail=f"asked for {len(texts)} embeddings, received {len(vectors)}",
            )
        for vector in vectors:
            if len(vector) != self.dimensions:
                raise RescueError(
                    ErrorCode.EMBEDDING_FAILED,
                    detail=(
                        f"provider returned {len(vector)} dimensions, expected "
                        f"{self.dimensions}; a vector of this width cannot be stored "
                        "or HNSW-indexed"
                    ),
                )

        usage = body.get("usage") or {}
        return EmbeddingBatch(
            vectors=vectors,
            model=body.get("model") or self.model,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            total_tokens=int(usage.get("total_tokens") or 0),
        )

    def embed(self, texts: Sequence[str]) -> EmbeddingBatch:
        """Embed any number of texts, batched at the configured size.

        Returns vectors positionally aligned with `texts`.
        """
        if not texts:
            return EmbeddingBatch(vectors=[], model=self.model, prompt_tokens=0, total_tokens=0)

        vectors: list[list[float]] = []
        prompt_tokens = total_tokens = 0
        batch_count = 0
        for batch in _batched(texts, self._settings.embedding_batch_size):
            result = self.embed_batch(batch)
            vectors.extend(result.vectors)
            prompt_tokens += result.prompt_tokens
            total_tokens += result.total_tokens
            batch_count += 1

        logger.info(
            "embeddings generated",
            extra={
                "count": len(vectors),
                "batches": batch_count,
                "dimensions": self.dimensions,
                "model": self.model,
                "total_tokens": total_tokens,
            },
        )
        return EmbeddingBatch(
            vectors=vectors,
            model=self.model,
            prompt_tokens=prompt_tokens,
            total_tokens=total_tokens,
        )

    def embed_one(self, text: str) -> list[float]:
        return self.embed_batch([text]).vectors[0]
