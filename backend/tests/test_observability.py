"""The household on the log line, and the one way it could silently not be.

The mechanism looks trivial and has one trap: `current_household_id` is a sync
dependency, so Starlette runs it in a worker thread on a COPY of the context. A
plain `ContextVar.set()` there is invisible to everything that logs afterwards
— the value would be absent precisely where it is wanted, with no error to say
so. The middleware installs a holder and the dependency fills it, and the test
below goes through a real threadpool rather than trusting that reasoning.

No database and no application: the pieces are exercised directly.
"""

from __future__ import annotations

import logging
import uuid

import pytest
from anyio import to_thread
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.observability import (
    ABSENT,
    HouseholdFilter,
    RequestContextMiddleware,
    bind_household,
    current_household,
)

HOUSEHOLD = uuid.UUID("335c58f8-2a24-42d3-9815-db48f39fb362")
CODE = "335C-58F8"


def _record() -> logging.LogRecord:
    record = logging.LogRecord("app", logging.WARNING, __file__, 1, "boom", None, None)
    HouseholdFilter().filter(record)
    return record


def test_outside_a_request_the_line_says_so_rather_than_failing() -> None:
    # Startup, the CLI, a unit test: there is no household and the format must
    # still resolve, because a logging error swallows the message it decorates.
    assert current_household() == ABSENT
    assert _record().household == ABSENT  # type: ignore[attr-defined]


def test_binding_outside_a_request_does_not_leak_into_the_next_one() -> None:
    # The reason the holder is `None` by default rather than `{}`: a shared
    # mutable default would keep this household and report it on every later
    # unbound request.
    bind_household(HOUSEHOLD)

    assert current_household() == ABSENT


def test_the_code_reaches_the_log_line_of_its_own_request() -> None:
    seen: list[str] = []

    def endpoint(request):  # type: ignore[no-untyped-def]
        bind_household(HOUSEHOLD)
        seen.append(current_household())
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/", endpoint)])
    app.add_middleware(RequestContextMiddleware)

    with TestClient(app) as client:
        client.get("/")

    assert seen == [CODE]


def test_it_survives_the_worker_thread_a_sync_dependency_runs_in() -> None:
    """The trap, exercised for real.

    `current_household_id` is a sync callable, so Starlette hands it to a
    worker thread with a copy of the context. What is written there has to be
    visible back in the request that logs.
    """
    seen: list[str] = []

    async def endpoint(request):  # type: ignore[no-untyped-def]
        # Exactly what Starlette does with a sync dependency.
        await to_thread.run_sync(lambda: bind_household(HOUSEHOLD))
        seen.append(current_household())
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/", endpoint)])
    app.add_middleware(RequestContextMiddleware)

    with TestClient(app) as client:
        client.get("/")

    assert seen == [CODE]


def test_one_request_does_not_inherit_the_previous_household() -> None:
    seen: list[str] = []

    async def bound(request):  # type: ignore[no-untyped-def]
        bind_household(HOUSEHOLD)
        return PlainTextResponse("ok")

    async def anonymous(request):  # type: ignore[no-untyped-def]
        seen.append(current_household())
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/in", bound), Route("/out", anonymous)])
    app.add_middleware(RequestContextMiddleware)

    with TestClient(app) as client:
        client.get("/in")
        client.get("/out")

    # A signed-out visitor reading the sign-in page must not be logged as the
    # household that was served just before them.
    assert seen == [ABSENT]


@pytest.mark.parametrize("scope_type", ["lifespan", "websocket"])
def test_a_non_http_scope_is_passed_through(scope_type: str) -> None:
    # The middleware must not swallow lifespan, or the app never starts.
    called: list[str] = []

    async def app(scope, receive, send):  # type: ignore[no-untyped-def]
        called.append(scope["type"])

    import anyio

    anyio.run(RequestContextMiddleware(app), {"type": scope_type}, None, None)

    assert called == [scope_type]
