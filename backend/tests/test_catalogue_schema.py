"""What the catalogue schema promises, checked without a database.

These are invariant tests, not mapping tests: each one fails only if someone
removes a guarantee the safety layer rests on.
"""

from __future__ import annotations

from app.db.models import Recipe, RecipeIngredient
from app.domain.enums import ProposalStatus, RecipeSourceType


def test_no_source_type_means_generated_by_a_model() -> None:
    """I7, expressed where it can actually be broken.

    Adding an `llm_generated` member here is all it would take to undo the
    invariant, and it would look reasonable in a diff. Model suggestions live in
    the plan and the history with `DishSource.LLM_SUGGESTION`; they never become
    catalogue entries.
    """
    assert {member.value for member in RecipeSourceType} == {"user", "scraped", "licensed_api"}


def test_a_proposal_starts_pending_and_both_decisions_are_recorded() -> None:
    """I4: only PENDING may be written by the machine.

    REJECTED has to exist and to be durable. Without it, the next resolution
    pass re-proposes a match a human already refused, and the queue asks the
    same question forever.
    """
    assert {member.value for member in ProposalStatus} == {"pending", "accepted", "rejected"}


def test_a_recipe_is_unverified_until_proven_otherwise() -> None:
    """I3: `allergens_verified` is derived, and its default cannot be optimistic.

    A default of true would make every freshly ingested recipe visible to a
    household with a severe allergy before a single ingredient resolved.
    """
    assert Recipe.__table__.columns["allergens_verified"].default.arg is False
    assert Recipe.__table__.columns["allergens_verified"].nullable is False


def test_the_source_url_identifies_a_scraped_recipe() -> None:
    """What makes a second campaign update instead of duplicate."""
    assert Recipe.__table__.columns["source_url"].unique is True


def test_the_raw_ingredient_line_is_never_optional() -> None:
    """It is the only faithful record of what the source wrote.

    Resolution can fail, be replayed, or be reverted; `raw_text` is what all of
    that is arbitrated against, so it cannot be dropped once parsed.
    """
    assert RecipeIngredient.__table__.columns["raw_text"].nullable is False


def test_a_section_header_can_never_resolve_to_an_ingredient() -> None:
    """`'Pour la pâte sucrée :'` arrives marked up as an ingredient."""
    names = {constraint.name for constraint in RecipeIngredient.__table__.constraints}
    assert "ck_recipe_ingredient_section_unresolved" in names
