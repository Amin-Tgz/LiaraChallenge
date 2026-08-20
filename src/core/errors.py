"""The error taxonomy from docs/deployment.md §10.

Governing rule: **every error names its own cause.** A generic "nothing found"
is forbidden. `NO_ACTIVE_INDEX` (the system is broken) and
`NO_RESULTS_ABOVE_THRESHOLD` (the system works; this is a real documentation
gap) look identical to a user and have nothing in common — they must never
share a code or a message.

One enumeration is used by API responses, log records, and dashboard
aggregation, so the same string appears everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    NO_ACTIVE_INDEX = "NO_ACTIVE_INDEX"
    NO_RESULTS_ABOVE_THRESHOLD = "NO_RESULTS_ABOVE_THRESHOLD"
    INDEX_STALE = "INDEX_STALE"
    RETRIEVAL_FAILED = "RETRIEVAL_FAILED"
    EMBEDDING_FAILED = "EMBEDDING_FAILED"
    ALL_PROVIDERS_UNAVAILABLE = "ALL_PROVIDERS_UNAVAILABLE"
    RATE_LIMITED = "RATE_LIMITED"
    NO_EVIDENCE = "NO_EVIDENCE"
    DOCUMENT_PARSE_FAILED = "DOCUMENT_PARSE_FAILED"
    INGESTION_SOURCE_UNAVAILABLE = "INGESTION_SOURCE_UNAVAILABLE"
    INDEX_VALIDATION_FAILED = "INDEX_VALIDATION_FAILED"
    FAQ_GENERATION_FAILED = "FAQ_GENERATION_FAILED"
    FAQ_OUTPUT_INVALID = "FAQ_OUTPUT_INVALID"
    INPUT_TOO_LARGE = "INPUT_TOO_LARGE"
    UNAUTHORIZED = "UNAUTHORIZED"
    INVALID_REQUEST = "INVALID_REQUEST"
    JOB_FAILED = "JOB_FAILED"
    AGENT_LIMIT_REACHED = "AGENT_LIMIT_REACHED"
    UPSTREAM_TIMEOUT = "UPSTREAM_TIMEOUT"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass(frozen=True, slots=True)
class ErrorSpec:
    code: ErrorCode
    http_status: int
    #: Persian, user-facing. States the actual cause and what to do next.
    message_fa: str
    #: What an operator should do. Never shown to a user.
    operator_action: str
    #: Whether the same request may succeed on retry.
    transient: bool


ERROR_SPECS: dict[ErrorCode, ErrorSpec] = {
    ErrorCode.NO_ACTIVE_INDEX: ErrorSpec(
        code=ErrorCode.NO_ACTIVE_INDEX,
        http_status=503,
        message_fa=(
            "هنوز هیچ مستندی ایندکس نشده است. این یک خطای سیستمی است، نه نبود پاسخ. "
            "لطفاً کمی بعد دوباره تلاش کنید."
        ),
        operator_action="Run ingestion; check the last index_versions row.",
        transient=False,
    ),
    ErrorCode.NO_RESULTS_ABOVE_THRESHOLD: ErrorSpec(
        code=ErrorCode.NO_RESULTS_ABOVE_THRESHOLD,
        http_status=200,
        message_fa=(
            "مستندات ایندکس شده‌اند، اما پاسخی مرتبط با این سؤال پیدا نشد. "
            "می‌توانید سؤال را با عبارت دیگری بپرسید یا از ابزارهای نجات استفاده کنید."
        ),
        operator_action="Genuine documentation gap — log to unresolved analytics.",
        transient=False,
    ),
    ErrorCode.INDEX_STALE: ErrorSpec(
        code=ErrorCode.INDEX_STALE,
        http_status=200,
        message_fa=(
            "این پاسخ از نسخه‌ای از مستندات آمده که مدتی است به‌روزرسانی نشده؛ "
            "ممکن است تغییرات تازه را نشان ندهد."
        ),
        operator_action="Trigger reindex; upstream docs SHA has moved.",
        transient=False,
    ),
    ErrorCode.RETRIEVAL_FAILED: ErrorSpec(
        code=ErrorCode.RETRIEVAL_FAILED,
        http_status=503,
        message_fa="مشکلی در جست‌وجوی مستندات پیش آمد. لطفاً دوباره تلاش کنید.",
        operator_action="Check Postgres and the pgvector query path.",
        transient=True,
    ),
    ErrorCode.EMBEDDING_FAILED: ErrorSpec(
        code=ErrorCode.EMBEDDING_FAILED,
        http_status=503,
        message_fa="تبدیل سؤال شما برای جست‌وجو ناموفق بود. لطفاً دوباره تلاش کنید.",
        operator_action="Check AvalAI embeddings and the gateway.",
        transient=True,
    ),
    ErrorCode.ALL_PROVIDERS_UNAVAILABLE: ErrorSpec(
        code=ErrorCode.ALL_PROVIDERS_UNAVAILABLE,
        http_status=503,
        message_fa="سرویس پاسخ‌گویی موقتاً در دسترس نیست. سؤال شما ذخیره شد.",
        operator_action="Check Portkey circuit state and both provider credentials.",
        transient=True,
    ),
    ErrorCode.RATE_LIMITED: ErrorSpec(
        code=ErrorCode.RATE_LIMITED,
        http_status=429,
        message_fa="تعداد درخواست‌ها زیاد است. لطفاً کمی صبر کنید.",
        operator_action="Expected behavior — no action unless a legitimate user is affected.",
        transient=True,
    ),
    ErrorCode.NO_EVIDENCE: ErrorSpec(
        code=ErrorCode.NO_EVIDENCE,
        http_status=200,
        message_fa=(
            "در مستندات شواهد کافی برای پاسخ به این سؤال پیدا نکردم و ترجیح می‌دهم "
            "حدس نزنم. این سؤال برای بهبود مستندات ثبت شد."
        ),
        operator_action="Feed to documentation-gap analytics.",
        transient=False,
    ),
    ErrorCode.DOCUMENT_PARSE_FAILED: ErrorSpec(
        code=ErrorCode.DOCUMENT_PARSE_FAILED,
        http_status=500,
        message_fa=(
            "یکی از صفحه‌های مستندات قابل پردازش نبود و ایندکس نشد. "
            "این یک خطای پردازش مستندات است، نه نبود پاسخ."
        ),
        operator_action=(
            "The MDX pre-pass produced no text for a non-empty document — check that "
            "path's discarded_char_ratio and the unrecognized tags in the ingestion "
            "report; upstream has probably introduced a component the transform table "
            "misses."
        ),
        transient=False,
    ),
    ErrorCode.INGESTION_SOURCE_UNAVAILABLE: ErrorSpec(
        code=ErrorCode.INGESTION_SOURCE_UNAVAILABLE,
        http_status=503,
        message_fa=(
            "دریافت مستندات از مخزن اصلی ممکن نشد، بنابراین ایندکس به‌روزرسانی نشد. "
            "پاسخ‌ها همچنان از آخرین نسخه‌ی سالم ارائه می‌شوند."
        ),
        operator_action=(
            "The docs repository could not be cloned, fetched, or read, or the "
            "configured scope matched no files. The previously active index is "
            "untouched — check DOCS_REPO_URL, DOCS_REPO_BRANCH, and INGEST_SECTIONS."
        ),
        transient=True,
    ),
    ErrorCode.INDEX_VALIDATION_FAILED: ErrorSpec(
        code=ErrorCode.INDEX_VALIDATION_FAILED,
        http_status=500,
        message_fa=(
            "نسخه‌ی جدید ایندکس اعتبارسنجی نشد و فعال نشد. "
            "پاسخ‌ها از نسخه‌ی سالم قبلی ارائه می‌شوند."
        ),
        operator_action=(
            "A freshly built index failed its smoke checks and was not activated; "
            "the prior version still serves. Read index_versions.validation_report "
            "for the failed check."
        ),
        transient=False,
    ),
    ErrorCode.FAQ_GENERATION_FAILED: ErrorSpec(
        code=ErrorCode.FAQ_GENERATION_FAILED,
        http_status=503,
        message_fa=(
            "تولید پرسش‌های مرتبط از مستندات ناموفق بود. پرسش‌های معتبر قبلی همچنان در دسترس‌اند."
        ),
        operator_action=(
            "Check the FAQ model request and gateway response for the affected document."
        ),
        transient=True,
    ),
    ErrorCode.FAQ_OUTPUT_INVALID: ErrorSpec(
        code=ErrorCode.FAQ_OUTPUT_INVALID,
        http_status=500,
        message_fa=(
            "خروجی تولید پرسش‌های مرتبط ساختار معتبر نداشت و ذخیره نشد. "
            "سایر پرسش‌های معتبر پردازش شدند."
        ),
        operator_action="Inspect the recorded validation errors and the source document.",
        transient=False,
    ),
    ErrorCode.INPUT_TOO_LARGE: ErrorSpec(
        code=ErrorCode.INPUT_TOO_LARGE,
        http_status=413,
        message_fa="ورودی از حد مجاز بلندتر است. لطفاً سؤال را کوتاه‌تر کنید.",
        operator_action="Expected — check limits if legitimate questions are rejected.",
        transient=False,
    ),
    ErrorCode.UNAUTHORIZED: ErrorSpec(
        code=ErrorCode.UNAUTHORIZED,
        http_status=401,
        message_fa="دسترسی مجاز نیست.",
        operator_action="Admin credentials missing or wrong.",
        transient=False,
    ),
    ErrorCode.INVALID_REQUEST: ErrorSpec(
        code=ErrorCode.INVALID_REQUEST,
        http_status=400,
        message_fa="درخواست معتبر نیست. لطفاً ورودی را بررسی کنید.",
        operator_action="Client sent a malformed payload — check the named field.",
        transient=False,
    ),
    ErrorCode.JOB_FAILED: ErrorSpec(
        code=ErrorCode.JOB_FAILED,
        http_status=200,
        message_fa="تولید پاسخ ناتمام ماند. سؤال شما ذخیره شده و می‌توانید دوباره تلاش کنید.",
        operator_action="Inspect request_jobs.last_error for the underlying code.",
        transient=True,
    ),
    ErrorCode.AGENT_LIMIT_REACHED: ErrorSpec(
        code=ErrorCode.AGENT_LIMIT_REACHED,
        http_status=200,
        message_fa=(
            "برای این سؤال به سقف جست‌وجوی مجاز رسیدم و پاسخ کامل نشد. "
            "لطفاً سؤال را دقیق‌تر بپرسید."
        ),
        operator_action="Check AGENT_MAX_TOOL_CALLS / token budget against real traffic.",
        transient=False,
    ),
    ErrorCode.UPSTREAM_TIMEOUT: ErrorSpec(
        code=ErrorCode.UPSTREAM_TIMEOUT,
        http_status=504,
        message_fa="پاسخ‌گویی بیش از حد طول کشید. لطفاً دوباره تلاش کنید.",
        operator_action="Check provider latency and AGENT_TIMEOUT_SECONDS.",
        transient=True,
    ),
    ErrorCode.INTERNAL_ERROR: ErrorSpec(
        code=ErrorCode.INTERNAL_ERROR,
        http_status=500,
        message_fa="خطای غیرمنتظره‌ای رخ داد. تیم فنی مطلع شد.",
        operator_action="Read the correlated log record for the original cause.",
        transient=False,
    ),
}


def spec_for(code: ErrorCode) -> ErrorSpec:
    return ERROR_SPECS[code]


class RescueError(Exception):
    """Base for every failure that reaches a user.

    Always wraps rather than replaces the original cause: raise with
    ``raise RescueError(...) from err``.
    """

    def __init__(
        self,
        code: ErrorCode,
        *,
        detail: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        self.spec = spec_for(code)
        self.code = code
        #: Operator-facing detail. Never rendered to a user.
        self.detail = detail
        self.context = context or {}
        super().__init__(f"{code}: {detail or self.spec.operator_action}")

    @property
    def message_fa(self) -> str:
        return self.spec.message_fa

    @property
    def http_status(self) -> int:
        return self.spec.http_status

    @property
    def transient(self) -> bool:
        return self.spec.transient

    def to_response(self) -> dict[str, Any]:
        return {"error": {"code": str(self.code), "message": self.spec.message_fa}}
