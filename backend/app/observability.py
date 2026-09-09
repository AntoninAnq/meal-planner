"""Putting the household on every log line of its own request.

The problem this exists for is narrow: a household reports a bug, gives its
support code, and the operator needs the log lines that belong to it. The
database half of that already worked — everything joins on `household_id` — but
the application log did not carry one, so a stack trace could only be found by
guessing at a timestamp, and two households using the product the same evening
were indistinguishable.

**Why a mutable holder and not a plain `ContextVar[UUID]`.** The household is
resolved by `current_household_id`, which is a *sync* dependency: Starlette runs
those in a worker thread, on a COPY of the context. A `ContextVar.set()` inside
that copy is invisible to the endpoint, to the exception handlers, and to
everything that logs — the value would be silently absent exactly where it is
wanted. So the middleware installs one dict per request, and the dependency
fills that dict in. The copy carries a reference to the same object, so the
write is seen everywhere. This is subtle enough that `test_observability`
exercises it through a real threadpool rather than trusting the reasoning.

The filter, not the call sites. Every logger already in the codebase and every
one added later carries the household without its author doing anything: a
convention that has to be remembered at each `logger.warning` is a convention
that is eventually forgotten, and the line that gets forgotten is the one being
hunted at 2 a.m.
"""

from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar
from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send

from app.domain.support_code import support_code

#: One dict per request, installed by the middleware and filled by the
#: dependency. `None` outside a request — startup, the CLI, a unit test.
#:
#: Not `default={}`: a mutable default is ONE dict shared by every context that
#: never installed its own, so a `bind_household` outside a request would write
#: a household into it and every later unbound request would report that one.
#: The absence of a request has to be its own value.
_request: ContextVar[dict[str, Any] | None] = ContextVar("request_context", default=None)

#: What a log line says when there is no household: an unauthenticated call,
#: the health check, anything at startup. A dash rather than "None" because a
#: log is read by eye first.
ABSENT = "-"


def bind_household(household_id: uuid.UUID) -> None:
    """Called once per authenticated request, from the one place that resolves
    a household. Silently does nothing outside a request, which is what lets
    the same dependency run under the test client and the CLI."""
    context = _request.get()
    if context is not None:
        context["household_id"] = household_id
        context["support_code"] = support_code(household_id)


def current_household() -> str:
    """The support code of the household this request belongs to, or `-`.

    The CODE and not the raw id: it is what the operator was given by the
    person reporting the problem, so it is what should be greppable. The id is
    one `admin find` away and the log is read before it is queried.
    """
    context = _request.get()
    return str(context.get("support_code", ABSENT)) if context else ABSENT


class HouseholdFilter(logging.Filter):
    """Adds `household` to every record, present or not.

    A filter rather than a formatter: a missing attribute makes `%(household)s`
    raise inside logging itself, and a logging error swallows the very message
    it was decorating.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.household = current_household()  # type: ignore[attr-defined]
        return True


class RequestContextMiddleware:
    """Installs a fresh holder for each request.

    Pure ASGI rather than `BaseHTTPMiddleware`: the latter runs the downstream
    app in a separate task, which is one more context boundary between the
    dependency that writes and the handler that reads.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token = _request.set({})
        try:
            await self.app(scope, receive, send)
        finally:
            _request.reset(token)


def configure_logging(level: str = "INFO") -> None:
    """Attach the filter to the root handler, once, at startup.

    Configured here rather than left to uvicorn's default so the household
    actually reaches the format string. Idempotent: re-running it replaces the
    handler instead of stacking a second one that prints everything twice.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(household)s] %(name)s — %(message)s")
    )
    handler.addFilter(HouseholdFilter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # uvicorn installs its own handlers on these; leaving them propagating as
    # well would print every request line twice, once with the household and
    # once without.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = [handler]
        logger.propagate = False
