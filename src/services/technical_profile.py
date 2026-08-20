"""Conversation-scoped technical context extracted from explicit user statements."""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.core.config import Settings, get_settings
from src.core.errors import ErrorCode, RescueError
from src.core.logging import get_logger
from src.core.normalization import normalize_query
from src.db.models import Conversation

logger = get_logger(__name__)
Executor = AsyncSession | AsyncConnection

TECHNICAL_PROFILE_FIELDS: frozenset[str] = frozenset(
    {
        "service",
        "runtime",
        "framework",
        "experience_level",
        "current_goal",
        "deployment_mode",
        "known_error",
    }
)

_VALUE_PATTERNS: Mapping[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "service": (
        ("paas", (r"\bpaas\b", r"پلتفرم")),
        ("dbaas", (r"\bdbaas\b", r"دیتابیس", r"پایگاه داده")),
        ("iaas", (r"\biaas\b", r"سرور ابری")),
        ("object-storage", (r"object[ -]?storage", r"فضای ابری")),
        ("dns", (r"\bdns\b", r"دامنه")),
        ("email", (r"email", r"ایمیل")),
    ),
    "runtime": (
        ("python", (r"\bpython\b", r"پایتون")),
        ("nodejs", (r"\bnode(?:\.js|js)?\b", r"نود(?:\.جی(?:‌| )?اس)?")),
        ("php", (r"\bphp\b",)),
        ("java", (r"\bjava\b", r"جاوا")),
        ("dotnet", (r"\b(?:dotnet|\.net)\b", r"دات[ -]?نت")),
        ("go", (r"\bgolang\b", r"\bgo\b", r"گولنگ")),
    ),
    "framework": (
        ("django", (r"\bdjango\b", r"جنگو")),
        ("flask", (r"\bflask\b", r"فلسک")),
        ("fastapi", (r"\bfastapi\b", r"فست[ -]?ای[ -]?پی[ -]?آی")),
        ("laravel", (r"\blaravel\b", r"لاراول")),
        ("nextjs", (r"\bnext(?:\.js|js)?\b", r"نکست(?:\.جی(?:‌| )?اس)?")),
    ),
    "deployment_mode": (
        ("docker", (r"\bdocker\b", r"داکر")),
        ("direct", (r"direct deploy", r"استقرار مستقیم")),
    ),
    "experience_level": (
        ("beginner", (r"\bbeginner\b", r"تازه[‌ ]?کار", r"تازه وارد")),
        ("experienced", (r"\bexperienced\b", r"با[‌ ]?تجربه")),
    ),
    "current_goal": (
        ("deploy", (r"\bdeploy(?:ment)?\b", r"استقرار", r"دیپلوی")),
        ("configure", (r"\bconfigur", r"تنظیم")),
        ("connect", (r"\bconnect", r"اتصال", r"وصل")),
        ("debug", (r"\bdebug", r"رفع خطا", r"عیب[‌ ]?یابی")),
    ),
}


def extract_explicit_technical_profile(
    user_message: str,
    *,
    settings: Settings | None = None,
) -> dict[str, str]:
    """Extract only explicitly named facts; absence never erases prior context."""
    settings = settings or get_settings()
    normalized = normalize_query(user_message)
    extracted: dict[str, str] = {}
    for field, candidates in _VALUE_PATTERNS.items():
        for value, patterns in candidates:
            if any(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in patterns):
                extracted[field] = value
                break
    if re.search(r"(?:\berror\b|\bexception\b|خطا|ارور)", normalized, flags=re.IGNORECASE):
        extracted["known_error"] = user_message.strip()[: settings.max_question_chars]
    return extracted


def sanitized_profile(profile: Mapping[str, Any]) -> dict[str, str]:
    return {
        key: str(value)
        for key, value in profile.items()
        if key in TECHNICAL_PROFILE_FIELDS and value not in (None, "")
    }


async def update_conversation_technical_profile(
    executor: Executor,
    conversation_id: uuid.UUID,
    user_message: str,
    *,
    settings: Settings | None = None,
) -> dict[str, str]:
    """Merge explicit facts into the conversation JSON and return the whole profile."""
    settings = settings or get_settings()
    try:
        row = (
            await executor.execute(
                select(Conversation.technical_profile)
                .where(Conversation.id == conversation_id)
                .with_for_update()
            )
        ).one_or_none()
        if row is None:
            raise RescueError(
                ErrorCode.INVALID_REQUEST,
                detail="technical profile conversation does not exist",
            )
        profile = sanitized_profile(row.technical_profile or {})
        profile.update(extract_explicit_technical_profile(user_message, settings=settings))
        await executor.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(technical_profile=profile, last_activity_at=func.now())
        )
    except RescueError:
        raise
    except SQLAlchemyError as err:
        raise RescueError(
            ErrorCode.INTERNAL_ERROR,
            detail="database failed while updating the conversation technical profile",
        ) from err
    logger.info(
        "conversation technical profile updated",
        extra={
            "conversation_id": str(conversation_id),
            "profile_fields": sorted(profile),
        },
    )
    return profile
