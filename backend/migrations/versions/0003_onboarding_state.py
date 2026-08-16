"""Onboarding state

`household_settings` gains `onboarded_at`, set when the onboarding page is
finished — including when the answer to the allergy question was "nobody here".

That answer is precisely what needs recording. Deducing "the onboarding is
done" from the existence of members has a hole that is not an edge case:
someone adds their members, is interrupted, comes back later, and is sent
straight to the week view — so the allergy question is never asked, in the one
case where asking it mattered.

Existing households are backfilled: they were provisioned before this column
existed and have already been through whatever passed for onboarding. Sending
them back through it would be a regression, not a fix.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "household_settings",
        sa.Column("onboarded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE household_settings SET onboarded_at = now()")


def downgrade() -> None:
    op.drop_column("household_settings", "onboarded_at")
