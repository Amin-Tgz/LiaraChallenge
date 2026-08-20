"""Central registration for versioned API routes — one place, no scattered includes.

Health endpoints are deliberately not here: they are mounted at the root so the
platform's probes do not depend on an API version.
"""

from __future__ import annotations

from fastapi import APIRouter

from src.api.v1.faq import router as faq_router

api_router = APIRouter()
api_router.include_router(faq_router)
