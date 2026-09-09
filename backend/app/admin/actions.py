"""What the operator commands do, separated from how they are typed.

Pure-ish functions over a session: every one of them is a test that runs
without a terminal, which is what stops "revoke" from being the code path
nobody exercised until the night it was needed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import GenerationLog, Household, HouseholdAccess, Member


class UnknownSubject(LookupError):
    """No access row for this identity — nothing to revoke or restore."""


class UnknownHousehold(LookupError):
    """No household with this id."""


@dataclass(frozen=True)
class Row:
    """One household, as an operator needs to see it.

    `subjects` is what identifies a person here, because nothing else does:
    `HouseholdAccess` holds an auth subject and no email, by design. An operator
    cannot look someone up by address, and adding that would mean starting to
    store one.
    """

    household_id: uuid.UUID
    name: str
    members: int
    subjects: tuple[str, ...]
    revoked: tuple[str, ...]
    limit_override: int | None
    calls_in_window: int


def survey(db: Session, *, window_hours: int) -> list[Row]:
    """Everyone on the instance, with what they have spent recently.

    Ordered by recent spend, because the reason to run this is almost always
    "who is burning the budget" — an alphabetical list would make the operator
    read all of it to find the one row that matters.
    """
    since = datetime.now(UTC) - timedelta(hours=window_hours)
    calls = {
        household_id: count
        for household_id, count in db.execute(
            select(GenerationLog.household_id, func.count())
            .where(GenerationLog.created_at >= since)
            .group_by(GenerationLog.household_id)
        ).all()
    }
    members = {
        household_id: count
        for household_id, count in db.execute(
            select(Member.household_id, func.count()).group_by(Member.household_id)
        ).all()
    }

    access: dict[uuid.UUID, list[HouseholdAccess]] = {}
    for row in db.scalars(select(HouseholdAccess)):
        access.setdefault(row.household_id, []).append(row)

    rows = [
        Row(
            household_id=household.id,
            name=household.name,
            members=members.get(household.id, 0),
            subjects=tuple(
                sorted(a.auth_subject for a in access.get(household.id, []) if not a.revoked_at)
            ),
            revoked=tuple(
                sorted(a.auth_subject for a in access.get(household.id, []) if a.revoked_at)
            ),
            limit_override=household.generation_limit_override,
            calls_in_window=calls.get(household.id, 0),
        )
        for household in db.scalars(select(Household))
    ]
    rows.sort(key=lambda row: (-row.calls_in_window, row.name))
    return rows


def revoke(db: Session, auth_subject: str) -> None:
    """Cut this identity off. The row survives, and that is the whole design.

    `callback` provisions a household exactly when it finds no access row, so
    deleting would hand the very identity that was cut off a brand-new
    household on its next login. Revoked but present means recognised, refused,
    and unable to re-register.

    Idempotent: revoking twice keeps the first timestamp, because when someone
    was cut off is a fact and the second command is a typo.
    """
    row = db.scalar(select(HouseholdAccess).where(HouseholdAccess.auth_subject == auth_subject))
    if row is None:
        raise UnknownSubject(auth_subject)
    if row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
        db.commit()


def restore(db: Session, auth_subject: str) -> None:
    """Let this identity back in, onto the household it already had."""
    row = db.scalar(select(HouseholdAccess).where(HouseholdAccess.auth_subject == auth_subject))
    if row is None:
        raise UnknownSubject(auth_subject)
    row.revoked_at = None
    db.commit()


def set_limit(db: Session, household_id: uuid.UUID, limit: int | None) -> None:
    """Give this household its own ceiling, or put it back on the rate card.

    `None` clears the override. Zero is a value, not a clear: it stops the
    spend while leaving the weeks already generated readable, which is the
    softest useful sanction and the right first move on a suspected bot.
    """
    household = db.get(Household, household_id)
    if household is None:
        raise UnknownHousehold(str(household_id))
    if limit is not None and limit < 0:
        raise ValueError("a ceiling cannot be negative; omit it to clear the override")
    household.generation_limit_override = limit
    db.commit()
