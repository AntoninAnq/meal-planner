"""What a household never wants proposed again

The other half of 0018's favourite, and what replaces "Ce plat a plu ?". That
question wrote `meal_history.rating`, which nothing read: a household that said
no saw the dish come back the next week. A withheld recipe leaves the pool the
generation and the alternatives are drawn from, for this household only.

Shaped like `household_favorite` on purpose, cascade included: if the recipe
leaves the catalogue there is nothing left to withhold.

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "household_exclusion",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("household.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "recipe_id",
            sa.Uuid(),
            sa.ForeignKey("recipe.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # Same as the favourite: a second click is settled by the database.
        sa.UniqueConstraint("household_id", "recipe_id", name="uq_exclusion_household_recipe"),
    )


def downgrade() -> None:
    op.drop_table("household_exclusion")
