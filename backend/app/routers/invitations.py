"""Invitations — a meal with guests, kept beside the plan.

**Not** folded into `/meal-plans`. An invitation is a standalone thing the
household creates and comes back to days later (`docs/UX-V0.md` §4): who is
coming to Saturday dinner and what they will not eat. It never generates
anything itself — the client saves it here, then asks `/meal-plans` for that
slot with the same POST the week uses. Regenerating or clearing the meal leaves
the invitation standing; deleting the invitation leaves the meal standing.

`household_id` appears in no signature — it is derived from the session (I6).
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import CurrentHousehold
from app.db.models import Invitation
from app.db.session import get_db
from app.schemas import InvitationCreate, InvitationOut

router = APIRouter(prefix="/invitations", tags=["invitations"])

DbDep = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[InvitationOut])
def list_invitations(
    db: DbDep, household_id: CurrentHousehold, week_start: Annotated[date, Query()]
) -> list[Invitation]:
    """Every invitation of one week, so the week screen can list them and the
    edit form can prefill from one — the "find it again after you leave" that
    `UX-V0.md` §4 asks for."""
    return list(
        db.scalars(
            select(Invitation)
            .where(
                Invitation.household_id == household_id,
                Invitation.week_start == week_start,
            )
            .order_by(Invitation.day_of_week, Invitation.meal_type)
        )
    )


@router.post("", response_model=InvitationOut)
def upsert_invitation(
    payload: InvitationCreate, db: DbDep, household_id: CurrentHousehold
) -> Invitation:
    """Create the slot's invitation, or replace it if the slot already has one.

    One row per slot (`uq_invitation_slot`): the interface edits "the Saturday
    dinner", so a second POST for the same slot is that edit, not a duplicate.
    There is no PATCH for the same reason — a single form, one write.
    """
    guests = [group.model_dump(mode="json") for group in payload.guests]
    dislikes = [entry.strip() for entry in payload.dislikes if entry.strip()]

    invitation = db.scalar(
        select(Invitation).where(
            Invitation.household_id == household_id,
            Invitation.week_start == payload.week_start,
            Invitation.day_of_week == payload.day_of_week,
            Invitation.meal_type == payload.meal_type,
        )
    )
    if invitation is None:
        invitation = Invitation(
            household_id=household_id,
            week_start=payload.week_start,
            day_of_week=payload.day_of_week,
            meal_type=payload.meal_type,
        )
        db.add(invitation)

    invitation.guests = guests
    invitation.dislikes = dislikes
    db.commit()
    db.refresh(invitation)
    return invitation


@router.delete("/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_invitation(invitation_id: uuid.UUID, db: DbDep, household_id: CurrentHousehold) -> None:
    """Removing the invitation does not touch the generated meal.

    The slot may still hold a perfectly good dish that was cooked for guests;
    emptying that is `DELETE /meal-plans/{id}/slots/{slot}`, a separate act.
    """
    invitation = db.get(Invitation, invitation_id)
    if invitation is None or invitation.household_id != household_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "invitation not found")
    db.delete(invitation)
    db.commit()
