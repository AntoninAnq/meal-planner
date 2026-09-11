"""Why a dish has no adaptation, and what somebody chose to override

Two booleans on `planned_dish`, both about a decision a person made rather than
about the dish itself.

`placed_from_favorite` is what makes the missing serving variant legible. A
favourite replaces a proposal; nothing recomputes the small portion, and
`0009`'s confirmation has nothing to confirm. Without this flag the interface
shows a slot where the baby's plate simply vanished, which reads as a fault.

`allergen_override` survives the click. A warning that disappears for ever the
moment it is dismissed is not a warning — and unlike a dialog, this meal is on a
table four days later, cooked by whoever is free that evening. The row is what
lets the panel keep saying it.

Both default false, for the rows that already exist and for every dish the
generation writes: a proposal is neither.

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "planned_dish",
        sa.Column(
            "placed_from_favorite",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "planned_dish",
        sa.Column(
            "allergen_override", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )


def downgrade() -> None:
    op.drop_column("planned_dish", "allergen_override")
    op.drop_column("planned_dish", "placed_from_favorite")
