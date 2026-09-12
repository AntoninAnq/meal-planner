"""What a household means to cook again.

Not the same thing as "never again": `routers/exclusions.py` is the other half,
and a recipe is never both.

Always a recipe. A dish someone makes without one — "pâtes au jambon" — is
written as a recipe OF THE HOUSEHOLD (`routers/recipes.py`), private to it, and
favourited like any other. It was briefly a title carried on this table; one
object rather than two is what stopped this router, the slot panel and the
shopping list from each having to know about both.

`household_id` appears in no signature — it comes from the session (I6).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.deps import CurrentHousehold
from app.db.models import DietaryConstraint, HouseholdExclusion, HouseholdFavorite, Recipe
from app.db.session import get_db
from app.domain.enums import ConstraintSeverity
from app.schemas import FavoriteCreate, FavoriteOut
from app.services.catalogue import offerable, visible_to
from app.services.conflicts import conflicts_for

router = APIRouter(prefix="/favorites", tags=["favorites"])

DbDep = Annotated[Session, Depends(get_db)]


def _declares_an_allergy(db: Session, household_id: uuid.UUID) -> bool:
    """An allergy or an intolerance, not an aversion — where `conflicts_for`
    draws the same line."""
    return bool(
        db.scalar(
            select(
                exists().where(
                    DietaryConstraint.household_id == household_id,
                    DietaryConstraint.severity != ConstraintSeverity.AVERSION,
                )
            )
        )
    )


@router.get("", response_model=list[FavoriteOut])
def list_favorites(
    db: DbDep,
    household_id: CurrentHousehold,
    for_slot: Annotated[bool, Query()] = False,
) -> list[FavoriteOut]:
    """The household's favourites, most recently added first.

    `for_slot` narrows the list to what may still be served, through the very
    predicate the pre-filter uses — so a favourite whose source has since been
    withdrawn stops being offered as a replacement without vanishing from the
    tab, where the household can still see it and remove it.

    A recipe nobody classified passes, exactly as it does in the pre-filter:
    111 of 555 verified recipes carry no `dish_type`, and refusing them here
    would quietly hide a fifth of the catalogue.

    `visible_to` applies in both cases: a recipe another household wrote and an
    operator has since un-shared is nobody else's to read, favourite or not.

    No pagination. The list is short by nature, and `created_at desc` is what
    the screen shows; past thirty or so favourites this needs revisiting, and
    so does the screen.
    """
    query = (
        select(
            HouseholdFavorite.recipe_id,
            Recipe.title,
            Recipe.prep_minutes,
            Recipe.cook_minutes,
            Recipe.complexity,
            Recipe.source_url,
            Recipe.allergens_verified,
        )
        .join(Recipe, Recipe.id == HouseholdFavorite.recipe_id)
        .where(HouseholdFavorite.household_id == household_id, visible_to(household_id))
        .order_by(HouseholdFavorite.created_at.desc())
    )
    if for_slot:
        query = query.where(offerable())

    rows = db.execute(query).all()
    conflicts = conflicts_for(db, household_id, {row.recipe_id for row in rows})
    unchecked = any(not row.allergens_verified for row in rows) and _declares_an_allergy(
        db, household_id
    )

    return [
        FavoriteOut(
            recipe_id=row.recipe_id,
            title=row.title,
            minutes=(
                (row.prep_minutes or 0) + (row.cook_minutes or 0)
                if (row.prep_minutes is not None or row.cook_minutes is not None)
                else None
            ),
            complexity=row.complexity,
            source_url=row.source_url or None,
            conflicts=conflicts.get(row.recipe_id, []),
            unchecked_allergens=not row.allergens_verified and unchecked,
        )
        for row in rows
    ]


@router.post("", response_model=FavoriteOut)
def add_favorite(
    payload: FavoriteCreate, db: DbDep, household_id: CurrentHousehold
) -> FavoriteOut:
    """Idempotent, and deliberately not a 409.

    The control is a two-state button, so a second POST is a click that arrived
    twice — a double tap, a retried request — not a mistake to report. The
    unique constraint settles it and the answer is the same either way: it is a
    favourite.
    """
    recipe = db.get(Recipe, payload.recipe_id)
    if recipe is None or not (
        recipe.household_id is None
        or recipe.household_id == household_id
        or recipe.shared_at is not None
    ):
        # Another household's private recipe answers exactly as a recipe that
        # does not exist: its existence is not this household's business.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "recipe not found")

    # Favouriting a withheld dish is changing one's mind about it: the latest
    # answer holds, and a recipe is never both.
    db.execute(
        delete(HouseholdExclusion).where(
            HouseholdExclusion.household_id == household_id,
            HouseholdExclusion.recipe_id == payload.recipe_id,
        )
    )
    db.add(HouseholdFavorite(household_id=household_id, recipe_id=payload.recipe_id))

    try:
        db.commit()
    except IntegrityError:
        # Already there. The unique constraint did the work, which is why no
        # SELECT precedes the INSERT: two parents clicking at once would both
        # pass that read.
        db.rollback()

    return next(
        favorite
        for favorite in list_favorites(db, household_id)
        if favorite.recipe_id == payload.recipe_id
    )


@router.delete("/{recipe_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_favorite(recipe_id: uuid.UUID, db: DbDep, household_id: CurrentHousehold) -> None:
    """Removing is immediate and has no confirmation.

    It is undone with one click from any slot panel, and a modal for that would
    cost more attention than the mistake it prevents.

    Removing something that is not there is not an error: the interface has
    already dropped the row, and answering 404 would make an optimistic update
    look like a failure.
    """
    db.execute(
        delete(HouseholdFavorite).where(
            HouseholdFavorite.household_id == household_id,
            HouseholdFavorite.recipe_id == recipe_id,
        )
    )
    db.commit()
