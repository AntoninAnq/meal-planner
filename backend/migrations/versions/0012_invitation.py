"""An invitation lives beside the plan, not inside it

`meal_plan.slot_guests` (0005) is a display cache: the generation rewrites it,
it holds an anonymous head count and nothing else, and it cannot say the
household *chose* to have people over — only that the last run for that slot was
told about some.

An invitation is the other half. It is created by the household, it is edited
and found again days later, and it survives a regeneration or a cleared slot —
so it is a row of its own. Guests are still transitory: no member, nothing
nominative, a count and a life stage. `dislikes` is free text, a soft signal
like a household aversion. The entity is deliberately standing on its own so a
seating plan can hang off it later.

One row per slot (`uq_invitation_slot`): the interface edits "the Saturday
dinner", and re-creating it for the same slot replaces it.

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Already created by 0002 for `planned_dish` and `meal_slot_config`. Referenced
#: with `create_type=False` so `create_table` does not try to emit it again.
MEAL_TYPE = postgresql.ENUM("lunch", "dinner", name="meal_type", create_type=False)


def upgrade() -> None:
    op.create_table(
        "invitation",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("day_of_week", sa.SmallInteger(), nullable=False),
        sa.Column("meal_type", MEAL_TYPE, nullable=False),
        sa.Column(
            "guests",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "dislikes",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("day_of_week BETWEEN 0 AND 6", name="ck_invitation_day"),
        sa.ForeignKeyConstraint(["household_id"], ["household.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "household_id",
            "week_start",
            "day_of_week",
            "meal_type",
            name="uq_invitation_slot",
        ),
    )
    op.create_index("ix_invitation_household", "invitation", ["household_id"])


def downgrade() -> None:
    op.drop_index("ix_invitation_household", table_name="invitation")
    op.drop_table("invitation")
