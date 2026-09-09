"""Who may run the instance, at two levels

The catalogue needs human judgement that no rule reaches. `Tartes, Clafoutis`
is the case that settled it: the rubric groups an onion tart with a strawberry
one, so `db/dish_types.yaml` deliberately maps it to nothing, and the recipes
under it stay untyped — which is how a dessert tart came to be offered as an
alternative for a Thursday dinner. Only a person looking at one recipe can tell
those apart, and there are enough of them to want help.

Recruiting help is what makes this a table rather than a list in the
configuration: helpers arrive and leave, and neither should be a redeploy.

**Two levels, one asymmetry.** A `contributor` retags — reversible, hurts
nobody. Only an `owner` grants, because granting is privilege escalation: a
helper who can add helpers can remove the person who invited them. A single
level forces a choice between not delegating and handing over the keys, and
adding the distinction afterwards means deciding retroactively who was which.

Its own table, not a column on `household_access`: operating the instance is
not a property of a link to one household. Someone may operate without ever
having generated a week, and losing the right must not touch their household.

`granted_by` is nullable for exactly one row — the first owner, created by
`python -m app.admin grant` before any interface exists to do it.

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

LEVELS = ("owner", "contributor")


def upgrade() -> None:
    # Created here and referenced with `create_type=False` below — the pattern
    # 0006 already uses. Letting `create_table` create it too issues a second
    # CREATE TYPE and the migration dies on `already exists`.
    sa.Enum(*LEVELS, name="operator_level").create(op.get_bind(), checkfirst=True)
    level = postgresql.ENUM(*LEVELS, name="operator_level", create_type=False)

    op.create_table(
        "operator",
        # Same shape and same prefix rule as `household_access.auth_subject`:
        # `google:117482…`. A mechanism added later returns an auth subject and
        # nothing here moves.
        sa.Column("auth_subject", sa.String(length=255), primary_key=True),
        sa.Column("level", level, nullable=False),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("granted_by", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("operator")
    sa.Enum(name="operator_level").drop(op.get_bind(), checkfirst=True)
