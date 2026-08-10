"""UX V0 contract — serving variants, household-scoped aversions

What the UX design phase added to the schema:

* dietary_constraint gains `household_id` and an OPTIONAL `member_id`: an
  aversion may belong to the whole household ("we don't eat that here") or to
  one person. One concept, one table, one filtering path. Allergies still
  require a member — their household scope comes from their SEVERITY, not from
  their storage.
* dietary_constraint gains `label`: in V0 there is no ingredient referential, so
  an aversion is free text ("les épinards").
* planned_dish_member gains `serving_variant`: same
  preparation, different plate. Carried by the ASSIGNMENT, because two people
  can have different variants on the same dish.
* planned_dish gains `derived_from_dish_id`: level 3, drawn now and left NULL
  until the catalogue exists.
* meal_history gains `confirmed_at`: history is implicit in V0, but rating
  a dish will confirm it implicitly later, with no migration needed.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- dietary_constraint --------------------------------------------------

    op.add_column("dietary_constraint", sa.Column("household_id", sa.Uuid(), nullable=True))
    op.add_column("dietary_constraint", sa.Column("label", sa.String(120), nullable=True))

    # Backfill through the member that currently owns each row.
    op.execute(
        """
        UPDATE dietary_constraint AS dc
           SET household_id = m.household_id
          FROM member AS m
         WHERE m.id = dc.member_id
        """
    )

    op.alter_column("dietary_constraint", "household_id", nullable=False)
    op.create_foreign_key(
        "fk_dietary_constraint_household",
        "dietary_constraint",
        "household",
        ["household_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_dietary_constraint_household_id", "dietary_constraint", ["household_id"])

    op.alter_column("dietary_constraint", "member_id", nullable=True)

    op.drop_constraint("ck_dietary_constraint_target", "dietary_constraint", type_="check")
    op.create_check_constraint(
        "ck_dietary_constraint_target",
        "dietary_constraint",
        "(allergen_code IS NOT NULL) OR (ingredient_id IS NOT NULL) OR (label IS NOT NULL)",
    )
    # Only an aversion may float free of a member. An allergy without someone it
    # belongs to is meaningless.
    op.create_check_constraint(
        "ck_dietary_constraint_member_required",
        "dietary_constraint",
        "(member_id IS NOT NULL) OR (severity = 'aversion')",
    )

    # --- planned_dish / planned_dish_member ----------------------------------

    op.add_column("planned_dish", sa.Column("derived_from_dish_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_planned_dish_derived_from",
        "planned_dish",
        "planned_dish",
        ["derived_from_dish_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "planned_dish_member", sa.Column("serving_variant", sa.String(200), nullable=True)
    )

    # --- meal_history --------------------------------------------------------

    op.add_column(
        "meal_history", sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("meal_history", "confirmed_at")

    op.drop_column("planned_dish_member", "serving_variant")
    op.drop_constraint("fk_planned_dish_derived_from", "planned_dish", type_="foreignkey")
    op.drop_column("planned_dish", "derived_from_dish_id")

    op.drop_constraint("ck_dietary_constraint_member_required", "dietary_constraint", type_="check")
    op.drop_constraint("ck_dietary_constraint_target", "dietary_constraint", type_="check")
    op.create_check_constraint(
        "ck_dietary_constraint_target",
        "dietary_constraint",
        "(allergen_code IS NOT NULL) OR (ingredient_id IS NOT NULL)",
    )

    op.execute("DELETE FROM dietary_constraint WHERE member_id IS NULL")
    op.alter_column("dietary_constraint", "member_id", nullable=False)

    op.drop_index("ix_dietary_constraint_household_id", table_name="dietary_constraint")
    op.drop_constraint("fk_dietary_constraint_household", "dietary_constraint", type_="foreignkey")
    op.drop_column("dietary_constraint", "label")
    op.drop_column("dietary_constraint", "household_id")
