"""ASGI entry point.

The built web bundle is served from this same origin, so cookies need only
`SameSite=Lax` and there is no credentialed CORS to configure. API routes are
namespaced under `/api/v1` and the SPA catch-all never shadows them.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.routing import Route

from src.api.health import router as health_router
from src.api.v1.routes import api_router
from src.core.config import get_settings
from src.core.errors import ErrorCode, RescueError, spec_for
from src.core.logging import (
    clear_correlation,
    configure_logging,
    get_logger,
    set_correlation,
    shutdown_telemetry_logging,
)
from src.mcp.server import build_mcp_asgi_app, build_mcp_server
from src.services.metrics import PrometheusMiddleware, prometheus_response

logger = get_logger(__name__)

API_PREFIX = "/api/v1"

#: Where MCP hosts connect. Kept out of `/api/v1` on purpose: the MCP protocol
#: carries its own versioning, and pinning it to this project's REST version
#: would force a protocol move every time an unrelated endpoint changed shape.
MCP_PREFIX = "/mcp"

#: Paths the SPA catch-all must never answer for.
_RESERVED_PREFIXES = (
    "api/",
    "health/",
    "metrics",
    "mcp",
    "skill/",
    "docs",
    "redoc",
    "openapi.json",
    "assets/",
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("api starting", extra={"app_env": get_settings().app_env})
    # Starlette does not run the lifespan of a mounted sub-application, so the
    # MCP session manager has to be entered here. Without this the endpoint
    # mounts and accepts connections, then fails on the first tool call — a
    # failure that looks like a broken tool rather than a server that never
    # started.
    mcp = getattr(app.state, "mcp_server", None)
    if mcp is None:
        yield
        return
    async with mcp.session_manager.run():
        yield
    from src.db.session import dispose_engine
    from src.services.redis_client import close_redis

    # Graceful shutdown: stop accepting work and release dependencies so
    # clients reconnect rather than hang.
    await close_redis()
    await dispose_engine()
    logger.info("api stopped")
    shutdown_telemetry_logging()


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()
    app = FastAPI(
        title="Liara Assistant",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
    )
    app.add_middleware(PrometheusMiddleware)
    if settings.metrics_enabled:
        app.add_api_route(
            settings.metrics_path,
            prometheus_response,
            methods=["GET"],
            include_in_schema=False,
        )

    @app.middleware("http")
    async def correlate(request: Request, call_next):  # type: ignore[no-untyped-def]
        clear_correlation()
        trace_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        set_correlation(trace_id=trace_id)
        response = await call_next(request)
        response.headers["x-request-id"] = trace_id
        path = request.url.path
        if path.startswith("/assets/"):
            response.headers["cache-control"] = "public, max-age=31536000, immutable"
        elif path.startswith(("/images/", "/brand/")):
            response.headers["cache-control"] = (
                "public, max-age=2592000, stale-while-revalidate=86400"
            )
        elif path in {"/", "/index.html", "/service-worker.js"}:
            response.headers["cache-control"] = "no-cache"
        return response

    @app.exception_handler(RescueError)
    async def rescue_error_handler(_: Request, err: RescueError) -> JSONResponse:
        logger.warning(
            "request failed",
            extra={"error_code": str(err.code), "cause": err.detail, **err.context},
        )
        return JSONResponse(status_code=err.http_status, content=err.to_response())

    @app.exception_handler(Exception)
    async def unhandled_handler(_: Request, err: Exception) -> JSONResponse:
        # Never surface a stack trace or a provider error to a user.
        logger.exception("unhandled error", extra={"error_code": str(ErrorCode.INTERNAL_ERROR)})
        spec = spec_for(ErrorCode.INTERNAL_ERROR)
        return JSONResponse(
            status_code=spec.http_status,
            content={"error": {"code": str(spec.code), "message": spec.message_fa}},
        )

    app.include_router(health_router)
    app.include_router(api_router, prefix=API_PREFIX)

    @app.get("/skill/SKILL.md", include_in_schema=False, response_model=None)
    async def download_skill() -> FileResponse:
        skill_path = Path(settings.skill_file_path)
        if not skill_path.is_file():
            raise RescueError(
                ErrorCode.SKILL_NOT_AVAILABLE,
                detail=f"configured Skill file does not exist: {skill_path}",
            )
        return FileResponse(
            skill_path,
            media_type="text/markdown; charset=utf-8",
            filename="liara-docs-rescue-SKILL.md",
        )

    mcp = build_mcp_server()
    app.state.mcp_server = mcp
    mcp_asgi = build_mcp_asgi_app(mcp)
    # Both spellings, deliberately. Starlette's `Mount` only matches a path with
    # something after it, so a mount alone serves `/mcp/` and lets bare `/mcp`
    # fall through to the SPA catch-all — which, being GET-only, answers a host's
    # POST with 405. Hosts are configured with the bare path far more often than
    # the trailing-slash one, so the exact route is registered too, before the
    # catch-all exists to shadow it.
    app.router.routes.append(Route(MCP_PREFIX, endpoint=mcp_asgi))
    app.mount(MCP_PREFIX, mcp_asgi)

    _mount_web(app, Path(settings.web_dist_dir))
    return app


def _mount_web(app: FastAPI, dist: Path) -> None:
    """Serve the Vite build with an SPA catch-all.

    Registered last so `/api/v1/*` and `/health/*` always win. A missing bundle
    is not fatal — the API is useful without it during development.
    """
    index = dist / "index.html"
    if not index.is_file():
        logger.warning("web bundle not found; SPA routes disabled", extra={"dist": str(dist)})
        return

    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False, response_model=None)
    async def spa(full_path: str) -> FileResponse | JSONResponse:
        if full_path.startswith(_RESERVED_PREFIXES):
            spec = spec_for(ErrorCode.INVALID_REQUEST)
            return JSONResponse(
                status_code=404,
                content={"error": {"code": str(spec.code), "message": spec.message_fa}},
            )
        candidate = (dist / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(dist.resolve()):
            return FileResponse(candidate)
        return FileResponse(index)


app = create_app()
