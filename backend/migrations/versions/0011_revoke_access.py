"""Cutting off an access without deleting anything

The pendant of the quota (§11.7). Signing up is open, so someone unwanted can
arrive; the quota bounds what they SPEND, and nothing until now closed the
door. Deleting the row was the only option, and it is the wrong one twice over:
it destroys the household's data along with the access, and it lets the same
Google identity walk straight back in on the next login — `callback` provisions
a new household precisely when it finds no access row.

**A revoked row still counts as known**, which is what makes re-registration
impossible: the lookup in `callback` does not filter on `revoked_at`, so the
identity is recognised, no household is created, and `current_household_id`
then refuses. That is not an accident of the code — it is the reason the column
lives here rather than on `household`.

**Per access, not per household.** Two parents will each have their own row
within six months (see `HouseholdAccess`); one of them abusing is not a reason
to lock the other out of the family's plans.

There is no interface for this and there should not be one at this size. It is
one statement, run by hand:

    UPDATE household_access SET revoked_at = now() WHERE auth_subject = 'google:…';

and reversing it is the same statement with NULL.

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "household_access",
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("household_access", "revoked_at")
