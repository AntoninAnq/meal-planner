"""The ceiling on what one household can spend on model calls.

Signing up is open — `provision_household` gives a household to any identity
that arrives — so this quota is the only thing standing between a stranger, or
a loop, and a metered API. It is a cost mechanism, and a cost mechanism nobody
tested is a cost mechanism that does not exist.

**The last test in this file is the one that matters most**, and it exists
because of a specific failure: on 2026-08-21, `skip_slot`, `time_budget` and
`repeat` were dead through the interface for a full day while 348 tests stayed
green. The logic was right; the WIRING was not, and nothing looked at the
wiring. So the rule is checked against the routing table itself — any endpoint
that reaches the model must sit behind the quota — rather than against a list
of endpoint names that would go stale the day someone adds one.

SQLite, not Postgres: CI runs without a database (`.github/workflows/ci.yml`),
and a guard that only runs on a developer's machine guards nothing.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.models import Base, GenerationLog, Household
from app.domain.enums import GenerationKind
from app.services.usage import calls_since, enforce_quota, record

LIMIT = 3
WINDOW_HOURS = 24


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite://")
    # Only the two tables involved. `Base.metadata.create_all` would drag in
    # the catalogue, whose JSONB columns have no SQLite equivalent.
    Base.metadata.create_all(engine, tables=[Household.__table__, GenerationLog.__table__])
    return sessionmaker(bind=engine)()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        session_secret="test",
        generation_daily_limit=LIMIT,
        generation_window_hours=WINDOW_HOURS,
    )


def _household(db: Session, name: str = "Mon foyer") -> uuid.UUID:
    household = Household(name=name)
    db.add(household)
    db.commit()
    return household.id


def _log(db: Session, household_id: uuid.UUID, *, hours_ago: float = 0, **kwargs: object) -> None:
    db.add(
        GenerationLog(
            household_id=household_id,
            created_at=datetime.now(UTC) - timedelta(hours=hours_ago),
            kind=GenerationKind.WEEK,
            **kwargs,  # type: ignore[arg-type]
        )
    )
    db.commit()


def test_a_household_under_the_limit_goes_through(db: Session, settings: Settings) -> None:
    household_id = _household(db)
    for _ in range(LIMIT - 1):
        _log(db, household_id)

    assert enforce_quota(household_id, db, settings) == household_id


def test_the_household_id_comes_back_so_it_replaces_the_other_dependency(
    db: Session, settings: Settings
) -> None:
    """`WithinQuota` is used INSTEAD of `CurrentHousehold`, never alongside it.

    Two dependencies would be two chances to wire one and forget the other, and
    the forgotten one is always the check. Returning the id is what lets an
    endpoint have only one.
    """
    household_id = _household(db)

    assert enforce_quota(household_id, db, settings) == household_id


def test_reaching_the_limit_refuses_with_429(db: Session, settings: Settings) -> None:
    household_id = _household(db)
    for _ in range(LIMIT):
        _log(db, household_id)

    with pytest.raises(HTTPException) as excinfo:
        enforce_quota(household_id, db, settings)

    assert excinfo.value.status_code == 429
    # The number and the window are named: a refusal saying only "too many
    # requests" reads, to whoever is looking at it, like the product is broken.
    assert str(LIMIT) in excinfo.value.detail
    assert str(WINDOW_HOURS) in excinfo.value.detail


def test_the_refusal_says_when_to_come_back(db: Session, settings: Settings) -> None:
    """`Retry-After` is the oldest call ageing out, not the whole window.

    Six hours in, a household that filled its quota gets its first slot back in
    eighteen — telling it twenty-four would be wrong by a quarter of a day.
    """
    household_id = _household(db)
    _log(db, household_id, hours_ago=6)
    for _ in range(LIMIT - 1):
        _log(db, household_id)

    with pytest.raises(HTTPException) as excinfo:
        enforce_quota(household_id, db, settings)

    retry_after = int((excinfo.value.headers or {})["Retry-After"])
    assert timedelta(hours=17) < timedelta(seconds=retry_after) < timedelta(hours=19)


def test_the_window_is_rolling_not_a_calendar_day(db: Session, settings: Settings) -> None:
    """A window that resets at midnight is a window someone waits out.

    Worse, it hands a household two full quotas back to back either side of the
    reset.
    """
    household_id = _household(db)
    _log(db, household_id, hours_ago=WINDOW_HOURS + 1)
    _log(db, household_id, hours_ago=WINDOW_HOURS - 1)

    since = datetime.now(UTC) - timedelta(hours=WINDOW_HOURS)
    assert calls_since(db, household_id, since) == 1


def test_a_failed_call_still_counts(db: Session, settings: Settings) -> None:
    """It cost tokens — more than a success, when three attempts were burnt.

    A quota that only counted successes would leave the cheapest way to spend an
    API key entirely uncounted.
    """
    household_id = _household(db)
    for _ in range(LIMIT):
        _log(db, household_id, succeeded=False, input_tokens=5886, output_tokens=1151)

    with pytest.raises(HTTPException) as excinfo:
        enforce_quota(household_id, db, settings)
    assert excinfo.value.status_code == 429


def test_one_household_never_consumes_another_s_quota(db: Session, settings: Settings) -> None:
    mine = _household(db, "Chez moi")
    theirs = _household(db, "Chez eux")
    for _ in range(LIMIT * 2):
        _log(db, theirs)

    assert enforce_quota(mine, db, settings) == mine


def test_record_writes_what_the_call_consumed(db: Session, settings: Settings) -> None:
    """Tokens and model id, because the bill is the other reason this exists.

    Without them the table answers "how many calls" and never "how many euros",
    which is the number pricing needs — and the one §14.6 needs to compare two
    models on anything but latency.
    """
    household_id = _household(db)

    record(
        db,
        household_id=household_id,
        kind=GenerationKind.WEEK,
        input_tokens=3490,
        output_tokens=640,
        attempts=1,
        model_id="claude-haiku-4-5",
    )

    row = db.query(GenerationLog).one()
    assert (row.input_tokens, row.output_tokens) == (3490, 640)
    assert row.model_id == "claude-haiku-4-5"
    assert row.succeeded is True
    assert row.kind == GenerationKind.WEEK


def test_every_endpoint_that_reaches_the_model_sits_behind_the_quota() -> None:
    """The guard that cannot go stale.

    Stated as a rule over the routing table — "uses the LLM" implies "checks the
    quota" — rather than as a list of paths. A list is a thing to forget on the
    day an endpoint is added, and forgetting it means an unmetered door onto a
    paid API that no other test would notice.

    The endpoints that call NO model are deliberately left alone: rating a
    dish, replacing one by hand or listing the alternatives the pre-filter
    already computed cost nothing, and rate-limiting them would only make the
    product worse for the household that is using it normally.
    """
    from app.llm.factory import get_llm_client
    from app.routers.meal_plans import router

    def called(dependant: object) -> set[object]:
        found = {getattr(dependant, "call", None)}
        for sub in getattr(dependant, "dependencies", []):
            found |= called(sub)
        return found

    checked: list[str] = []
    for route in router.routes:
        if not isinstance(route, APIRoute):
            continue
        dependencies = called(route.dependant)
        if get_llm_client not in dependencies:
            continue
        checked.append(route.path)
        assert enforce_quota in dependencies, (
            f"{route.path} calls the model without going through the quota"
        )

    # The rule is worthless if it matched nothing — which is what a renamed
    # dependency or a restructured router would look like from here.
    assert len(checked) >= 3, f"expected several model-calling endpoints, found {checked}"
