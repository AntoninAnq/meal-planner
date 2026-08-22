#!/usr/bin/env sh
# The catalogue and the referential, and NOTHING a household typed.
#
# The catalogue takes days of crawling to rebuild and belongs on every
# deployment; the household tables belong to one family. `dietary_constraint`
# alone is health data (GDPR art. 9), and there is no reason for a copy of it
# to travel to a hosting provider because someone wanted the recipes there.
#
# `--data-only`, because the target gets its schema from `alembic upgrade head`
# — which also creates `unaccent` and `pg_trgm` (migration 0006). A full dump
# would carry a schema frozen at the moment it was taken, and would then be one
# migration away from disagreeing with the code.
#
# `alembic_version` is deliberately absent for the same reason: the target's
# version is whatever its own migrations reached, never what a dump claims.
#
#   sh db/dump-catalogue.sh > catalogue.sql
#   psql "$DATABASE_URL" -f catalogue.sql      # after `alembic upgrade head`
#
# Run it from the repository root, with the local stack up.
set -eu

CONTAINER="${DB_CONTAINER:-meal-planner-db-1}"

# Referential first, then what points at it: loaded in this order, every
# foreign key resolves as it goes and no constraint has to be deferred.
#
# `portion_coefficient` and `life_stage_threshold` are ABSENT, and it took a
# restore onto an empty database to notice: migration 0001 seeds them itself.
# Dumping them makes the load die on `duplicate key value violates unique
# constraint "life_stage_threshold_pkey"` — halfway through, with the recipes
# already in and the ingredients not. They are configuration the migration
# owns; the target's values are its own.
TABLES="
food_category
ingredient
ingredient_alias
ingredient_allergen
ingredient_food_category
ingredient_match_proposal
recipe
recipe_allergen
recipe_food_category
recipe_ingredient
recipe_suitable_stage
"

ARGS=""
for table in $TABLES; do
	ARGS="$ARGS --table=public.$table"
done

# shellcheck disable=SC2086
docker exec "$CONTAINER" sh -c \
	"pg_dump -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" --data-only --no-owner --no-privileges $ARGS"
