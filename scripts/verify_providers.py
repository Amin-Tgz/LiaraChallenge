"""Verify provider credentials and reachability without disclosing them.

Two OpenSpec tasks depend on this being runnable from anywhere:

* **1.1** — after the planning-era key is rotated, the *old* key must return 401.
  Pass it through an environment variable (never an argument, which would land
  in shell history and process listings) and check the reported status.
* **1.6** — the fallback provider must be reachable **from a deployed
  container**, not from a developer laptop. Egress rules differ between the two,
  so a local success proves nothing about production. Run this inside the
  container and record the base URL it reports.

Every code path here prints status codes, latencies, and booleans. It never
prints a key, and it never logs a request body containing one — see
`RULES.md` §4.

Usage::

    uv run python -m scripts.verify_providers                    # configured keys
    uv run python -m scripts.verify_providers --expect-unauthorized OLD_KEY_VAR
    uv run python -m scripts.verify_providers --json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from dataclasses import asdict, dataclass

import httpx

from src.core.config import Settings, get_settings
from src.services.embeddings import CUSTOM_HOST_HEADER, PROVIDER_HEADER, PROVIDER_PROTOCOL

#: A credential check must not be mistaken for a load test. One token out is
#: enough to prove the key is accepted and the model is routable.
_PROBE_MAX_TOKENS = 1
_PROBE_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """The disclosable outcome of one provider probe."""

    name: str
    #: Where the request was actually sent — the answer task 1.6 must record.
    endpoint: str
    #: The upstream the gateway was told to forward to, when routed.
    upstream: str | None
    model: str
    status_code: int | None
    ok: bool
    latency_ms: int
    #: Failure class only. Never a provider body, which can echo a key back.
    failure: str | None = None

    def render(self) -> str:
        mark = "PASS" if self.ok else "FAIL"
        status = self.status_code if self.status_code is not None else "-"
        line = (
            f"[{mark}] {self.name}: status={status} "
            f"model={self.model} latency={self.latency_ms}ms"
        )
        if self.upstream:
            line += f"\n       via {self.endpoint} -> {self.upstream}"
        else:
            line += f"\n       via {self.endpoint}"
        if self.failure:
            line += f"\n       failure: {self.failure}"
        return line


def _headers(api_key: str, upstream: str | None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if upstream:
        headers[PROVIDER_HEADER] = PROVIDER_PROTOCOL
        headers[CUSTOM_HOST_HEADER] = upstream.rstrip("/")
    return headers


async def _probe(
    client: httpx.AsyncClient,
    *,
    name: str,
    endpoint: str,
    upstream: str | None,
    api_key: str,
    model: str,
    expected_status: int | None,
) -> ProbeResult:
    """Send one minimal completion and report only what is safe to disclose.

    `expected_status` inverts the verdict: task 1.1 wants a 401 to count as a
    pass, because a rotated key that still authenticates is the failure.
    """
    # The gateway is addressed at its root and owns the `/v1` prefix; a provider
    # base URL already carries its own. Appending blindly yields `/v1/v1/...`,
    # which providers answer with a 404 that looks deceptively like a bad model.
    base = endpoint.rstrip("/")
    suffix = "/chat/completions" if base.endswith("/v1") else "/v1/chat/completions"
    url = f"{base}{suffix}"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": _PROBE_MAX_TOKENS,
    }
    started = time.perf_counter()
    try:
        response = await client.post(url, headers=_headers(api_key, upstream), json=payload)
    except httpx.TimeoutException:
        elapsed = int((time.perf_counter() - started) * 1000)
        return ProbeResult(
            name=name,
            endpoint=url,
            upstream=upstream,
            model=model,
            status_code=None,
            ok=False,
            latency_ms=elapsed,
            failure="timeout",
        )
    except httpx.HTTPError as err:
        elapsed = int((time.perf_counter() - started) * 1000)
        return ProbeResult(
            name=name,
            endpoint=url,
            upstream=upstream,
            model=model,
            status_code=None,
            ok=False,
            latency_ms=elapsed,
            failure=f"transport_error:{type(err).__name__}",
        )

    elapsed = int((time.perf_counter() - started) * 1000)
    if expected_status is not None:
        ok = response.status_code == expected_status
        failure = None if ok else f"expected_status_{expected_status}"
    else:
        ok = response.status_code < 400
        failure = None if ok else f"http_{response.status_code}"
    return ProbeResult(
        name=name,
        endpoint=url,
        upstream=upstream,
        model=model,
        status_code=response.status_code,
        ok=ok,
        latency_ms=elapsed,
        failure=failure,
    )


async def run_probes(
    settings: Settings,
    *,
    old_key_var: str | None,
    skip_gateway: bool,
) -> list[ProbeResult]:
    results: list[ProbeResult] = []
    async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_SECONDS) as client:
        # Direct, gateway bypassed: separates "the provider rejects us" from
        # "the gateway container is down", which are different incidents.
        results.append(
            await _probe(
                client,
                name="primary-direct",
                endpoint=settings.llm_base_url,
                upstream=None,
                api_key=settings.llm_api_key,
                model=settings.llm_model,
                expected_status=None,
            )
        )

        if not skip_gateway:
            results.append(
                await _probe(
                    client,
                    name="primary-via-gateway",
                    endpoint=settings.portkey_base_url,
                    upstream=settings.llm_base_url,
                    api_key=settings.llm_api_key,
                    model=settings.llm_model,
                    expected_status=None,
                )
            )

        # Task 1.6. Absent configuration is reported as its own outcome rather
        # than silently skipped — an unconfigured fallback is a finding.
        fallback_configured = all(
            (
                settings.portkey_fallback_base_url,
                settings.portkey_fallback_api_key,
                settings.portkey_fallback_model,
            )
        )
        if fallback_configured:
            results.append(
                await _probe(
                    client,
                    name="fallback-direct",
                    endpoint=settings.portkey_fallback_base_url,
                    upstream=None,
                    api_key=settings.portkey_fallback_api_key,
                    model=settings.portkey_fallback_model,
                    expected_status=None,
                )
            )
            if not skip_gateway:
                results.append(
                    await _probe(
                        client,
                        name="fallback-via-gateway",
                        endpoint=settings.portkey_base_url,
                        upstream=settings.portkey_fallback_base_url,
                        api_key=settings.portkey_fallback_api_key,
                        model=settings.portkey_fallback_model,
                        expected_status=None,
                    )
                )
        else:
            results.append(
                ProbeResult(
                    name="fallback-direct",
                    endpoint="(unconfigured)",
                    upstream=None,
                    model="(unconfigured)",
                    status_code=None,
                    ok=False,
                    latency_ms=0,
                    failure="fallback_provider_not_configured",
                )
            )

        if old_key_var:
            old_key = os.environ.get(old_key_var, "")
            if not old_key:
                results.append(
                    ProbeResult(
                        name="rotated-key-rejected",
                        endpoint="(not attempted)",
                        upstream=None,
                        model=settings.llm_model,
                        status_code=None,
                        ok=False,
                        latency_ms=0,
                        failure=f"env_var_{old_key_var}_is_empty",
                    )
                )
            else:
                results.append(
                    await _probe(
                        client,
                        name="rotated-key-rejected",
                        endpoint=settings.llm_base_url,
                        upstream=None,
                        api_key=old_key,
                        model=settings.llm_model,
                        expected_status=401,
                    )
                )
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--expect-unauthorized",
        metavar="ENV_VAR",
        default=None,
        help=(
            "Name of an environment variable holding the OLD, rotated key. "
            "Passes only if the provider answers 401 (OpenSpec task 1.1)."
        ),
    )
    parser.add_argument(
        "--skip-gateway",
        action="store_true",
        help="Probe providers directly only, when no gateway container is reachable.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable results.")
    args = parser.parse_args(argv)

    settings = get_settings()
    results = asyncio.run(
        run_probes(
            settings,
            old_key_var=args.expect_unauthorized,
            skip_gateway=args.skip_gateway,
        )
    )

    if args.json:
        print(json.dumps([asdict(result) for result in results], indent=2))
    else:
        for result in results:
            print(result.render())

    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
