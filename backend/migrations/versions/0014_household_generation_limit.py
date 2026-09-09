"""A household can be given its own ceiling on model calls

`generation_daily_limit` in `Settings` is the rate card everyone gets, and it
is the right shape for a rate card: one number, in configuration, derived from
what the provider charges (I8). What it cannot do is differ per household, and
three separate needs want exactly that.

* A paid tier is a HIGH ceiling, never the absence of one. An account whose
  session is stolen spends the operator's money at the provider regardless of
  what the customer paid, so "unlimited" is a promise nobody should make to
  their own billing.
* A suspected bot gets a low ceiling. Throttling keeps a false positive usable
  — a real household reads its week and cooks — where a ban does not.
* Zero is a real value, and the softest sanction that still stops the spend:
  no generation, the weeks already there still readable.

On `household` rather than `household_settings`: the latter is what the
household chooses and edits through its own endpoint, this is what the operator
allows. Sharing a table is one careless field on `HouseholdSettingsUpdate` away
from letting a household set its own quota.

Cutting an identity off entirely stays `household_access.revoked_at` (0011). A
ceiling and a revocation are different decisions with different blast radii,
and collapsing them into one column would make the mild one feel like the
severe one.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # Nullable with no server default: NULL is not "unset pending a value", it
    # is the answer — this household is on the standard rate card.
    op.add_column(
        "household",
        sa.Column("generation_limit_override", sa.SmallInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("household", "generation_limit_override")
