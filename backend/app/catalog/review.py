"""Confirming what a machine proposed.

This is the human half of I1, and its design has one job: make a real reading
cheap enough that it actually happens. A queue that presents 249 entries in
arbitrary order gets abandoned at entry 40, and the invariant then holds on
paper only.

So the order is **by risk, descending**. Entries carrying an allergen come
first, most-used first within that; the ones carrying none come last and can be
confirmed in bulk, because a wrong "no allergen" on `eau` is not a thing that
happens. What deserves attention is `sauce soja` (soy AND wheat), `bouillon`
(celery), `nuoc-mâm` (fish) — the ones whose name says nothing about what they
contain, which is the whole reason I2 exists.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.catalog.confirmations import (
    confirmations_file,
    load_confirmations,
    record,
    save_confirmations,
)
from app.db.models import (
    FoodCategory,
    Ingredient,
    IngredientAlias,
    IngredientAllergen,
    IngredientFoodCategory,
    RecipeIngredient,
)


class ReadOnlyConfirmations(RuntimeError):
    """The approvals file cannot be written, so the review must not start."""


def _refuse_if_unwritable(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8"):
            pass
    except OSError as exc:
        raise ReadOnlyConfirmations(
            f"{path} n'est pas accessible en écriture ({exc.strerror}).\n"
            "La revue s'exécute sur le service `catalog`, pas sur `api` — "
            "seul le premier monte db/ en écriture :\n"
            "    docker compose run --rm catalog review --bulk-safe"
        ) from exc


def pending(db: Session) -> list[tuple[Ingredient, list[str], list[str], int]]:
    """Unconfirmed ingredients, riskiest first.

    Returns each one with its allergens, its categories and how many catalogue
    lines depend on it — that last number is what tells a reader whether an
    entry is worth arguing about.
    """
    usage = dict(
        db.execute(
            select(RecipeIngredient.ingredient_id, func.count())
            .where(RecipeIngredient.ingredient_id.is_not(None))
            .group_by(RecipeIngredient.ingredient_id)
        ).all()
    )

    rows = []
    for ingredient in db.scalars(select(Ingredient).where(Ingredient.confirmed_at.is_(None))):
        allergens = sorted(
            row.allergen_code.value
            for row in db.scalars(
                select(IngredientAllergen).where(
                    IngredientAllergen.ingredient_id == ingredient.id
                )
            )
        )
        categories = sorted(
            db.scalars(
                select(FoodCategory.code)
                .join(
                    IngredientFoodCategory,
                    IngredientFoodCategory.food_category_id == FoodCategory.id,
                )
                .where(IngredientFoodCategory.ingredient_id == ingredient.id)
            )
        )
        rows.append((ingredient, allergens, categories, usage.get(ingredient.id, 0)))

    # Risk first, then usage. Both descending.
    rows.sort(key=lambda row: (-len(row[1]), -row[3]))
    return rows


def confirm(db: Session, ingredient: Ingredient, allergens: list[str],
            records: dict[str, dict]) -> None:
    """Written to the database AND to the versioned file.

    The database alone would put an hour of human judgement — the one part of
    this pipeline no machine can reproduce — inside a Docker volume, where a
    single `down -v` ends it. The file records WHAT was approved, so a later
    correction to the referential cannot inherit the approval.
    """
    ingredient.confirmed_at = datetime.now(UTC)
    record(records, name=ingredient.canonical_name, allergens=allergens)


def describe(db: Session, ingredient: Ingredient, allergens: list[str], categories: list[str],
             usage: int) -> str:
    aliases = sorted(
        db.scalars(
            select(IngredientAlias.normalized_name).where(
                IngredientAlias.ingredient_id == ingredient.id
            )
        )
    )
    lines = [
        f"  {ingredient.canonical_name}",
        f"    allergènes  {', '.join(allergens) if allergens else '— aucun —'}",
        f"    catégories  {', '.join(categories) or '—'}",
        f"    utilisé par {usage} lignes du catalogue",
    ]
    if aliases:
        shown = ", ".join(aliases[:8])
        more = f" (+{len(aliases) - 8})" if len(aliases) > 8 else ""
        lines.append(f"    écritures   {shown}{more}")
    return "\n".join(lines)


def run_review(
    db: Session,
    *,
    ask: Callable[[str], str] = input,
    say: Callable[[str], None] = print,
    bulk_safe: bool = False,
) -> int:
    """The loop. `ask` and `say` are injected so the flow is testable.

    `bulk_safe` confirms, in one go, only the entries that declare NO allergen.
    It exists because roughly 150 of 249 entries are `eau`, `carotte`, `thym` —
    reading them one by one is what makes someone abandon the queue before
    reaching `sauce soja`.
    """
    # Checked BEFORE anything is read or written. The `api` service mounts
    # `db/` read-only and only `catalog` mounts it writable, so running this on
    # the wrong service used to commit the database and then fail on the file —
    # leaving entries confirmed in one place and absent from the other, which
    # is the exact drift this file exists to prevent.
    _refuse_if_unwritable(confirmations_file())

    queue = pending(db)
    if not queue:
        say("rien à confirmer.")
        return 0

    risky = [row for row in queue if row[1]]
    plain = [row for row in queue if not row[1]]
    say(
        f"{len(queue)} entrées à confirmer — {len(risky)} portent un allergène, "
        f"{len(plain)} n'en portent aucun."
    )

    records = load_confirmations()
    confirmed = 0
    if bulk_safe:
        for ingredient, allergens, *_ in plain:
            confirm(db, ingredient, allergens, records)
            confirmed += 1
        # File first, database second. The file is the durable record and the
        # database is derived from it; committing first would claim a
        # confirmation that nothing outside a Docker volume remembers.
        save_confirmations(records)
        db.commit()
        say(f"{confirmed} entrées sans allergène confirmées en bloc.")
        queue = risky

    say("o = confirmer · n = passer · q = quitter\n")
    for ingredient, allergens, categories, usage in queue:
        say(describe(db, ingredient, allergens, categories, usage))
        answer = ask("    [o/n/q] ").strip().lower()
        if answer == "q":
            break
        if answer == "o":
            confirm(db, ingredient, allergens, records)
            confirmed += 1
            # Written after every answer rather than at the end, so a review
            # interrupted by Ctrl-C keeps what was already decided — and file
            # first, for the same reason as above.
            save_confirmations(records)
            db.commit()
        say("")

    say(
        f"{confirmed} entrées confirmées, écrites dans db/confirmations.yaml — "
        "pense à le commiter. `catalog resolve` prendra en compte les nouvelles."
    )
    return confirmed


def iter_pending_names(db: Session) -> Iterator[str]:
    for ingredient, *_ in pending(db):
        yield ingredient.canonical_name
