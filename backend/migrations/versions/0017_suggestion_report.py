"""A household saying a suggestion is wrong for everyone, not just for them

The other channel already exists: `Proposer autre chose` records a refusal as a
constraint on one household. This one says the catalogue is at fault, and its
resolution changes what every household sees.

Three categories, and each is here because the back office can act on it —
`not_a_meal` is retagged, `dead_link` and `bad_recipe` are withdrawn. A category
with no resolution produces a queue nobody can empty, which is how a feedback
channel becomes a place complaints go to die. There is deliberately no "we did
not fancy it": that is a matter of taste and it already has its own path.

Keyed on the RECIPE. The person clicks a dish in their week, but the defect
belongs to the catalogue entry behind it, and the queue has to group ten reports
of the same tart into one decision. One row per household and recipe, so
re-reporting corrects the category rather than adding a voice: a queue ranked by
how many different households complained is a signal, one ranked by clicks is a
measure of persistence.

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

CATEGORIES = ("not_a_meal", "dead_link", "bad_recipe")


def upgrade() -> None:
    sa.Enum(*CATEGORIES, name="report_category").create(op.get_bind(), checkfirst=True)
    category = postgresql.ENUM(*CATEGORIES, name="report_category", create_type=False)

    op.create_table(
        "suggestion_report",
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
        sa.Column("category", category, nullable=False),
        sa.Column("note", sa.String(length=280), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(length=255), nullable=True),
        sa.UniqueConstraint("household_id", "recipe_id", name="uq_report_household_recipe"),
    )


def downgrade() -> None:
    op.drop_table("suggestion_report")
    sa.Enum(name="report_category").drop(op.get_bind(), checkfirst=True)
