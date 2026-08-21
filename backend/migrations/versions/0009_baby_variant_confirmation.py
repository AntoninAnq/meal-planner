"""A baby's serving variant is confirmed by the parent, never by the system

Measured, and the reason this column exists: **zero** of the 3 439 catalogue
recipes carries `baby` in its `suitable_stages`. A household with a child under
18 months could not be served at all — the stage left the grid entirely rather
than raise `eater_not_served` on all nine slots.

`ARCHITECTURE.md` §4.9 now lifts that, for the `baby` stage only: an assignment
onto a recipe that does not carry the stage is allowed **when a parent has
confirmed the serving variant**, dish by dish.

**Why a column and not a convention.** I1 forbids a *LLM* deciding safety, not a
*human* deciding it — but the difference has to be recorded somewhere the code
can read, or "the parent agreed" is a claim nobody can check. This is the same
shape as `ingredient.confirmed_at`: a model proposes, a human confirms, and
nothing is active in between.

**NULL is the default and it means "not yet".** A variant that has never been
confirmed is shown and marked as pending; it is not a meal the household can
count on. Only an assignment whose recipe genuinely suits the eater's stage
needs no confirmation at all.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "planned_dish_member",
        sa.Column("variant_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    # What the model proposed removing, as ingredient ids it had to choose from
    # the recipe's own list. Structured rather than prose for the reason the
    # week of 2026-08-20 made plain: asked in free text, the model wrote "sans
    # tomate" next to an eater on nine dishes, several of which held no tomato.
    # Ids can be checked against the recipe; a sentence cannot.
    op.create_table(
        "planned_dish_member_removal",
        sa.Column("planned_dish_id", sa.Uuid(), nullable=False),
        sa.Column("member_id", sa.Uuid(), nullable=False),
        sa.Column("ingredient_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["planned_dish_id", "member_id"],
            ["planned_dish_member.planned_dish_id", "planned_dish_member.member_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["ingredient_id"], ["ingredient.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("planned_dish_id", "member_id", "ingredient_id"),
    )


def downgrade() -> None:
    op.drop_table("planned_dish_member_removal")
    op.drop_column("planned_dish_member", "variant_confirmed_at")
