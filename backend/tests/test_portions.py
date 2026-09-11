"""Deterministic core — portion scaling."""

from decimal import Decimal

import pytest

from app.domain.enums import LifeStage
from app.domain.portions import counts_people, scale_factor, scale_quantity, total_portions


def test_total_portions_mixed_household() -> None:
    # 2 adults + 1 young child + 1 baby = 1 + 1 + 0.5 + 0.25
    stages = [
        LifeStage.TEEN_ADULT,
        LifeStage.TEEN_ADULT,
        LifeStage.YOUNG_CHILD,
        LifeStage.BABY,
    ]
    assert total_portions(stages) == Decimal("2.75")


def test_total_portions_empty_cluster() -> None:
    assert total_portions([]) == Decimal(0)


def test_scale_quantity_down() -> None:
    """A recipe 'for 4' recooked for 2 adults + 1 young child."""
    result = scale_quantity(
        quantity=Decimal("800"),
        recipe_servings=4,
        eater_stages=[LifeStage.TEEN_ADULT, LifeStage.TEEN_ADULT, LifeStage.YOUNG_CHILD],
    )
    assert result == Decimal("500")


def test_scale_quantity_rejects_zero_servings() -> None:
    with pytest.raises(ValueError):
        scale_quantity(
            quantity=Decimal("100"),
            recipe_servings=0,
            eater_stages=[LifeStage.TEEN_ADULT],
        )


def test_coefficients_are_configurable() -> None:
    """Invariant I8 again: the coefficients are seeded data, not constants."""
    custom = {
        LifeStage.BABY: Decimal("0.1"),
        LifeStage.YOUNG_CHILD: Decimal("0.7"),
        LifeStage.TEEN_ADULT: Decimal("1.0"),
    }
    assert total_portions([LifeStage.YOUNG_CHILD], custom) == Decimal("0.7")


@pytest.mark.parametrize(
    "raw", ["4 personnes", "Pour 6", "6 parts", "4 pers.", "8 convives", "4 bols", "2 Portions"]
)
def test_a_yield_that_counts_people(raw: str) -> None:
    assert counts_people(raw)


@pytest.mark.parametrize("raw", ["20 tartelettes", "1 gâteau", "4", "30", "", None])
def test_a_yield_that_does_not(raw: str | None) -> None:
    """Pieces are not people, and a bare number is not assumed to be."""
    assert not counts_people(raw)


def test_the_factor_is_the_table_over_the_yield() -> None:
    """A recipe for 4, eaten by two adults and a young child: 2.5 portions."""
    stages = [LifeStage.TEEN_ADULT, LifeStage.TEEN_ADULT, LifeStage.YOUNG_CHILD]
    assert scale_factor(4, "4 personnes", stages) == Decimal("0.625")


def test_no_factor_when_it_cannot_be_said() -> None:
    adults = [LifeStage.TEEN_ADULT, LifeStage.TEEN_ADULT]
    assert scale_factor(20, "20 tartelettes", adults) is None
    assert scale_factor(None, None, adults) is None
    assert scale_factor(4, "4 personnes", []) is None
