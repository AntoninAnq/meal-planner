"""What the household says about the SHAPE of its week, applied deterministically.

Three constraints were handed to the model as sentences and all three were
ignored, on one real week, measured:

  « des plats rapides »           -> 9 slots out of 9 at the highest complexity,
                                     while 14 quick dishes sat in the same
                                     candidate list
  « absent mardi »                -> a dinner planned for Tuesday
  « un plat deux soirs de suite » -> four different dishes, each repeated

The first two are computable, so §6.3 says they must be computed. What is
checked here is that half — the pure half. The third stays with the model
because "which dish is worth cooking twice" is a judgement, and it is measured
by the eval harness rather than asserted.
"""

from __future__ import annotations

import uuid
from datetime import date

from app.domain.days import parse_days, parse_meals, slots_to_skip
from app.domain.enums import MealType
from app.domain.planning import SlotSpec
from app.services.catalogue import rank
from app.services.planning_service import Intent, _without_skipped

FULL_WEEK = [
    SlotSpec(day, meal, ("m1",))
    for day in range(7)
    for meal in (MealType.LUNCH, MealType.DINNER)
]


# ---------------------------------------------------------------------------
# Reading a day back
# ---------------------------------------------------------------------------


def test_a_day_is_read_as_a_whole_word() -> None:
    """`samedi` contains `same`, and `Sunday` and `Saturday` share a prefix.

    A substring match cancels the wrong dinner, and a wrongly cancelled dinner
    is a meal the household expected and does not get.
    """
    assert parse_days("on est absents mardi", "fr") == frozenset({1})
    assert parse_days("absent samedi", "fr") == frozenset({5})
    assert parse_days("Saturday away", "en") == frozenset({5})
    assert parse_days("Sunday away", "en") == frozenset({6})
    # `mardi` inside a longer word is not Tuesday.
    assert parse_days("mardigras", "fr") == frozenset()


def test_accents_and_case_do_not_hide_a_day() -> None:
    assert parse_days("ABSENT MARDI", "fr") == frozenset({1})
    assert parse_days("on part Vendredi", "fr") == frozenset({4})


def test_the_meal_is_read_when_it_is_named() -> None:
    assert parse_meals("vendredi soir", "fr") == frozenset({MealType.DINNER})
    assert parse_meals("samedi midi", "fr") == frozenset({MealType.LUNCH})
    assert parse_meals("Friday dinner", "en") == frozenset({MealType.DINNER})
    # No meal named means the whole day, which the caller reads as `None`.
    assert parse_meals("absent mardi", "fr") == frozenset()


# ---------------------------------------------------------------------------
# Cancelling a slot
# ---------------------------------------------------------------------------


def test_a_day_named_without_a_meal_cancels_the_whole_day() -> None:
    assert slots_to_skip(["absence mardi: mardi"], "fr") == frozenset({(1, None)})


def test_naming_the_meal_cancels_only_that_meal() -> None:
    assert slots_to_skip(["on part vendredi soir"], "fr") == frozenset(
        {(4, MealType.DINNER)}
    )


def test_a_phrase_naming_no_day_cancels_nothing() -> None:
    """"On ne sera pas là" is true of some day nobody stated.

    Guessing which one is worse than planning a meal that gets skipped: the
    first costs a meal, the second costs a suggestion.
    """
    assert slots_to_skip(["on ne sera pas là"], "fr") == frozenset()


def test_the_tuesday_slot_is_removed_from_the_grid() -> None:
    """The case that motivated all of this, end to end on the pure part."""
    kept = _without_skipped(
        FULL_WEEK, [Intent(kind="skip_slot", label="absence mardi", detail="mardi")], "fr"
    )

    assert len(kept) == len(FULL_WEEK) - 2
    assert all(slot.day_of_week != 1 for slot in kept)


def test_only_a_skip_constraint_removes_anything() -> None:
    """A `time_budget` naming Tuesday must not cancel Tuesday.

    "mardi je rentre tard" is the household asking for a QUICK dinner, not for
    no dinner — and the interpretation puts the day in `detail` for both kinds.
    """
    kept = _without_skipped(
        FULL_WEEK,
        [Intent(kind="time_budget", label="retour tardif mardi", detail="mardi")],
        "fr",
    )

    assert kept == FULL_WEEK


def test_a_reading_that_would_empty_the_week_is_refused_whole() -> None:
    """`parse_days` reads every day it finds, so a chatty note can name them all.

    An empty plan and a bare "no slot to fill" is a worse answer than ignoring
    a constraint nobody can satisfy.
    """
    every_day = Intent(
        kind="skip_slot",
        label="absent",
        detail="lundi mardi mercredi jeudi vendredi samedi dimanche",
    )

    assert _without_skipped(FULL_WEEK, [every_day], "fr") == FULL_WEEK


# ---------------------------------------------------------------------------
# Ranking quick dishes first
# ---------------------------------------------------------------------------


def _ids(n: int) -> list[uuid.UUID]:
    return [uuid.UUID(int=index) for index in range(n)]


def test_quick_dishes_come_first_when_the_household_has_no_time() -> None:
    everything = _ids(20)
    quick = set(everything[10:])

    ordered = rank(everything, last_planned={}, seed="s", quick=quick)

    assert set(ordered[:10]) == quick


def test_time_never_outranks_what_the_household_actually_asked_for() -> None:
    """A sub-ordering, not a sixth band.

    "Peu de temps" must not outrank "il reste du jambon", and above all it must
    not outrank being free of an allergen someone at the table excludes —
    those are the bands, and this only sorts inside them.
    """
    everything = _ids(20)
    ham = {everything[0]}  # wanted, but long
    quick = set(everything[10:])  # quick, but nobody asked for them

    ordered = rank(everything, last_planned={}, seed="s", wanted=ham, quick=quick)

    assert ordered[0] == everything[0]


def test_a_long_dish_is_ranked_down_and_never_removed() -> None:
    """The household said it had little time, not that every meal must be quick.

    A Sunday can hold a long dish, and the reserve behind `alternatives` is the
    same ranked list — dropping them would empty it.
    """
    everything = _ids(20)
    ordered = rank(everything, last_planned={}, seed="s", quick=set(everything[10:]))

    assert sorted(ordered, key=str) == sorted(everything, key=str)


def test_the_ranking_stays_reproducible_with_a_time_constraint() -> None:
    """The reserve is recomputed from the seed, never stored.

    Every ordering rule added here has to preserve that or `GET …/alternatives`
    stops offering what the model was actually shown.
    """
    everything = _ids(30)
    quick = set(everything[:12])
    planned = {everything[3]: date(2026, 8, 10)}

    first = rank(everything, last_planned=planned, seed="h:2026-08-17", quick=quick)
    second = rank(
        list(reversed(everything)), last_planned=planned, seed="h:2026-08-17", quick=quick
    )

    assert first == second
