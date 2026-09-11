"""The invitation contract, at its two brittle points.

The CRUD itself is thin — one row per slot, replace on re-POST — and follows
the same shape as `constraints`. What is worth pinning down is the validation
boundary (an invitation with nobody coming is not a state) and the slot-key
parser behind `DELETE /meal-plans/{id}/slots/{slot}`, where a malformed key
must be a named 422 rather than a 500.

No database: like the quota and revocation suites, this runs on a CI box with
no Postgres, and `invitation` carries JSONB columns SQLite cannot render.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.days import parse_slot
from app.domain.enums import LifeStage, MealType
from app.schemas import InvitationCreate


def _payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "week_start": "2026-09-07",
        "day_of_week": 5,
        "meal_type": "dinner",
        "guests": [{"life_stage": "teen_adult", "count": 6}],
        "dislikes": ["coriandre"],
    }
    base.update(overrides)
    return base


def test_a_full_invitation_parses() -> None:
    invitation = InvitationCreate.model_validate(_payload())

    assert invitation.day_of_week == 5
    assert invitation.meal_type is MealType.DINNER
    assert invitation.guests[0].life_stage is LifeStage.TEEN_ADULT
    assert invitation.guests[0].count == 6
    assert invitation.dislikes == ["coriandre"]


def test_an_invitation_with_no_guests_is_refused() -> None:
    """Nobody coming is not an invitation worth storing."""
    with pytest.raises(ValidationError):
        InvitationCreate.model_validate(_payload(guests=[]))


def test_a_guest_count_outside_one_to_twenty_is_refused() -> None:
    with pytest.raises(ValidationError):
        InvitationCreate.model_validate(_payload(guests=[{"life_stage": "baby", "count": 0}]))
    with pytest.raises(ValidationError):
        InvitationCreate.model_validate(_payload(guests=[{"life_stage": "baby", "count": 21}]))


def test_a_day_outside_the_week_is_refused() -> None:
    with pytest.raises(ValidationError):
        InvitationCreate.model_validate(_payload(day_of_week=7))


def test_dislikes_are_optional() -> None:
    payload = _payload()
    del payload["dislikes"]
    assert InvitationCreate.model_validate(payload).dislikes == []


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("5-dinner", (5, MealType.DINNER)),
        ("0-lunch", (0, MealType.LUNCH)),
        ("6-dinner", (6, MealType.DINNER)),
    ],
)
def test_a_well_formed_slot_key_parses(key: str, expected: tuple[int, MealType]) -> None:
    assert parse_slot(key) == expected


@pytest.mark.parametrize("key", ["7-dinner", "-1-dinner", "3-brunch", "dinner", "3", "3-"])
def test_a_malformed_slot_key_is_a_value_error(key: str) -> None:
    """The caller turns this into a 422 that names the problem, not a 500."""
    with pytest.raises(ValueError):
        parse_slot(key)
