"""Where the human approvals live.

A separate file from `ingredients.yaml`, and deliberately so. That one is
hand-authored and carries the reasoning behind every allergen — a machine
rewriting it would destroy the comments that justify the choices. This one is
machine-written and never annotated.

**What it records is what was APPROVED, not merely that something was.** Each
entry carries the allergen set as it stood when a human read it. The loader then
grants a confirmation only when the file still declares the same thing:
correcting `sauce soja` from `[soybeans]` to `[gluten, soybeans]` cannot inherit
an approval given for the shorter list. The rule is declarative rather than
stateful, so it survives a database that was restored, rebuilt, or dropped.

That last point is the reason this file exists at all. The confirmations are the
one part of the whole pipeline no machine can reproduce — an hour of human
judgement — and they were living only in a Docker volume.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import yaml

HEADER = """\
# Confirmations humaines du référentiel — écrit par `catalog review`.
#
# NE PAS ÉDITER À LA MAIN. Pour retirer une confirmation, supprime son bloc ;
# pour en ajouter une, passe par la CLI, qui est l'endroit où on la lit.
#
# `allergens` est la liste TELLE QU'ELLE A ÉTÉ APPROUVÉE. Si `ingredients.yaml`
# en déclare une autre, la confirmation ne s'applique plus et l'entrée retourne
# dans la file (I1, I3) — une approbation porte sur une valeur, pas sur un nom.
"""


def confirmations_file() -> Path:
    from app.config import get_settings

    return Path(get_settings().catalog_confirmations_path)


def load_confirmations(path: Path | None = None) -> dict[str, dict]:
    """Ingredient name → what was approved, and when."""
    target = path or confirmations_file()
    if not target.is_file():
        return {}
    document = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    return {entry["name"]: entry for entry in document.get("confirmations") or []}


def save_confirmations(records: dict[str, dict], path: Path | None = None) -> None:
    """Rewritten whole, sorted by name.

    Sorted so a diff shows what changed rather than where it landed — the file
    is meant to be read in a review, and a stable order is what makes that
    possible.
    """
    target = path or confirmations_file()
    payload = {
        "confirmations": [records[name] for name in sorted(records)],
    }
    target.write_text(
        HEADER + "\n" + yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def record(records: dict[str, dict], *, name: str, allergens: list[str]) -> dict[str, dict]:
    records[name] = {
        "name": name,
        "allergens": sorted(allergens),
        "at": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }
    return records


def approves(entry: dict | None, allergens: list[str]) -> bool:
    """Does this confirmation still cover what the referential now declares?"""
    if entry is None:
        return False
    return sorted(entry.get("allergens") or []) == sorted(allergens)
