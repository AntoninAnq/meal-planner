"""The one signal that differentiates the product, and its two failure modes.

Pantry has to go first or every savoury pair matches; and the link has to point
backwards in the week or the marker says "same ingredients as Sunday" on a
Monday, which reads as nonsense to someone planning forwards.

No database: pure functions over the shapes the router assembles.
"""

from __future__ import annotations

from app.domain.shared_ingredients import (
    PANTRY_SHARE,
    SHARED_MINIMUM,
    pantry,
    shared_ingredient_links,
)


def test_pantry_is_what_is_in_almost_everything() -> None:
    # 100 recipes: salt in half of them is a cupboard, aubergine in five is not.
    common = pantry({"salt": 50, "onion": 20, "aubergine": 5}, 100)
    assert common == {"salt", "onion"}


def test_pantry_share_is_a_ceiling_not_a_floor() -> None:
    # Exactly at the share is kept: the constant names what is too common, and
    # a value sitting on the line has not passed it.
    at_the_line = int(100 * PANTRY_SHARE)
    assert pantry({"x": at_the_line}, 100) == set()
    assert pantry({"x": at_the_line + 1}, 100) == {"x"}


def test_an_empty_catalogue_declares_nothing_pantry() -> None:
    # Guards the division. A fresh install has no recipes, and answering
    # "everything is pantry" would silence the signal for good.
    assert pantry({"salt": 3}, 0) == set()


def test_a_dish_points_at_the_earlier_one_it_shares_with() -> None:
    order = ["wed", "thu"]
    links = shared_ingredient_links(
        order,
        {
            "wed": frozenset({"aubergine", "courgette", "lime", "bay"}),
            "thu": frozenset({"aubergine", "courgette", "lime", "rice"}),
        },
    )
    # Thursday carries the marker, Wednesday does not: it was cooked first.
    assert links == {"thu": "wed"}


def test_below_the_minimum_nothing_is_claimed() -> None:
    links = shared_ingredient_links(
        ["mon", "tue"],
        {
            "mon": frozenset({"aubergine", "tomato"}),
            "tue": frozenset({"aubergine", "tomato", "beef"}),
        },
    )
    # Two shared ingredients is two salads with tomato in them, not a base.
    assert len(frozenset({"aubergine", "tomato"})) < SHARED_MINIMUM
    assert links == {}


def test_a_dish_with_no_resolved_ingredients_claims_nothing() -> None:
    # A fifth of the catalogue's lines never resolved, and a hand-written dish
    # has none at all. Silence is the right answer, not a link to whatever the
    # empty set happens to intersect.
    links = shared_ingredient_links(
        ["mon", "tue"],
        {"mon": frozenset({"a", "b", "c"}), "tue": frozenset()},
    )
    assert links == {}


def test_the_link_is_the_first_match_walking_backwards() -> None:
    base = frozenset({"a", "b", "c"})
    links = shared_ingredient_links(
        ["mon", "tue", "wed"],
        {"mon": base, "tue": base, "wed": base},
    )
    # Tuesday points at Monday, Wednesday at Tuesday — never a chain rewritten
    # to a single origin, which would claim an intent nobody expressed.
    assert links == {"tue": "mon", "wed": "tue"}
