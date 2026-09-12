"""Reading one ingredient line, for someone who is typing it.

The collection pipeline resolves 29 000 lines at a time and builds an index in
memory to do it (`app/catalog/resolution.py`). This is the other shape of the
same question: one line, now, while a person watches — so it is a query, and it
lives here because **the API may not import `app/catalog/`**
(`tests/test_catalog_boundaries.py`). What the two share is the part that
carries the meaning: the parser and the name rules, both in `app/domain/`.

The matching rule is the pipeline's, unchanged: exact spelling first, then the
relaxations of `variants`, and never anything approximate (I4). A substitute is
named after the food it replaces — `farine de riz` is closest to `farine de
blé` — so a near miss is as likely to mean the opposite as the same thing, and
the answer to a line nobody recognises is to say so, not to guess.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Ingredient, IngredientAlias
from app.domain.ingredient_lines import parse_line
from app.domain.ingredient_names import normalise, variants


@dataclass(frozen=True)
class ResolvedLine:
    """One line as the database will hold it, plus what to say about it."""

    raw: str
    quantity: Decimal | None
    unit: str | None
    #: What matching read. Empty for a line that names no food.
    normalized: str
    ingredient_id: uuid.UUID | None
    #: A heading or an aside — `Pour la pâte :`, `(si vous avez un alligator)`.
    #: Never resolved, and never counted against the recipe (I3).
    is_structural: bool


def _as_decimal(quantity: Fraction | None) -> Decimal | None:
    """`NUMERIC` cannot take a `Fraction`, and rightly so — see the pipeline's
    copy of this reasoning: the parser works in exact fractions because `1 1/2`
    and `0,5` both occur."""
    if quantity is None:
        return None
    return Decimal(quantity.numerator) / Decimal(quantity.denominator)


def _lookup(db: Session, spellings: list[str]) -> uuid.UUID | None:
    """The first of these spellings the referential knows, in order.

    Order matters and is the caller's: an exact hit must win, so every compound
    the referential carries — `petits pois`, `chocolat noir` — is matched as
    itself and never taken apart.
    """
    if not spellings:
        return None
    rows = dict(
        db.execute(
            select(Ingredient.normalized_name, Ingredient.id).where(
                Ingredient.normalized_name.in_(spellings)
            )
        ).all()
    )
    rows.update(
        dict(
            db.execute(
                select(IngredientAlias.normalized_name, IngredientAlias.ingredient_id).where(
                    IngredientAlias.normalized_name.in_(spellings),
                    # An alias never overrides a name the referential carries
                    # itself: the loop below takes the first spelling that hits,
                    # and both dictionaries are keyed by that spelling.
                    IngredientAlias.normalized_name.not_in(list(rows)),
                )
            ).all()
        )
    )
    for spelling in spellings:
        found = rows.get(spelling)
        if found is not None:
            return found
    return None


def resolve_line(db: Session, raw: str) -> ResolvedLine:
    """Split a line, then look its food up. No writing, no side effect."""
    parsed = parse_line(raw)
    if parsed.is_structural or not parsed.normalized:
        return ResolvedLine(
            raw=parsed.raw,
            quantity=None,
            unit=None,
            normalized=parsed.normalized,
            ingredient_id=None,
            is_structural=True,
        )

    spellings = [parsed.normalized, *variants(parsed.normalized)]
    return ResolvedLine(
        raw=parsed.raw,
        quantity=_as_decimal(parsed.quantity),
        unit=parsed.unit,
        normalized=parsed.normalized,
        ingredient_id=_lookup(db, spellings),
        is_structural=False,
    )


def search(db: Session, query: str, *, limit: int = 8) -> list[tuple[uuid.UUID, str]]:
    """Foods whose name starts with what is being typed, then contains it.

    For the one case the exact rule cannot serve: a line nobody recognised, and
    a person who can say which food they meant. Prefix first because that is
    how someone types a word they know; the contains pass catches `huile
    d'olive` from `olive`.
    """
    needle = normalise(query)
    if not needle:
        return []
    rows = db.execute(
        select(Ingredient.id, Ingredient.canonical_name)
        .where(Ingredient.normalized_name.like(f"%{needle}%"))
        .order_by(
            # `LIKE 'x%'` first, then the rest, and alphabetical inside each.
            func.coalesce(func.nullif(Ingredient.normalized_name.like(f"{needle}%"), False), False)
            .desc(),
            Ingredient.canonical_name,
        )
        .limit(limit)
    ).all()
    return [(row.id, row.canonical_name) for row in rows]
