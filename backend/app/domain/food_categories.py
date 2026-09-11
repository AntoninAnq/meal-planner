"""The order a shopping list is read in, which is not the order it is stored in.

`FoodCategory` is a nutrition axis — it feeds the rotation signal of §6.2, "23
days since legumes" — and its codes were never meant to describe a shop. A list
sorted alphabetically sends someone from `Alcools` to `Bouillons` to
`Céréales`, which is three ends of the same building.

So the walk is written down here, once, rather than in the component that
renders it: the same order has to hold in the copied text, and two lists that
disagree about where the cheese is would be worse than one that is wrong.

Produce, then the counters, then the chilled aisle, then the shelves, then what
is bought last. `other` is always last: it is the absence of a category, not a
place.

An ingredient may carry SEVERAL categories — `huile d'olive` is `fat_oil` and
nothing else, but `crème` is `dairy` and `fat_oil`. It appears once, in the
first of its categories along this walk, so that a list never asks anyone to
buy the same thing twice.
"""

from __future__ import annotations

#: Every code in `db/ingredients.yaml`, in the order a shop is walked.
STORE_ORDER: tuple[str, ...] = (
    "green_vegetable",
    "root_vegetable",
    "vegetable",
    "fruit",
    "herb_spice",
    "red_meat",
    "white_meat",
    "charcuterie",
    "fish",
    "seafood",
    "egg",
    "dairy",
    "cheese",
    "fat_oil",
    "cereal",
    "legumes_secs",
    "nuts_seeds",
    "condiment",
    "broth",
    "sweetener",
    "leavening",
    "alcohol",
    "other",
)

_RANK = {code: rank for rank, code in enumerate(STORE_ORDER)}


def rank_of(code: str | None) -> int:
    """Where this category falls on the walk.

    No category, and a category this module has never heard of, are the same
    thing to a reader: neither names a place in a shop. Both sort with `other`,
    last — rather than raising, because a category added to the referential and
    not here is a heading in an odd place, not a list that fails to render.
    """
    return _RANK.get(code or "other", _RANK["other"])
