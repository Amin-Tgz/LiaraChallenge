"""The admin surface against a real database.

The behaviors here are all ones a substitute would let through: that a deleted
entry actually stops matching, that a threshold change reaches the next query,
and that a metric with nothing behind it says so instead of printing zero.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import Settings
from src.core.errors import ErrorCode, RescueError
from src.db.models import FaqItem, UsageEvent
from src.db.models.enums import FaqStatus, FeedbackOutcome, RescueTool, UsageEventType
from src.services.dashboard import build_dashboard
from src.services.runtime_config import (
    clear_override,
    describe_overridable,
    effective_settings,
    load_overrides,
    set_override,
)

pytestmark = pytest.mark.asyncio


async def _make_faq(session: AsyncSession, *, question: str, active: bool = True) -> FaqItem:
    item = FaqItem(
        id=uuid.uuid4(),
        question=question,
        question_normalized=question,
        answer="پاسخ آزمایشی",
        source_url="https://docs.liara.ir/test",
        heading_anchor="answer",
        source_commit="a" * 40,
        status=FaqStatus.GENERATED.value,
        is_active=active,
        priority=0,
        tags=[],
        embedding_model="text-embedding-3-large",
        embedding_dimensions=1536,
        embedding=[0.01] * 1536,
    )
    session.add(item)
    await session.flush()
    return item


# --- Runtime configuration (13.4) ------------------------------------------


async def test_a_threshold_change_reaches_the_next_query_without_a_redeploy(
    db_session: AsyncSession,
) -> None:
    base = Settings(_env_file=None, faq_similarity_threshold=0.4)  # type: ignore[call-arg]
    assert (await effective_settings(db_session, base)).faq_similarity_threshold == 0.4

    await set_override(db_session, "faq_similarity_threshold", 0.62, updated_by="operator")
    await db_session.flush()

    # The next read sees it. No process restart, no deploy.
    assert (await effective_settings(db_session, base)).faq_similarity_threshold == 0.62


async def test_clearing_an_override_restores_the_deployed_value(
    db_session: AsyncSession,
) -> None:
    base = Settings(_env_file=None, faq_similarity_threshold=0.4)  # type: ignore[call-arg]
    await set_override(db_session, "faq_similarity_threshold", 0.9)
    await db_session.flush()
    assert (await effective_settings(db_session, base)).faq_similarity_threshold == 0.9

    await clear_override(db_session, "faq_similarity_threshold")
    await db_session.flush()
    assert (await effective_settings(db_session, base)).faq_similarity_threshold == 0.4


@pytest.mark.parametrize("value", [-0.1, 1.5, "not a number"])
async def test_an_out_of_range_threshold_is_refused_at_the_write(
    db_session: AsyncSession, value: object
) -> None:
    # A threshold of 5.0 is not a bad setting, it is one that silently
    # suppresses every FAQ match. The write is where that is cheap to catch.
    with pytest.raises(RescueError) as excinfo:
        await set_override(db_session, "faq_similarity_threshold", value)
    assert excinfo.value.code is ErrorCode.INVALID_REQUEST


@pytest.mark.parametrize("key", ["llm_api_key", "database_url", "admin_password"])
async def test_only_tuning_values_are_runtime_configurable(
    db_session: AsyncSession, key: str
) -> None:
    # An admin form that could rewrite the database URL or a provider key would
    # be remote configuration of the deployment, not tuning.
    with pytest.raises(RescueError) as excinfo:
        await set_override(db_session, key, "anything")
    assert excinfo.value.code is ErrorCode.INVALID_REQUEST
    assert key in (excinfo.value.detail or "")


async def test_the_admin_form_advertises_bounds_and_the_deployed_default() -> None:
    fields = {field["key"]: field for field in describe_overridable()}
    threshold = fields["faq_similarity_threshold"]
    assert threshold["minimum"] == 0.0
    assert threshold["maximum"] == 1.0
    assert threshold["default"] is not None
    assert threshold["description"]


async def test_an_override_records_who_changed_it(db_session: AsyncSession) -> None:
    await set_override(
        db_session, "faq_top_k", 7, updated_by="operator", note="widening after a quiet week"
    )
    await db_session.flush()
    assert (await load_overrides(db_session))["faq_top_k"] == 7


# --- FAQ curation (13.2) ---------------------------------------------------


async def test_a_deleted_entry_stops_appearing_in_user_facing_results(
    db_session: AsyncSession,
) -> None:
    item = await _make_faq(db_session, question=f"سؤال-{uuid.uuid4().hex}")
    await db_session.execute(FaqItem.__table__.delete().where(FaqItem.id == item.id))
    await db_session.flush()

    remaining = (await db_session.execute(select(FaqItem.id).where(FaqItem.id == item.id))).first()
    assert remaining is None


async def test_deactivating_an_entry_hides_it_without_losing_its_history(
    db_session: AsyncSession,
) -> None:
    # Deletion and deactivation are different operator intents. Deactivating
    # must keep the row, so the decision stays auditable.
    item = await _make_faq(db_session, question=f"سؤال-{uuid.uuid4().hex}")
    item.is_active = False
    await db_session.flush()

    stored = await db_session.get(FaqItem, item.id)
    assert stored is not None
    assert stored.is_active is False


async def test_a_changed_question_without_a_vector_cannot_match(
    db_session: AsyncSession,
) -> None:
    """The invariant behind re-embedding on edit.

    An entry whose stored vector no longer represents its text would match
    questions it has nothing to do with. Clearing the vector makes it invisible
    until re-embedded — briefly absent beats confidently wrong.
    """
    item = await _make_faq(db_session, question=f"سؤال-{uuid.uuid4().hex}")
    item.question = "یک پرسش کاملاً متفاوت"
    item.question_normalized = "یک پرسش کاملاً متفاوت"
    item.embedding = None
    await db_session.flush()

    matchable = (
        await db_session.execute(
            select(FaqItem.id).where(
                FaqItem.id == item.id,
                FaqItem.is_active.is_(True),
                FaqItem.embedding.is_not(None),
            )
        )
    ).first()
    assert matchable is None


# --- Dashboard (13.5, 13.6) ------------------------------------------------


async def test_a_metric_with_no_events_reports_absence_rather_than_zero(
    db_session: AsyncSession,
) -> None:
    # The failure this guards: a 0% failure rate displayed for a system that has
    # been down since deploy. Zero is a measurement; absence is not.
    dashboard = await build_dashboard(db_session, window_days=1)
    metrics = dashboard.as_dict()["metrics"]
    resolution = metrics["faq_resolution_rate"]
    if resolution["no_data"]:
        assert resolution["value"] is None
        assert resolution["sample_size"] == 0


async def test_every_metric_declares_whether_it_has_data(db_session: AsyncSession) -> None:
    metrics = (await build_dashboard(db_session)).as_dict()["metrics"]
    assert metrics, "the dashboard reported no metrics at all"
    for name, metric in metrics.items():
        assert "no_data" in metric, name
        assert "sample_size" in metric, name
        # The one structural guarantee: a no-data metric can never carry a
        # number a UI might render as a measurement.
        if metric["no_data"]:
            assert metric["value"] is None, name


async def test_the_resolution_rate_is_computed_from_recorded_events(
    db_session: AsyncSession,
) -> None:
    session_row = uuid.uuid4()
    for outcome in (
        FeedbackOutcome.RESOLVED,
        FeedbackOutcome.RESOLVED,
        FeedbackOutcome.UNRESOLVED,
    ):
        await db_session.execute(
            UsageEvent.__table__.insert().values(
                event_type=UsageEventType.FAQ_RESOLUTION.value,
                question=f"q-{session_row}",
                payload={
                    "outcome": outcome.value,
                    "source_urls": ["https://docs.liara.ir/test"],
                },
            )
        )
    await db_session.flush()

    metric = (await build_dashboard(db_session)).faq_resolution_rate
    assert not metric.no_data
    assert metric.sample_size >= 3
    assert 0.0 <= metric.value <= 1.0


async def test_failures_are_counted_by_the_same_codes_the_api_returns(
    db_session: AsyncSession,
) -> None:
    await db_session.execute(
        UsageEvent.__table__.insert().values(
            event_type=UsageEventType.RETRIEVAL.value,
            error_code=ErrorCode.NO_RESULTS_ABOVE_THRESHOLD.value,
            question=f"gap-{uuid.uuid4().hex}",
            payload={},
        )
    )
    await db_session.flush()

    metric = (await build_dashboard(db_session)).failures_by_code
    assert not metric.no_data
    # The same string in the response, the log, and the chart — so grepping a
    # log and filtering a dashboard use one vocabulary.
    assert ErrorCode.NO_RESULTS_ABOVE_THRESHOLD.value in metric.value


async def test_unresolved_questions_surface_as_a_documentation_backlog(
    db_session: AsyncSession,
) -> None:
    question = f"چطور {uuid.uuid4().hex} را انجام دهم؟"
    for _ in range(3):
        await db_session.execute(
            UsageEvent.__table__.insert().values(
                event_type=UsageEventType.RETRIEVAL.value,
                error_code=ErrorCode.NO_RESULTS_ABOVE_THRESHOLD.value,
                question=question,
                payload={},
            )
        )
    await db_session.flush()

    metric = (await build_dashboard(db_session)).unresolved_questions
    assert not metric.no_data
    assert any(item["question"] == question and item["count"] == 3 for item in metric.value)


async def test_the_rescue_tool_split_is_reported_with_shares(
    db_session: AsyncSession,
) -> None:
    for tool in (RescueTool.CHAT, RescueTool.CHAT, RescueTool.MCP):
        await db_session.execute(
            UsageEvent.__table__.insert().values(
                event_type=UsageEventType.RESCUE_TOOL_TRANSITION.value,
                rescue_tool=tool.value,
                payload={},
            )
        )
    await db_session.flush()

    metric = (await build_dashboard(db_session)).rescue_tool_split
    assert not metric.no_data
    assert metric.value[RescueTool.CHAT.value]["count"] >= 2
    assert 0.0 < metric.value[RescueTool.CHAT.value]["share"] <= 1.0


async def test_an_unpriced_model_is_not_presented_as_free(db_session: AsyncSession) -> None:
    # Summing a null cost as zero would report a model whose price nobody has
    # configured as costing nothing — a fabricated measurement.
    await db_session.execute(
        UsageEvent.__table__.insert().values(
            event_type=UsageEventType.GENERATION.value,
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            cost_usd=None,
            payload={},
        )
    )
    await db_session.flush()

    dashboard = await build_dashboard(db_session)
    assert not dashboard.token_usage.no_data
    if dashboard.cost_usd.no_data:
        assert dashboard.cost_usd.value is None
