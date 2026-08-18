"""When a recipe can be eaten

Measured, and the reason this column exists: of the 555 catalogue recipes at
`allergens_verified = true`, **296 contain a sweetener**. That is not an
accident of the sources, it is a property of I3 — a cake's eight ingredient
lines all resolve, a tajine's fifteen include four nobody has written down yet.
The completeness the invariant demands selects dessert.

A pre-filter reading that catalogue would answer a Tuesday dinner with cake.

The value is derived from the rubric the source publishes as metadata — same
status as the title or the duration, so neither generated (I7) nor republished
(I9) — through the mapping in `db/dish_types.yaml`. Derived and replayable like
`allergens_verified`, never written at ingestion.

**NULL is a real state and it passes the filter.** 111 of those 555 carry no
rubric at all, and excluding them would spend 20 % of the catalogue on a
comfort guarantee. A dessert at dinner is a quality defect, not a safety one —
the allergen filter is elsewhere and does not consult this column.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DISH_TYPE = sa.Enum(
    "main",
    "starter",
    "side",
    "dessert",
    "snack",
    "breakfast",
    "drink",
    "component",
    name="dish_type",
)


def upgrade() -> None:
    DISH_TYPE.create(op.get_bind(), checkfirst=True)
    op.add_column("recipe", sa.Column("dish_type", DISH_TYPE, nullable=True))
    # The pre-filter excludes dessert, snack, drink and component from a meal
    # slot on every generation, so this is a hot-path read.
    op.create_index("ix_recipe_dish_type", "recipe", ["dish_type"])


def downgrade() -> None:
    op.drop_index("ix_recipe_dish_type", table_name="recipe")
    op.drop_column("recipe", "dish_type")
    DISH_TYPE.drop(op.get_bind(), checkfirst=True)
