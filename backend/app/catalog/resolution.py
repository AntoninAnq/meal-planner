"""Matching ingredient lines against the referential, and deriving I3.

Separate from ingestion and replayable, which is the whole point: a recipe
fetched when the referential held fifty entries must gain its resolutions when
it holds three hundred, without asking anyone's server for the page again
(§7.5).

Three things happen here, and only the first is a match:

1. **Exact match after normalisation.** Approximate matches are proposed, never
   applied — I4, because substitute ingredients are named after the food they
   replace and a high similarity signals allergenic OPPOSITION as often as
   equivalence.
2. **`recipe_allergen` is derived** from the ingredients that resolved. It is
   written even for unconfirmed ones: an allergen tag can only exclude a recipe,
   and excluding one too many is the safe direction.
3. **`allergens_verified` is derived**, and it is the strict one: true only when
   every line of the recipe resolves AND every ingredient it resolves to has
   been confirmed by a human. That is I3 read literally, and it is what stops a
   machine-written referential from silently becoming a safety guarantee (I1).
"""

from __future__ import annotations

import collections
from dataclasses import dataclass, field
from decimal import Decimal
from fractions import Fraction

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog.ingredient_lines import parse_line
from app.catalog.referential import find, spelling_index
from app.db.models import (
    Ingredient,
    IngredientAllergen,
    Recipe,
    RecipeAllergen,
    RecipeIngredient,
)


@dataclass
class ResolutionReport:
    lines_seen: int = 0
    lines_resolved: int = 0
    lines_structural: int = 0
    recipes_complete: int = 0
    recipes_verified: int = 0
    recipes_total: int = 0
    #: What would be gained by adding one more referential entry, most valuable
    #: first. This is the list that says what to write next.
    next_best: list[tuple[str, int, int]] = field(default_factory=list)

    def render(self) -> str:
        rate = self.lines_resolved * 100 / max(self.lines_seen, 1)
        lines = [
            f"lignes            {self.lines_seen} ({self.lines_structural} structurelles)",
            f"résolues          {self.lines_resolved} ({rate:.1f} %)",
            f"recettes          {self.recipes_total}",
            f"  toutes lignes résolues   {self.recipes_complete}",
            f"  allergens_verified       {self.recipes_verified}",
        ]
        if self.recipes_complete and not self.recipes_verified:
            lines.append(
                "  ⚠ aucune recette vérifiée : les ingrédients sont encore des "
                "propositions. `catalog review` les confirme (I3)."
            )
        if self.next_best:
            lines.append("")
            lines.append("chaînes non résolues — occurrences, recettes qu'elles achèveraient :")
            for name, count, completes in self.next_best:
                lines.append(f"  {completes:4} recettes  ×{count:<5} {name}")
        return "\n".join(lines)


def _as_decimal(quantity: Fraction | None) -> Decimal | None:
    """`NUMERIC` cannot take a `Fraction`, and rightly so.

    The parser works in exact fractions because `1 1/2` and `0,5` both occur and
    floating point would drift on the halves. The database column is
    `NUMERIC(10,3)`, so the conversion happens here, once, at the boundary.
    """
    if quantity is None:
        return None
    return Decimal(quantity.numerator) / Decimal(quantity.denominator)


def _allergens_by_ingredient(db: Session) -> dict[str, set[str]]:
    mapping: dict[str, set[str]] = collections.defaultdict(set)
    for row in db.scalars(select(IngredientAllergen)):
        mapping[str(row.ingredient_id)].add(row.allergen_code.value)
    return mapping


def resolve(db: Session, *, report_only: bool = False, top: int = 40) -> ResolutionReport:
    report = ResolutionReport()
    index = spelling_index(db)
    allergens = _allergens_by_ingredient(db)
    confirmed_ids = {
        str(i.id) for i in db.scalars(select(Ingredient)) if i.confirmed_at is not None
    }

    lines = db.scalars(select(RecipeIngredient)).all()
    per_recipe: dict[str, list[tuple[str, str | None]]] = collections.defaultdict(list)
    unresolved = collections.Counter()

    for line in lines:
        report.lines_seen += 1
        parsed = parse_line(line.raw_text)

        # A line that normalises to nothing names no food — `(1 grosse)`,
        # `(si vous avez un alligator ☺)`. It can never resolve, so counting it
        # would keep its recipe out of the verified catalogue permanently. Same
        # treatment as a heading.
        if parsed.is_structural or line.is_section or not parsed.normalized:
            report.lines_structural += 1
            if not report_only and not line.is_section:
                line.is_section = True
                line.ingredient_id = None
            continue

        match = find(index, parsed.normalized)
        if match is None:
            unresolved[parsed.normalized] += 1
        else:
            report.lines_resolved += 1

        per_recipe[str(line.recipe_id)].append((parsed.normalized, match[0] if match else None))

        if not report_only:
            line.quantity = _as_decimal(parsed.quantity)
            line.unit = parsed.unit
            line.ingredient_id = match[0] if match else None

    # `next_best` ranks by RECIPES COMPLETED, not by raw frequency. A string
    # occurring 200 times across recipes that each have three other unknowns
    # unlocks nothing; one occurring 20 times as the last missing line unlocks
    # twenty recipes. Frequency alone would send someone down the wrong list.
    completes = collections.Counter()
    for names in per_recipe.values():
        missing = {name for name, ingredient_id in names if ingredient_id is None}
        if len(missing) == 1:
            completes[next(iter(missing))] += 1

    report.recipes_total = len(per_recipe)
    report.next_best = [
        (name, unresolved[name], completes[name])
        for name, _ in sorted(
            unresolved.items(), key=lambda kv: (-completes[kv[0]], -kv[1])
        )[:top]
    ]

    for recipe_id, names in per_recipe.items():
        resolved_ids = [ingredient_id for _, ingredient_id in names if ingredient_id]
        complete = all(ingredient_id for _, ingredient_id in names) and bool(names)
        if complete:
            report.recipes_complete += 1
        verified = complete and all(i in confirmed_ids for i in resolved_ids)
        if verified:
            report.recipes_verified += 1

        if report_only:
            continue

        recipe = db.get(Recipe, recipe_id)
        if recipe is None:
            continue
        recipe.allergens_verified = verified

        db.query(RecipeAllergen).filter(RecipeAllergen.recipe_id == recipe.id).delete()
        codes: set[str] = set()
        for ingredient_id in resolved_ids:
            codes |= allergens.get(ingredient_id, set())
        for code in sorted(codes):
            db.add(RecipeAllergen(recipe_id=recipe.id, allergen_code=code))

    if report_only:
        db.rollback()
    else:
        db.commit()
    return report
