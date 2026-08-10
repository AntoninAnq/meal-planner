"""Invariant I5 — nothing identifying reaches the prompt.

Allergies are health data (GDPR art. 9) and we store children's birth dates. The
rule costs nothing today and is very painful to retrofit, so it is enforced by a
test from the first commit.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import date

from app.domain.enums import AllergenCode, LifeStage
from app.domain.prompt_context import MemberInput, build_prompt_context

FIRST_NAMES = ("Antonin", "Camille", "Léo")
BIRTH_DATES = (date(2024, 3, 12), date(2016, 9, 1))
HOUSEHOLD_ID = uuid.uuid4()

MEMBERS = [
    MemberInput(
        member_id=uuid.uuid4(),
        life_stage=LifeStage.BABY,
        severe_allergens=frozenset({AllergenCode.PEANUTS}),
    ),
    MemberInput(
        member_id=uuid.uuid4(),
        life_stage=LifeStage.TEEN_ADULT,
        intolerances=frozenset({AllergenCode.MILK}),
        aversion_tags=frozenset({"coriander"}),
    ),
]


def _serialised(context: object) -> str:
    return json.dumps(asdict(context), default=str)  # type: ignore[call-overload]


def test_no_first_name_reaches_the_prompt() -> None:
    context, _ = build_prompt_context(MEMBERS)
    payload = _serialised(context)

    for name in FIRST_NAMES:
        assert name not in payload


def test_no_birth_date_reaches_the_prompt() -> None:
    context, _ = build_prompt_context(MEMBERS)
    payload = _serialised(context)

    for birth_date in BIRTH_DATES:
        assert birth_date.isoformat() not in payload
    assert "birth" not in payload.lower()


def test_no_database_identifier_reaches_the_prompt() -> None:
    """Not even a pseudonymous key that could be correlated across requests."""
    context, mapping = build_prompt_context(MEMBERS)
    payload = _serialised(context)

    assert str(HOUSEHOLD_ID) not in payload
    for member in MEMBERS:
        assert str(member.member_id) not in payload

    # The caller keeps the mapping; the prompt only ever sees the aliases.
    assert set(mapping) == set(context.aliases())
    assert set(mapping.values()) == {member.member_id for member in MEMBERS}


def test_severe_allergies_are_hoisted_to_household_scope() -> None:
    """Severe allergy excludes the allergen for EVERYONE, so it is stated once."""
    context, _ = build_prompt_context(MEMBERS)

    assert context.household_excluded_allergens == (AllergenCode.PEANUTS,)
    # ...and never leaks back into a per-member field.
    for member in context.members:
        assert AllergenCode.PEANUTS not in member.intolerances


def test_intolerances_stay_member_scoped() -> None:
    context, _ = build_prompt_context(MEMBERS)
    adult = next(m for m in context.members if m.life_stage is LifeStage.TEEN_ADULT)

    assert adult.intolerances == (AllergenCode.MILK,)
    assert AllergenCode.MILK not in context.household_excluded_allergens


def test_rotation_signals_are_passed_as_context() -> None:
    """Rotation is a SIGNAL, never a filter."""
    context, _ = build_prompt_context(MEMBERS, rotation_signals={"legumes": 23, "fish": 4})

    assert context.rotation_signals == {"legumes": 23, "fish": 4}
