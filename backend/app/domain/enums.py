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


class RecipeSourceType(StrEnum):
    """Where a catalogue recipe comes from.

    Invariant I7: there is deliberately no `llm_generated` member, and adding one
    would be the whole invariant undone. Model suggestions live in the plan and
    the history with `DishSource.LLM_SUGGESTION`, and never cross over here.
    """

    USER = "user"
    SCRAPED = "scraped"
    LICENSED_API = "licensed_api"


class ProposalStatus(StrEnum):
    """A proposal is never applied by itself (I4).

    PENDING is the only state the machine may write. The other two record a
    human decision, and both are final: a rejected match must not come back at
    the next resolution pass, or the same question gets asked forever.
    """

    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


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


class DishType(StrEnum):
    """When a recipe can be eaten, derived from the rubric its source publishes.

    A quality axis, not a safety one — which is why it is allowed to be wrong
    and why no member of this enum ever gates the allergen filter. It exists
    because the verified catalogue is majority-sweet by construction: I3
    requires every ingredient line to resolve, and a cake's eight lines all do
    where a tajine's fifteen do not.

    `COMPONENT` is the member that is easy to forget and expensive to omit. A
    vinaigrette, a roux or a pastry base is a catalogue recipe that is not a
    meal at all; without it they fall into "not labelled dessert", and from
    there into the dinner candidates.

    There is deliberately no `UNKNOWN` member: absence of a rubric is a NULL
    column, not a value. A recipe nobody classified must read as unclassified
    everywhere, and a magic member would let it be selected by mistake.
    """

    MAIN = "main"
    STARTER = "starter"
    SIDE = "side"
    DESSERT = "dessert"
    SNACK = "snack"
    BREAKFAST = "breakfast"
    DRINK = "drink"
    COMPONENT = "component"
