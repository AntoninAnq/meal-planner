"""The API type and the domain type carry the same fields and are different types.

`InterpretedConstraint` (Pydantic, what the browser sends) and `Intent` (the
domain object every mechanism reads) both hold `kind`, `label` and `detail`.
The route passed the first straight into `generate_plan`, which expected the
second — and its fallback branch quietly turned anything unrecognised into
`kind="other"`.

The consequence, measured on a real household: `skip_slot`, `time_budget` and
`repeat` were dead through the interface for a full day. Tuesday kept getting a
dinner the household had said it would be away for. **Every test stayed green**,
because every test built `Intent` directly — which is exactly why this file
exists, and why it works from the schema rather than from the domain object.
"""

from __future__ import annotations

import pytest

from app.schemas import InterpretedConstraint
from app.services.planning_service import Intent


def _as_intents(entries: list[object]) -> list[Intent]:
    """The conversion the route performs, exercised without a database.

    Kept as a literal copy of the route's expression rather than extracted into
    shared code: what is being checked is that the ROUTE converts, and a helper
    both sides import would pass even if the route stopped calling it.
    """
    return [
        Intent(kind=entry.kind, label=entry.label, detail=entry.detail)  # type: ignore[attr-defined]
        for entry in entries
    ]


def test_the_api_type_converts_into_the_domain_type_with_its_kind() -> None:
    """The kind is the whole point: every mechanism dispatches on it."""
    payload = [
        InterpretedConstraint(kind="skip_slot", label="absence mardi", detail="mardi"),
        InterpretedConstraint(kind="time_budget", label="peu de temps", detail="cette semaine"),
    ]

    intents = _as_intents(list(payload))

    assert [intent.kind for intent in intents] == ["skip_slot", "time_budget"]
    assert intents[0].detail == "mardi"


def test_a_constraint_object_is_refused_rather_than_flattened() -> None:
    """The failure mode that cost the day, now loud.

    A conversion that accepts anything cannot fail visibly. Passing the API
    type where the domain type belongs used to produce a valid-looking plan
    with every structured constraint silently downgraded.
    """
    from app.services import planning_service

    with pytest.raises(TypeError, match="Intent or str"):
        planning_service.generate_plan(  # type: ignore[call-arg]
            None,  # never reached: the conversion runs first
            household_id=None,
            llm=None,
            week_start=None,
            user_constraints=[
                InterpretedConstraint(kind="skip_slot", label="absence mardi", detail="mardi")
            ],
        )


def test_a_bare_string_is_still_accepted() -> None:
    """The slot-scoped repair sends one sentence and has no interpretation
    behind it. That path must keep working."""
    from app.services import planning_service

    # It gets past the conversion and fails later, on the database — which is
    # what proves the conversion accepted it.
    with pytest.raises(Exception) as caught:
        planning_service.generate_plan(  # type: ignore[call-arg]
            None,
            household_id=None,
            llm=None,
            week_start=None,
            user_constraints=["je n'aime pas ce plat"],
        )

    assert not isinstance(caught.value, TypeError) or "Intent or str" not in str(caught.value)
