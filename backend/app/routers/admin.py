"""The back office, and the one gate in front of all of it.

It exists for judgement no rule reaches. `Tartes, Clafoutis` is the case that
settled the argument: the rubric groups an onion tart with a strawberry one, so
`db/dish_types.yaml` maps it to nothing on purpose, and a dessert tart ends up
offered as an alternative for a Thursday dinner. Only a person looking at one
recipe can tell those apart.

**Every route here takes `CurrentOperator` INSTEAD of `CurrentHousehold`**, and
`tests/test_admin_authorisation.py` walks this module to enforce it. That is
the whole defence: a back office is new surface reachable from the internet,
and the route that gets left unguarded is never the one being looked at.

Granting is separated behind `CurrentOwner`. Recruiting help to retag is the
point; letting a helper recruit — or remove the person who invited them — is
not.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import CurrentOperator, CurrentOwner
from app.db.models import HouseholdAccess, Operator
from app.db.session import get_db
from app.domain.enums import OperatorLevel
from app.domain.support_code import looks_like_code, normalise, support_code

DbDep = Annotated[Session, Depends(get_db)]

router = APIRouter(prefix="/admin", tags=["admin"])


class OperatorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    auth_subject: str
    level: OperatorLevel
    granted_at: datetime
    granted_by: str | None


class GrantRequest(BaseModel):
    """Who to let in, named by the code they read in their own settings screen.

    Not an email, and not because one was forgotten: none is stored (§11.7).
    The person signs in with Google first, reads their support code, and sends
    it over by any channel. The right is then granted to an identity Google has
    already verified — rather than to an address someone typed, which is the
    weaker thing to trust.
    """

    support_code: str = Field(min_length=8, max_length=16)
    level: OperatorLevel = OperatorLevel.CONTRIBUTOR


@router.get("/operators", response_model=list[OperatorOut])
def list_operators(db: DbDep, operator: CurrentOperator) -> list[Operator]:
    """Readable by any operator: a contributor should be able to see who else
    can change the catalogue they are working on."""
    return list(db.scalars(select(Operator).order_by(Operator.granted_at)))


@router.post("/operators", response_model=OperatorOut, status_code=status.HTTP_201_CREATED)
def grant(payload: GrantRequest, db: DbDep, owner: CurrentOwner) -> Operator:
    if not looks_like_code(payload.support_code):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "not a support code — expected eight hex characters",
        )

    wanted = normalise(payload.support_code)
    live = select(HouseholdAccess).where(HouseholdAccess.revoked_at.is_(None))
    matches = [
        access
        for access in db.scalars(live)
        if normalise(support_code(access.household_id)) == wanted
    ]
    if not matches:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no household with this support code")
    if len({access.household_id for access in matches}) > 1:
        # Eight hex characters can in principle name two households. Refusing is
        # the honest answer: granting to the wrong person is not recoverable by
        # the person who was granted nothing.
        raise HTTPException(status.HTTP_409_CONFLICT, "several households share this code")

    subject = matches[0].auth_subject
    existing = db.get(Operator, subject)
    if existing is not None:
        # Idempotent on the level, so re-granting is a correction and not an
        # error. `granted_by` follows, because who last decided is the useful
        # fact, not who decided first.
        existing.level = payload.level
        existing.granted_by = owner.auth_subject
        existing.granted_at = datetime.now(UTC)
        db.commit()
        return existing

    operator = Operator(
        auth_subject=subject,
        level=payload.level,
        granted_by=owner.auth_subject,
    )
    db.add(operator)
    db.commit()
    return operator


@router.delete("/operators/{auth_subject}", status_code=status.HTTP_204_NO_CONTENT)
def revoke(auth_subject: str, db: DbDep, owner: CurrentOwner) -> None:
    """Remove the right to operate. The person keeps their household.

    Refuses to remove the last owner: an instance with no owner can never grant
    again, and the only way back is a shell on the production database. That is
    the kind of lockout a confirmation dialog does not prevent and a check does.
    """
    operator = db.get(Operator, auth_subject)
    if operator is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not an operator")

    if operator.level is OperatorLevel.OWNER:
        owners = db.scalars(
            select(Operator).where(Operator.level == OperatorLevel.OWNER)
        ).all()
        if len(owners) <= 1:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "the last owner cannot be removed: nobody could grant access again",
            )

    db.delete(operator)
    db.commit()
