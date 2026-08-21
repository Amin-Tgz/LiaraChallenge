"""The production startup order is part of schema compatibility."""

from __future__ import annotations

from pathlib import Path

ENTRYPOINT = Path(__file__).parents[2] / "docker" / "entrypoint.sh"
MAIN_CASE = 'case "${APP_ROLE:-api}" in'


def _role_branch(script: str, role: str, next_role: str) -> str:
    case_start = script.rindex(MAIN_CASE)
    start = script.index(f"  {role})", case_start)
    end = script.index(f"  {next_role})", start)
    return script[start:end]


def test_api_migrates_before_accepting_traffic() -> None:
    script = ENTRYPOINT.read_text(encoding="utf-8")
    api = _role_branch(script, "api", "worker")

    assert api.index("alembic upgrade head") < api.index("exec uvicorn")


def test_worker_does_not_race_api_for_migrations() -> None:
    script = ENTRYPOINT.read_text(encoding="utf-8")
    worker = _role_branch(script, "worker", "*")

    assert "alembic" not in worker
    assert "exec python -m src.worker" in worker


def test_health_probe_never_runs_migrations() -> None:
    script = ENTRYPOINT.read_text(encoding="utf-8")
    probe = script[: script.rindex(MAIN_CASE)]

    assert "alembic upgrade head" not in probe
