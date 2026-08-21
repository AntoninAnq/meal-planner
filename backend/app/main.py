"""FastAPI application.

A single façade for the frontend, routing internally to the workflows. No
separate API per technical workflow — endpoints are business-oriented.
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI
from fastapi.exceptions import RequestValidationError

from app.config import get_settings
from app.errors import log_validation_error
from app.routers import auth, constraints, households, meal_plans, members

settings = get_settings()

app = FastAPI(
    title="Meal Planner API",
    version="0.1.0",
    # Behind the proxy everything is served under /api on a single origin,
    # which keeps the session cookie first-party.
    root_path="/api",
)

health = APIRouter(tags=["health"])


@health.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok", "environment": settings.environment}


# Registered rather than decorated: the handler lives in `app.errors`, which
# imports no configuration. A unit test of "does a 422 name its field" must not
# need a session secret to run — that is exactly how the CI broke.
app.add_exception_handler(RequestValidationError, log_validation_error)  # type: ignore[arg-type]

app.include_router(health)
app.include_router(auth.router)
app.include_router(households.router)
app.include_router(members.router)
app.include_router(constraints.router)
app.include_router(meal_plans.router)
