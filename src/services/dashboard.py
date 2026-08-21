"""Dashboard figures, every one of them derived from a recorded event.

The governing rule is the one the spec states and this module enforces
structurally: **a metric with no recorded events reports its absence, and never
a number.** Zero is a measurement — "no question has failed" — and it is a very
different claim from "nothing has been recorded yet". A dashboard that renders
them identically will show a healthy 0% failure rate for a system that has been
down since deploy, which is the precise failure this product exists to not have.

So every figure is a `Metric`, and a `Metric` is either a value with the event
count behind it or an explicit `no_data`. There is no third state and no
default.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Integer, Select, func, select, true
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.core.errors import ErrorCode, RescueError
from src.core.logging import get_logger
from src.db.models import FaqItem, IndexVersion, UsageEvent
from src.db.models.enums import FeedbackOutcome, UsageEventType
from src.services.interactions import NORMALIZED_QUESTION_KEY as _NORMALIZED_QUESTION_KEY
from src.services.interactions import SEARCH_MARKER as _SEARCH_MARKER

logger = get_logger(__name__)
Executor = AsyncSession | AsyncConnection

#: Default reporting window. Wide enough to survive a quiet weekend, short
#: enough that a change made on Monday is visible by Tuesday.
DEFAULT_WINDOW_DAYS = 30


@dataclass(frozen=True, slots=True)
class Metric:
    """A figure, or an honest statement that there is nothing to report."""

    value: Any | None
    #: How many events the figure was computed from. Zero means `no_data`.
    sample_size: int
    unit: str | None = None

    @property
    def no_data(self) -> bool:
        return self.sample_size == 0

    def as_dict(self) -> dict[str, Any]:
        # `value` is null when there is no data — a consumer that ignores
        # `no_data` and renders `value` still cannot print a fabricated zero.
        return {
            "value": None if self.no_data else self.value,
            "sample_size": self.sample_size,
            "unit": self.unit,
            "no_data": self.no_data,
        }

    @classmethod
    def absent(cls, unit: str | None = None) -> Metric:
        return cls(value=None, sample_size=0, unit=unit)


@dataclass
class Dashboard:
    window_days: int
    since: datetime
    faq_resolution_rate: Metric = field(default_factory=Metric.absent)
    rescue_tool_split: Metric = field(default_factory=Metric.absent)
    unresolved_questions: Metric = field(default_factory=Metric.absent)
    unresolved_pages: Metric = field(default_factory=Metric.absent)
    failures_by_code: Metric = field(default_factory=Metric.absent)
    token_usage: Metric = field(default_factory=Metric.absent)
    cost_usd: Metric = field(default_factory=Metric.absent)
    provider_fallbacks: Metric = field(default_factory=Metric.absent)
    active_index: Metric = field(default_factory=Metric.absent)
    faq_corpus: Metric = field(default_factory=Metric.absent)
    # Answer quality and demand, from chat-stage feedback and usage.
    chat_satisfaction_rate: Metric = field(default_factory=Metric.absent)
    lowest_rated_pages: Metric = field(default_factory=Metric.absent)
    feedback_reasons: Metric = field(default_factory=Metric.absent)
    top_questions: Metric = field(default_factory=Metric.absent)
    top_cited_pages: Metric = field(default_factory=Metric.absent)
    questions_over_time: Metric = field(default_factory=Metric.absent)
    abstention_rate: Metric = field(default_factory=Metric.absent)
    faq_hit_rate: Metric = field(default_factory=Metric.absent)

    def as_dict(self) -> dict[str, Any]:
        return {
            "window_days": self.window_days,
            "since": self.since.isoformat(),
            "metrics": {
                "faq_resolution_rate": self.faq_resolution_rate.as_dict(),
                "rescue_tool_split": self.rescue_tool_split.as_dict(),
                "unresolved_questions": self.unresolved_questions.as_dict(),
                "unresolved_pages": self.unresolved_pages.as_dict(),
                "failures_by_code": self.failures_by_code.as_dict(),
                "token_usage": self.token_usage.as_dict(),
                "cost_usd": self.cost_usd.as_dict(),
                "provider_fallbacks": self.provider_fallbacks.as_dict(),
                "active_index": self.active_index.as_dict(),
                "faq_corpus": self.faq_corpus.as_dict(),
                "chat_satisfaction_rate": self.chat_satisfaction_rate.as_dict(),
                "lowest_rated_pages": self.lowest_rated_pages.as_dict(),
                "feedback_reasons": self.feedback_reasons.as_dict(),
                "top_questions": self.top_questions.as_dict(),
                "top_cited_pages": self.top_cited_pages.as_dict(),
                "questions_over_time": self.questions_over_time.as_dict(),
                "abstention_rate": self.abstention_rate.as_dict(),
                "faq_hit_rate": self.faq_hit_rate.as_dict(),
            },
        }


def _within(statement: Select[Any], since: datetime) -> Select[Any]:
    return statement.where(UsageEvent.created_at >= since)


async def _faq_resolution_rate(executor: Executor, since: datetime) -> Metric:
    """Share of FAQ outcomes the user marked solved.

    Counted over `FAQ_RESOLUTION` events only. Impressions are not the
    denominator: a user who never answered told us nothing, and folding their
    silence in as an unresolved case would understate the FAQ stage by however
    many people simply closed the tab.
    """
    rows = (
        await executor.execute(
            _within(
                select(
                    func.count().label("total"),
                    func.count()
                    .filter(UsageEvent.payload["outcome"].astext == FeedbackOutcome.RESOLVED.value)
                    .label("resolved"),
                ).where(UsageEvent.event_type == UsageEventType.FAQ_RESOLUTION.value),
                since,
            )
        )
    ).one()
    total, resolved = int(rows.total or 0), int(rows.resolved or 0)
    if total == 0:
        return Metric.absent(unit="ratio")
    return Metric(value=round(resolved / total, 4), sample_size=total, unit="ratio")


async def _rescue_tool_split(executor: Executor, since: datetime) -> Metric:
    rows = await executor.execute(
        _within(
            select(UsageEvent.rescue_tool, func.count().label("count"))
            .where(
                UsageEvent.event_type == UsageEventType.RESCUE_TOOL_TRANSITION.value,
                UsageEvent.rescue_tool.is_not(None),
            )
            .group_by(UsageEvent.rescue_tool),
            since,
        )
    )
    counts = {tool: int(count) for tool, count in rows}
    total = sum(counts.values())
    if total == 0:
        return Metric.absent(unit="events")
    return Metric(
        value={
            tool: {"count": count, "share": round(count / total, 4)}
            for tool, count in sorted(counts.items(), key=lambda item: -item[1])
        },
        sample_size=total,
        unit="events",
    )


async def _unresolved_questions(executor: Executor, since: datetime, limit: int) -> Metric:
    """The questions the documentation could not answer.

    This is the most valuable output on the dashboard: not a health metric but a
    backlog, each row a page somebody needed and did not find.
    """
    rows = await executor.execute(
        _within(
            select(UsageEvent.question, func.count().label("count"))
            .where(
                UsageEvent.error_code.in_(
                    (
                        ErrorCode.NO_RESULTS_ABOVE_THRESHOLD.value,
                        ErrorCode.NO_EVIDENCE.value,
                    )
                ),
                UsageEvent.question.is_not(None),
            )
            .group_by(UsageEvent.question)
            .order_by(func.count().desc())
            .limit(limit),
            since,
        )
    )
    items = [{"question": question, "count": int(count)} for question, count in rows]
    if not items:
        return Metric.absent(unit="questions")
    return Metric(value=items, sample_size=sum(item["count"] for item in items), unit="questions")


async def _unresolved_pages(executor: Executor, since: datetime, limit: int) -> Metric:
    """Documentation pages users marked unhelpful, most-reported first.

    One resolution event carries every page that was shown, so the array is
    unnested and each page counted individually — a user rejecting five
    suggestions is five reports, not one, which is what makes the ordering
    reflect how often a page actually failed somebody.
    """
    # A LATERAL join, not a plain select of the set-returning function: without
    # correlating it to `usage_events` the planner pairs every unnested URL with
    # every event row, and the counts come out multiplied by the table size.
    elements = (
        func.jsonb_array_elements_text(UsageEvent.payload["source_urls"])
        .table_valued("value")
        .lateral("page")
    )
    rows = await executor.execute(
        _within(
            select(elements.c.value.label("source_url"), func.count().label("count"))
            .select_from(UsageEvent)
            .join(elements, true())
            .where(
                UsageEvent.event_type == UsageEventType.FAQ_RESOLUTION.value,
                UsageEvent.payload["outcome"].astext == FeedbackOutcome.UNRESOLVED.value,
                # Guard the unnest: `jsonb_array_elements_text` raises on a
                # value that is not an array, and one malformed payload would
                # take the whole dashboard down.
                func.jsonb_typeof(UsageEvent.payload["source_urls"]) == "array",
            )
            .group_by(elements.c.value)
            .order_by(func.count().desc())
            .limit(limit),
            since,
        )
    )
    items = [{"source_url": url, "count": int(count)} for url, count in rows]
    if not items:
        return Metric.absent(unit="pages")
    return Metric(value=items, sample_size=sum(item["count"] for item in items), unit="pages")


async def _failures_by_code(executor: Executor, since: datetime) -> Metric:
    """Counted by the same error codes the API returns and the logs carry.

    One vocabulary across response, log, and dashboard is what lets an operator
    grep for the string they just read on a chart.
    """
    rows = await executor.execute(
        _within(
            select(UsageEvent.error_code, func.count().label("count"))
            .where(UsageEvent.error_code.is_not(None))
            .group_by(UsageEvent.error_code)
            .order_by(func.count().desc()),
            since,
        )
    )
    counts = {code: int(count) for code, count in rows}
    if not counts:
        return Metric.absent(unit="events")
    return Metric(value=counts, sample_size=sum(counts.values()), unit="events")


async def _token_usage(executor: Executor, since: datetime) -> tuple[Metric, Metric]:
    row = (
        await executor.execute(
            _within(
                select(
                    func.count().label("events"),
                    func.sum(UsageEvent.prompt_tokens).label("prompt"),
                    func.sum(UsageEvent.completion_tokens).label("completion"),
                    func.sum(UsageEvent.total_tokens).label("total"),
                    func.sum(UsageEvent.cost_usd).label("cost"),
                    func.count(UsageEvent.cost_usd).label("costed"),
                ).where(UsageEvent.total_tokens > 0),
                since,
            )
        )
    ).one()
    events = int(row.events or 0)
    if events == 0:
        return Metric.absent(unit="tokens"), Metric.absent(unit="usd")

    tokens = Metric(
        value={
            "prompt": int(row.prompt or 0),
            "completion": int(row.completion or 0),
            "total": int(row.total or 0),
        },
        sample_size=events,
        unit="tokens",
    )
    # Cost is reported separately and only over the events that actually carry
    # one. Summing a null cost as zero would present an unpriced model as free.
    costed = int(row.costed or 0)
    cost = (
        Metric(value=round(float(row.cost or 0), 6), sample_size=costed, unit="usd")
        if costed
        else Metric.absent(unit="usd")
    )
    return tokens, cost


async def _provider_fallbacks(executor: Executor, since: datetime) -> Metric:
    row = (
        await executor.execute(
            _within(
                select(
                    func.count().label("total"),
                    func.count().filter(UsageEvent.fallback_used.is_(True)).label("fallbacks"),
                ).where(
                    UsageEvent.event_type.in_(
                        (
                            UsageEventType.GENERATION.value,
                            UsageEventType.PROVIDER_FALLBACK.value,
                        )
                    )
                ),
                since,
            )
        )
    ).one()
    total = int(row.total or 0)
    if total == 0:
        return Metric.absent(unit="events")
    fallbacks = int(row.fallbacks or 0)
    return Metric(
        value={
            "count": fallbacks,
            "share": round(fallbacks / total, 4),
            "generations": total,
        },
        sample_size=total,
        unit="events",
    )


async def _active_index(executor: Executor) -> Metric:
    """Which documentation the answers are actually coming from.

    Absent here does not mean "quiet system" — it means NO_ACTIVE_INDEX, and the
    product is answering nothing. It is the one metric whose no-data state is an
    outage.
    """
    row = (
        await executor.execute(
            select(
                IndexVersion.id,
                IndexVersion.status,
                IndexVersion.source_commit,
                IndexVersion.document_count,
                IndexVersion.chunk_count,
                IndexVersion.embedding_model,
                IndexVersion.embedding_dimensions,
                IndexVersion.activated_at,
                IndexVersion.created_at,
            ).where(IndexVersion.is_active.is_(True))
        )
    ).first()
    if row is None:
        return Metric.absent(unit="index")
    return Metric(
        value={
            "index_version_id": str(row.id),
            "status": row.status,
            "source_commit": row.source_commit,
            "document_count": row.document_count,
            "chunk_count": row.chunk_count,
            "embedding_model": row.embedding_model,
            "embedding_dimensions": row.embedding_dimensions,
            "activated_at": row.activated_at.isoformat() if row.activated_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        },
        sample_size=1,
        unit="index",
    )


async def _faq_corpus(executor: Executor) -> Metric:
    row = (
        await executor.execute(
            select(
                func.count().label("total"),
                func.count().filter(FaqItem.is_active.is_(True)).label("active"),
                func.count().filter(FaqItem.embedding.is_(None)).label("unembedded"),
            )
        )
    ).one()
    total = int(row.total or 0)
    if total == 0:
        return Metric.absent(unit="entries")
    return Metric(
        value={
            "total": total,
            "active": int(row.active or 0),
            # An entry whose question changed and has not been re-embedded
            # cannot match anything, so it is invisible without being deleted.
            "awaiting_reembedding": int(row.unembedded or 0),
        },
        sample_size=total,
        unit="entries",
    )


async def _chat_satisfaction_rate(executor: Executor, since: datetime) -> Metric:
    """Share of answers the user judged helpful.

    Deliberately not comparable to `faq_resolution_rate`: that one measures
    whether a canned entry matched, this one measures whether a generated answer
    was any good. Both are opt-in, so both under-count silence rather than
    guessing at it.
    """
    rows = (
        await executor.execute(
            _within(
                select(
                    func.count().label("total"),
                    func.count()
                    .filter(UsageEvent.payload["outcome"].astext == FeedbackOutcome.RESOLVED.value)
                    .label("resolved"),
                ).where(UsageEvent.event_type == UsageEventType.CHAT_RESOLUTION.value),
                since,
            )
        )
    ).one()
    total, resolved = int(rows.total or 0), int(rows.resolved or 0)
    if total == 0:
        return Metric.absent(unit="ratio")
    return Metric(value=round(resolved / total, 4), sample_size=total, unit="ratio")


async def _lowest_rated_pages(executor: Executor, since: datetime, limit: int) -> Metric:
    """Documentation pages whose citations keep producing rejected answers.

    This is the operational point of chat feedback. A page that repeatedly backs
    an answer the user rejects is either wrong, incomplete, or chunked so that
    its useful part never survives retrieval — and this list is the only place
    that shows up.
    """
    elements = (
        func.jsonb_array_elements_text(UsageEvent.payload["source_urls"])
        .table_valued("value")
        .lateral("page")
    )
    rows = await executor.execute(
        _within(
            select(elements.c.value.label("source_url"), func.count().label("count"))
            .select_from(UsageEvent)
            .join(elements, true())
            .where(
                UsageEvent.event_type == UsageEventType.CHAT_RESOLUTION.value,
                UsageEvent.payload["outcome"].astext == FeedbackOutcome.UNRESOLVED.value,
                # Same guard as `_unresolved_pages`: one malformed payload must
                # not take the whole dashboard down.
                func.jsonb_typeof(UsageEvent.payload["source_urls"]) == "array",
            )
            .group_by(elements.c.value)
            .order_by(func.count().desc())
            .limit(limit),
            since,
        )
    )
    items = [{"source_url": url, "count": int(count)} for url, count in rows]
    if not items:
        return Metric.absent(unit="pages")
    return Metric(value=items, sample_size=sum(item["count"] for item in items), unit="pages")


async def _feedback_reasons(executor: Executor, since: datetime) -> Metric:
    """What kind of wrong the rejected answers were.

    "Incomplete" points at the corpus, "irrelevant" at retrieval, "incorrect" at
    grounding. Without the split, a falling satisfaction rate says only that
    something got worse.
    """
    reason = UsageEvent.payload["reason"].astext
    rows = await executor.execute(
        _within(
            select(
                reason.label("reason"),
                func.count().label("count"),
            )
            .where(
                UsageEvent.event_type == UsageEventType.CHAT_RESOLUTION.value,
                UsageEvent.payload["outcome"].astext == FeedbackOutcome.UNRESOLVED.value,
            )
            .group_by(reason),
            since,
        )
    )
    counts = {(reason or "unspecified"): int(count) for reason, count in rows}
    total = sum(counts.values())
    if total == 0:
        return Metric.absent(unit="reports")
    return Metric(
        value={
            reason: {"count": count, "share": round(count / total, 4)}
            for reason, count in sorted(counts.items(), key=lambda item: -item[1])
        },
        sample_size=total,
        unit="reports",
    )


async def _top_questions(executor: Executor, since: datetime, limit: int) -> Metric:
    """What people actually ask, answered or not.

    `unresolved_questions` is a backlog of failures; this is demand. A question
    that is asked constantly and answered well is still the strongest argument
    for where the documentation deserves attention.

    Counted over search rows, not impression rows: an impression is written per
    entry shown, so counting those would rank a question by how many results it
    happened to return rather than by how often it was asked. Grouped on the
    normalized form so two spellings of one question are one row.
    """
    normalized = UsageEvent.payload[_NORMALIZED_QUESTION_KEY].astext.label("question")
    rows = await executor.execute(
        _within(
            select(
                normalized,
                func.min(UsageEvent.question).label("sample"),
                func.count().label("count"),
            )
            .where(
                UsageEvent.event_type == UsageEventType.FAQ_IMPRESSION.value,
                UsageEvent.payload.has_key(_SEARCH_MARKER),
                UsageEvent.payload[_NORMALIZED_QUESTION_KEY].astext.is_not(None),
            )
            .group_by(normalized)
            .order_by(func.count().desc())
            .limit(limit),
            since,
        )
    )
    items = [
        {"question": sample or question, "count": int(count)} for question, sample, count in rows
    ]
    if not items:
        return Metric.absent(unit="questions")
    return Metric(value=items, sample_size=sum(item["count"] for item in items), unit="questions")


async def _top_cited_pages(executor: Executor, since: datetime, limit: int) -> Metric:
    """Which parts of the documentation the answers keep leaning on.

    Read alongside `lowest_rated_pages`: heavy use plus poor ratings is the
    worst combination on the dashboard, and neither number says it alone.
    """
    elements = (
        func.jsonb_array_elements_text(UsageEvent.payload["source_urls"])
        .table_valued("value")
        .lateral("page")
    )
    rows = await executor.execute(
        _within(
            select(elements.c.value.label("source_url"), func.count().label("count"))
            .select_from(UsageEvent)
            .join(elements, true())
            .where(
                UsageEvent.event_type.in_(
                    (
                        UsageEventType.CHAT_RESOLUTION.value,
                        UsageEventType.FAQ_RESOLUTION.value,
                    )
                ),
                func.jsonb_typeof(UsageEvent.payload["source_urls"]) == "array",
            )
            .group_by(elements.c.value)
            .order_by(func.count().desc())
            .limit(limit),
            since,
        )
    )
    items = [{"source_url": url, "count": int(count)} for url, count in rows]
    if not items:
        return Metric.absent(unit="pages")
    return Metric(value=items, sample_size=sum(item["count"] for item in items), unit="pages")


async def _questions_over_time(executor: Executor, since: datetime) -> Metric:
    """Daily question volume, oldest first.

    Days with no traffic are absent rather than zero-filled: this module does
    not manufacture data points, and a gap is legible as a gap.
    """
    day = func.date_trunc("day", UsageEvent.created_at).label("day")
    rows = await executor.execute(
        _within(
            select(day, func.count().label("count"))
            .where(UsageEvent.event_type == UsageEventType.GENERATION.value)
            .group_by(day)
            .order_by(day),
            since,
        )
    )
    items = [{"day": moment.date().isoformat(), "count": int(count)} for moment, count in rows]
    if not items:
        return Metric.absent(unit="questions")
    return Metric(value=items, sample_size=sum(item["count"] for item in items), unit="questions")


async def _abstention_rate(executor: Executor, since: datetime) -> Metric:
    """Share of answered turns that honestly declined to answer.

    Not a failure rate. A rising figure means the corpus is missing what people
    ask; a figure near zero on a corpus known to have gaps means the agent is
    answering things it should not.
    """
    rows = (
        await executor.execute(
            _within(
                select(
                    func.count().label("total"),
                    func.count()
                    .filter(UsageEvent.error_code == ErrorCode.NO_EVIDENCE.value)
                    .label("abstained"),
                ).where(UsageEvent.event_type == UsageEventType.JOB_OUTCOME.value),
                since,
            )
        )
    ).one()
    total, abstained = int(rows.total or 0), int(rows.abstained or 0)
    if total == 0:
        return Metric.absent(unit="ratio")
    return Metric(value=round(abstained / total, 4), sample_size=total, unit="ratio")


async def _faq_hit_rate(executor: Executor, since: datetime) -> Metric:
    """Share of FAQ searches that returned anything at all above the threshold.

    The number to watch after moving `faq_similarity_threshold`: it says whether
    a change let more real questions through, which the resolution rate alone
    cannot, since a search that matched nothing never gets rated.
    """
    rows = (
        await executor.execute(
            _within(
                select(
                    func.count().label("total"),
                    func.count()
                    .filter(UsageEvent.payload[_SEARCH_MARKER].astext.cast(Integer) > 0)
                    .label("hits"),
                ).where(
                    UsageEvent.event_type == UsageEventType.FAQ_IMPRESSION.value,
                    UsageEvent.payload.has_key(_SEARCH_MARKER),
                ),
                since,
            )
        )
    ).one()
    total, hits = int(rows.total or 0), int(rows.hits or 0)
    if total == 0:
        return Metric.absent(unit="ratio")
    return Metric(value=round(hits / total, 4), sample_size=total, unit="ratio")


async def build_dashboard(
    executor: Executor,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    top_n: int = 10,
) -> Dashboard:
    """Compute every dashboard figure over one window."""
    since = datetime.now(UTC) - timedelta(days=window_days)
    dashboard = Dashboard(window_days=window_days, since=since)
    try:
        dashboard.faq_resolution_rate = await _faq_resolution_rate(executor, since)
        dashboard.rescue_tool_split = await _rescue_tool_split(executor, since)
        dashboard.unresolved_questions = await _unresolved_questions(executor, since, top_n)
        dashboard.unresolved_pages = await _unresolved_pages(executor, since, top_n)
        dashboard.failures_by_code = await _failures_by_code(executor, since)
        dashboard.token_usage, dashboard.cost_usd = await _token_usage(executor, since)
        dashboard.provider_fallbacks = await _provider_fallbacks(executor, since)
        dashboard.active_index = await _active_index(executor)
        dashboard.faq_corpus = await _faq_corpus(executor)
        dashboard.chat_satisfaction_rate = await _chat_satisfaction_rate(executor, since)
        dashboard.lowest_rated_pages = await _lowest_rated_pages(executor, since, top_n)
        dashboard.feedback_reasons = await _feedback_reasons(executor, since)
        dashboard.top_questions = await _top_questions(executor, since, top_n)
        dashboard.top_cited_pages = await _top_cited_pages(executor, since, top_n)
        dashboard.questions_over_time = await _questions_over_time(executor, since)
        dashboard.abstention_rate = await _abstention_rate(executor, since)
        dashboard.faq_hit_rate = await _faq_hit_rate(executor, since)
    except SQLAlchemyError as err:
        # A dashboard that renders zeros because its query failed is worse than
        # one that does not render. Name the cause.
        raise RescueError(
            ErrorCode.RETRIEVAL_FAILED,
            detail="dashboard aggregation query failed",
        ) from err
    return dashboard
