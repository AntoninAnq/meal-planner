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
from datetime import datetime
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog.confirmations import approves, load_confirmations
from app.db.models import (
    FoodCategory,
    Ingredient,
    IngredientAlias,
    IngredientAllergen,
    IngredientFoodCategory,
)
from app.domain.enums import AllergenCode
from app.domain.ingredient_names import normalise, variants


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
    reconfirmed: int = 0
    unconfirmed: int = 0
    warnings: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines = [
            f"catégories        {self.categories}",
            f"ingrédients       {self.ingredients_created} créés, "
            f"{self.ingredients_updated} mis à jour",
            f"alias             {self.aliases}",
            f"portant allergène {self.with_allergens}",
            f"confirmations restaurées depuis le fichier  {self.reconfirmed}",
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
    approvals = load_confirmations()
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

        # A confirmation applies to what was READ, not to a name. The approval
        # file records the allergen set as it stood when a human looked at it,
        # so correcting `sauce soja` from `[soybeans]` to `[gluten, soybeans]`
        # cannot inherit the approval given for the shorter list. Declarative
        # rather than stateful, which means it survives a database that was
        # restored or rebuilt (I1, I3).
        approval = approvals.get(canonical)
        declared = list(entry.get("allergens") or [])
        if approves(approval, declared):
            if ingredient.confirmed_at is None:
                ingredient.confirmed_at = datetime.fromisoformat(approval["at"])
                report.reconfirmed += 1
        else:
            if approval is not None:
                report.warnings.append(
                    f"{canonical} : approuvé pour {approval.get('allergens')}, "
                    f"déclaré {sorted(declared)} — confirmation non appliquée"
                )
            ingredient.confirmed_at = None

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

        # Deduplicated: two spellings of the SAME entry can normalise to one
        # string — `jus d' citron` and `jus citron` did, once the parser stopped
        # leaving elided articles behind. `_validate` cannot catch it (it only
        # refuses a spelling claimed by two DIFFERENT ingredients), so the
        # collision surfaced as a unique-constraint violation mid-load.
        written: set[str] = set()
        for spelling in entry.get("aliases") or []:
            alias = normalise(spelling)
            if not alias or alias == normalized or alias in written:
                continue
            written.add(alias)
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


def find(index: dict[str, tuple[str, bool]], normalized: str) -> tuple[str, bool] | None:
    """The exact spelling first, then progressively relaxed ones.

    The order is what makes the relaxation safe: an exact hit always wins, so
    every compound the referential carries — `petits pois`, `chocolat noir`,
    `crème fraîche` — is matched as itself and never taken apart. Relaxation
    only ever runs on a string nobody has written down.
    """
    match = index.get(normalized)
    if match is not None:
        return match
    for candidate in variants(normalized):
        match = index.get(candidate)
        if match is not None:
            return match
    return None
