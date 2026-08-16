"""Domain enumerations.

Values are stable identifiers written to the database. Display labels are the
frontend's job (the product ships in French first but is i18n-ready), so nothing
here is ever shown to a user as-is.
"""

from enum import StrEnum


class LifeStage(StrEnum):
    """What counts as a real meal for a member."""

    BABY = "baby"
    YOUNG_CHILD = "young_child"
    TEEN_ADULT = "teen_adult"


class MealType(StrEnum):
    LUNCH = "lunch"
    DINNER = "dinner"


class ConstraintSeverity(StrEnum):
    """Severity decides the SCOPE of the filter.

    SEVERE_ALLERGY -> household-wide exclusion (cross-contamination is real)
    INTOLERANCE    -> member-level exclusion (allows one more dish)
    AVERSION       -> soft signal only, never removes a dish by force
    """

    SEVERE_ALLERGY = "severe_allergy"
    INTOLERANCE = "intolerance"
    AVERSION = "aversion"


class DishSource(StrEnum):
    """Where a planned dish comes from.

    Invariant I7: LLM_SUGGESTION entries live in the plan and the history, and
    are NEVER promoted to catalogue recipes.
    """

    CATALOG = "catalog"
    LLM_SUGGESTION = "llm_suggestion"


class AllergenCode(StrEnum):
    """The 14 regulatory allergens (EU INCO 1169/2011).

    Invariant I2: the hard allergen filter reads these codes, never free text.
    """

    GLUTEN = "gluten"
    CRUSTACEANS = "crustaceans"
    EGGS = "eggs"
    FISH = "fish"
    PEANUTS = "peanuts"
    SOYBEANS = "soybeans"
    MILK = "milk"
    NUTS = "nuts"
    CELERY = "celery"
    MUSTARD = "mustard"
    SESAME = "sesame"
    SULPHITES = "sulphites"
    LUPIN = "lupin"
    MOLLUSCS = "molluscs"
