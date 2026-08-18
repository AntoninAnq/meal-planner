"""How much work a recipe is, computed rather than judged.

§6.4 took `complexity` away from the model on the grounds that it is
deterministic: the sources declare a preparation time, a cooking time and a
number of steps, and the ingredient count is a fact about data we already hold.
A model asked to rate difficulty would be guessing at something arithmetic.

**The thresholds are the catalogue's own quartiles, not a taste.** Measured over
the 3 439 recipes:

    temps (prep+cuisson)   p25 = 25 min   p50 = 40   p75 = 65
    étapes                 p25 = 4        p50 = 6    p75 = 10
    ingrédients            p25 = 6        p50 = 8    p75 = 10

So "simple" means *simpler than three quarters of what exists*, which is a claim
the data supports, where "under 30 minutes" would have been a number someone
liked the sound of. If a later campaign shifts the distribution, these move —
and the constants below are the one place to move them (I8).

**NULL is a real answer.** A recipe declaring neither a time nor a step count
has one usable signal out of three, and inventing a rating from the ingredient
count alone would put a confident number on a guess. 48 % of the catalogue
declares steps, 78 % declares a time; what neither declares stays NULL, and the
prompt simply says nothing about it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Recipe, RecipeIngredient

#: Quartiles of the measured distribution. Below the first, the recipe is in the
#: easiest quarter; above the third, in the hardest.
MINUTES_EASY, MINUTES_HARD = 25, 65
STEPS_EASY, STEPS_HARD = 4, 10
INGREDIENTS_EASY, INGREDIENTS_HARD = 6, 10

#: Points, out of a possible 6, at which each rating starts.
MODERATE_AT, INVOLVED_AT = 2, 4

LABELS = {1: "simple", 2: "moyen", 3: "long"}


def _points(value: int, easy: int, hard: int) -> int:
    if value <= easy:
        return 0
    return 1 if value <= hard else 2


def score(
    *,
    minutes: int | None,
    steps: int | None,
    ingredients: int,
) -> int | None:
    """1, 2, 3 — or None when the sources declared too little to say.

    At least one of time or steps is required. The ingredient count alone is a
    poor proxy: a salad of twelve raw things is not harder than a two-ingredient
    sauce that needs an hour of stirring.
    """
    if minutes is None and steps is None:
        return None

    total = _points(ingredients, INGREDIENTS_EASY, INGREDIENTS_HARD)
    if minutes is not None:
        total += _points(minutes, MINUTES_EASY, MINUTES_HARD)
    if steps is not None:
        total += _points(steps, STEPS_EASY, STEPS_HARD)

    # One missing signal must not make a recipe look easy by default: the score
    # is read against what was actually available.
    available = 1 + (minutes is not None) + (steps is not None)
    scaled = total * 3 / available

    if scaled < MODERATE_AT:
        return 1
    return 2 if scaled < INVOLVED_AT else 3


@dataclass
class ComplexityReport:
    recipes: int = 0
    rated: int = 0
    unrated: int = 0
    per_rating: dict[int, int] = field(default_factory=dict)

    def render(self) -> str:
        lines = [
            f"recettes          {self.recipes}",
            f"notées            {self.rated}",
            f"sans données      {self.unrated} — le prompt n'en dira rien",
        ]
        lines += [
            f"  {rating} {LABELS[rating]:<8} {count}"
            for rating, count in sorted(self.per_rating.items())
        ]
        return "\n".join(lines)


def derive(db: Session, *, report_only: bool = False) -> ComplexityReport:
    counts = dict(
        db.execute(
            select(RecipeIngredient.recipe_id, func.count())
            .where(RecipeIngredient.is_section.is_(False))
            .group_by(RecipeIngredient.recipe_id)
        ).all()
    )

    report = ComplexityReport()
    for recipe in db.scalars(select(Recipe)):
        report.recipes += 1

        minutes: int | None = None
        if recipe.prep_minutes is not None or recipe.cook_minutes is not None:
            minutes = (recipe.prep_minutes or 0) + (recipe.cook_minutes or 0)

        rating = score(
            minutes=minutes,
            steps=recipe.step_count,
            ingredients=counts.get(recipe.id, 0),
        )
        if rating is None:
            report.unrated += 1
        else:
            report.rated += 1
            report.per_rating[rating] = report.per_rating.get(rating, 0) + 1

        if not report_only:
            recipe.complexity = rating

    if report_only:
        db.rollback()
    else:
        db.commit()
    return report
