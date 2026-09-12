"""A favourite that has no recipe, kept by its title

"Pâtes au jambon" is a dish a household makes without looking anything up, and
it could not be a favourite: `recipe_id` was required. It is now either a
catalogue recipe or the title as it was written — exactly one of the two, which
the check constraint holds.

Nothing enters the catalogue (I7): this row is the household's. What a title
costs is said where it shows — no ingredients, so no allergen check and nothing
on the shopping list, and never proposed by the generation.

The downgrade drops the favourites that have no recipe: the old schema has
nowhere to put them.

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("household_favorite", "recipe_id", existing_type=sa.Uuid(), nullable=True)
    op.add_column("household_favorite", sa.Column("label", sa.String(length=200), nullable=True))
    op.create_unique_constraint(
        "uq_favorite_household_label", "household_favorite", ["household_id", "label"]
    )
    op.create_check_constraint(
        "ck_favorite_recipe_or_label",
        "household_favorite",
        "(recipe_id IS NULL) <> (label IS NULL)",
    )


def downgrade() -> None:
    op.execute("DELETE FROM household_favorite WHERE recipe_id IS NULL")
    op.drop_constraint("ck_favorite_recipe_or_label", "household_favorite", type_="check")
    op.drop_constraint("uq_favorite_household_label", "household_favorite", type_="unique")
    op.drop_column("household_favorite", "label")
    op.alter_column("household_favorite", "recipe_id", existing_type=sa.Uuid(), nullable=False)
