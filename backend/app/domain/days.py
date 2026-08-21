"""Naming a day, and reading one back.

Shared vocabulary rather than prompt decoration: the prompt writes `day 1 =
mardi` so the household recognises its week, and `skip_slot` reads `mardi` back
to know which slot not to plan. One table, so the two can never disagree.

Everything here is pure — no database, no clock, no model.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

from app.domain.enums import MealType

#: Days as the household names them, in its own language.
DAY_NAMES: dict[str, list[str]] = {
    "fr": ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"],
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
}

LANGUAGE_NAMES = {"fr": "French", "en": "English"}

#: How a household says which meal. `midi` and `soir` are what people write;
#: `déjeuner` and `dîner` are what a form would call them, and both appear.
_MEAL_WORDS: dict[str, dict[MealType, tuple[str, ...]]] = {
    "fr": {
        MealType.LUNCH: ("midi", "dejeuner", "déjeuner"),
        MealType.DINNER: ("soir", "diner", "dîner", "souper"),
    },
    "en": {
        MealType.LUNCH: ("lunch", "midday", "noon"),
        MealType.DINNER: ("dinner", "evening", "supper", "tonight"),
    },
}


def _fold(text: str) -> str:
    stripped = unicodedata.normalize("NFD", text.lower())
    return "".join(char for char in stripped if unicodedata.category(char) != "Mn")


def day_name(day_of_week: int, language: str) -> str:
    names = DAY_NAMES.get(language, DAY_NAMES["en"])
    return names[day_of_week]


#: How a range is written. `du mardi au vendredi` is the exact phrasing of the
#: founder's own reference week, and reading only its endpoints silently
#: dropped Wednesday and Thursday — half the constraint.
_RANGE_WORDS = {
    "fr": r"(?:au|a|jusqu'au|jusqu'a|\-)",
    "en": r"(?:to|through|until|till|\-)",
}


def parse_days(text: str, language: str) -> frozenset[int]:
    """Every day the text names, as indices — ranges included.

    Whole words matter more than it looks: `samedi` contains `same`, and in
    English `Sunday` and `Saturday` share a prefix. A substring search here
    cancels the wrong dinner, and a cancelled dinner is not a small mistake —
    it is a meal the household expected and does not get.

    A range wraps around the week end: `du vendredi au lundi` is four days, not
    an empty set. Weeks are circular and households say this.
    """
    folded = _fold(text)
    names = [_fold(name) for name in DAY_NAMES.get(language, DAY_NAMES["en"])]
    found: set[int] = set()

    alternatives = "|".join(re.escape(name) for name in names)
    connector = _RANGE_WORDS.get(language, _RANGE_WORDS["en"])
    for start, end in re.findall(
        rf"\b({alternatives})\b\s*{connector}\s*\b({alternatives})\b", folded
    ):
        first, last = names.index(start), names.index(end)
        span = (last - first) % 7
        found |= {(first + step) % 7 for step in range(span + 1)}

    found |= {
        index for index, name in enumerate(names) if re.search(rf"\b{re.escape(name)}\b", folded)
    }
    return frozenset(found)


def parse_meals(text: str, language: str) -> frozenset[MealType]:
    """Which meal the text names, if it names one. Empty means "the whole day"."""
    folded = _fold(text)
    words = _MEAL_WORDS.get(language, _MEAL_WORDS["en"])
    return frozenset(
        meal
        for meal, spellings in words.items()
        if any(re.search(rf"\b{re.escape(_fold(word))}\b", folded) for word in spellings)
    )


def slots_to_skip(
    phrases: Sequence[str], language: str
) -> frozenset[tuple[int, MealType | None]]:
    """Read `skip_slot` constraints into the slots they cancel.

    `None` as the meal means the whole day. A phrase naming no day cancels
    nothing: "on ne sera pas là" is true of some day nobody stated, and
    guessing which one is worse than planning a meal that gets skipped.
    """
    skipped: set[tuple[int, MealType | None]] = set()
    for phrase in phrases:
        days = parse_days(phrase, language)
        if not days:
            continue
        meals = parse_meals(phrase, language)
        for day in days:
            if meals:
                skipped |= {(day, meal) for meal in meals}
            else:
                skipped.add((day, None))
    return frozenset(skipped)
