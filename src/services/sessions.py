"""Anonymous, cookie-scoped sessions.

There is no end-user auth in v1, but a returning tab still has to find its own
conversations. A signed-out visitor gets an opaque UUID in a `SameSite=Lax`
cookie — same-origin, because the web bundle is served from the API — and every
conversation hangs off it.

The client address is never stored. Only a salted digest is kept, and only
because rate limiting and abuse investigation need to tell two visitors apart.
A digest cannot be turned back into an address, so a database leak does not
become a list of who read which documentation page.
"""

from __future__ import annotations

import hashlib
import uuid

from fastapi import Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import Settings, get_settings
from src.db.models.conversation import AnonymousSession


def client_fingerprint(request: Request, *, settings: Settings | None = None) -> str | None:
    """A stable, non-reversible identifier for the caller."""
    settings = settings or get_settings()
    client = request.client
    # X-Forwarded-For is set by Liara's router; the first hop is the real client.
    forwarded = request.headers.get("x-forwarded-for", "")
    address = forwarded.split(",")[0].strip() or (client.host if client else "")
    if not address:
        return None
    # Salted with a deployment secret so the digests are not a rainbow-table
    # lookup of every IPv4 address.
    salt = settings.admin_password or settings.app_env
    return hashlib.sha256(f"{salt}:{address}".encode()).hexdigest()


def _cookie_session_id(request: Request, *, settings: Settings) -> uuid.UUID | None:
    raw = request.cookies.get(settings.session_cookie_name)
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        # A malformed cookie is treated as no cookie; the visitor simply gets a
        # new session rather than an error they cannot act on.
        return None


async def resolve_session(
    db: AsyncSession,
    request: Request,
    response: Response,
    *,
    settings: Settings | None = None,
) -> AnonymousSession:
    """Return the caller's session, creating and setting one if needed."""
    settings = settings or get_settings()
    fingerprint = client_fingerprint(request, settings=settings)

    session_id = _cookie_session_id(request, settings=settings)
    existing = await db.get(AnonymousSession, session_id) if session_id else None
    if existing is not None:
        existing.client_fingerprint = fingerprint or existing.client_fingerprint
        await db.flush()
        # Re-set so an active visitor's cookie does not quietly expire mid-use.
        _set_cookie(response, existing.id, settings=settings)
        return existing

    created = AnonymousSession(id=uuid.uuid4(), client_fingerprint=fingerprint)
    db.add(created)
    await db.flush()
    _set_cookie(response, created.id, settings=settings)
    return created


def _set_cookie(response: Response, session_id: uuid.UUID, *, settings: Settings) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=str(session_id),
        max_age=settings.session_cookie_max_age_seconds,
        httponly=True,
        # Same-origin delivery means Lax is sufficient; None would require
        # Secure everywhere and buy nothing here.
        samesite="lax",
        secure=settings.app_env == "production",
        path="/",
    )
