"""Admin authentication: what it refuses, and what it refuses to disclose."""

from __future__ import annotations

import base64

import httpx
import pytest

from src.core.config import Settings, get_settings
from src.main import create_app

ADMIN_PATHS = (
    "/api/v1/admin/faq",
    "/api/v1/admin/config",
    "/api/v1/admin/dashboard",
    "/api/v1/admin/sync",
    "/api/v1/admin/index-versions",
)


def _auth_header(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture
def configured_admin(monkeypatch: pytest.MonkeyPatch):
    """An app whose admin credentials are set, without touching the real ones."""

    def _settings() -> Settings:
        return Settings(  # type: ignore[call-arg]
            _env_file=None,
            admin_username="operator",
            admin_password="correct horse battery staple",
        )

    app = create_app()
    app.dependency_overrides[get_settings] = _settings
    return app


async def _get(app, path: str, headers: dict[str, str] | None = None) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(path, headers=headers or {})


@pytest.mark.parametrize("path", ADMIN_PATHS)
async def test_every_admin_route_refuses_an_unauthenticated_request(
    configured_admin, path: str
) -> None:
    response = await _get(configured_admin, path)
    assert response.status_code == 401


@pytest.mark.parametrize("path", ADMIN_PATHS)
async def test_a_refusal_discloses_no_administrative_data(configured_admin, path: str) -> None:
    response = await _get(configured_admin, path)
    body = response.text.lower()
    # Nothing about the corpus, the configuration, or the credentials may leak
    # into a 401 — including the configured username.
    for leaked in ("operator", "correct horse", "faq_similarity", "source_commit", "chunk"):
        assert leaked not in body, leaked


async def test_the_challenge_is_sent_so_a_browser_can_prompt(configured_admin) -> None:
    response = await _get(configured_admin, "/api/v1/admin/config")
    assert response.headers.get("www-authenticate", "").startswith("Basic")


async def test_a_wrong_password_is_refused(configured_admin) -> None:
    response = await _get(
        configured_admin, "/api/v1/admin/config", _auth_header("operator", "wrong")
    )
    assert response.status_code == 401


async def test_a_wrong_username_is_refused_identically_to_a_wrong_password(
    configured_admin,
) -> None:
    # Identical responses, or the difference tells a prober which half was right.
    wrong_user = await _get(
        configured_admin,
        "/api/v1/admin/config",
        _auth_header("nobody", "correct horse battery staple"),
    )
    wrong_password = await _get(
        configured_admin, "/api/v1/admin/config", _auth_header("operator", "nope")
    )
    assert wrong_user.status_code == wrong_password.status_code == 401
    assert wrong_user.text == wrong_password.text


async def test_an_unconfigured_admin_surface_is_closed_not_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The failure mode worth preventing: a deployment that forgot the variables
    # exposing FAQ deletion and the dashboard to the internet.
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(  # type: ignore[call-arg]
        _env_file=None, admin_username="", admin_password=""
    )
    response = await _get(app, "/api/v1/admin/config", _auth_header("", ""))
    assert response.status_code == 401


async def test_correct_credentials_are_accepted(configured_admin) -> None:
    response = await _get(
        configured_admin,
        "/api/v1/admin/config",
        _auth_header("operator", "correct horse battery staple"),
    )
    assert response.status_code == 200
    assert "fields" in response.json()


async def test_the_rescue_flow_needs_no_login(configured_admin) -> None:
    # v1 introduces no end-user authentication; guarding admin must not have
    # leaked a credential requirement into the user-facing product.
    response = await _get(configured_admin, "/health/live")
    assert response.status_code == 200
