"""Every schema we hand the model, checked against what the API accepts.

Written after a 400 that only production could produce: `day_of_week` was
`{"type": "integer", "minimum": 0, "maximum": 6}` — valid JSON Schema, refused
by structured outputs with "For 'integer' type, properties maximum, minimum are
not supported". Nothing caught it. The fake client never validates a schema, and
the suite has no key, so the first request that ever carried this schema was a
household asking for its week.

So the rule is enforced here, over every schema this application sends, walked
recursively: the keyword that breaks it is never in the part being edited.

This is a SUBSET of JSON Schema, not a lint. `enum` says what a bounded integer
was trying to say — and says it better, since seven listed values cannot admit
3.5 the way a range in a typeless schema could.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.domain.plan_schema import plan_output_schema
from app.workflows.prompts import INTERPRETATION_SCHEMA

#: Rejected by the API on integers, and rejecting the whole request with it.
#: Kept as a set so the day another keyword is found it is one line.
UNSUPPORTED_ON_INTEGERS = {"minimum", "maximum"}

SCHEMAS = {
    "interpretation": INTERPRETATION_SCHEMA,
    "plan with a catalogue": plan_output_schema(with_catalogue=True),
    "plan without a catalogue": plan_output_schema(with_catalogue=False),
}


def _offences(node: Any, path: str = "") -> list[str]:
    if isinstance(node, dict):
        found = []
        if node.get("type") == "integer":
            found += [
                f"{path or '<root>'}: {keyword}"
                for keyword in sorted(UNSUPPORTED_ON_INTEGERS & node.keys())
            ]
        for key, value in node.items():
            found += _offences(value, f"{path}.{key}" if path else key)
        return found
    if isinstance(node, list):
        return [
            offence
            for index, item in enumerate(node)
            for offence in _offences(item, f"{path}[{index}]")
        ]
    return []


@pytest.mark.parametrize("name", sorted(SCHEMAS))
def test_no_schema_bounds_an_integer(name: str) -> None:
    offences = _offences(SCHEMAS[name])

    assert offences == [], (
        f"{name}: the API refuses these and answers 400, so every generation "
        f"fails. Use `enum` instead — {offences}"
    )


def test_the_walk_would_actually_find_one() -> None:
    # Guards the guard. Three of these assertions are worthless if `_offences`
    # silently returns nothing, and a recursive walk over nested dicts and lists
    # is exactly the kind of thing that quietly does.
    planted = {
        "type": "object",
        "properties": {
            "rows": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"day": {"type": "integer", "minimum": 0}},
                },
            }
        },
    }

    assert _offences(planted) == ["properties.rows.items.properties.day: minimum"]


def test_the_day_of_week_still_says_which_seven() -> None:
    """Dropping the bound must not mean dropping the constraint.

    The fix is `enum`, not deletion: an unbounded integer would let the model
    answer 9 for a day of the week, and the schema is the only place that
    refusal costs nothing.
    """
    day = plan_output_schema(with_catalogue=True)["properties"]["slots"]["items"][
        "properties"
    ]["day_of_week"]

    assert day["enum"] == [0, 1, 2, 3, 4, 5, 6]
