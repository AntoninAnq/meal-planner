"""What each household spends on model calls, and the ceiling that bounds it

Signing up is open: `provision_household` gives a household to any Google
identity that arrives, and that was chosen over an invite list on purpose — a
stranger who finds the product should be able to try it. The price of that
choice is a metered API behind an unguarded door, and this table is what closes
the gap.

**Counting `meal_plan` rows would not have worked, and that is why a table.** A
regeneration overwrites the week in place — same row, same id — so the plans
hold no trace of the second, third and tenth attempt. Those are exactly the
calls a quota exists to count.

It pays for itself twice more. `input_tokens`/`output_tokens`/`model_id` turn
"it seems to cost something" into a figure per household per month — the number
pricing will need, and the one §14.6 needs to compare two models on anything
but latency. And how often a real household regenerates is a product fact
nothing else records.

Rows are written for FAILED calls too, with the tokens the exhausted attempts
really consumed. A generation that burns its three attempts costs more than one
that succeeds, so an accounting that only sees successes understates the bill
exactly where it is highest.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: `create_type=False`, and the migration creates it by hand below.
#:
#: Left at its default, `create_table` emits its own CREATE TYPE for any enum
#: column it sees — after the explicit create, which then fails on "type
#: already exists". The two must not both own it, and the explicit one is kept
#: so `downgrade` has something symmetric to drop.
GENERATION_KIND = postgresql.ENUM(
    "week",
    "slot",
    "regenerate",
    "interpret",
    name="generation_kind",
    create_type=False,
)


def upgrade() -> None:
    GENERATION_KIND.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "generation_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("kind", GENERATION_KIND, nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempts", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("model_id", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("succeeded", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.ForeignKeyConstraint(["household_id"], ["household.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # Composite, and in this order: the quota asks one question — how many rows
    # for THIS household since a moment — and an index on the household alone
    # stops helping the day a tester has thousands of rows, which is the day the
    # quota starts mattering.
    op.create_index(
        "ix_generation_log_household_created",
        "generation_log",
        ["household_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_generation_log_household_created", table_name="generation_log")
    op.drop_table("generation_log")
    GENERATION_KIND.drop(op.get_bind(), checkfirst=True)
