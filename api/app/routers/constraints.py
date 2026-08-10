"""Dietary constraints.

**Not** nested under `/members/{id}`: an aversion may have no member at all. One
concept, one table, one URL — two entities would produce two behaviours and the
question of what happens when they contradict each other.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import CurrentHousehold
from app.db.models import DietaryConstraint, Member
from app.db.session import get_db
from app.domain.enums import ConstraintSeverity
from app.schemas import DietaryConstraintCreate, DietaryConstraintOut

router = APIRouter(prefix="/household/constraints", tags=["constraints"])

DbDep = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[DietaryConstraintOut])
def list_constraints(db: DbDep, household_id: CurrentHousehold) -> list[DietaryConstraint]:
    return list(
        db.scalars(select(DietaryConstraint).where(DietaryConstraint.household_id == household_id))
    )


@router.post("", response_model=DietaryConstraintOut, status_code=status.HTTP_201_CREATED)
def add_constraint(
    payload: DietaryConstraintCreate, db: DbDep, household_id: CurrentHousehold
) -> DietaryConstraint:
    if payload.member_id is not None:
        member = db.get(Member, payload.member_id)
        if member is None or member.household_id != household_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "member not found")
    elif payload.severity is not ConstraintSeverity.AVERSION:
        # An allergy without someone it belongs to is meaningless; its household
        # scope comes from its severity, not from a missing member.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "only an aversion may apply to the whole household without a member",
        )

    if payload.allergen_code is None and not payload.label:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "either allergen_code or label is required",
        )

    constraint = DietaryConstraint(
        household_id=household_id,
        member_id=payload.member_id,
        allergen_code=payload.allergen_code,
        label=payload.label,
        severity=payload.severity,
        note=payload.note,
    )
    db.add(constraint)
    db.commit()
    return constraint


@router.patch("/{constraint_id}", response_model=DietaryConstraintOut)
def attach_to_member(
    constraint_id: uuid.UUID,
    member_id: uuid.UUID,
    db: DbDep,
    household_id: CurrentHousehold,
) -> DietaryConstraint:
    """Refine a household aversion down to one person.

    Refinement goes ONE WAY only. "Nobody likes spinach here" -> "actually it is
    mostly Léo" is a natural move; the reverse is not, so there is no endpoint
    for it. And a per-member aversion is an argument for a second dish — it
    reveals the problem the product exists to solve, where a household-wide one
    just removes the ingredient for everyone.
    """
    constraint = db.get(DietaryConstraint, constraint_id)
    if constraint is None or constraint.household_id != household_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "constraint not found")
    if constraint.severity is not ConstraintSeverity.AVERSION:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "only aversions can be reattached"
        )

    member = db.get(Member, member_id)
    if member is None or member.household_id != household_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "member not found")

    constraint.member_id = member_id
    db.commit()
    return constraint


@router.delete("/{constraint_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_constraint(constraint_id: uuid.UUID, db: DbDep, household_id: CurrentHousehold) -> None:
    constraint = db.get(DietaryConstraint, constraint_id)
    if constraint is None or constraint.household_id != household_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "constraint not found")
    db.delete(constraint)
    db.commit()
