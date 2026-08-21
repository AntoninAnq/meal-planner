"""Turning a rejected request into something someone can act on.

Separate from `main.py` on purpose, and the reason is a CI failure: `main`
builds `Settings()` at import time, so anything importing it needs a full
environment — `session_secret` has no default, which is right for a secret and
fatal for a unit test. A test of "does a 422 name its field" has no business
requiring a session secret.

Nothing here reads configuration, touches a database, or knows about a route.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


def shape_of(value: Any) -> str:
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
        return f"list[{len(value)}] of {shape_of(value[0]) if value else '-'}"
    return type(value).__name__


async def log_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
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
        {key: shape_of(value) for key, value in body.items()},
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
