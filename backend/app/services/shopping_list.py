"""What to buy for the meals someone picked, and what we cannot tell them.

Three limits come from the schema rather than from a choice of screen, and all
three are visible in the output because hiding any of them makes a list that is
quietly wrong.

**Scaled when the source counts people.** `Recipe.servings` is the first
number in `recipeYield`, and "20 tartelettes" and "4 personnes" are not the
same unit. Only a yield that counts people — personnes, parts, portions,
convives… — is scaled, to the life-stage coefficients of whoever eats the dish
plus the slot's guests (`domain/portions.py`). A bare "4" is left alone too.
The others keep the source's quantities and are named in `unscaled`, with what
the source wrote: fifteen guests on a recipe for four must not be bought for
four, and a list that is quietly off on one recipe is worse than one that says
which.

**Units are free text** (`RecipeIngredient.unit`, 40 characters). "200 g de
tomates" and "3 tomates" do not add up. Two quantities are summed only when
their unit is identical after normalisation; otherwise they are juxtaposed. No
conversion table — it would be wrong on "pincée", "verre" and "bouquet", which
is most of what a conversion table would be asked about.

**Roughly a quarter of lines do not resolve.** They have no ingredient, no
category and no possible grouping. They cannot be hidden — the list would be
incomplete — and they cannot be folded in with the rest — it would be
unreadable. They get their own section, copied verbatim, with the sentence that
explains them. That section shrinks as the referential fills, which is the
right incentive.

**A dish counts once.** A `PlannedDish` eaten by four members, or carrying a
variant for a fifth, is one set of ingredients. Counting per
`PlannedDishMember` would multiply the list by the number of people at the
table.

**A dish with no recipe has no ingredients.** Model suggestions (I7) contribute
nothing, and the caller is told so rather than left with a list it believes is
complete.
"""

from __future__ import annotations

import re
import uuid
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import Row, func, select
from sqlalchemy.orm import Session

from app.db.models import (
    FoodCategory,
    Ingredient,
    IngredientFoodCategory,
    MealPlan,
    Member,
    PlannedDish,
    Recipe,
    RecipeIngredient,
)
from app.domain.enums import LifeStage
from app.domain.food_categories import rank_of
from app.domain.portions import scale_factor
from app.domain.shared_ingredients import pantry
from app.schemas import (
    ShoppingLineOut,
    ShoppingListOut,
    ShoppingSectionOut,
    UnscaledRecipeOut,
)

_SPACES = re.compile(r"\s+")


def _unit_key(unit: str | None) -> str:
    """Two units add up only when they are the same word.

    Lowercased and with runs of whitespace collapsed, which is as far as this
    goes on purpose: "c. à soupe" and "cuillère à soupe" stay apart, because
    deciding they are the same is a parsing problem and I4 forbids solving it
    with string similarity.
    """
    return _SPACES.sub(" ", (unit or "").strip().lower())


def _amount(quantity: Decimal) -> str:
    """`Decimal("200.000")` → `"200"`, `Decimal("1.500")` → `"1.5"`."""
    trimmed = quantity.normalize()
    # `normalize()` turns 200 into 2E+2. Expanding it back is the difference
    # between "200 g" and "2E+2 g" on a shopping list.
    if trimmed == trimmed.to_integral_value():
        return str(trimmed.quantize(Decimal(1)))
    return format(trimmed, "f")


def _render(parts: dict[str, Decimal]) -> str | None:
    """"250 g", or "250 g + 2 verres" when the units disagree.

    Ordered by unit so the same two lines always come out the same way round —
    a bare count first, since "3 + 200 g" reads as a count of something and
    "200 g + 3" reads as an afterthought. Null when not one line carried a
    quantity: a real state, and a different one from "zero". The source wrote
    "du sel", and the list says it does not know rather than inventing.
    """
    if not parts:
        return None
    return " + ".join(
        f"{_amount(total)} {unit}".strip() if unit else _amount(total)
        for unit, total in sorted(parts.items())
    )


#: What a scaled quantity is rounded to. "1.3 oignon" is already generous to
#: the arithmetic; "1.3333 oignon" is a bug report.
_SCALED_STEP = Decimal("0.1")


def _scaled(quantity: Decimal, factor: Decimal | None) -> Decimal:
    if factor is None:
        return quantity
    return max((quantity * factor).quantize(_SCALED_STEP, rounding=ROUND_HALF_UP), _SCALED_STEP)


def _factors(
    db: Session,
    household_id: uuid.UUID,
    plan: MealPlan,
    dishes: list[PlannedDish],
    recipes: dict[uuid.UUID, Row[Any]],
) -> dict[uuid.UUID, Decimal | None]:
    """Per dish, how much of its recipe the table needs — None when unknown.

    Guests are stored per slot, not per dish, so they are counted once, on the
    dish most of the household eats: the one `SlotCard` calls the default. A
    baby's separate plate must not be bought for the four adults who came to
    dinner.
    """
    stages: dict[uuid.UUID, LifeStage] = {
        member_id: stage
        for member_id, stage in db.execute(
            select(Member.id, Member.life_stage).where(Member.household_id == household_id)
        ).all()
    }

    carries_guests: dict[tuple[int, str], PlannedDish] = {}
    for dish in dishes:
        key = (dish.day_of_week, dish.meal_type.value)
        current = carries_guests.get(key)
        if current is None or (len(dish.eaters), -dish.position) > (
            len(current.eaters),
            -current.position,
        ):
            carries_guests[key] = dish

    factors: dict[uuid.UUID, Decimal | None] = {}
    for dish in dishes:
        if dish.recipe_id is None:
            continue
        eating = [
            stages[assignment.member_id]
            for assignment in dish.eaters
            if assignment.member_id in stages
        ]
        key = (dish.day_of_week, dish.meal_type.value)
        if carries_guests[key] is dish:
            for group in (plan.slot_guests or {}).get(f"{key[0]}-{key[1]}", []):
                eating += [LifeStage(group["life_stage"])] * int(group["count"])
        recipe = recipes[dish.recipe_id]
        factors[dish.id] = scale_factor(recipe.servings, recipe.servings_raw, eating)
    return factors


def build(
    db: Session,
    *,
    household_id: uuid.UUID,
    plan: MealPlan,
    slots: set[tuple[int, str]],
) -> ShoppingListOut:
    dishes = [
        dish
        for dish in plan.dishes
        if (dish.day_of_week, dish.meal_type.value) in slots
    ]
    # Counted on the SELECTION, not on the week: the header of the copied text
    # says how many meals it covers, and that has to be the meals it covers.
    chosen = {(dish.day_of_week, dish.meal_type.value) for dish in dishes}

    recipe_ids = {dish.recipe_id for dish in dishes if dish.recipe_id is not None}
    missing_recipe = any(dish.recipe_id is None for dish in dishes)

    if not recipe_ids:
        return ShoppingListOut(
            week_start=plan.week_start,
            meals=len(chosen),
            days=len({day for day, _ in chosen}),
            sections=[],
            pantry=[],
            unparsed=[],
            missing_recipe=missing_recipe,
        )

    recipes = {
        row.id: row
        for row in db.execute(
            select(Recipe.id, Recipe.title, Recipe.servings, Recipe.servings_raw).where(
                Recipe.id.in_(recipe_ids)
            )
        ).all()
    }
    factors = _factors(db, household_id, plan, dishes, recipes)

    by_recipe: dict[uuid.UUID, list[Row[Any]]] = {}
    for row in db.execute(
        select(
            RecipeIngredient.recipe_id,
            RecipeIngredient.raw_text,
            RecipeIngredient.quantity,
            RecipeIngredient.unit,
            RecipeIngredient.ingredient_id,
        )
        .where(
            RecipeIngredient.recipe_id.in_(recipe_ids),
            # A section header is not an ingredient and is not an unresolved
            # line either: "Pour la pâte sucrée :" belongs in neither list.
            RecipeIngredient.is_section.is_(False),
        )
        .order_by(RecipeIngredient.position)
    ).all():
        by_recipe.setdefault(row.recipe_id, []).append(row)

    # Read in the order of the week, not in the order the database returned the
    # rows. It is what makes the unrecognised lines come out in a stable order
    # — and a list whose sections shuffle between two identical requests is one
    # nobody can proof-read.
    in_week_order = sorted(dishes, key=lambda dish: (dish.day_of_week, dish.meal_type.value))
    # Each line with the factor of the dish it came from: the same recipe on two
    # days can feed two different tables.
    lines = [
        (row, factors.get(dish.id))
        for dish in in_week_order
        if dish.recipe_id is not None
        for row in by_recipe.get(dish.recipe_id, [])
    ]

    # The same function the week grid uses for "mêmes ingrédients", and for the
    # same reason: salt is in 49 % of the catalogue, and a list that opens on
    # salt, sugar and oil buries the four things actually worth buying.
    catalogue_size = db.scalar(select(func.count()).select_from(Recipe)) or 0
    census = {
        ingredient_id: count
        for ingredient_id, count in db.execute(
            select(
                RecipeIngredient.ingredient_id,
                func.count(func.distinct(RecipeIngredient.recipe_id)),
            )
            .where(RecipeIngredient.ingredient_id.is_not(None))
            .group_by(RecipeIngredient.ingredient_id)
        ).all()
    }
    cupboard = pantry(census, catalogue_size)

    resolved = {row.ingredient_id for row, _ in lines if row.ingredient_id is not None}
    names: dict[uuid.UUID, str] = {
        ingredient_id: name
        for ingredient_id, name in db.execute(
            select(Ingredient.id, Ingredient.canonical_name).where(Ingredient.id.in_(resolved))
        ).all()
    }

    # An ingredient may carry several categories; it appears once, in the first
    # of them along the walk, so a list never asks for the same thing twice.
    category_of: dict[uuid.UUID, tuple[str, str, str | None]] = {}
    for ingredient_id, code, label, label_en in db.execute(
        select(
            IngredientFoodCategory.ingredient_id,
            FoodCategory.code,
            FoodCategory.label,
            FoodCategory.label_en,
        )
        .join(FoodCategory, FoodCategory.id == IngredientFoodCategory.food_category_id)
        .where(IngredientFoodCategory.ingredient_id.in_(resolved))
    ).all():
        current = category_of.get(ingredient_id)
        if current is None or rank_of(code) < rank_of(current[0]):
            category_of[ingredient_id] = (code, label, label_en)

    unparsed: list[str] = []
    # Quantities per ingredient, kept per unit — they are only summed within a
    # unit, and juxtaposed across units.
    amounts: dict[uuid.UUID, dict[str, Decimal]] = {}
    seen: dict[uuid.UUID, None] = {}

    for row, factor in lines:
        if row.ingredient_id is None:
            # Verbatim, and de-duplicated on the exact text: the same line from
            # two recipes is one thing to buy, and we cannot tell that of two
            # lines that merely look alike.
            if row.raw_text not in unparsed:
                unparsed.append(row.raw_text)
            continue
        seen.setdefault(row.ingredient_id, None)
        if row.quantity is None:
            continue
        per_unit = amounts.setdefault(row.ingredient_id, {})
        key = _unit_key(row.unit)
        per_unit[key] = per_unit.get(key, Decimal(0)) + _scaled(row.quantity, factor)

    # Names only, and no quantities: nobody checks whether they have 200 g of
    # salt, they check whether there is salt.
    cupboard_names = sorted(
        names[ingredient_id]
        for ingredient_id in seen
        if ingredient_id in cupboard and ingredient_id in names
    )

    by_section: dict[str, ShoppingSectionOut] = {}
    for ingredient_id in seen:
        if ingredient_id in cupboard or ingredient_id not in names:
            continue
        code, label, label_en = category_of.get(ingredient_id, ("other", "Autres", "Other"))
        section = by_section.get(code)
        if section is None:
            section = ShoppingSectionOut(code=code, label=label, label_en=label_en, lines=[])
            by_section[code] = section
        section.lines.append(
            ShoppingLineOut(
                name=names[ingredient_id],
                amount=_render(amounts.get(ingredient_id, {})),
            )
        )

    sections = sorted(by_section.values(), key=lambda section: rank_of(section.code))
    for section in sections:
        section.lines.sort(key=lambda line: line.name.lower())

    unscaled: dict[uuid.UUID, UnscaledRecipeOut] = {}
    for dish in in_week_order:
        if dish.recipe_id is None or factors.get(dish.id) is not None:
            continue
        recipe = recipes[dish.recipe_id]
        unscaled.setdefault(
            dish.recipe_id,
            UnscaledRecipeOut(title=recipe.title, servings_raw=recipe.servings_raw),
        )

    return ShoppingListOut(
        week_start=plan.week_start,
        meals=len(chosen),
        days=len({day for day, _ in chosen}),
        sections=sections,
        pantry=cupboard_names,
        unparsed=unparsed,
        missing_recipe=missing_recipe,
        scaled=any(factor is not None for factor in factors.values()),
        unscaled=list(unscaled.values()),
    )
