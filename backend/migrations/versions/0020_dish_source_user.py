"""The dish source nothing vouched for

`DishSource` was missing `USER` while three places already relied on it:
`replace_dish` assigns it when someone types a title, the client type declares
it, and `DishCard` renders "écrit à la main — non vérifié" on it — the mark
`UX-V0.md` §15 keeps after the global allergen notice disappears.

The consequences were a 500 on every hand-written title (`AttributeError: type
object 'DishSource' has no attribute 'USER'`) and a safety mark that could never
appear. Nothing had a test, and mypy had been reporting the attribute error for
some time.

Adding a value to a Postgres enum cannot run inside a transaction block on older
servers, hence the autocommit. There is no downgrade: removing a value from an
enum means rebuilding the type and rewriting every column that uses it, for a
value no row can hold until this migration exists.

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-11
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE dish_source ADD VALUE IF NOT EXISTS 'user'")


def downgrade() -> None:
    """Deliberately empty — see the module docstring."""
