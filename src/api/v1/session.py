"""The caller's own anonymous session identity.

The session cookie is `httpOnly`, which is what keeps a stolen script from
reading it — but the FAQ, feedback, and interaction endpoints all take a
`session_id` in their body, and the browser cannot read the cookie to supply
it. This endpoint closes that gap without weakening the cookie: the server
resolves the session it already trusts and tells the client its id.

Calling it also establishes a session, so the landing view can record an
impression on the very first question rather than on the second.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_session
from src.services.sessions import resolve_session

router = APIRouter(tags=["session"])


class SessionResponse(BaseModel):
    session_id: uuid.UUID


@router.get("/session", response_model=SessionResponse)
async def current_session(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_session)],
) -> SessionResponse:
    session = await resolve_session(db, request, response)
    return SessionResponse(session_id=session.id)
