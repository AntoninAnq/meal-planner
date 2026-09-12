"""Recipes a household writes for itself

The catalogue proposes dishes with eight ingredients and forty minutes of work,
and a Tuesday is often "steak purée". A row with `household_id` is private to
that household — `services/catalogue.visible_to` — and becomes everyone's only
when an operator sets `shared_at`.

`instructions` is the first prose this database holds, and the check constraint
is what keeps it the only one: a collected recipe links to its source and never
copies it (I9). A collection run cannot fill this column even by accident.

It also undoes the title-carrying favourite of 0023. Two ways to save a dish
without a recipe was one too many: the title becomes a recipe of the household,
and the favourite goes back to being a reference. Existing rows are converted
here rather than dropped.

`SET NULL` on the household, not cascade: a household that leaves must not take
a recipe other households already cook with.

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "recipe",
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("household.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    op.add_column("recipe", sa.Column("instructions", sa.Text(), nullable=True))
    op.add_column("recipe", sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "recipe", sa.Column("shared_at", sa.DateTime(timezone=True), nullable=True, index=True)
    )
    op.add_column("recipe", sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("recipe", sa.Column("rejected_reason", sa.String(length=40), nullable=True))
    op.create_check_constraint(
        "ck_recipe_instructions_user",
        "recipe",
        "instructions IS NULL OR source_type = 'user'",
    )

    # The favourites 0023 held as a title become recipes of their household,
    # and the favourite points at them. One statement, so a favourite is never
    # left without either.
    op.execute(
        """
        WITH created AS (
            INSERT INTO recipe (id, title, source_type, household_id)
            SELECT gen_random_uuid(), f.label, 'user', f.household_id
            FROM household_favorite f
            WHERE f.recipe_id IS NULL AND f.label IS NOT NULL
            RETURNING id, title, household_id
        )
        UPDATE household_favorite f
        SET recipe_id = c.id, label = NULL
        FROM created c
        WHERE f.recipe_id IS NULL AND f.household_id = c.household_id AND f.label = c.title
        """
    )

    op.drop_constraint("ck_favorite_recipe_or_label", "household_favorite", type_="check")
    op.drop_constraint("uq_favorite_household_label", "household_favorite", type_="unique")
    op.drop_column("household_favorite", "label")
    op.alter_column("household_favorite", "recipe_id", existing_type=sa.Uuid(), nullable=False)


def downgrade() -> None:
    """Gives the favourite its title back and takes the households' recipes out.

    A household recipe already on a planned week blocks its own deletion
    (`planned_dish.recipe_id` is RESTRICT), and that is the right failure: the
    week records what was eaten.
    """
    op.add_column("household_favorite", sa.Column("label", sa.String(length=200), nullable=True))
    op.alter_column("household_favorite", "recipe_id", existing_type=sa.Uuid(), nullable=True)
    op.execute(
        """
        UPDATE household_favorite f
        SET label = r.title, recipe_id = NULL
        FROM recipe r
        WHERE r.id = f.recipe_id AND r.household_id IS NOT NULL
        """
    )
    op.execute("DELETE FROM recipe WHERE household_id IS NOT NULL")
    op.create_unique_constraint(
        "uq_favorite_household_label", "household_favorite", ["household_id", "label"]
    )
    op.create_check_constraint(
        "ck_favorite_recipe_or_label",
        "household_favorite",
        "(recipe_id IS NULL) <> (label IS NULL)",
    )

    op.drop_constraint("ck_recipe_instructions_user", "recipe", type_="check")
    op.drop_column("recipe", "rejected_reason")
    op.drop_column("recipe", "rejected_at")
    op.drop_column("recipe", "shared_at")
    op.drop_column("recipe", "submitted_at")
    op.drop_column("recipe", "instructions")
    op.drop_column("recipe", "household_id")
