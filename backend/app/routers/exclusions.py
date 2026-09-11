"""What a household never wants proposed again.

The other half of the favourite, and what replaced "Ce plat a plu ?". That
question wrote a rating nothing ever read, so a household that said no saw the
dish come back the next week. This one acts: a withheld recipe leaves the pool
`SqlCatalogue` builds for this household, which feeds both the generation and
the alternatives.

Only catalogue recipes. With a catalogue the model chooses among candidates and
writes no dish of its own, so a one-line dish is never proposed again anyway —
there would be nothing to withhold.

A favourite and a withheld dish answer the same question in opposite ways, so a
recipe is never both: setting one clears the other.

`household_id` appears in no signature — it comes from the session (I6).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.deps import CurrentHousehold
from app.db.models import HouseholdExclusion, HouseholdFavorite, Recipe
from app.db.session import get_db
from app.schemas import ExclusionCreate, ExclusionOut

router = APIRouter(prefix="/exclusions", tags=["exclusions"])

DbDep = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[ExclusionOut])
def list_exclusions(db: DbDep, household_id: CurrentHousehold) -> list[ExclusionOut]:
    """Most recently withheld first — the one most likely to be a mistake."""
    rows = db.execute(
        select(HouseholdExclusion.recipe_id, Recipe.title, Recipe.source_url)
        .join(Recipe, Recipe.id == HouseholdExclusion.recipe_id)
        .where(HouseholdExclusion.household_id == household_id)
        .order_by(HouseholdExclusion.created_at.desc())
    ).all()
    return [
        ExclusionOut(recipe_id=row.recipe_id, title=row.title, source_url=row.source_url or None)
        for row in rows
    ]


@router.post("", response_model=ExclusionOut)
def add_exclusion(
    payload: ExclusionCreate, db: DbDep, household_id: CurrentHousehold
) -> ExclusionOut:
    """Idempotent, like the favourite, and for the same reason: a second POST
    is a click that arrived twice.

    The dish already on this week's plan stays where it is. Withholding says
    "not in the weeks to come" — the button is often pressed after the meal was
    eaten — and replacing it is a separate gesture, one section down.
    """
    if db.get(Recipe, payload.recipe_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "recipe not found")

    db.execute(
        delete(HouseholdFavorite).where(
            HouseholdFavorite.household_id == household_id,
            HouseholdFavorite.recipe_id == payload.recipe_id,
        )
    )
    db.add(HouseholdExclusion(household_id=household_id, recipe_id=payload.recipe_id))
    try:
        db.commit()
    except IntegrityError:
        # Already withheld, so it cannot have been a favourite either.
        db.rollback()

    return next(
        exclusion
        for exclusion in list_exclusions(db, household_id)
        if exclusion.recipe_id == payload.recipe_id
    )


@router.delete("/{recipe_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_exclusion(recipe_id: uuid.UUID, db: DbDep, household_id: CurrentHousehold) -> None:
    """"Reproposer". Not an error when there is nothing to remove: the row has
    already left the screen."""
    db.execute(
        delete(HouseholdExclusion).where(
            HouseholdExclusion.household_id == household_id,
            HouseholdExclusion.recipe_id == recipe_id,
        )
    )
    db.commit()
