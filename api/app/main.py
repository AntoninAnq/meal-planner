"""FastAPI application.

A single façade for the frontend, routing internally to the workflows. No
separate API per technical workflow — endpoints are business-oriented
(docs/ARCHITECTURE.md §9).
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI

from app.config import get_settings
from app.routers import auth, households, members

settings = get_settings()

app = FastAPI(
    title="Meal Planner API",
    version="0.1.0",
    # Behind the proxy everything is served under /api on a single origin,
    # which keeps the session cookie first-party (§11.1).
    root_path="/api",
)

health = APIRouter(tags=["health"])


@health.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok", "environment": settings.environment}


app.include_router(health)
app.include_router(auth.router)
app.include_router(households.router)
app.include_router(members.router)
