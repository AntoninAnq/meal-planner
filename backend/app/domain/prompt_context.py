"""Building the constraint DTO handed to the LLM (invariant I5).

> The prompt builder NEVER receives the `member` entity. It receives stages,
> allergen codes, taste tags and rotation signals. Never a first name, a birth
> date or a household id.

Members are referenced by a per-request opaque alias (`m1`, `m2`, …) rather than
by their database id. The caller keeps the mapping and resolves the model's
answer locally, so nothing identifying can leave — not even a pseudonymous key
that could be correlated across requests.

This module is pure: no database, no I/O. It is the seam that makes I5 testable.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.domain.enums import AllergenCode, ConstraintSeverity, LifeStage


@dataclass(frozen=True)
class MemberInput:
    """What the caller knows. Never crosses into the prompt as-is."""

    member_id: uuid.UUID
    life_stage: LifeStage
    severe_allergens: frozenset[AllergenCode] = frozenset()
    intolerances: frozenset[AllergenCode] = frozenset()
    aversion_tags: frozenset[str] = frozenset()


@dataclass(frozen=True)
class MemberContext:
    """What the prompt is allowed to see."""

    alias: str
    life_stage: LifeStage
    intolerances: tuple[AllergenCode, ...]
    aversion_tags: tuple[str, ...]
    #: How many people this alias stands for. Always 1 for a household member;
    #: a group of guests is ONE alias covering several seats, because nothing
    #: distinguishes them and asking the model to enumerate six identical
    #: eaters made it drop some (see `_guest_aliases`). No name, no identity —
    #: a count, which is all `slot_guests` ever stored either.
    headcount: int = 1


@dataclass(frozen=True)
class PromptContext:
    members: tuple[MemberContext, ...]
    #: Severe allergies are excluded household-wide, so they are stated
    #: once for the whole prompt rather than per member.
    household_excluded_allergens: tuple[AllergenCode, ...]

    def aliases(self) -> tuple[str, ...]:
        return tuple(member.alias for member in self.members)


def build_prompt_context(
    members: list[MemberInput],
) -> tuple[PromptContext, dict[str, uuid.UUID]]:
    """Return the DTO and the alias -> member_id mapping the caller keeps.

    It used to carry a `rotation_signals` field, drawn in V0 and never fed by
    anyone. When the rotation signal was actually built it went through
    `PlanRequest` instead — leaving two seams for one idea, one of them dead.
    Removed rather than wired up: the live one reads `recipe_food_category`,
    which did not exist when this was drawn.
    """
    contexts: list[MemberContext] = []
    mapping: dict[str, uuid.UUID] = {}
    household_severe: set[AllergenCode] = set()

    for index, member in enumerate(members, start=1):
        alias = f"m{index}"
        mapping[alias] = member.member_id
        household_severe |= set(member.severe_allergens)
        contexts.append(
            MemberContext(
                alias=alias,
                life_stage=member.life_stage,
                intolerances=tuple(sorted(member.intolerances)),
                aversion_tags=tuple(sorted(member.aversion_tags)),
            )
        )

    context = PromptContext(
        members=tuple(contexts),
        household_excluded_allergens=tuple(sorted(household_severe)),
    )
    return context, mapping


def severity_scope(severity: ConstraintSeverity) -> str:
    """Documents, in one place, what each severity means for the filter scope."""
    return {
        ConstraintSeverity.SEVERE_ALLERGY: "household",
        ConstraintSeverity.INTOLERANCE: "member",
        ConstraintSeverity.AVERSION: "signal",
    }[severity]
