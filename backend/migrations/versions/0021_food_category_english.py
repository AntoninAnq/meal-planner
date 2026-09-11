"""The one piece of catalogue data a reader sees in their own language

`food_category.label` is French, and the shopping list prints those labels as
its section headings — so on the English locale the whole list would come out
with French headings over English chrome.

A column rather than message keys, for the same reason the codes live in
`db/ingredients.yaml` and are reviewed as a Git diff: splitting a category's
labels across two files lets one exist with no heading at all. The loader writes
both from the same YAML entry, and this migration backfills the rows that are
already there.

Nullable, and the reader falls back on the French label. A heading in the wrong
language is legible; a section with no name is not.

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

LABELS: tuple[tuple[str, str], ...] = (
    ("cereal", "Grains and starches"),
    ("legumes_secs", "Pulses"),
    ("green_vegetable", "Green vegetables"),
    ("root_vegetable", "Root vegetables"),
    ("vegetable", "Other vegetables"),
    ("fruit", "Fruit"),
    ("red_meat", "Red meat"),
    ("white_meat", "White meat"),
    ("charcuterie", "Cured meats"),
    ("fish", "Fish"),
    ("seafood", "Seafood"),
    ("egg", "Eggs"),
    ("dairy", "Dairy"),
    ("cheese", "Cheese"),
    ("nuts_seeds", "Nuts and seeds"),
    ("fat_oil", "Fats and oils"),
    ("sweetener", "Sugars"),
    ("herb_spice", "Herbs and spices"),
    ("condiment", "Condiments and sauces"),
    ("alcohol", "Alcohol"),
    ("broth", "Stocks"),
    ("leavening", "Leavening agents"),
    ("other", "Other"),
)


def upgrade() -> None:
    op.add_column("food_category", sa.Column("label_en", sa.String(length=120), nullable=True))

    category = sa.table(
        "food_category",
        sa.column("code", sa.String),
        sa.column("label_en", sa.String),
    )
    for code, label_en in LABELS:
        op.execute(
            category.update().where(category.c.code == code).values(label_en=label_en)
        )


def downgrade() -> None:
    op.drop_column("food_category", "label_en")
