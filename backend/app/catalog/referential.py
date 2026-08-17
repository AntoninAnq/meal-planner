"""Loading `db/ingredients.yaml` into the referential.

Idempotent, and deliberately dull: it reads a versioned file and makes the
database match it. The file is the source of truth, so a mistake is corrected by
editing it and reloading, and the correction is visible in a Git diff — which is
the whole reason the referential is a file rather than a form (§7.5).

**It never sets `confirmed_at`.** The entries it writes are proposals; only
`review` confirms them, and only confirmed ingredients count towards
`allergens_verified` (I1, I3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog.ingredient_lines import normalise
from app.db.models import (
    FoodCategory,
    Ingredient,
    IngredientAlias,
    IngredientAllergen,
    IngredientFoodCategory,
)
from app.domain.enums import AllergenCode


def referential_file() -> Path:
    """Where `ingredients.yaml` is mounted.

    Configuration rather than a path walked up from `__file__` (I8): the file
    lives in `db/` in the repository and is mounted into the container, so its
    location there is a deployment fact, not a property of the source tree.
    """
    from app.config import get_settings

    return Path(get_settings().catalog_referential_path)


class ReferentialError(ValueError):
    """The file is malformed. Refused whole rather than loaded in part."""


@dataclass
class LoadReport:
    categories: int = 0
    ingredients_created: int = 0
    ingredients_updated: int = 0
    aliases: int = 0
    with_allergens: int = 0
    unconfirmed: int = 0
    warnings: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines = [
            f"catégories        {self.categories}",
            f"ingrédients       {self.ingredients_created} créés, "
            f"{self.ingredients_updated} mis à jour",
            f"alias             {self.aliases}",
            f"portant allergène {self.with_allergens}",
            f"À CONFIRMER       {self.unconfirmed} — tant qu'ils ne le sont pas, "
            "les recettes qui en dépendent restent non vérifiées (I3)",
        ]
        lines += [f"  ! {w}" for w in self.warnings]
        return "\n".join(lines)


def _validate(document: dict, known_categories: set[str]) -> dict[str, str]:
    """Every alias, normalised, mapped to its ingredient name.

    Refuses a duplicate alias outright: two entries claiming the same string
    would make resolution depend on which row a query happened to reach first,
    and on the data the allergen filter reads that is not a bug worth having.
    """
    allergen_codes = {code.value for code in AllergenCode}
    owner: dict[str, str] = {}

    for entry in document.get("ingredients") or []:
        name = entry.get("name")
        if not name:
            raise ReferentialError("an ingredient has no name")

        unknown = set(entry.get("allergens") or []) - allergen_codes
        if unknown:
            raise ReferentialError(f"{name}: unknown allergen code {sorted(unknown)}")
        unknown = set(entry.get("categories") or []) - known_categories
        if unknown:
            raise ReferentialError(f"{name}: unknown food category {sorted(unknown)}")

        names = [normalise(name), *(normalise(a) for a in entry.get("aliases") or [])]
        for spelling in names:
            if not spelling:
                continue
            if spelling in owner and owner[spelling] != name:
                raise ReferentialError(
                    f"{spelling!r} is claimed by both {owner[spelling]!r} and {name!r}"
                )
            owner[spelling] = name
    return owner


def load_referential(db: Session, path: Path | None = None) -> LoadReport:
    path = path or referential_file()
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    report = LoadReport()

    categories: dict[str, FoodCategory] = {}
    for entry in document.get("food_categories") or []:
        category = db.scalar(select(FoodCategory).where(FoodCategory.code == entry["code"]))
        if category is None:
            category = FoodCategory(code=entry["code"], label=entry["label"])
            db.add(category)
        else:
            category.label = entry["label"]
        categories[entry["code"]] = category
    db.flush()
    report.categories = len(categories)

    _validate(document, set(categories))

    for entry in document.get("ingredients") or []:
        canonical = entry["name"]
        normalized = normalise(canonical)
        ingredient = db.scalar(
            select(Ingredient).where(Ingredient.normalized_name == normalized)
        )
        if ingredient is None:
            ingredient = Ingredient(canonical_name=canonical, normalized_name=normalized)
            db.add(ingredient)
            report.ingredients_created += 1
        else:
            ingredient.canonical_name = canonical
            report.ingredients_updated += 1
        db.flush()

        # Replaced wholesale rather than merged: the file is the source of
        # truth, so removing an allergen from it must remove it from the
        # database. A merge would make deletions impossible and quietly keep a
        # tag someone deliberately withdrew.
        db.query(IngredientAllergen).filter(
            IngredientAllergen.ingredient_id == ingredient.id
        ).delete()
        db.query(IngredientFoodCategory).filter(
            IngredientFoodCategory.ingredient_id == ingredient.id
        ).delete()
        db.query(IngredientAlias).filter(
            IngredientAlias.ingredient_id == ingredient.id
        ).delete()

        allergens = entry.get("allergens") or []
        for code in allergens:
            db.add(
                IngredientAllergen(
                    ingredient_id=ingredient.id, allergen_code=AllergenCode(code)
                )
            )
        if allergens:
            report.with_allergens += 1

        for code in entry.get("categories") or []:
            db.add(
                IngredientFoodCategory(
                    ingredient_id=ingredient.id, food_category_id=categories[code].id
                )
            )

        for spelling in entry.get("aliases") or []:
            alias = normalise(spelling)
            if not alias or alias == normalized:
                continue
            db.add(IngredientAlias(ingredient_id=ingredient.id, normalized_name=alias))
            report.aliases += 1

        if ingredient.confirmed_at is None:
            report.unconfirmed += 1

    db.commit()
    return report


def spelling_index(db: Session) -> dict[str, tuple[str, bool]]:
    """Every recognised spelling → (ingredient id, confirmed).

    One dictionary rather than a query per line: resolution walks 29 000 rows,
    and the referential is a few hundred.
    """
    index: dict[str, tuple[str, bool]] = {}
    for ingredient in db.scalars(select(Ingredient)):
        confirmed = ingredient.confirmed_at is not None
        index[ingredient.normalized_name] = (str(ingredient.id), confirmed)
    for alias in db.scalars(select(IngredientAlias)):
        ingredient = db.get(Ingredient, alias.ingredient_id)
        if ingredient is not None:
            index[alias.normalized_name] = (str(ingredient.id), ingredient.confirmed_at is not None)
    return index
