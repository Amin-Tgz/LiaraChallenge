"""Typed application configuration.

Every threshold, top-k, model id, budget, and timeout in the system is read from
here. Nothing that appears in `.env.example` may be hardcoded elsewhere.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Runtime ---
    app_env: str = "local"
    log_level: str = "INFO"
    web_dist_dir: str = "web/dist"
    skill_file_path: str = ".agents/skills/liara-docs-rescue/SKILL.md"

    # --- Chat LLM ---
    llm_base_url: str = "https://api.avalai.ir/v1"
    llm_api_key: str = ""
    llm_model: str = "gemini-3.7-flash"

    # --- Bulk FAQ generation ---
    faq_llm_model: str = "gemini-3.7-flash"
    faq_reasoning_effort: str = "low"
    faq_items_per_document: int = 15
    faq_max_output_tokens: int = 12288
    faq_generation_timeout_seconds: float = 120.0
    faq_generation_concurrency: int = 20

    # --- Embeddings ---
    embedding_base_url: str = "https://api.avalai.ir/v1"
    embedding_api_key: str = ""
    embedding_model: str = "text-embedding-3-large"
    embedding_dimensions: int = 1536

    # --- Gateway ---
    portkey_base_url: str = "http://portkey:8787"
    portkey_fallback_base_url: str = ""
    portkey_fallback_api_key: str = ""
    portkey_fallback_model: str = ""

    # --- Evaluation ---
    eval_judge_model: str = ""

    # --- Infrastructure ---
    database_url: str = "postgresql+asyncpg://rescue:rescue@localhost:5432/rescue"
    redis_url: str = "redis://localhost:6379/0"

    # --- Ingestion scope ---
    docs_repo_url: str = "https://github.com/liara-cloud/docs"
    docs_repo_branch: str = "master"
    ingest_sections: str = "*"
    ingest_exclude_globs: str = ""
    chunk_target_tokens: int = 700
    chunk_overlap_tokens: int = 80
    chunk_min_tokens: int = 120
    chunk_max_tokens: int = 1200
    ingest_discard_ratio_threshold: float = 0.35
    #: Where the docs checkout is kept between runs, so an unchanged upstream
    #: costs a fetch rather than a clone.
    docs_cache_dir: str = ".cache/docs"
    #: Public site the citations point at. Not the repository URL.
    docs_base_url: str = "https://docs.liara.ir"
    #: Inputs per embedding request. The model accepts 8191 tokens per input, so
    #: this is not a context limit — it is how much work a single retry has to
    #: repeat. The route to the provider has been observed to drop mid-run, and
    #: a smaller batch loses less to each interruption.
    embedding_batch_size: int = 16
    #: Per-request ceiling for an embedding call. Generous on purpose: a request
    #: that is merely slow must not be retried as though it had failed.
    embedding_timeout_seconds: float = 120.0
    #: How many superseded index versions survive an activation. At least one,
    #: or rollback has nothing to roll back to.
    index_retention_count: int = 2

    # --- Retrieval ---
    faq_similarity_threshold: float = 0.4
    faq_short_query_max_chars: int = 8
    faq_short_query_similarity_threshold: float = 0.6
    faq_top_k: int = 5
    faq_candidate_multiplier: int = 4
    faq_priority_weight: float = 0.01
    retrieval_top_k: int = 8
    retrieval_candidate_multiplier: int = 3
    retrieval_duplicate_threshold: float = 0.9
    retrieval_similarity_threshold: float = 0.25
    rrf_k: int = 60
    rrf_dense_weight: float = 1.0
    rrf_lexical_weight: float = 1.0
    retrieval_metadata_boost_weight: float = 0.15
    index_stale_after_days: int = 14

    # --- Agent bounds ---
    agent_max_tool_calls: int = 3
    agent_max_rewrites: int = 2
    #: Must be able to hold one full retrieval round plus the answer. With
    #: RETRIEVAL_TOP_K=8 and chunks bounded at CHUNK_MAX_TOKENS=1200, evidence
    #: alone can reach ~9.6k tokens, so the previous 8000 made every
    #: well-retrieved question terminate as AGENT_LIMIT_REACHED before it could
    #: answer. The model's context is 1M; this bound exists to cap cost and
    #: runaway loops, not to fit the window.
    agent_token_budget: int = 32000
    agent_timeout_seconds: float = 60.0
    max_question_chars: int = 2000
    max_history_turns: int = 3
    max_conversation_turns: int = 3

    # --- Queue, streaming, durability ---
    #: How many times a job may be attempted before it reaches the terminal
    #: failed state. Bounded in code so exhausted retries stop rather than loop.
    job_max_attempts: int = 3
    #: How long the worker blocks waiting for a job before re-checking its stop
    #: flag. Bounds shutdown latency, nothing else.
    job_queue_block_seconds: float = 2.0
    #: Lease held by the worker processing a job, refreshed while it works. If
    #: the worker dies the lease expires and the job is reclaimed, so a killed
    #: worker loses no question.
    job_lease_seconds: float = 90.0
    #: How long a completed job's relay stream is retained for reconnecting
    #: clients. Long enough to survive a reload, short enough to bound memory.
    job_stream_ttl_seconds: int = 3600
    #: Size of each chunk pushed onto the relay stream. Delivery granularity
    #: only; it has no effect on what the model produces.
    job_stream_chunk_chars: int = 24
    #: Idle interval between SSE keepalive comments, so proxies do not close a
    #: quiet connection mid-generation.
    sse_keepalive_seconds: float = 15.0
    #: Lifetime of the anonymous session cookie that links a browser to its
    #: prior conversations.
    session_cookie_max_age_seconds: int = 60 * 60 * 24 * 30
    session_cookie_name: str = "rescue_session"

    # --- Rate limiting ---
    rate_limit_per_ip_per_minute: int = 30
    rate_limit_per_session_per_minute: int = 15

    # --- Admin ---
    admin_username: str = ""
    admin_password: str = ""

    # --- Observability ---
    opik_api_key: str = ""
    opik_workspace: str = ""
    metrics_enabled: bool = True
    metrics_path: str = "/metrics"
    metrics_service_name: str = "liara-rescue-api"
    otel_logs_enabled: bool = False
    otel_exporter_otlp_logs_endpoint: str = ""
    otel_service_name: str = "liara-rescue-api"

    # --- Liara operator helpers ---
    # External connection URLs, used only by CLI verification and by migrations
    # targeting the managed database from a laptop. The deployed containers
    # reach the same services over the private network via DATABASE_URL and
    # REDIS_URL, so nothing at runtime reads these.
    liara_database_url: str = ""
    liara_redis_url: str = ""
    #: Every `liara` CLI call against this project must carry the team id, or
    #: it resolves against the personal account and 404s as if the app did not
    #: exist. See docs/deployment.md §4.
    liara_team_id: str = ""

    @field_validator("database_url", "liara_database_url")
    @classmethod
    def _async_postgres_driver(cls, v: str, info: ValidationInfo) -> str:
        # Liara's panel emits `postgresql://…`, but `create_async_engine` refuses
        # any scheme without an async driver — so a verbatim paste takes the API
        # and the worker down at boot. Normalize the paste; reject a driver the
        # operator chose deliberately, since rewriting that would hide intent.
        name = (info.field_name or "database_url").upper()
        # Only the operator helper is optional — an unset LIARA_DATABASE_URL
        # simply means migrations are not being pointed at the managed database.
        if not v and info.field_name == "liara_database_url":
            return v
        scheme, separator, remainder = v.partition("://")
        if not separator:
            raise ValueError(f"{name} must be a URL of the form <scheme>://<host>/<database>")
        if scheme in {"postgres", "postgresql"}:
            return f"postgresql+asyncpg://{remainder}"
        if scheme == "postgresql+asyncpg":
            return v
        raise ValueError(
            f"{name} scheme {scheme!r} is not supported; "
            "use postgresql+asyncpg (or plain postgresql, which is normalized)"
        )

    @field_validator("embedding_dimensions")
    @classmethod
    def _hnsw_indexable(cls, v: int) -> int:
        # pgvector caps HNSW indexes at 2000 dimensions; anything above is
        # unindexable and every query degrades to a sequential scan.
        if not 0 < v <= 2000:
            raise ValueError("EMBEDDING_DIMENSIONS must be in (0, 2000] to stay HNSW-indexable")
        return v

    @field_validator("rrf_k")
    @classmethod
    def _positive_rrf_k(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("RRF_K must be positive")
        return v

    @field_validator("faq_generation_concurrency")
    @classmethod
    def _positive_faq_concurrency(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("FAQ_GENERATION_CONCURRENCY must be positive")
        return v

    @field_validator(
        "faq_items_per_document",
        "faq_max_output_tokens",
        "faq_candidate_multiplier",
        "retrieval_candidate_multiplier",
        "max_conversation_turns",
    )
    @classmethod
    def _positive_configured_count(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("configured counts and generation budgets must be positive")
        return v

    @field_validator("faq_short_query_max_chars", "max_history_turns")
    @classmethod
    def _non_negative_history_or_short_query_bound(cls, v: int) -> int:
        if v < 0:
            raise ValueError("short-query and history bounds must be non-negative")
        return v

    @field_validator("metrics_path")
    @classmethod
    def _absolute_metrics_path(cls, v: str) -> str:
        if not v.startswith("/") or v == "/":
            raise ValueError("METRICS_PATH must be an absolute non-root path")
        return v

    @field_validator("agent_max_tool_calls", "agent_max_rewrites")
    @classmethod
    def _non_negative_agent_count(cls, v: int) -> int:
        if v < 0:
            raise ValueError("agent call and rewrite limits must be non-negative")
        return v

    @field_validator("job_max_attempts")
    @classmethod
    def _at_least_one_attempt(cls, v: int) -> int:
        if v < 1:
            raise ValueError("JOB_MAX_ATTEMPTS must allow at least one attempt")
        return v

    @field_validator(
        "job_queue_block_seconds",
        "job_lease_seconds",
        "sse_keepalive_seconds",
    )
    @classmethod
    def _positive_interval(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("queue, lease, and keepalive intervals must be positive")
        return v

    @field_validator("job_stream_ttl_seconds", "job_stream_chunk_chars")
    @classmethod
    def _positive_stream_bound(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("stream retention and chunk size must be positive")
        return v

    @field_validator("agent_token_budget", "agent_timeout_seconds")
    @classmethod
    def _positive_agent_budget(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("agent token budget and timeout must be positive")
        return v

    @field_validator(
        "rrf_dense_weight",
        "rrf_lexical_weight",
        "retrieval_metadata_boost_weight",
        "faq_priority_weight",
    )
    @classmethod
    def _non_negative_rrf_weight(cls, v: float) -> float:
        if v < 0:
            raise ValueError("ranking weights must be non-negative")
        return v

    @field_validator(
        "faq_similarity_threshold",
        "faq_short_query_similarity_threshold",
        "retrieval_similarity_threshold",
        "retrieval_duplicate_threshold",
    )
    @classmethod
    def _cosine_similarity_range(cls, v: float) -> float:
        if not -1.0 <= v <= 1.0:
            raise ValueError("cosine similarity thresholds must be in [-1, 1]")
        return v

    @property
    def ingest_section_list(self) -> list[str]:
        raw = self.ingest_sections.strip()
        if not raw or raw == "*":
            return []
        return [s.strip() for s in raw.split(",") if s.strip()]

    @property
    def ingest_exclude_glob_list(self) -> list[str]:
        raw = self.ingest_exclude_globs.strip()
        if not raw:
            return []
        return [s.strip() for s in raw.split(",") if s.strip()]

    def assert_judge_differs_from_model_under_test(self) -> None:
        """A model scoring its own output inflates every metric that matters."""
        if not self.eval_judge_model:
            raise ValueError("EVAL_JUDGE_MODEL is not configured")
        if self.eval_judge_model == self.llm_model:
            raise ValueError(
                "EVAL_JUDGE_MODEL must differ from LLM_MODEL — self-preference bias "
                "silently inflates judge scores"
            )


# Field names whose values must never reach a log record.
SECRET_FIELDS: frozenset[str] = frozenset(
    {
        "llm_api_key",
        "embedding_api_key",
        "portkey_fallback_api_key",
        "database_url",
        "redis_url",
        "admin_password",
        "opik_api_key",
    }
)


@lru_cache
def get_settings() -> Settings:
    return Settings()
