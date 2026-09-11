"""What a household means to cook again — distinct from what it liked

`MealHistory.rating` already grades a meal that happened. This table answers a
different question, asked at a different moment: what do you want proposed
again. A dinner everyone liked can be one nobody wants twice a month, and a
favourite can have gone badly the one time it was tried — so the two share no
storage and no display.

At the HOUSEHOLD, not at the account: the plan is the household's,
`household_access` already carries the sharing, and two parents planning
together do not keep two lists.

`recipe_id` cascades, unlike `meal_history` which restricts. A favourite is not
a historical fact — if the recipe leaves the catalogue there is nothing left to
cook. A meal that WAS eaten stays true whatever happens to the catalogue, which
is why that table is not aligned on this one.

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "household_favorite",
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
        # What makes `POST /favorites` idempotent without a read first: a second
        # click is a conflict the database settles, not a race the router has to.
        sa.UniqueConstraint("household_id", "recipe_id", name="uq_favorite_household_recipe"),
    )


def downgrade() -> None:
    op.drop_table("household_favorite")
