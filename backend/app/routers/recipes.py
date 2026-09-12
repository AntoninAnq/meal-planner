"""Recipes a household writes for itself.

The catalogue proposes dishes with eight ingredients and forty minutes of work,
and a Tuesday is often "steak purée". Nothing here reaches the catalogue: these
rows carry `household_id`, which makes them visible to their household and to
nobody else (`services/catalogue.visible_to`) until an operator shares them.

**Verification is derived, never declared** (I3). Every line is parsed and
looked up in the referential like any collected recipe; if all of them resolve
to foods a human has confirmed, the recipe is verified and may be proposed
automatically. If one does not, the recipe still works — its author knows what
they wrote — but it is placed by hand, marked unchecked, and its unrecognised
lines land in the shopping list's own "non reconnues" section.

**A new recipe is a favourite straight away.** Writing one IS saying "I want
this again", and asking for a second click to say it would be a question with
one sensible answer.

`household_id` appears in no signature — it comes from the session (I6).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.deps import CurrentHousehold
from app.db.models import (
    HouseholdExclusion,
    HouseholdFavorite,
    Ingredient,
    IngredientAllergen,
    PlannedDish,
    Recipe,
    RecipeAllergen,
    RecipeIngredient,
)
from app.db.session import get_db
from app.domain.enums import RecipeSourceType
from app.schemas import IngredientMatchOut, RecipeIn, RecipeLineOut, RecipeOut
from app.services.ingredients import ResolvedLine, resolve_line, search

router = APIRouter(prefix="/recipes", tags=["recipes"])

DbDep = Annotated[Session, Depends(get_db)]


def _state(recipe: Recipe) -> str:
    if recipe.shared_at is not None:
        return "shared"
    if recipe.rejected_at is not None:
        return "rejected"
    if recipe.submitted_at is not None:
        return "pending"
    return "private"


def _serialise(db: Session, recipe: Recipe) -> RecipeOut:
    rows = db.execute(
        select(RecipeIngredient, Ingredient.canonical_name)
        .outerjoin(Ingredient, Ingredient.id == RecipeIngredient.ingredient_id)
        .where(RecipeIngredient.recipe_id == recipe.id)
        .order_by(RecipeIngredient.position)
    ).all()
    return RecipeOut(
        id=recipe.id,
        title=recipe.title,
        servings=recipe.servings,
        servings_raw=recipe.servings_raw,
        instructions=recipe.instructions,
        source_url=recipe.source_url,
        allergens_verified=recipe.allergens_verified,
        state=_state(recipe),
        rejected_reason=recipe.rejected_reason,
        lines=[
            RecipeLineOut(
                raw=line.raw_text,
                quantity=line.quantity,
                unit=line.unit,
                ingredient_id=line.ingredient_id,
                name=name,
                is_structural=line.is_section,
            )
            for line, name in rows
        ],
    )


def _write_lines(db: Session, recipe: Recipe, lines: list[str]) -> None:
    """Replace the recipe's lines, and derive what they imply.

    The two derivations are the pipeline's, on purpose — the same rule written
    twice would drift, and this is the rule, not a copy of the code:

    * `recipe_allergen` comes from the foods that resolved, confirmed or not:
      an allergen tag can only EXCLUDE a recipe, so tagging one too many is the
      safe direction.
    * `allergens_verified` is the strict one (I3): every line resolved, and
      every food it resolved to confirmed by a human.
    """
    db.execute(delete(RecipeIngredient).where(RecipeIngredient.recipe_id == recipe.id))
    db.execute(delete(RecipeAllergen).where(RecipeAllergen.recipe_id == recipe.id))

    resolved: list[ResolvedLine] = [resolve_line(db, raw) for raw in lines if raw.strip()]
    for position, line in enumerate(resolved):
        db.add(
            RecipeIngredient(
                recipe_id=recipe.id,
                position=position,
                raw_text=line.raw,
                quantity=line.quantity,
                unit=line.unit,
                ingredient_id=line.ingredient_id,
                is_section=line.is_structural,
            )
        )

    food = [line for line in resolved if not line.is_structural]
    ids = [line.ingredient_id for line in food if line.ingredient_id is not None]
    confirmed = {
        ingredient_id
        for ingredient_id in db.scalars(
            select(Ingredient.id).where(
                Ingredient.id.in_(ids), Ingredient.confirmed_at.is_not(None)
            )
        )
    }
    recipe.allergens_verified = bool(food) and len(ids) == len(food) and set(ids) <= confirmed

    codes = set(
        db.scalars(
            select(IngredientAllergen.allergen_code).where(
                IngredientAllergen.ingredient_id.in_(ids)
            )
        )
    )
    for code in sorted(codes):
        db.add(RecipeAllergen(recipe_id=recipe.id, allergen_code=code))


def _load(db: Session, recipe_id: uuid.UUID, household_id: uuid.UUID) -> Recipe:
    """This household's own recipe. Another's is a 404, shared or not: what it
    may read of a shared recipe it reads through the catalogue, and what it may
    change is only ever its own."""
    recipe = db.get(Recipe, recipe_id)
    if recipe is None or recipe.household_id != household_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such recipe")
    return recipe


@router.get("", response_model=list[RecipeOut])
def list_recipes(db: DbDep, household_id: CurrentHousehold) -> list[RecipeOut]:
    """The household's own, most recent first."""
    recipes = db.scalars(
        select(Recipe)
        .where(Recipe.household_id == household_id)
        .order_by(Recipe.created_at.desc())
    ).all()
    return [_serialise(db, recipe) for recipe in recipes]


@router.get("/ingredients", response_model=list[IngredientMatchOut])
def search_ingredients(
    db: DbDep,
    household_id: CurrentHousehold,
    q: Annotated[str, Query(min_length=1, max_length=80)],
) -> list[IngredientMatchOut]:
    """For a line nobody recognised, and a person who can say what they meant.

    Behind the session like everything else: the referential is not a public
    dictionary, and an open endpoint over it is a crawl waiting to happen.
    """
    return [
        IngredientMatchOut(ingredient_id=ingredient_id, name=name)
        for ingredient_id, name in search(db, q)
    ]


@router.post("", response_model=RecipeOut, status_code=status.HTTP_201_CREATED)
def create_recipe(payload: RecipeIn, db: DbDep, household_id: CurrentHousehold) -> RecipeOut:
    """Written here, favourited here, and offered to the shared catalogue.

    `servings_raw` is written as "N personnes" rather than left to a parser:
    the form asked for people, so the shopping list can scale it — which is the
    reason the field is on the form at all.
    """
    recipe = Recipe(
        title=payload.title.strip(),
        source_type=RecipeSourceType.USER,
        household_id=household_id,
        servings=payload.servings,
        servings_raw=f"{payload.servings} personnes" if payload.servings else None,
        instructions=(payload.instructions or "").strip() or None,
        source_url=(payload.source_url or "").strip() or None,
        # Straight into the queue, as decided: what a household writes is a
        # candidate for everyone, and an operator is the one who says yes.
        submitted_at=datetime.now(UTC),
    )
    db.add(recipe)
    try:
        db.flush()
    except IntegrityError as clash:
        # `source_url` is unique: that link is already a recipe, and a second
        # row for it would split one dish in two.
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "this link is already a recipe"
        ) from clash

    _write_lines(db, recipe, payload.lines)
    db.add(HouseholdFavorite(household_id=household_id, recipe_id=recipe.id))
    db.commit()
    return _serialise(db, recipe)


@router.put("/{recipe_id}", response_model=RecipeOut)
def update_recipe(
    recipe_id: uuid.UUID, payload: RecipeIn, db: DbDep, household_id: CurrentHousehold
) -> RecipeOut:
    """Editing a shared recipe makes it private again, and queues it anew.

    Otherwise the review is decorative: anything could be validated bland and
    rewritten afterwards, in everyone's week. The author keeps their version
    throughout; the other households simply stop seeing it until it is looked
    at again.
    """
    recipe = _load(db, recipe_id, household_id)

    recipe.title = payload.title.strip()
    recipe.servings = payload.servings
    recipe.servings_raw = f"{payload.servings} personnes" if payload.servings else None
    recipe.instructions = (payload.instructions or "").strip() or None
    recipe.source_url = (payload.source_url or "").strip() or None
    recipe.shared_at = None
    recipe.rejected_at = None
    recipe.rejected_reason = None
    recipe.submitted_at = datetime.now(UTC)

    _write_lines(db, recipe, payload.lines)
    db.commit()
    return _serialise(db, recipe)


@router.delete("/{recipe_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_recipe(recipe_id: uuid.UUID, db: DbDep, household_id: CurrentHousehold) -> None:
    """Gone, unless a week already points at it.

    `planned_dish.recipe_id` is `RESTRICT`, and rightly: a week that was cooked
    records what was eaten. Rather than let the database raise, this says so —
    and the recipe can still be removed from the favourites.
    """
    recipe = _load(db, recipe_id, household_id)

    planned = db.scalar(
        select(PlannedDish.id).where(PlannedDish.recipe_id == recipe.id).limit(1)
    )
    if planned is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "this recipe is on a week that was planned"
        )

    db.execute(delete(HouseholdFavorite).where(HouseholdFavorite.recipe_id == recipe.id))
    db.execute(delete(HouseholdExclusion).where(HouseholdExclusion.recipe_id == recipe.id))
    db.delete(recipe)
    db.commit()
