"""Aliases for ingredients, and a confirmation that has teeth

Two additions, both forced by measurement rather than by taste.

**`ingredient_alias`** — the catalogue's 29 000 ingredient lines reduce to 7 312
distinct strings, and reaching the phase-1 exit criterion needs roughly 500 of
them recognised. But those 500 strings are not 500 foods: `sucre`, `sucre en
poudre` and `sucre glace` are one ingredient written three ways. Without
aliases, someone types 500 entities where about 300 exist, and the referential
grows a duplicate of itself.

**`ingredient.confirmed_at`** — the referential is the data the allergen filter
rests on (I2, I3), and a machine may propose it but never decide it (I1). A file
of proposals nobody re-reads satisfies the invariant on paper and breaks it in
substance, so the confirmation is made load-bearing instead of moral: the
resolution pass only counts CONFIRMED ingredients when deriving
`allergens_verified`. A recipe whose ingredients are still proposals stays
invisible to households with a severe allergy — which is precisely what I3
describes, arrived at from the other end.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ingredient", sa.Column("confirmed_at", sa.DateTime(timezone=True)))
    op.create_index("ix_ingredient_confirmed_at", "ingredient", ["confirmed_at"])

    op.create_table(
        "ingredient_alias",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "ingredient_id",
            sa.Uuid(),
            sa.ForeignKey("ingredient.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Unique across aliases, and the loader refuses one that collides with a
        # canonical name: two rows normalising the same way would make
        # resolution depend on which one the query happened to reach first.
        sa.Column("normalized_name", sa.String(160), nullable=False, unique=True),
    )
    op.create_index("ix_ingredient_alias_name", "ingredient_alias", ["normalized_name"])
    op.create_index("ix_ingredient_alias_ingredient", "ingredient_alias", ["ingredient_id"])
    op.execute(
        "CREATE INDEX ix_ingredient_alias_trgm "
        "ON ingredient_alias USING gin (normalized_name gin_trgm_ops)"
    )


def downgrade() -> None:
    op.drop_table("ingredient_alias")
    op.drop_index("ix_ingredient_confirmed_at", table_name="ingredient")
    op.drop_column("ingredient", "confirmed_at")
