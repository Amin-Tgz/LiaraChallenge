"""Typed application configuration.

Every threshold, top-k, model id, budget, and timeout in the system is read from
here. Nothing that appears in `.env.example` may be hardcoded elsewhere.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
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

    # --- Chat LLM ---
    llm_base_url: str = "https://api.avalai.ir/v1"
    llm_api_key: str = ""
    llm_model: str = "gemini-3.7-flash"

    # --- Bulk FAQ generation ---
    faq_llm_model: str = "gemini-3.7-flash"

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
    faq_top_k: int = 5
    retrieval_top_k: int = 8
    retrieval_similarity_threshold: float = 0.25
    rrf_k: int = 60
    rrf_dense_weight: float = 1.0
    rrf_lexical_weight: float = 1.0
    index_stale_after_days: int = 14

    # --- Agent bounds ---
    agent_max_tool_calls: int = 3
    agent_max_rewrites: int = 2
    agent_token_budget: int = 8000
    agent_timeout_seconds: int = 60
    max_question_chars: int = 2000
    max_history_turns: int = 20

    # --- Rate limiting ---
    rate_limit_per_ip_per_minute: int = 30
    rate_limit_per_session_per_minute: int = 15

    # --- Admin ---
    admin_username: str = ""
    admin_password: str = ""

    # --- Observability ---
    opik_api_key: str = ""
    opik_workspace: str = ""

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

    @field_validator("rrf_dense_weight", "rrf_lexical_weight")
    @classmethod
    def _non_negative_rrf_weight(cls, v: float) -> float:
        if v < 0:
            raise ValueError("RRF weights must be non-negative")
        return v

    @field_validator("faq_similarity_threshold", "retrieval_similarity_threshold")
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
