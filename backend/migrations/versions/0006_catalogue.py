"""The catalogue: recipes, ingredients, categories, and the proposal queue

Section 8.2 of the architecture, deliberately left out of the initial schema
(§7.3) because nothing read it before phase 1.

Three things here are load-bearing rather than structural:

* `unaccent` and `pg_trgm` are what I4 rests on — normalisation and trigram
  similarity. The GIN index makes the approximate search usable; the fact that
  it is fast never authorises applying it on its own.
* `recipe.source_url` is UNIQUE. It is the identity of a scraped recipe, and it
  is what makes a second campaign update instead of duplicate.
* The three `recipe_id` columns that plan, history and snack rows have carried
  since phase 0 finally get their foreign key — with RESTRICT, not SET NULL. A
  recipe someone actually ate cannot be made to vanish from the history by a
  catalogue cleanup, and blanking a planned dish's reference would leave a row
  claiming nothing was planned (`ck_planned_dish_identity`).

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Already created by 0001. Referencing them without `create_type=False` would
# make Alembic emit a second CREATE TYPE and fail.
LIFE_STAGE = postgresql.ENUM(name="life_stage", create_type=False)
ALLERGEN = postgresql.ENUM(name="allergen_code", create_type=False)

RECIPE_SOURCE = postgresql.ENUM(
    "user", "scraped", "licensed_api", name="recipe_source_type", create_type=False
)
PROPOSAL_STATUS = postgresql.ENUM(
    "pending", "accepted", "rejected", name="proposal_status", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    RECIPE_SOURCE.create(bind, checkfirst=True)
    PROPOSAL_STATUS.create(bind, checkfirst=True)

    op.create_table(
        "food_category",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("code", sa.String(60), nullable=False, unique=True),
        sa.Column("label", sa.String(120), nullable=False),
    )

    op.create_table(
        "ingredient",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("canonical_name", sa.String(160), nullable=False),
        # lower + unaccent + singular + collapsed whitespace. Unique: two rows
        # normalising the same way would make resolution non-deterministic.
        sa.Column("normalized_name", sa.String(160), nullable=False, unique=True),
    )
    op.create_index("ix_ingredient_normalized_name", "ingredient", ["normalized_name"])
    # Trigram index for the APPROXIMATE search of I4. It makes the proposal
    # cheap to compute; it never makes it applicable on its own.
    op.execute(
        "CREATE INDEX ix_ingredient_normalized_trgm "
        "ON ingredient USING gin (normalized_name gin_trgm_ops)"
    )

    op.create_table(
        "ingredient_allergen",
        sa.Column(
            "ingredient_id",
            sa.Uuid(),
            sa.ForeignKey("ingredient.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("allergen_code", ALLERGEN, primary_key=True),
    )

    op.create_table(
        "ingredient_food_category",
        sa.Column(
            "ingredient_id",
            sa.Uuid(),
            sa.ForeignKey("ingredient.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "food_category_id",
            sa.Uuid(),
            sa.ForeignKey("food_category.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    op.create_table(
        "recipe",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("source_type", RECIPE_SOURCE, nullable=False),
        sa.Column("source_code", sa.String(60)),
        sa.Column("source_url", sa.Text(), unique=True),
        sa.Column("license", sa.String(200)),
        sa.Column("instructions_url", sa.Text()),
        sa.Column("prep_minutes", sa.SmallInteger()),
        sa.Column("cook_minutes", sa.SmallInteger()),
        sa.Column("complexity", sa.SmallInteger()),
        sa.Column("step_count", sa.SmallInteger()),
        sa.Column("servings", sa.SmallInteger()),
        sa.Column("servings_raw", sa.String(120)),
        sa.Column(
            "allergens_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "complexity IS NULL OR complexity BETWEEN 1 AND 3", name="ck_recipe_complexity"
        ),
    )
    op.create_index("ix_recipe_source_code", "recipe", ["source_code"])
    # A household with a severe allergy only ever sees verified recipes (I3), so
    # this flag is in the hot path of the pre-filter.
    op.create_index("ix_recipe_allergens_verified", "recipe", ["allergens_verified"])

    op.create_table(
        "recipe_ingredient",
        sa.Column(
            "recipe_id",
            sa.Uuid(),
            sa.ForeignKey("recipe.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("position", sa.SmallInteger(), primary_key=True),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(10, 3)),
        sa.Column("unit", sa.String(40)),
        sa.Column("is_section", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "ingredient_id", sa.Uuid(), sa.ForeignKey("ingredient.id", ondelete="RESTRICT")
        ),
        # 'Pour la pâte sucrée :' arrives marked up as an ingredient. It keeps
        # its position so the ordering survives, and must never resolve.
        sa.CheckConstraint(
            "NOT (is_section AND ingredient_id IS NOT NULL)",
            name="ck_recipe_ingredient_section_unresolved",
        ),
    )
    op.create_index("ix_recipe_ingredient_ingredient_id", "recipe_ingredient", ["ingredient_id"])

    op.create_table(
        "recipe_allergen",
        sa.Column(
            "recipe_id", sa.Uuid(), sa.ForeignKey("recipe.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("allergen_code", ALLERGEN, primary_key=True),
    )

    op.create_table(
        "recipe_suitable_stage",
        sa.Column(
            "recipe_id", sa.Uuid(), sa.ForeignKey("recipe.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("life_stage", LIFE_STAGE, primary_key=True),
    )

    op.create_table(
        "recipe_food_category",
        sa.Column(
            "recipe_id", sa.Uuid(), sa.ForeignKey("recipe.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column(
            "food_category_id",
            sa.Uuid(),
            sa.ForeignKey("food_category.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    # Keyed by the normalised STRING, not by the ingredient line: one decision
    # resolves every line carrying that text, in every recipe and every future
    # campaign. Deciding the same `échalotte` forty times is how a review queue
    # stops being reviewed.
    op.create_table(
        "ingredient_match_proposal",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("normalized_text", sa.String(160), nullable=False, unique=True),
        sa.Column(
            "ingredient_id",
            sa.Uuid(),
            sa.ForeignKey("ingredient.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("similarity", sa.Numeric(4, 3), nullable=False),
        sa.Column(
            "status", PROPOSAL_STATUS, nullable=False, server_default=sa.text("'pending'")
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_ingredient_match_proposal_status", "ingredient_match_proposal", ["status"]
    )

    for table in ("planned_dish", "meal_history", "snack_suggestion"):
        op.create_foreign_key(
            f"fk_{table}_recipe_id", table, "recipe", ["recipe_id"], ["id"], ondelete="RESTRICT"
        )


def downgrade() -> None:
    for table in ("planned_dish", "meal_history", "snack_suggestion"):
        op.drop_constraint(f"fk_{table}_recipe_id", table, type_="foreignkey")

    op.drop_table("ingredient_match_proposal")
    op.drop_table("recipe_food_category")
    op.drop_table("recipe_suitable_stage")
    op.drop_table("recipe_allergen")
    op.drop_table("recipe_ingredient")
    op.drop_table("recipe")
    op.drop_table("ingredient_food_category")
    op.drop_table("ingredient_allergen")
    op.drop_table("ingredient")
    op.drop_table("food_category")

    bind = op.get_bind()
    PROPOSAL_STATUS.drop(bind, checkfirst=True)
    RECIPE_SOURCE.drop(bind, checkfirst=True)
    # The extensions are left in place: dropping them would break anything else
    # in the database that came to rely on them.
