"""Remember that a slot was planned for guests

Guests are transitory and never become members — people who eat here twice a
year would otherwise skew anti-repetition, default portions and stage proposals
all year long. That rule stands.

But a meal planned for nine people displayed dishes for three, with nothing
saying why: you look at Saturday, see a dish for the household, and have
forgotten it was the dinner with the in-laws.

So an anonymous count per slot is kept — a life stage and a number, nothing
that identifies anyone, and **nothing the planner ever reads**. It exists for
the interface and for no other purpose. The guest information used to live in
`meal_plan.generation_input`, which is plan-level: regenerating Saturday
rewrote it for the whole week, so it could not say WHICH meal had guests.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "meal_plan",
        sa.Column(
            "slot_guests",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("meal_plan", "slot_guests")
