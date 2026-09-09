"""An operator is shown by the one thing about them a person can recognise.

`auth_subject` is `google:117482000000000000000` — correct, unique, and
unreadable. The back office grants BY support code, because that is what
somebody sends you after signing in; a list that then names people by their
Google identifier would mean revoking a row with no one behind it. So the two
directions have to agree, and this checks that they do.

SQLite, like the other admin suites: CI runs without a database.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Base, Household, HouseholdAccess, Operator
from app.domain.enums import OperatorLevel
from app.domain.support_code import support_code
from app.routers.admin import with_support_code

SUBJECT = "google:117482000000000000000"
TABLES = [Household.__table__, HouseholdAccess.__table__, Operator.__table__]


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=TABLES)
    return sessionmaker(bind=engine)()


def _operator(db: Session, *, revoked: bool = False, access: bool = True) -> Operator:
    household = Household(name="Mon foyer")
    db.add(household)
    db.flush()
    if access:
        db.add(
            HouseholdAccess(
                auth_subject=SUBJECT,
                household_id=household.id,
                revoked_at=datetime.now(UTC) if revoked else None,
            )
        )
    operator = Operator(auth_subject=SUBJECT, level=OperatorLevel.CONTRIBUTOR)
    db.add(operator)
    db.commit()
    return operator


def test_an_operator_carries_the_code_of_their_own_household(db: Session) -> None:
    operator = _operator(db)
    household_id = db.scalar(  # the one row created above
        Household.__table__.select().with_only_columns(Household.id)
    )

    out = with_support_code(db, operator)

    assert household_id is not None
    assert out.support_code == support_code(household_id)


def test_a_revoked_identity_shows_no_code_rather_than_a_stale_one(db: Session) -> None:
    """Blank is the honest answer.

    The household still exists and its code is still derivable, so printing it
    would say "here is how to reach this person" about somebody who has been
    cut off — and the grant form, which only ever finds live access rows, would
    refuse that very code.
    """
    operator = _operator(db, revoked=True)

    assert with_support_code(db, operator).support_code is None


def test_an_operator_with_no_household_at_all_is_still_listed(db: Session) -> None:
    """A row that cannot be resolved must not hide the person holding the keys.

    Raising here — or filtering the row out — would mean an operator nobody can
    see and nobody can revoke, which is the one failure this screen exists to
    prevent.
    """
    operator = _operator(db, access=False)

    out = with_support_code(db, operator)

    assert out.support_code is None
    assert out.auth_subject == SUBJECT


def test_the_unknown_is_not_confused_with_the_absent(db: Session) -> None:
    # A different subject entirely: `db.get` returns None, same as no access.
    other = Operator(auth_subject="google:" + str(uuid.uuid4()), level=OperatorLevel.OWNER)
    db.add(other)
    db.commit()

    assert with_support_code(db, other).support_code is None
