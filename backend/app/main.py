"""FastAPI application.

A single façade for the frontend, routing internally to the workflows. No
separate API per technical workflow — endpoints are business-oriented.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.routers import auth, constraints, households, meal_plans, members

settings = get_settings()

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Meal Planner API",
    version="0.1.0",
    # Behind the proxy everything is served under /api on a single origin,
    # which keeps the session cookie first-party.
    root_path="/api",
)

def _shape(value: Any) -> str:
    """The SHAPE of what arrived, never the value.

    A rejected body carries dietary constraints, which are health data (GDPR
    art. 9) — so the log says `str` or `dict{type,week_start}` and never what
    was written. That is also all a diagnosis needs: this handler exists
    because `scope` arriving as a string and `scope` arriving as null produce
    the same sentence, and neither says which field it was about.
    """
    if isinstance(value, dict):
        return f"dict{{{','.join(sorted(map(str, value))[:6])}}}"
    if isinstance(value, list):
        return f"list[{len(value)}] of {_shape(value[0]) if value else '-'}"
    return type(value).__name__


@app.exception_handler(RequestValidationError)
async def _log_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Name the field, in the log and in the response.

    FastAPI's default answer is the errors alone, and the frontend shows the
    first `msg` — which for a discriminated union reads "Input should be a
    valid dictionary or object to extract fields from" with nothing saying
    WHICH field. A 422 nobody can locate costs an afternoon; this costs six
    lines.
    """
    body = exc.body if isinstance(exc.body, dict) else {}
    logger.warning(
        "422 on %s %s — fields %s — body shape %s",
        request.method,
        request.url.path,
        [".".join(str(part) for part in error["loc"]) for error in exc.errors()],
        {key: _shape(value) for key, value in body.items()},
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "detail": [
                # `field` is added rather than `msg` rewritten: the shape stays
                # the one every existing client already parses. `input` and
                # `ctx` are dropped — the first echoes the rejected value back,
                # the second can hold an exception object that will not
                # serialise, and neither helps anyone reading the message.
                {
                    "type": error["type"],
                    "loc": list(error["loc"]),
                    "msg": error["msg"],
                    "field": ".".join(str(part) for part in error["loc"]),
                }
                for error in exc.errors()
            ]
        },
    )


health = APIRouter(tags=["health"])


@health.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok", "environment": settings.environment}


app.include_router(health)
app.include_router(auth.router)
app.include_router(households.router)
app.include_router(members.router)
app.include_router(constraints.router)
app.include_router(meal_plans.router)
