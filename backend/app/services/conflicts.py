"""Which allergen in a dish belongs to whom in this household.

Both halves are in the database — `recipe_allergen` says what a recipe
contains, `dietary_constraint` says who cannot have it — so the join belongs
here rather than in a client that would have to fetch two lists and intersect
them. Naming only the allergen would send the reader off to check whose it is,
which is the one thing an allergen warning must not do.

Aversions are excluded on purpose. Red is what this product keeps for the
allergen and for the irreversible; spending it on "n'aime pas les épinards"
spends it everywhere, and then it says nothing anywhere.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DietaryConstraint, Member, RecipeAllergen
from app.domain.enums import ConstraintSeverity
from app.schemas import AllergenConflictOut


def conflicts_for(
    db: Session, household_id: uuid.UUID, recipe_ids: set[uuid.UUID]
) -> dict[uuid.UUID, list[AllergenConflictOut]]:
    """Per recipe, the allergens somebody here cannot eat, and who they are."""
    if not recipe_ids:
        return {}

    rows = db.execute(
        select(RecipeAllergen.recipe_id, RecipeAllergen.allergen_code, Member.display_name)
        .join(
            DietaryConstraint,
            DietaryConstraint.allergen_code == RecipeAllergen.allergen_code,
        )
        .outerjoin(Member, Member.id == DietaryConstraint.member_id)
        .where(
            RecipeAllergen.recipe_id.in_(recipe_ids),
            DietaryConstraint.household_id == household_id,
            DietaryConstraint.severity != ConstraintSeverity.AVERSION,
        )
    ).all()

    found: dict[uuid.UUID, list[AllergenConflictOut]] = {}
    for recipe_id, allergen_code, member_name in rows:
        conflict = AllergenConflictOut(allergen_code=allergen_code, member_name=member_name)
        against = found.setdefault(recipe_id, [])
        # Two people allergic to the same thing are two sentences; one
        # household-wide row and one member row for the same allergen are not.
        if conflict not in against:
            against.append(conflict)
    return found
