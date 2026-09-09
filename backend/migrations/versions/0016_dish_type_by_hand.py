"""A dish type a person decided, which the pipeline may not undo

`catalog dish-types` is idempotent by design: it rewrites `recipe.dish_type`
for every recipe from the rubric mapping, so re-running it after a mapping
change corrects the whole catalogue. That property is worth keeping — and it is
exactly what would erase the back office's work, silently, on the next run.

So a manual decision records who made it, and `derive` leaves those recipes
alone. The column carries the audit and the protection at once.

It exists because some rubrics cannot be mapped at all. `Tartes, Clafoutis`
groups an onion tart with a strawberry one; `db/dish_types.yaml` maps it to
nothing on purpose, and the recipes under it stay untyped — which is how a
dessert tart came to be offered as an alternative for a Thursday dinner. No
rule reaches that. A person looking at one recipe does.

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("recipe", sa.Column("dish_type_set_by", sa.String(length=255), nullable=True))
    op.add_column(
        "recipe", sa.Column("dish_type_set_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("recipe", "dish_type_set_at")
    op.drop_column("recipe", "dish_type_set_by")
