"""Initial schema — phase 0

Scope (docs/ARCHITECTURE.md §7.3): everything in §8 except the scraped
catalogue. Household, access, members, constraints, slots, configuration, plans,
history and snacks. The catalogue tables of §8.2 arrive in phase 1, and add the
foreign keys on the `recipe_id` columns created here.

Revision ID: 0001
Revises:
Create Date: 2026-08-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


LIFE_STAGES = ("baby", "young_child", "teen_adult")
MEAL_TYPES = ("lunch", "dinner")
SEVERITIES = ("severe_allergy", "intolerance", "aversion")
DISH_SOURCES = ("catalog", "llm_suggestion")
ALLERGENS = (
    "gluten",
    "crustaceans",
    "eggs",
    "fish",
    "peanuts",
    "soybeans",
    "milk",
    "nuts",
    "celery",
    "mustard",
    "sesame",
    "sulphites",
    "lupin",
    "molluscs",
)

life_stage = postgresql.ENUM(*LIFE_STAGES, name="life_stage", create_type=False)
meal_type = postgresql.ENUM(*MEAL_TYPES, name="meal_type", create_type=False)
severity = postgresql.ENUM(*SEVERITIES, name="constraint_severity", create_type=False)
dish_source = postgresql.ENUM(*DISH_SOURCES, name="dish_source", create_type=False)
allergen_code = postgresql.ENUM(*ALLERGENS, name="allergen_code", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in (life_stage, meal_type, severity, dish_source, allergen_code):
        enum_type.create(bind, checkfirst=True)

    # --- Household and access ------------------------------------------------

    op.create_table(
        "household",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    # auth_subject is prefixed by its mechanism: 'google:117482…'.
    # Holds no secret and no personal data, and survives every change of
    # authentication mechanism (§11.1).
    op.create_table(
        "household_access",
        sa.Column("auth_subject", sa.String(255), primary_key=True),
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("household.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_household_access_household_id", "household_access", ["household_id"])

    op.create_table(
        "household_settings",
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("household.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("snacks_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("max_dishes_soft_limit", sa.SmallInteger(), nullable=False, server_default="2"),
    )

    # --- Members and constraints --------------------------------------------

    op.create_table(
        "member",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("household.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("display_name", sa.String(80), nullable=False),
        sa.Column("birth_date", sa.Date(), nullable=True),
        # Effective stage, confirmed by a parent. birth_date only produces a
        # proposal (§4.3).
        sa.Column("life_stage", life_stage, nullable=False),
        sa.Column("life_stage_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_member_household_id", "member", ["household_id"])

    op.create_table(
        "dietary_constraint",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "member_id", sa.Uuid(), sa.ForeignKey("member.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("allergen_code", allergen_code, nullable=True),
        # FK added in phase 1, with the ingredient referential.
        sa.Column("ingredient_id", sa.Uuid(), nullable=True),
        sa.Column("severity", severity, nullable=False, server_default="severe_allergy"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "(allergen_code IS NOT NULL) OR (ingredient_id IS NOT NULL)",
            name="ck_dietary_constraint_target",
        ),
    )
    op.create_index("ix_dietary_constraint_member_id", "dietary_constraint", ["member_id"])

    # --- Household configuration --------------------------------------------

    op.create_table(
        "meal_slot_config",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("household.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("day_of_week", sa.SmallInteger(), nullable=False),  # 0 = Monday
        sa.Column("meal_type", meal_type, nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("household_id", "day_of_week", "meal_type", name="uq_meal_slot_config"),
        sa.CheckConstraint("day_of_week BETWEEN 0 AND 6", name="ck_meal_slot_day"),
    )
    op.create_index("ix_meal_slot_config_household_id", "meal_slot_config", ["household_id"])

    op.create_table(
        "portion_coefficient",
        sa.Column("life_stage", life_stage, primary_key=True),
        sa.Column("coefficient", sa.Numeric(4, 2), nullable=False),
    )

    op.create_table(
        "life_stage_threshold",
        sa.Column("life_stage", life_stage, primary_key=True),
        sa.Column("upper_bound_months", sa.Integer(), nullable=True),
    )

    # --- Plans and history ---------------------------------------------------

    op.create_table(
        "meal_plan",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("household.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column(
            "generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("generation_input", sa.Text(), nullable=True),
        sa.UniqueConstraint("household_id", "week_start", name="uq_meal_plan_week"),
    )
    op.create_index("ix_meal_plan_household_id", "meal_plan", ["household_id"])

    op.create_table(
        "planned_dish",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "meal_plan_id",
            sa.Uuid(),
            sa.ForeignKey("meal_plan.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("day_of_week", sa.SmallInteger(), nullable=False),
        sa.Column("meal_type", meal_type, nullable=False),
        # FK added in phase 1. NULL throughout V0.
        sa.Column("recipe_id", sa.Uuid(), nullable=True),
        sa.Column("free_text_label", sa.String(200), nullable=True),
        sa.Column("source", dish_source, nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.CheckConstraint("day_of_week BETWEEN 0 AND 6", name="ck_planned_dish_day"),
        sa.CheckConstraint(
            "(recipe_id IS NOT NULL) OR (free_text_label IS NOT NULL)",
            name="ck_planned_dish_identity",
        ),
    )
    op.create_index("ix_planned_dish_meal_plan_id", "planned_dish", ["meal_plan_id"])

    # The assignment of §4.1, and what makes per-member anti-repetition possible.
    op.create_table(
        "planned_dish_member",
        sa.Column(
            "planned_dish_id",
            sa.Uuid(),
            sa.ForeignKey("planned_dish.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "member_id",
            sa.Uuid(),
            sa.ForeignKey("member.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    op.create_table(
        "meal_history",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("household.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "member_id", sa.Uuid(), sa.ForeignKey("member.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("eaten_on", sa.Date(), nullable=False),
        sa.Column("meal_type", meal_type, nullable=False),
        # FK added in phase 1.
        sa.Column("recipe_id", sa.Uuid(), nullable=True),
        sa.Column("free_text_label", sa.String(200), nullable=True),
        sa.Column("source", dish_source, nullable=False),
        sa.Column("rating", sa.SmallInteger(), nullable=True),
    )
    op.create_index("ix_meal_history_household_id", "meal_history", ["household_id"])
    op.create_index("ix_meal_history_member_id", "meal_history", ["member_id"])
    op.create_index("ix_meal_history_eaten_on", "meal_history", ["eaten_on"])

    op.create_table(
        "snack_suggestion",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "household_id",
            sa.Uuid(),
            sa.ForeignKey("household.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("suggested_on", sa.Date(), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        # FK added in phase 1.
        sa.Column("recipe_id", sa.Uuid(), nullable=True),
        sa.Column("source", dish_source, nullable=False),
    )
    op.create_index("ix_snack_suggestion_household_id", "snack_suggestion", ["household_id"])
    op.create_index("ix_snack_suggestion_suggested_on", "snack_suggestion", ["suggested_on"])

    # --- Seeds ---------------------------------------------------------------
    #
    # Defaults, not constants: both tables exist precisely so these values are
    # configurable rather than hardcoded (invariant I8).

    op.bulk_insert(
        sa.table(
            "portion_coefficient",
            sa.column("life_stage", life_stage),
            sa.column("coefficient", sa.Numeric(4, 2)),
        ),
        [
            {"life_stage": "baby", "coefficient": 0.25},
            {"life_stage": "young_child", "coefficient": 0.5},
            {"life_stage": "teen_adult", "coefficient": 1.0},
        ],
    )

    # 18 months rather than 12: the regulatory prohibitions (honey, cow's milk)
    # lift at 12 months, but textures and choking risk do not (§4.3).
    op.bulk_insert(
        sa.table(
            "life_stage_threshold",
            sa.column("life_stage", life_stage),
            sa.column("upper_bound_months", sa.Integer),
        ),
        [
            {"life_stage": "baby", "upper_bound_months": 18},
            {"life_stage": "young_child", "upper_bound_months": 132},  # 11 years
            {"life_stage": "teen_adult", "upper_bound_months": None},
        ],
    )


def downgrade() -> None:
    for table in (
        "snack_suggestion",
        "meal_history",
        "planned_dish_member",
        "planned_dish",
        "meal_plan",
        "life_stage_threshold",
        "portion_coefficient",
        "meal_slot_config",
        "dietary_constraint",
        "member",
        "household_settings",
        "household_access",
        "household",
    ):
        op.drop_table(table)

    bind = op.get_bind()
    for enum_type in (allergen_code, dish_source, severity, meal_type, life_stage):
        enum_type.drop(bind, checkfirst=True)
