"""The planning graph and its envelope loop.

No real LLM is ever called. `FakeLLMClient` replays scripted output — including
output that violates the envelope — so the re-validation node is proven to reject
and to feed the violations back.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from app.domain.enums import LifeStage, MealType
from app.domain.planning import SlotSpec
from app.domain.prompt_context import MemberInput, build_prompt_context
from app.llm.fake import FakeLLMClient
from app.workflows.week_plan import (
    MAX_ENVELOPE_ATTEMPTS,
    EmptyCatalogue,
    PlanRequest,
    run_plan,
)

SPEC = [
    SlotSpec(0, MealType.DINNER, ("m1", "m2")),
    SlotSpec(1, MealType.DINNER, ("m1", "m2")),
]

MEMBERS = [
    MemberInput(member_id=uuid.uuid4(), life_stage=LifeStage.TEEN_ADULT),
    MemberInput(member_id=uuid.uuid4(), life_stage=LifeStage.YOUNG_CHILD),
]


def _request(**kwargs: Any) -> PlanRequest:
    context, _ = build_prompt_context(MEMBERS)
    return PlanRequest(spec=SPEC, prompt_context=context, **kwargs)


def _plan(*slots: dict[str, Any]) -> str:
    return json.dumps({"slots": list(slots)})


def _slot(day: int, *dishes: dict[str, Any]) -> dict[str, Any]:
    return {"day_of_week": day, "meal_type": "dinner", "dishes": list(dishes)}


def _dish(*eaters: str, label: str = "Poulet aux olives", **kwargs: Any) -> dict[str, Any]:
    return {"label": label, "eaters": list(eaters), **kwargs}


GOOD = _plan(
    _slot(0, _dish("m1", "m2")),
    _slot(1, _dish("m1", "m2", label="Gratin de courgettes")),
)


def test_a_valid_plan_is_accepted_on_the_first_attempt() -> None:
    outcome = run_plan(_request(), llm=FakeLLMClient([GOOD]))

    assert outcome.accepted
    assert outcome.attempts == 1
    assert len(outcome.proposal) == 2


def test_an_invalid_plan_is_rejected_and_retried() -> None:
    """m2 eats nothing on Monday: the graph must send it back, not accept it."""
    broken = _plan(_slot(0, _dish("m1")), _slot(1, _dish("m1", "m2")))
    llm = FakeLLMClient([broken, GOOD])

    outcome = run_plan(_request(), llm=llm)

    assert outcome.accepted
    assert outcome.attempts == 2
    assert len(llm.calls) == 2


#: The opening of `repair_hint`, matched in full rather than on the word
#: "rejected". That word now also appears in the slot block — "a plan that
#: breaks this is rejected" — and two tests started failing on a prompt change
#: that was correct. A sentinel has to be the thing itself, not a word from it.
REPAIR_MARKER = "Your previous plan was rejected"


def test_the_repair_hint_carries_the_violations_back_to_the_model() -> None:
    broken = _plan(_slot(0, _dish("m1")), _slot(1, _dish("m1", "m2")))
    llm = FakeLLMClient([broken, GOOD])

    run_plan(_request(), llm=llm)

    first, second = llm.calls
    assert REPAIR_MARKER not in first["context"]
    assert "eater_not_served" in second["context"]


def test_an_unchanged_verdict_stops_the_loop_before_the_last_attempt() -> None:
    """A model repeating itself is refusing, not misreading — stop paying for it.

    `FakeLLMClient` replays its last response, so this is the household whose
    week never works: on the harness, `baby_only` spent all three attempts on
    the same nine assignments, every run, for three times the tokens and 33 s
    instead of 12 s — to return exactly what the first attempt returned.

    The second attempt is still made, and always will be: it takes a second
    answer to learn that it is the same as the first. What stops is the third.
    """
    broken = _plan(_slot(0, _dish("m1")), _slot(1, _dish("m1", "m2")))
    llm = FakeLLMClient([broken])

    outcome = run_plan(_request(), llm=llm)

    assert len(llm.calls) == 2
    assert MAX_ENVELOPE_ATTEMPTS == 3, "the saving this test measures is one call in three"

    # Nothing about the outcome changes: a plan that never passed is returned
    # WITH its violations, never as a success.
    assert not outcome.accepted
    assert outcome.violations


def test_a_different_verdict_still_earns_the_last_attempt() -> None:
    """Because the retry raises the temperature, and a hot draw can be worse.

    `validate` carries the measurement: an attempt with two violations followed
    by one with eighteen. Stopping on "no better" would forfeit the third try
    after one bad draw; stopping on "identical" only forfeits it when nothing
    moved at all. These two failures are the same count and the same code —
    what differs is the day — so a rule watching the count would confuse them.
    """
    monday = _plan(_slot(0, _dish("m1")), _slot(1, _dish("m1", "m2")))
    tuesday = _plan(_slot(0, _dish("m1", "m2")), _slot(1, _dish("m1")))
    llm = FakeLLMClient([monday, tuesday, monday])

    outcome = run_plan(_request(), llm=llm)

    assert len(llm.calls) == MAX_ENVELOPE_ATTEMPTS
    assert not outcome.accepted


def test_v0_catalogue_is_unbounded_not_empty() -> None:
    """`None` means unbounded. An empty set would reject every possible plan."""
    catalogue = EmptyCatalogue()
    assert catalogue.candidates_for(SPEC[0]) is None

    outcome = run_plan(_request(), llm=FakeLLMClient([GOOD]), catalogue=catalogue)
    assert outcome.accepted


def test_serving_variants_survive_the_round_trip() -> None:
    with_variant = _plan(
        _slot(0, _dish("m1", "m2", serving_variants=[{"eater": "m2", "variant": "sans olives"}])),
        _slot(1, _dish("m1", "m2", label="Gratin")),
    )
    outcome = run_plan(_request(), llm=FakeLLMClient([with_variant]))

    assert outcome.accepted
    assert outcome.proposal[0].dishes[0].serving_variants == {"m2": "sans olives"}


def test_telemetry_is_aggregated_across_attempts() -> None:
    """The eval harness reads these; they must survive the retry loop."""
    broken = _plan(_slot(0, _dish("m1")), _slot(1, _dish("m1", "m2")))
    llm = FakeLLMClient([broken, GOOD], input_tokens=1_500, output_tokens=300)

    outcome = run_plan(_request(), llm=llm)

    assert len(outcome.llm_results) == 2
    assert outcome.input_tokens == 3_000
    assert outcome.output_tokens == 600


def test_no_member_identifier_reaches_the_prompt() -> None:
    """Invariant I5, checked at the graph level and not only in isolation."""
    llm = FakeLLMClient([GOOD])
    run_plan(_request(), llm=llm)

    context = llm.calls[0]["context"]
    for member in MEMBERS:
        assert str(member.member_id) not in context
    assert "m1" in context and "m2" in context


def test_soft_signals_reach_the_prompt_as_context() -> None:
    """Rotation is a SIGNAL, never a filter — so it belongs in the prompt.

    This asserted `"legumes" in context` while feeding a `rotation_signals`
    field that nothing in production ever populated. It passed for years and
    was the only thing keeping a dead seam alive — which is how a duplicate
    mechanism survives: a test exercises the one nobody uses.
    """
    llm = FakeLLMClient([GOOD])
    run_plan(
        _request(
            recent_meals=["Gratin de courgettes"],
            rotation=["legumes_secs: 23 jours"],
        ),
        llm=llm,
    )

    context = llm.calls[0]["context"]
    assert "legumes_secs: 23 jours" in context
    assert "Gratin de courgettes" in context


def test_the_language_travels_with_the_request_not_the_instructions() -> None:
    """Dish titles are shown to the household as-is, so they must be in its language.

    The instructions stay stable and cacheable, so the language cannot live in
    them — a per-request block carries it instead.
    """
    llm = FakeLLMClient([GOOD])
    run_plan(_request(language="fr"), llm=llm)

    call = llm.calls[0]
    assert "LANGUAGE\nFrench" in call["context"]
    assert "French" not in call["instructions"]


def test_an_unknown_language_code_is_passed_through() -> None:
    """A locale we have no name for still reaches the model rather than silently defaulting."""
    llm = FakeLLMClient([GOOD])
    run_plan(_request(language="es"), llm=llm)

    assert "LANGUAGE\nes" in llm.calls[0]["context"]


def test_a_retry_does_not_ask_the_same_question_again() -> None:
    """Rejecting a plan and asking again in identical terms is time spent to
    obtain the identical plan.

    At temperature 0 the same prompt returns the same output byte for byte —
    measured on qwen3:8b, where attempts 2 and 3 came back with the same 828
    output tokens and the same violations. The first shot stays deterministic;
    the retries must differ.
    """
    broken = _plan(_slot(0, _dish("m1")), _slot(1, _dish("m1", "m2")))
    llm = FakeLLMClient([broken, broken, GOOD])

    run_plan(_request(), llm=llm)

    temperatures = [call["temperature"] for call in llm.calls]
    assert temperatures[0] == 0.0, "the best shot deserves the most likely answer"
    assert len(set(temperatures)) == len(temperatures), f"identical retries: {temperatures}"
    assert all(t is not None and 0.0 <= t <= 1.0 for t in temperatures)


def test_the_repair_hint_changes_between_attempts_too() -> None:
    """Temperature is not the only thing that must move: the model is also told
    what it got wrong, which is the part that can actually steer it."""
    broken = _plan(_slot(0, _dish("m1")), _slot(1, _dish("m1", "m2")))
    llm = FakeLLMClient([broken, GOOD])

    run_plan(_request(), llm=llm)

    assert len(llm.calls) == 2
    assert REPAIR_MARKER in llm.calls[1]["context"]
    assert REPAIR_MARKER not in llm.calls[0]["context"]
