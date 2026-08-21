"""The production startup order is part of schema compatibility."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from src.main import create_app

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


@pytest.mark.asyncio
async def test_static_cache_headers_keep_bundles_fast_and_shell_revalidatable() -> None:
    app = create_app()
    asset = next((Path("web/dist/assets")).glob("index-*.js")).name
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        bundle = await client.get(f"/assets/{asset}")
        image = await client.get("/images/logoLiara.png")
        shell = await client.get("/")
        worker = await client.get("/service-worker.js")

    assert bundle.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert "max-age=2592000" in image.headers["cache-control"]
    assert shell.headers["cache-control"] == "no-cache"
    assert worker.headers["cache-control"] == "no-cache"
