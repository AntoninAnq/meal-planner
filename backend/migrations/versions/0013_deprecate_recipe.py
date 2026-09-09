"""A recipe can be withdrawn without being deleted

`cuisine-libre.org` answers 404. It is 1 984 of the 3 439 recipes in the
catalogue — 57.7 % — so the interface currently sends more than half of every
week's "voir la recette" links into nothing, which is the half of I9 the
catalogue owes its authors.

Deleting them is wrong twice. `planned_dish.recipe_id` is `ondelete="RESTRICT"`
by design, so weeks already cooked would either block the delete or lose the
dish they record; and a site that is down may come back, at which point a
re-scrape restores rows instead of re-discovering them. So the rows stay and
stop being offered.

Per recipe rather than per source, and not a `catalog_source` table: §8.2 keeps
source metadata in the YAML descriptor precisely so it cannot drift against a
duplicate in the database. A column on the recipe also happens to be the finer
tool — one bad page can be withdrawn without condemning its whole site.

The licences are the reason this is reversible rather than a loss: 927 of these
recipes are CC BY-SA, 256 CC0, 234 Public Domain Mark, 108 CC BY. Nothing about
withdrawing them forecloses recovering the content from an archive later.

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

#: Withdrawn here because its site is gone. Named in the migration rather than
#: read from `sources.yaml`: a migration records what was done on a date, and
#: must keep saying the same thing after the descriptor is edited.
DEAD_SOURCE = "cuisine-libre"


def upgrade() -> None:
    op.add_column(
        "recipe",
        sa.Column("deprecated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_recipe_deprecated_at", "recipe", ["deprecated_at"])

    op.execute(
        sa.text(
            "UPDATE recipe SET deprecated_at = now() WHERE source_code = :code"
        ).bindparams(code=DEAD_SOURCE)
    )


def downgrade() -> None:
    op.drop_index("ix_recipe_deprecated_at", table_name="recipe")
    op.drop_column("recipe", "deprecated_at")
