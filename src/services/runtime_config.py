"""Tuning values an operator can change without a redeploy.

The FAQ similarity threshold is tuned against live traffic — you watch how many
real questions the FAQ stage resolves and move it — so a loop that costs a
deploy per turn is a loop nobody runs. This module lets a small, explicit set of
values be overridden in the database and read back on the next request.

Three deliberate limits:

* **Only allowlisted keys.** `_OVERRIDABLE` is the whole surface. Making every
  `Settings` field writable would turn an admin form into remote configuration
  of database URLs and API keys.
* **Every value is validated on write**, against the same bounds the environment
  is validated against. A threshold of 5.0 is not a bad setting, it is one that
  silently suppresses every FAQ match, and the write is where that is cheap to
  refuse.
* **An absent row means the environment value stands.** The deployed
  configuration remains the default; this table records only deliberate
  departures from it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from src.core.config import Settings, get_settings
from src.core.errors import ErrorCode, RescueError
from src.core.logging import get_logger
from src.db.models import RuntimeSetting

logger = get_logger(__name__)
Executor = AsyncSession | AsyncConnection


@dataclass(frozen=True, slots=True)
class OverridableSetting:
    """One tuning value an operator may change, and what a valid change is."""

    key: str
    kind: Callable[[Any], Any]
    minimum: float
    maximum: float
    description: str

    def parse(self, raw: Any) -> Any:
        try:
            value = self.kind(raw)
        except (TypeError, ValueError) as err:
            raise RescueError(
                ErrorCode.INVALID_REQUEST,
                detail=f"{self.key} must be a {self.kind.__name__}, got {raw!r}",
            ) from err
        if not self.minimum <= value <= self.maximum:
            raise RescueError(
                ErrorCode.INVALID_REQUEST,
                detail=(
                    f"{self.key} must be between {self.minimum} and {self.maximum}, " f"got {value}"
                ),
            )
        return value


#: The complete set of runtime-overridable values. Retrieval tuning only —
#: nothing here can reach a credential, an endpoint, or a model id.
_OVERRIDABLE: Mapping[str, OverridableSetting] = MappingProxyType(
    {
        setting.key: setting
        for setting in (
            OverridableSetting(
                key="faq_similarity_threshold",
                kind=float,
                # Cosine similarity, never distance (RULES.md §2). Zero would
                # match everything; one would match only an exact vector.
                minimum=0.0,
                maximum=1.0,
                description=(
                    "Minimum cosine similarity for a FAQ entry to be offered as a "
                    "related question. Lower matches more and risks irrelevance; "
                    "higher sends more users past the FAQ stage to the rescue tools."
                ),
            ),
            OverridableSetting(
                key="retrieval_similarity_threshold",
                kind=float,
                minimum=0.0,
                maximum=1.0,
                description=(
                    "Minimum cosine similarity for a documentation chunk to count as "
                    "evidence. Below this the answer abstains with "
                    "NO_RESULTS_ABOVE_THRESHOLD."
                ),
            ),
            OverridableSetting(
                key="faq_top_k",
                kind=int,
                minimum=1,
                maximum=50,
                description="How many related questions to offer at most.",
            ),
            OverridableSetting(
                key="retrieval_top_k",
                kind=int,
                minimum=1,
                maximum=50,
                description="How many documentation chunks to retrieve as evidence.",
            ),
            OverridableSetting(
                key="faq_priority_weight",
                kind=float,
                minimum=0.0,
                maximum=1.0,
                description=(
                    "How much an operator's curated priority moves a FAQ entry's "
                    "ordering, on top of its similarity."
                ),
            ),
        )
    }
)


def describe_overridable() -> list[dict[str, Any]]:
    """The admin form's field list, with bounds and the deployed default."""
    environment = Settings(_env_file=None)  # type: ignore[call-arg]
    return [
        {
            "key": setting.key,
            "type": setting.kind.__name__,
            "minimum": setting.minimum,
            "maximum": setting.maximum,
            "description": setting.description,
            "default": getattr(environment, setting.key),
        }
        for setting in _OVERRIDABLE.values()
    ]


async def load_overrides(executor: Executor) -> dict[str, Any]:
    """Every stored override, ignoring keys no longer overridable.

    A key dropped from `_OVERRIDABLE` in a later release leaves its row behind.
    Skipping it is deliberate: refusing to start because an obsolete row exists
    would turn a tidy-up into an outage.
    """
    try:
        rows = await executor.execute(select(RuntimeSetting.key, RuntimeSetting.value))
    except SQLAlchemyError as err:
        # Configuration is an optimization over the environment, never a
        # dependency of it. A database blip must not take down retrieval.
        logger.warning(
            "runtime overrides unavailable; using environment configuration",
            extra={"cause": type(err).__name__},
        )
        return {}

    overrides: dict[str, Any] = {}
    for key, stored in rows:
        setting = _OVERRIDABLE.get(key)
        if setting is None:
            continue
        try:
            overrides[key] = setting.parse((stored or {}).get("value"))
        except RescueError:
            # A row that no longer validates — bounds tightened in a release,
            # say — is skipped rather than allowed to break every request.
            logger.warning("stored runtime override is invalid; ignoring", extra={"key": key})
    return overrides


async def effective_settings(executor: Executor, base: Settings | None = None) -> Settings:
    """Environment configuration with operator overrides applied on top."""
    base = base or get_settings()
    overrides = await load_overrides(executor)
    if not overrides:
        return base
    return base.model_copy(update=overrides)


async def set_override(
    executor: Executor,
    key: str,
    raw_value: Any,
    *,
    updated_by: str | None = None,
    note: str | None = None,
) -> Any:
    """Validate and store one override, returning the value actually stored."""
    setting = _OVERRIDABLE.get(key)
    if setting is None:
        raise RescueError(
            ErrorCode.INVALID_REQUEST,
            detail=(
                f"{key!r} is not runtime-configurable; "
                f"overridable keys are {', '.join(sorted(_OVERRIDABLE))}"
            ),
        )
    value = setting.parse(raw_value)

    statement = (
        pg_insert(RuntimeSetting.__table__)
        .values(key=key, value={"value": value}, updated_by=updated_by, note=note)
        .on_conflict_do_update(
            index_elements=[RuntimeSetting.key],
            set_={"value": {"value": value}, "updated_by": updated_by, "note": note},
        )
    )
    await executor.execute(statement)
    logger.info(
        "runtime override set",
        extra={"key": key, "value": value, "updated_by": updated_by},
    )
    return value


async def clear_override(executor: Executor, key: str) -> bool:
    """Drop one override so the environment value stands again."""
    if key not in _OVERRIDABLE:
        raise RescueError(
            ErrorCode.INVALID_REQUEST,
            detail=f"{key!r} is not runtime-configurable",
        )
    result = await executor.execute(
        RuntimeSetting.__table__.delete().where(RuntimeSetting.key == key)
    )
    removed = bool(result.rowcount)
    if removed:
        logger.info("runtime override cleared", extra={"key": key})
    return removed
