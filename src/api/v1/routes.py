"""Central registration for versioned API routes — one place, no scattered includes.

Health endpoints are deliberately not here: they are mounted at the root so the
platform's probes do not depend on an API version.
"""

from __future__ import annotations

from fastapi import APIRouter

from src.api.v1.chat import router as chat_router
from src.api.v1.faq import router as faq_router
from src.api.v1.feedback import router as feedback_router
from src.api.v1.interactions import router as interactions_router
from src.api.v1.session import router as session_router

api_router = APIRouter()
api_router.include_router(chat_router)
api_router.include_router(faq_router)
api_router.include_router(feedback_router)
api_router.include_router(interactions_router)
api_router.include_router(session_router)
