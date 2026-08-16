"""Persist the re-validation violations with the plan

The violations describe the plan that was written, so they belong with it.

They only existed in the response of `POST /meal-plans`. But the week view
loads through `GET` — deliberately, because that is what makes a lost response
survivable — so a reload dropped exactly the information saying the plan was
incomplete. The plan survived; the warning about it did not.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "meal_plan",
        sa.Column(
            "violations",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("meal_plan", "violations")
