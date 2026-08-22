"""Cutting an identity off, and keeping it off.

The pendant of the quota: that one bounds what a household SPENDS, this one
closes the door on a household that should no longer have one. Both exist
because signing up is open by design (`ARCHITECTURE.md` §11.7).

The second test is the one with teeth. Revocation that can be undone by
clicking "sign in with Google" again is not revocation, and the mechanism that
prevents it is subtle enough to be broken by a well-meaning cleanup: the access
row must SURVIVE, because `callback` provisions a new household exactly when it
finds none.

SQLite, like the quota tests: CI runs without a database.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.auth.deps import current_household_id
from app.db.models import Base, Household, HouseholdAccess

SUBJECT = "google:117482000000000000000"


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[Household.__table__, HouseholdAccess.__table__])
    return sessionmaker(bind=engine)()


def _grant(db: Session, subject: str = SUBJECT) -> uuid.UUID:
    household = Household(name="Mon foyer")
    db.add(household)
    db.flush()
    db.add(HouseholdAccess(auth_subject=subject, household_id=household.id))
    db.commit()
    return household.id


def test_an_active_access_resolves_to_its_household(db: Session) -> None:
    household_id = _grant(db)

    assert current_household_id(SUBJECT, db) == household_id


def test_a_revoked_access_is_refused(db: Session) -> None:
    _grant(db)
    db.execute(
        HouseholdAccess.__table__.update()
        .where(HouseholdAccess.auth_subject == SUBJECT)
        .values(revoked_at=datetime.now(UTC))
    )
    db.commit()

    with pytest.raises(HTTPException) as excinfo:
        current_household_id(SUBJECT, db)

    assert excinfo.value.status_code == 403
    # The same answer an unknown identity gets. Someone who was cut off learns
    # nothing from the distinction, and could do nothing with it.
    assert excinfo.value.detail == "no household linked to this identity"


def test_a_revoked_identity_is_still_KNOWN_so_it_cannot_re_register(db: Session) -> None:
    """The test that makes revocation permanent rather than a delay.

    `callback` creates a household when its lookup finds no access row. If
    revocation deleted the row — or if that lookup ever grew a `revoked_at`
    filter to look tidy — the identity that was just cut off would be handed a
    fresh household on its next login, and nothing would have been revoked at
    all.
    """
    _grant(db)
    db.execute(
        HouseholdAccess.__table__.update()
        .where(HouseholdAccess.auth_subject == SUBJECT)
        .values(revoked_at=datetime.now(UTC))
    )
    db.commit()

    # Exactly the query `callback` runs before deciding to provision.
    known = db.scalar(select(HouseholdAccess).where(HouseholdAccess.auth_subject == SUBJECT))

    assert known is not None, "a revoked identity must still read as known, or it re-registers"


def test_revoking_one_access_leaves_the_other_parent_alone(db: Session) -> None:
    """Per access, not per household.

    Both parents get their own row (see `HouseholdAccess`), and one of them
    abusing is not a reason to lock the family out of its own plans.
    """
    household_id = _grant(db)
    other = "google:117482000000000000001"
    db.add(HouseholdAccess(auth_subject=other, household_id=household_id))
    db.commit()

    db.execute(
        HouseholdAccess.__table__.update()
        .where(HouseholdAccess.auth_subject == SUBJECT)
        .values(revoked_at=datetime.now(UTC))
    )
    db.commit()

    assert current_household_id(other, db) == household_id
    with pytest.raises(HTTPException):
        current_household_id(SUBJECT, db)


def test_undoing_a_revocation_restores_the_access(db: Session) -> None:
    """One statement, and its exact inverse.

    There is no interface for this at this size, so the operation has to be a
    column someone can set and unset — a mistake made at 2am must be reversible
    at 2:01 without a migration.
    """
    household_id = _grant(db)
    table = HouseholdAccess.__table__
    for value in (datetime.now(UTC), None):
        db.execute(
            table.update().where(HouseholdAccess.auth_subject == SUBJECT).values(revoked_at=value)
        )
        db.commit()

    assert current_household_id(SUBJECT, db) == household_id
