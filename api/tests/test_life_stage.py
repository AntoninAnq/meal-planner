"""Deterministic core — life-stage derivation."""

from datetime import date

import pytest

from app.domain.enums import LifeStage
from app.domain.life_stage import (
    age_in_months,
    pending_transition,
    proposed_life_stage,
)

TODAY = date(2026, 8, 4)


@pytest.mark.parametrize(
    ("birth", "expected"),
    [
        (date(2026, 8, 4), 0),
        (date(2026, 7, 4), 1),
        (date(2025, 8, 4), 12),
        (date(2025, 8, 5), 11),  # birthday not reached this month
        (date(2027, 1, 1), 0),  # future date never goes negative
    ],
)
def test_age_in_months(birth: date, expected: int) -> None:
    assert age_in_months(birth, TODAY) == expected


@pytest.mark.parametrize(
    ("birth", "expected"),
    [
        (date(2026, 6, 1), LifeStage.BABY),  # 2 months
        (date(2025, 3, 4), LifeStage.BABY),  # 17 months, still below 18
        (date(2025, 2, 4), LifeStage.YOUNG_CHILD),  # 18 months exactly -> crossed
        (date(2016, 9, 4), LifeStage.YOUNG_CHILD),  # 10 years 11 months
        (date(2015, 8, 4), LifeStage.TEEN_ADULT),  # 11 years exactly -> crossed
        (date(1985, 1, 1), LifeStage.TEEN_ADULT),
    ],
)
def test_proposed_life_stage_boundaries(birth: date, expected: LifeStage) -> None:
    assert proposed_life_stage(birth, TODAY) == expected


def test_thresholds_are_configurable() -> None:
    """Invariant I8: the boundaries are data, not constants baked into the code."""
    custom = {LifeStage.BABY: 36, LifeStage.YOUNG_CHILD: 132, LifeStage.TEEN_ADULT: None}
    two_years_old = date(2024, 8, 4)

    assert proposed_life_stage(two_years_old, TODAY) == LifeStage.YOUNG_CHILD
    assert proposed_life_stage(two_years_old, TODAY, custom) == LifeStage.BABY


def test_no_transition_when_stage_already_matches() -> None:
    assert (
        pending_transition(
            current=LifeStage.BABY,
            birth_date=date(2026, 1, 4),
            on=TODAY,
        )
        is None
    )


def test_transition_is_proposed_not_applied() -> None:
    """Crossing BABY -> YOUNG_CHILD widens what is allowed, so it is never silent."""
    transition = pending_transition(
        current=LifeStage.BABY,
        birth_date=date(2024, 1, 4),  # well past 18 months
        on=TODAY,
    )
    assert transition is not None
    assert transition.current == LifeStage.BABY
    assert transition.proposed == LifeStage.YOUNG_CHILD


def test_transition_is_proposed_in_both_directions() -> None:
    """A parent may have moved a member backwards; the rule stays uniform."""
    transition = pending_transition(
        current=LifeStage.TEEN_ADULT,
        birth_date=date(2020, 1, 4),  # 6 years old
        on=TODAY,
    )
    assert transition is not None
    assert transition.proposed == LifeStage.YOUNG_CHILD


def test_member_without_birth_date_never_generates_a_proposal() -> None:
    assert pending_transition(current=LifeStage.BABY, birth_date=None, on=TODAY) is None
