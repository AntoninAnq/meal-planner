"""What a recipe is MADE OF, derived from the ingredients that resolved.

§6.4 says it plainly: `recipe_food_category` se dérive des catégories des
ingrédients résolus. So this pass is deliberately dumb — it copies, it does not
judge. Every category carried by a resolved ingredient becomes a category of
the recipe, and the choice of which ones are worth reporting belongs to the
signal that reads them, not here.

**Two axes, and confusing them is what delayed this.** `dish_type` says WHEN a
recipe is eaten and comes from the rubric its source publishes. This says WHAT
IT CONTAINS and comes from our own referential. A quiche and an apple tart
share `dish_type`-adjacent ingredients and differ entirely in when they are
eaten; a chicken tajine and a chicken pie share this and differ in nothing else
that matters to rotation.

**It exists to unblock the fourth soft signal** (§6.2): "jours depuis la
dernière occurrence par food_category". That signal was deferred on the grounds
that the referential knew too few proteins — measured at 16, now 66. The
measurement that followed showed the reasoning was wrong twice over: it counted
desserts in the denominator, and it read "contains meat" where the signal needs
"is made of". On the 196 verified mains and starters, 83 % carry a vegetable
and 72 % a protein once eggs and cheese are counted. The composition was always
there; nothing was writing it down.

Replayable and idempotent, like every other derivation here: a recipe ingested
when the referential held fifty entries gains its categories when it holds
three hundred, without asking anyone's server for the page again.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    FoodCategory,
    IngredientFoodCategory,
    Recipe,
    RecipeFoodCategory,
    RecipeIngredient,
)


@dataclass
class FoodCategoryReport:
    recipes: int = 0
    with_categories: int = 0
    without: int = 0
    rows: int = 0
    per_category: dict[str, int] = field(default_factory=dict)

    def render(self) -> str:
        lines = [
            f"recettes          {self.recipes}",
            f"avec catégories   {self.with_categories}",
            f"sans              {self.without} — aucune ligne résolue",
            f"liens écrits      {self.rows}",
        ]
        lines += [
            f"  {code:<16} {count}"
            for code, count in sorted(self.per_category.items(), key=lambda kv: -kv[1])
        ]
        return "\n".join(lines)


def derive(db: Session, *, report_only: bool = False) -> FoodCategoryReport:
    by_ingredient: dict[uuid.UUID, set[uuid.UUID]] = {}
    for ingredient_id, category_id in db.execute(
        select(IngredientFoodCategory.ingredient_id, IngredientFoodCategory.food_category_id)
    ).all():
        by_ingredient.setdefault(ingredient_id, set()).add(category_id)

    labels = dict(db.execute(select(FoodCategory.id, FoodCategory.code)).all())

    per_recipe: dict[uuid.UUID, set[uuid.UUID]] = {}
    for recipe_id, ingredient_id in db.execute(
        select(RecipeIngredient.recipe_id, RecipeIngredient.ingredient_id).where(
            RecipeIngredient.ingredient_id.is_not(None),
            RecipeIngredient.is_section.is_(False),
        )
    ).all():
        per_recipe.setdefault(recipe_id, set()).update(by_ingredient.get(ingredient_id, set()))

    report = FoodCategoryReport()
    if not report_only:
        # Replaced wholesale rather than merged, for the same reason the
        # referential loader replaces: correcting an ingredient's categories
        # must be able to REMOVE one from every recipe that used it.
        db.query(RecipeFoodCategory).delete()

    for recipe_id in db.scalars(select(Recipe.id)):
        categories = per_recipe.get(recipe_id, set())
        report.recipes += 1
        if categories:
            report.with_categories += 1
        else:
            report.without += 1

        for category_id in sorted(categories, key=str):
            report.rows += 1
            code = labels.get(category_id, "?")
            report.per_category[code] = report.per_category.get(code, 0) + 1
            if not report_only:
                db.add(
                    RecipeFoodCategory(recipe_id=recipe_id, food_category_id=category_id)
                )

    if report_only:
        db.rollback()
    else:
        db.commit()
    return report
