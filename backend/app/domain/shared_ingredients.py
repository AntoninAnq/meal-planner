"""Which meals of a week are built on the same things.

This is the one signal that differentiates the product — `UX-V0.md` §12, "lundi
et jeudi partagent une base" — and until now it was visible nowhere: the plan
carried `derived_from_dish_id`, documented as never filled because "overlap is
not computable without ingredients". Ingredients resolve today (22 418 of
29 115 lines), so it is computable, and this module computes it.

**What it claims, and what it deliberately does not.** Two dishes are linked
here when they share enough NON-PANTRY ingredients. That is a fact about a
shopping list, not about a saucepan. A real culinary base — one pot of colombo
split across two evenings — lives in the preparation steps, and `Recipe` is
"structured metadata and a link, never the prose" (I9): the catalogue does not
hold them and never will. Measured on a real week, the two colombos share
aubergine, courgette, citron vert, laurier — and no colombo at all, because
that line never resolved. Calling that "the same base" would be a claim the
data cannot support, so the interface says "the same ingredients", which is
exactly what was measured.

Pantry is removed first, and that is the whole difficulty. Salt is in 49 % of
the catalogue, sugar 31 %, egg 27 %, olive oil 21 %, onion 20 %: with a plain
count, every pair of savoury dishes clears any threshold and a signal that
fires everywhere carries nothing. The same trap `services.catalogue` documents
for the prompt hint, one scope up — here the share is measured against the
whole catalogue rather than a candidate pool, because at read time there is no
pool, and because "is this a cupboard staple" is a property of cooking, not of
one household's shortlist.
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping, Sequence

#: An ingredient in more than this share of the catalogue is a cupboard, not a
#: base. Measured: 10 % cuts below pepper (12.2 %) and above tomato (7.6 %),
#: which puts salt, sugar, egg, butter, flour, olive oil, onion, water, garlic,
#: milk, lemon and pepper on the pantry side and leaves everything a household
#: would call an ingredient on the other.
PANTRY_SHARE = 0.10

#: How many distinctive ingredients two dishes must share before it is worth
#: saying so. Measured on a real week: the pair the week was actually planned
#: around scored 5, the next pairs scored 2, and the tail scored 1 — three
#: separates them with room on both sides.
SHARED_MINIMUM = 3

def pantry[Ingredient: Hashable](
    recipes_per_ingredient: Mapping[Ingredient, int], catalogue_size: int
) -> set[Ingredient]:
    """The ingredients too common to mean anything."""
    if catalogue_size <= 0:
        return set()
    ceiling = catalogue_size * PANTRY_SHARE
    return {
        ingredient for ingredient, count in recipes_per_ingredient.items() if count > ceiling
    }


def shared_ingredient_links[Dish: Hashable, Ingredient: Hashable](
    order: Sequence[Dish],
    ingredients: Mapping[Dish, frozenset[Ingredient]],
) -> dict[Dish, Dish]:
    """Map each dish to the EARLIER dish it shares its ingredients with.

    Directional by chronology, because the marker reads "same ingredients as
    Wednesday" and Wednesday is the one already cooked.

    The NEAREST earlier match, not the best and not the first. Nearest is the
    one whose shopping is still in the fridge; ranking candidates instead would
    put a score on screen that nobody asked for, and reaching back to the first
    match of the week would point Sunday at Monday over a Friday that shares
    just as much.

    `ingredients` is expected to be pantry-free already — see `pantry`.
    """
    links: dict[Dish, Dish] = {}
    for index, dish in enumerate(order):
        mine = ingredients.get(dish) or frozenset()
        if not mine:
            continue
        for earlier in reversed(order[:index]):
            theirs = ingredients.get(earlier) or frozenset()
            if len(mine & theirs) >= SHARED_MINIMUM:
                links[dish] = earlier
                break
    return links
