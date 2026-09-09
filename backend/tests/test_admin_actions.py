"""The operator commands, exercised without a terminal.

These are the verbs you reach for on a bad night — someone is burning the
budget, or should not be here any more — which is exactly when a code path
nobody ever ran is worst. Revocation in particular has a subtlety a cleanup
could undo: the access row must SURVIVE, because `callback` provisions a new
household precisely when it finds none.

SQLite, like the quota and revocation suites: CI runs without a database.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.admin.actions import (
    UnknownHousehold,
    UnknownSubject,
    restore,
    revoke,
    set_limit,
    survey,
)
from app.config import Settings
from app.db.models import Base, GenerationLog, Household, HouseholdAccess, Member
from app.domain.enums import GenerationKind
from app.services.usage import limit_for

SUBJECT = "google:117482000000000000000"
TABLES = [
    Household.__table__,
    HouseholdAccess.__table__,
    Member.__table__,
    GenerationLog.__table__,
]


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=TABLES)
    return sessionmaker(bind=engine)()


def _household(db: Session, name: str = "Mon foyer", subject: str = SUBJECT) -> uuid.UUID:
    household = Household(name=name)
    db.add(household)
    db.flush()
    db.add(HouseholdAccess(auth_subject=subject, household_id=household.id))
    db.commit()
    return household.id


def _burn(db: Session, household_id: uuid.UUID, calls: int, *, hours_ago: float = 0.0) -> None:
    for _ in range(calls):
        db.add(
            GenerationLog(
                household_id=household_id,
                kind=GenerationKind.WEEK,
                created_at=datetime.now(UTC) - timedelta(hours=hours_ago),
            )
        )
    db.commit()


# -- Seeing who is here ------------------------------------------------------


def test_the_survey_puts_the_biggest_spender_first(db: Session) -> None:
    quiet = _household(db, "Foyer calme", "google:1")
    loud = _household(db, "Foyer bruyant", "google:2")
    _burn(db, quiet, 2)
    _burn(db, loud, 9)

    rows = survey(db, window_hours=24)

    # The reason to run this is "who is burning the budget"; alphabetical would
    # make the operator read the whole list to find the one row that matters.
    assert [row.household_id for row in rows] == [loud, quiet]
    assert rows[0].calls_in_window == 9


def test_the_survey_ignores_calls_older_than_the_window(db: Session) -> None:
    household_id = _household(db)
    _burn(db, household_id, 5, hours_ago=48)

    assert survey(db, window_hours=24)[0].calls_in_window == 0


def test_the_survey_separates_live_identities_from_revoked_ones(db: Session) -> None:
    household_id = _household(db)
    db.add(HouseholdAccess(auth_subject="google:9", household_id=household_id))
    db.commit()
    revoke(db, "google:9")

    row = survey(db, window_hours=24)[0]

    assert row.subjects == (SUBJECT,)
    assert row.revoked == ("google:9",)


# -- Closing the door --------------------------------------------------------


def test_revoking_keeps_the_row_so_the_identity_cannot_re_register(db: Session) -> None:
    _household(db)

    revoke(db, SUBJECT)

    row = db.scalar(select(HouseholdAccess).where(HouseholdAccess.auth_subject == SUBJECT))
    # Deleting would hand the very identity that was cut off a brand-new
    # household on its next login. This is the whole mechanism.
    assert row is not None
    assert row.revoked_at is not None


def test_revoking_twice_keeps_the_first_moment(db: Session) -> None:
    _household(db)
    revoke(db, SUBJECT)
    first = db.scalar(select(HouseholdAccess.revoked_at))

    revoke(db, SUBJECT)

    # When someone was cut off is a fact; the second command is a typo.
    assert db.scalar(select(HouseholdAccess.revoked_at)) == first


def test_restoring_puts_the_identity_back_on_its_own_household(db: Session) -> None:
    household_id = _household(db)
    revoke(db, SUBJECT)

    restore(db, SUBJECT)

    row = db.scalar(select(HouseholdAccess).where(HouseholdAccess.auth_subject == SUBJECT))
    assert row is not None and row.revoked_at is None
    assert row.household_id == household_id


def test_an_unknown_subject_is_named_rather_than_silently_ignored(db: Session) -> None:
    with pytest.raises(UnknownSubject):
        revoke(db, "google:nobody")


# -- Bounding the spend ------------------------------------------------------


def _settings() -> Settings:
    return Settings.model_construct(generation_daily_limit=50, generation_window_hours=24)


def test_a_household_without_an_override_is_on_the_rate_card(db: Session) -> None:
    household_id = _household(db)

    assert limit_for(db, _settings(), household_id) == 50


def test_a_paid_tier_is_a_high_ceiling_not_the_absence_of_one(db: Session) -> None:
    household_id = _household(db)

    set_limit(db, household_id, 5000)

    assert limit_for(db, _settings(), household_id) == 5000


def test_zero_is_a_value_and_it_stops_the_spend(db: Session) -> None:
    household_id = _household(db)

    set_limit(db, household_id, 0)

    # The softest useful sanction: nothing new is generated, and the weeks
    # already there stay readable. Not the same act as revoking.
    assert limit_for(db, _settings(), household_id) == 0


def test_clearing_the_override_returns_to_the_rate_card(db: Session) -> None:
    household_id = _household(db)
    set_limit(db, household_id, 0)

    set_limit(db, household_id, None)

    assert limit_for(db, _settings(), household_id) == 50


def test_a_negative_ceiling_is_refused(db: Session) -> None:
    household_id = _household(db)

    with pytest.raises(ValueError):
        set_limit(db, household_id, -1)


def test_an_unknown_household_is_named(db: Session) -> None:
    with pytest.raises(UnknownHousehold):
        set_limit(db, uuid.uuid4(), 10)
