from __future__ import annotations

from src.core.config import Settings
from src.services.technical_profile import (
    TECHNICAL_PROFILE_FIELDS,
    extract_explicit_technical_profile,
    sanitized_profile,
)


def test_explicit_runtime_framework_and_mode_are_extracted() -> None:
    profile = extract_explicit_technical_profile(
        "پروژه Django من با Python و Docker روی PaaS deploy می‌شود.",
        settings=Settings(_env_file=None),
    )

    assert profile == {
        "service": "paas",
        "runtime": "python",
        "framework": "django",
        "deployment_mode": "docker",
        "current_goal": "deploy",
    }


def test_absent_detail_does_not_fabricate_a_profile_value() -> None:
    assert (
        extract_explicit_technical_profile(
            "برنامه بالا نمی‌آید؛ چه چیزی را بررسی کنم؟",
            settings=Settings(_env_file=None),
        )
        == {}
    )


def test_only_the_session_technical_fields_survive() -> None:
    sanitized = sanitized_profile(
        {"runtime": "python", "name": "personal name", "email": "person@example.test"}
    )

    assert set(sanitized) <= TECHNICAL_PROFILE_FIELDS
    assert sanitized == {"runtime": "python"}
