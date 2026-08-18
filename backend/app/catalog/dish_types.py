"""Reading `source_categories` as a moment of the meal.

Deterministic and replayable, like resolution: the mapping is a versioned file,
the derivation is a pass that can be run again when the file grows. Nothing
here is judged by a model (§6.4 postpones enrichment) and nothing is guessed
from the prose — the input is the rubric the source publishes as metadata,
which is the same class of data as the title and the duration.

**Two axes, and confusing them is the trap this module exists to avoid.**
`recipe_food_category` describes the COMPOSITION and is derived from the
resolved ingredients; it feeds the rotation signal. `dish_type` describes WHEN
the thing is eaten, and it is not derivable from composition — a quiche and an
apple tart carry the same ingredient categories.

This is a quality signal. The allergen filter never reads it, and a mistake
here costs a candidate, not a safety guarantee.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Recipe
from app.domain.enums import DishType


def dish_types_file() -> Path:
    from app.config import get_settings

    return Path(get_settings().catalog_dish_types_path)


class DishTypeError(ValueError):
    """The mapping is malformed. Refused whole rather than applied in part."""


@dataclass(frozen=True)
class DishTypeMapping:
    #: Source rubric -> type. Rubrics deliberately mapped to "no information"
    #: are absent from this dict and present in `examined` — the difference
    #: matters to a reader, not to the machine.
    labels: dict[str, DishType]
    #: Most restrictive first. A recipe carrying several rubrics takes the
    #: first of them that appears here.
    precedence: tuple[DishType, ...]
    examined: frozenset[str]

    def classify(self, categories: list[str]) -> DishType | None:
        """The most restrictive rubric wins.

        A recipe tagged both `Plat` and `Dessert` is a dessert. Missing a dish
        costs one candidate out of several hundred; putting a cake on a Tuesday
        dinner costs the trust someone places in the tool, and that is not
        symmetrical.
        """
        found = {self.labels[label] for label in categories if label in self.labels}
        if not found:
            return None
        for candidate in self.precedence:
            if candidate in found:
                return candidate
        # Unreachable while `_load` validates that precedence covers every
        # type, which it does — but returning something arbitrary here would
        # hide that regression rather than surface it.
        raise DishTypeError(f"no precedence for {sorted(t.value for t in found)}")


def load_mapping(path: Path | None = None) -> DishTypeMapping:
    document = yaml.safe_load((path or dish_types_file()).read_text(encoding="utf-8")) or {}

    declared = {entry["code"] for entry in document.get("types") or []}
    known = {member.value for member in DishType}
    if declared != known:
        raise DishTypeError(
            f"types declared {sorted(declared)} but DishType has {sorted(known)}"
        )

    precedence = [DishType(code) for code in document.get("precedence") or []]
    if set(precedence) != set(DishType):
        raise DishTypeError("precedence must list every dish type exactly once")

    labels: dict[str, DishType] = {}
    examined: set[str] = set()
    for code, entries in (document.get("labels") or {}).items():
        for label in entries or []:
            if label in examined:
                raise DishTypeError(f"{label!r} is mapped twice")
            examined.add(label)
            if code == "unknown":
                # Written down rather than omitted, so the next reader knows it
                # was looked at. Same effect as absence, different meaning.
                continue
            labels[label] = DishType(code)

    return DishTypeMapping(
        labels=labels, precedence=tuple(precedence), examined=frozenset(examined)
    )


@dataclass
class DishTypeReport:
    recipes: int = 0
    classified: int = 0
    unclassified: int = 0
    per_type: dict[str, int] = field(default_factory=dict)
    #: Rubrics present in the catalogue that the file says nothing about. This
    #: is the work list: each one is a line to add, or to record as examined.
    unmapped: list[tuple[str, int]] = field(default_factory=list)

    def render(self) -> str:
        lines = [
            f"recettes          {self.recipes}",
            f"classées          {self.classified}",
            f"sans rubrique     {self.unclassified} — elles passent le pré-filtre",
        ]
        lines += [f"  {code:<10} {count}" for code, count in sorted(self.per_type.items())]
        if self.unmapped:
            lines.append("")
            lines.append("rubriques inconnues du fichier — à cartographier :")
            lines += [f"  ×{count:<4} {label}" for label, count in self.unmapped[:40]]
        return "\n".join(lines)


def derive(db: Session, *, report_only: bool = False, path: Path | None = None) -> DishTypeReport:
    mapping = load_mapping(path)
    report = DishTypeReport()
    unmapped: dict[str, int] = {}

    for recipe in db.scalars(select(Recipe)):
        report.recipes += 1
        categories = list(recipe.source_categories or [])
        for label in categories:
            if label not in mapping.examined:
                unmapped[label] = unmapped.get(label, 0) + 1

        dish_type = mapping.classify(categories)
        if dish_type is None:
            report.unclassified += 1
        else:
            report.classified += 1
            report.per_type[dish_type.value] = report.per_type.get(dish_type.value, 0) + 1

        if not report_only:
            recipe.dish_type = dish_type

    report.unmapped = sorted(unmapped.items(), key=lambda kv: -kv[1])

    if report_only:
        db.rollback()
    else:
        db.commit()
    return report
