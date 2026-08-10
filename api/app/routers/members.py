"""Member endpoints, including the parent-validated life-stage transition."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import CurrentHousehold
from app.db.models import LifeStageThreshold, Member
from app.db.session import get_db
from app.domain.enums import LifeStage
from app.domain.life_stage import pending_transition, proposed_life_stage
from app.schemas import (
    LifeStageConfirmation,
    MemberCreate,
    MemberOut,
    MemberUpdate,
    PendingTransitionOut,
)

router = APIRouter(prefix="/members", tags=["members"])

DbDep = Annotated[Session, Depends(get_db)]


def _thresholds(db: Session) -> dict[LifeStage, int | None]:
    rows = db.scalars(select(LifeStageThreshold)).all()
    return {row.life_stage: row.upper_bound_months for row in rows}


def _load(db: Session, member_id: uuid.UUID, household_id: uuid.UUID) -> Member:
    member = db.get(Member, member_id)
    # Scoping the lookup by household is what turns a guessed id into a 404
    # instead of someone else's child (invariant I6).
    if member is None or member.household_id != household_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "member not found")
    return member


@router.get("", response_model=list[MemberOut])
def list_members(db: DbDep, household_id: CurrentHousehold) -> list[Member]:
    return list(
        db.scalars(
            select(Member).where(Member.household_id == household_id).order_by(Member.created_at)
        )
    )


@router.post("", response_model=MemberOut, status_code=status.HTTP_201_CREATED)
def create_member(payload: MemberCreate, db: DbDep, household_id: CurrentHousehold) -> Member:
    if payload.life_stage is not None:
        stage = payload.life_stage
    elif payload.birth_date is not None:
        stage = proposed_life_stage(payload.birth_date, date.today(), _thresholds(db))
    else:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "either birth_date or life_stage must be provided",
        )

    member = Member(
        household_id=household_id,
        display_name=payload.display_name,
        birth_date=payload.birth_date,
        life_stage=stage,
        life_stage_confirmed_at=datetime.now(UTC),
    )
    db.add(member)
    db.commit()
    return member


@router.patch("/{member_id}", response_model=MemberOut)
def update_member(
    member_id: uuid.UUID,
    payload: MemberUpdate,
    db: DbDep,
    household_id: CurrentHousehold,
) -> Member:
    member = _load(db, member_id, household_id)
    if payload.display_name is not None:
        member.display_name = payload.display_name
    if payload.birth_date is not None:
        # Changing the birth date may surface a proposal; it never moves the
        # effective stage on its own.
        member.birth_date = payload.birth_date
    db.commit()
    return member


@router.get("/pending-transitions", response_model=list[PendingTransitionOut])
def list_pending_transitions(
    db: DbDep, household_id: CurrentHousehold
) -> list[PendingTransitionOut]:
    """Stage changes the age suggests, awaiting parental confirmation."""
    thresholds = _thresholds(db)
    today = date.today()
    out: list[PendingTransitionOut] = []

    for member in db.scalars(select(Member).where(Member.household_id == household_id)):
        transition = pending_transition(
            current=member.life_stage,
            birth_date=member.birth_date,
            on=today,
            thresholds=thresholds,
        )
        if transition is not None:
            out.append(
                PendingTransitionOut(
                    member_id=member.id,
                    current=transition.current,
                    proposed=transition.proposed,
                )
            )
    return out


@router.post("/{member_id}/life-stage", response_model=MemberOut)
def confirm_life_stage(
    member_id: uuid.UUID,
    payload: LifeStageConfirmation,
    db: DbDep,
    household_id: CurrentHousehold,
) -> Member:
    """Apply a stage change. The parent decides — always, in both directions."""
    member = _load(db, member_id, household_id)
    member.life_stage = payload.confirmed
    member.life_stage_confirmed_at = datetime.now(UTC)
    db.commit()
    return member


@router.delete("/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_member(member_id: uuid.UUID, db: DbDep, household_id: CurrentHousehold) -> None:
    """Remove a member, along with their constraints, assignments and history.

    Everything hanging off a member cascades, which is what we want: their past
    meals should stop feeding the anti-repetition signal the moment they are no
    longer part of the household.

    A household must keep at least one member — an empty one can generate
    nothing, and leaves the user facing an error rather than an explanation.
    """
    member = _load(db, member_id, household_id)

    remaining = db.scalar(
        select(func.count())
        .select_from(Member)
        .where(Member.household_id == household_id, Member.id != member_id)
    )
    if not remaining:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "a household needs at least one member",
        )

    db.delete(member)
    db.commit()


# Constraints live in `routers/constraints.py`, NOT nested here: an aversion may
# have no member at all, so the URL cannot hang off a member.
