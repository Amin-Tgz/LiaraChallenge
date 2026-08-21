"""Configuration invariants that would otherwise fail silently in production."""

from __future__ import annotations

import pytest

from src.core.config import Settings


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def test_embedding_dimensions_must_stay_hnsw_indexable() -> None:
    # pgvector caps HNSW at 2000 dims; the model's native 3072 would silently
    # degrade every query to a sequential scan.
    with pytest.raises(ValueError, match="HNSW-indexable"):
        _settings(embedding_dimensions=3072)


def test_default_embedding_dimensions_is_1536() -> None:
    assert _settings().embedding_dimensions == 1536


def test_faq_generation_concurrency_must_be_positive() -> None:
    with pytest.raises(ValueError, match="FAQ_GENERATION_CONCURRENCY must be positive"):
        _settings(faq_generation_concurrency=0)


@pytest.mark.parametrize("path", ["metrics", "/"])
def test_metrics_path_must_be_a_non_root_absolute_path(path: str) -> None:
    with pytest.raises(ValueError, match="METRICS_PATH"):
        _settings(metrics_path=path)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"agent_max_tool_calls": -1}, "must be non-negative"),
        ({"agent_max_rewrites": -1}, "must be non-negative"),
        ({"agent_token_budget": 0}, "must be positive"),
        ({"agent_timeout_seconds": 0}, "must be positive"),
    ],
)
def test_agent_bounds_reject_invalid_values(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _settings(**overrides)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"rrf_k": 0}, "RRF_K must be positive"),
        ({"rrf_dense_weight": -1}, "ranking weights must be non-negative"),
        ({"rrf_lexical_weight": -1}, "ranking weights must be non-negative"),
        ({"retrieval_metadata_boost_weight": -0.1}, "ranking weights must be non-negative"),
        ({"faq_priority_weight": -0.1}, "ranking weights must be non-negative"),
        ({"retrieval_similarity_threshold": 1.1}, "cosine similarity thresholds"),
        ({"faq_similarity_threshold": -1.1}, "cosine similarity thresholds"),
    ],
)
def test_rrf_configuration_rejects_invalid_values(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _settings(**overrides)


def test_judge_must_differ_from_the_model_under_test() -> None:
    settings = _settings(llm_model="gemini-3.7-flash", eval_judge_model="gemini-3.7-flash")
    with pytest.raises(ValueError, match="must differ"):
        settings.assert_judge_differs_from_model_under_test()


def test_judge_must_be_configured() -> None:
    with pytest.raises(ValueError, match="not configured"):
        _settings(eval_judge_model="").assert_judge_differs_from_model_under_test()


def test_distinct_judge_is_accepted() -> None:
    settings = _settings(llm_model="gemini-3.7-flash", eval_judge_model="gpt-5.6-luna")
    settings.assert_judge_differs_from_model_under_test()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("*", []), ("", []), ("paas,dbaas", ["paas", "dbaas"]), (" paas , iaas ", ["paas", "iaas"])],
)
def test_ingest_scope_is_configuration_not_code(raw: str, expected: list[str]) -> None:
    assert _settings(ingest_sections=raw).ingest_section_list == expected


# --- DATABASE_URL driver scheme -------------------------------------------
#
# Liara's panel hands out `postgresql://…`. SQLAlchemy's `create_async_engine`
# rejects that scheme outright, so an operator pasting the panel value verbatim
# takes both the API and the worker down at boot. Normalize instead of relying
# on every human remembering to type `+asyncpg`.


def test_bare_postgresql_scheme_is_normalized_to_asyncpg() -> None:
    settings = _settings(database_url="postgresql://root:pw@liaradb:5432/postgres")
    assert settings.database_url == "postgresql+asyncpg://root:pw@liaradb:5432/postgres"


def test_postgres_alias_scheme_is_normalized_to_asyncpg() -> None:
    settings = _settings(database_url="postgres://root:pw@liaradb:5432/postgres")
    assert settings.database_url == "postgresql+asyncpg://root:pw@liaradb:5432/postgres"


def test_explicit_asyncpg_scheme_is_left_alone() -> None:
    url = "postgresql+asyncpg://rescue:rescue@postgres:5432/rescue"
    assert _settings(database_url=url).database_url == url


def test_a_non_async_driver_is_rejected_rather_than_silently_rewritten() -> None:
    # psycopg2 is a deliberate choice, not a paste artifact; rewriting it would
    # hide the operator's intent. Fail loudly instead.
    with pytest.raises(ValueError, match="DATABASE_URL"):
        _settings(database_url="postgresql+psycopg2://root:pw@liaradb:5432/postgres")


def test_a_non_postgres_url_is_rejected() -> None:
    with pytest.raises(ValueError, match="DATABASE_URL"):
        _settings(database_url="mysql://root:pw@liaradb:3306/postgres")


# --- LIARA_DATABASE_URL ----------------------------------------------------
#
# The operator helper carries the *external* connection URL, used only by
# `alembic -x target=liara` and by CLI verification. It shares the normalizer
# with DATABASE_URL — a panel paste is a panel paste either way — but unlike
# DATABASE_URL it is optional, because not every checkout migrates production.


def test_liara_database_url_is_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    # `_env_file=None` skips the dotenv file but not the process environment,
    # and the containers set LIARA_DATABASE_URL for real. Clearing it is what
    # makes this a test of the default rather than of the machine it runs on.
    monkeypatch.delenv("LIARA_DATABASE_URL", raising=False)
    assert _settings().liara_database_url == ""


def test_liara_database_url_is_normalized_to_asyncpg() -> None:
    settings = _settings(liara_database_url="postgresql://root:pw@liaradb:5432/postgres")
    assert settings.liara_database_url == "postgresql+asyncpg://root:pw@liaradb:5432/postgres"


def test_liara_database_url_rejects_a_non_postgres_url_naming_its_own_field() -> None:
    # The message must name LIARA_DATABASE_URL, not DATABASE_URL; pointing an
    # operator at the wrong variable during a deploy is its own outage.
    with pytest.raises(ValueError, match="LIARA_DATABASE_URL"):
        _settings(liara_database_url="mysql://root:pw@liaradb:3306/postgres")


def test_summary_trigger_must_stay_below_the_hard_ceiling() -> None:
    # A ceiling at or below the trigger means summarization can never run and
    # the conversation is cut off exactly as it was before this feature existed.
    with pytest.raises(ValueError, match="below MAX_CONVERSATION_TURNS"):
        _settings(max_conversation_turns=3, conversation_summary_trigger_turns=3)


def test_summary_trigger_below_the_ceiling_is_accepted() -> None:
    settings = _settings(max_conversation_turns=40, conversation_summary_trigger_turns=3)
    assert settings.conversation_summary_trigger_turns == 3
    assert settings.max_conversation_turns == 40


def test_conversation_ceiling_is_an_abuse_bound_not_a_three_turn_product_rule() -> None:
    # Guards the regression this change exists to prevent: a default of 3 here
    # is the old cut-off, not a ceiling.
    assert _settings().max_conversation_turns > _settings().conversation_summary_trigger_turns


def test_summary_budget_and_timeout_must_be_positive() -> None:
    with pytest.raises(ValueError, match="CONVERSATION_SUMMARY_MAX_TOKENS"):
        _settings(conversation_summary_max_tokens=0)
    with pytest.raises(ValueError, match="CONVERSATION_SUMMARY_TIMEOUT_SECONDS"):
        _settings(conversation_summary_timeout_seconds=0)


def test_summary_model_falls_back_to_the_chat_model() -> None:
    assert _settings(llm_model="chat-model").summary_model == "chat-model"
    assert (
        _settings(llm_model="chat-model", conversation_summary_model="cheap").summary_model
        == "cheap"
    )


def test_similarity_thresholds_carry_the_relaxed_defaults() -> None:
    # Lowered 15% from 0.4/0.6/0.25 so questions phrased in a user's own words
    # stop falling just under the bar.
    settings = _settings()
    assert settings.faq_similarity_threshold == pytest.approx(0.34)
    assert settings.faq_short_query_similarity_threshold == pytest.approx(0.51)
    assert settings.retrieval_similarity_threshold == pytest.approx(0.2125)
    # The short-query bar stays strictly higher: two words match almost anything.
    assert settings.faq_short_query_similarity_threshold > settings.faq_similarity_threshold
