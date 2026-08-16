"""The planning graph.

    pre-filter ──▶ signals ──▶ arbitrate ──▶ validate ──┬──▶ END
                                    ▲                   │
                                    └───────────────────┘
                                      violations, bounded

Two levels of retry, and they are not the same thing:

* `RetryingLLMClient` retries a SHAPE failure — malformed JSON, schema mismatch.
  It lives in the LLM layer because every caller wants it identically.
* This graph retries an ENVELOPE failure — a dish outside the candidate set, an
  eater served twice, a slot missing. That is domain knowledge, so it lives here,
  and the violations are fed back to the model as a repair hint.

In V0 the pre-filter is stubbed: `CataloguePort` returns no candidates, meaning
"unbounded", and the envelope check has nothing to enforce. Every structural
check still runs. The seam is real; only its data is missing.

The graph holds no I/O of its own: the database work happens in the service that
builds `PlanRequest`, so every node here is a pure function of the state.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Annotated, Any, Protocol, TypedDict

from langgraph.graph import END, StateGraph

from app.domain.plan_schema import parse_proposal, plan_output_schema
from app.domain.planning import (
    ProposedSlot,
    SlotSpec,
    Violation,
    repair_hint,
    validate_proposal,
)
from app.domain.prompt_context import PromptContext
from app.llm.base import LLMClient, StructuredResult
from app.workflows.prompts import ARBITRATION_INSTRUCTIONS, build_context

#: How many times the graph may send violations back to the model. Beyond this
#: the plan is returned WITH its violations rather than silently accepted —
#: never pretend a rejected plan passed.
MAX_ENVELOPE_ATTEMPTS = 3

#: One temperature per envelope attempt. The first is deterministic — the best
#: shot deserves the model's most likely answer. The retries are not: at
#: temperature 0 the same prompt returns the same output byte for byte, so
#: rejecting a plan and asking again in exactly the same terms is 29 seconds
#: (measured) spent to obtain the identical plan. Asking again only means
#: something if something changed.
#:
#: Kept moderate on purpose: the output is schema-constrained, and pushing the
#: temperature high trades one failure mode (a repetitive plan) for another
#: (an invalid one, caught by the shape loop, paid for twice).
RETRY_TEMPERATURES = (0.0, 0.7, 1.0)


class CataloguePort(Protocol):
    """The pre-filter's data source. Stubbed in V0, SQL from V1 on."""

    def candidates_for(self, slot: SlotSpec) -> frozenset[str] | None:
        """Allowed recipe ids for this slot, or None when unbounded (V0)."""

    def describe(self, recipe_ids: frozenset[str]) -> list[str]:
        """One short line per candidate: title and key ingredients."""


class EmptyCatalogue:
    """V0 stub — there is no catalogue yet.

    It returns `None` rather than an empty set, and the difference matters: an
    empty set would mean "nothing is allowed" and every plan would be rejected.
    `None` means "unbounded", which is the truth in V0.
    """

    def candidates_for(self, slot: SlotSpec) -> frozenset[str] | None:
        return None

    def describe(self, recipe_ids: frozenset[str]) -> list[str]:
        return []


@dataclass(frozen=True)
class PlanRequest:
    spec: list[SlotSpec]
    prompt_context: PromptContext
    #: Dish titles and serving variants are shown to the household as-is, so
    #: the model must write them in the right language. It travels with the
    #: request rather than living in the instructions, which stay stable and
    #: cacheable.
    language: str = "fr"
    user_constraints: list[str] = field(default_factory=list)
    #: Free-text labels eaten recently, for the anti-repetition signal. Computed
    #: from past planned dishes — history is implicit in V0.
    recent_meals: list[str] = field(default_factory=list)
    with_catalogue: bool = False


@dataclass
class PlanOutcome:
    proposal: list[ProposedSlot]
    violations: list[Violation]
    attempts: int
    llm_results: list[StructuredResult]

    @property
    def accepted(self) -> bool:
        return not self.violations

    @property
    def input_tokens(self) -> int:
        return sum(result.input_tokens for result in self.llm_results)

    @property
    def output_tokens(self) -> int:
        return sum(result.output_tokens for result in self.llm_results)


def _keep_last(_current: Any, incoming: Any) -> Any:
    return incoming


def _append(current: list[Any], incoming: list[Any]) -> list[Any]:
    return [*current, *incoming]


class PlanState(TypedDict, total=False):
    request: PlanRequest
    allowed_recipe_ids: Annotated[frozenset[str] | None, _keep_last]
    candidate_lines: Annotated[list[str], _keep_last]
    context: Annotated[str, _keep_last]
    proposal: Annotated[list[ProposedSlot], _keep_last]
    violations: Annotated[list[Violation], _keep_last]
    attempt: Annotated[int, _keep_last]
    llm_results: Annotated[list[StructuredResult], _append]


def build_graph(llm: LLMClient, catalogue: CataloguePort) -> Any:
    """Compile the planning graph for a given LLM and catalogue."""

    def prefilter(state: PlanState) -> PlanState:
        """Hard constraints -> the candidate envelope. Deterministic, SQL from V1."""
        request = state["request"]
        per_slot = [catalogue.candidates_for(slot) for slot in request.spec]

        if any(candidates is None for candidates in per_slot):
            # Unbounded: V0, or a slot the catalogue cannot constrain.
            allowed: frozenset[str] | None = None
            lines: list[str] = []
        else:
            allowed = frozenset().union(*per_slot)  # type: ignore[arg-type]
            lines = catalogue.describe(allowed)

        return {"allowed_recipe_ids": allowed, "candidate_lines": lines}

    def signals(state: PlanState) -> PlanState:
        """Soft signals -> prompt context. They inform, they never filter."""
        request = state["request"]
        return {
            "context": build_context(
                spec=request.spec,
                prompt_context=request.prompt_context,
                language=request.language,
                user_constraints=request.user_constraints,
                candidate_lines=state.get("candidate_lines", []),
                recent_meals=request.recent_meals,
            ),
            "attempt": 0,
        }

    def arbitrate(state: PlanState) -> PlanState:
        """The LLM picks among candidates. It emits identifiers, never prose."""
        request = state["request"]
        attempt = state.get("attempt", 0) + 1

        context = state["context"]
        violations = state.get("violations") or []
        if violations:
            context = f"{context}\n\n{repair_hint(violations)}"

        index = min(attempt, len(RETRY_TEMPERATURES)) - 1
        result = llm.complete_structured(
            instructions=ARBITRATION_INSTRUCTIONS,
            context=context,
            schema=plan_output_schema(with_catalogue=request.with_catalogue),
            temperature=RETRY_TEMPERATURES[index],
        )

        return {
            "proposal": parse_proposal(result.data),
            "attempt": attempt,
            "llm_results": [result],
        }

    def validate(state: PlanState) -> PlanState:
        """Re-validation. The output is checked, never trusted."""
        request = state["request"]
        return {
            "violations": validate_proposal(
                state.get("proposal", []),
                request.spec,
                state.get("allowed_recipe_ids"),
            )
        }

    def should_retry(state: PlanState) -> str:
        if not state.get("violations"):
            return END
        if state.get("attempt", 0) >= MAX_ENVELOPE_ATTEMPTS:
            return END
        return "arbitrate"

    graph = StateGraph(PlanState)
    graph.add_node("prefilter", prefilter)
    graph.add_node("signals", signals)
    graph.add_node("arbitrate", arbitrate)
    graph.add_node("validate", validate)

    graph.set_entry_point("prefilter")
    graph.add_edge("prefilter", "signals")
    graph.add_edge("signals", "arbitrate")
    graph.add_edge("arbitrate", "validate")
    graph.add_conditional_edges("validate", should_retry, {"arbitrate": "arbitrate", END: END})

    return graph.compile()


def run_plan(
    request: PlanRequest,
    *,
    llm: LLMClient,
    catalogue: CataloguePort | None = None,
) -> PlanOutcome:
    """Run the graph and return the outcome, violations included.

    A plan that never satisfied the envelope is returned WITH its violations.
    Callers decide what to do; nothing here pretends a rejected plan passed.
    """
    compiled = build_graph(llm, catalogue or EmptyCatalogue())
    final: PlanState = compiled.invoke({"request": request})

    return PlanOutcome(
        proposal=final.get("proposal", []),
        violations=final.get("violations", []),
        attempts=final.get("attempt", 0),
        llm_results=final.get("llm_results", []),
    )


def slot_specs_from(
    slots: Sequence[tuple[int, Any]],
    eater_aliases: Sequence[str],
) -> list[SlotSpec]:
    """Convenience: same eaters at every slot, the common case."""
    return [
        SlotSpec(day_of_week=day, meal_type=meal_type, eater_aliases=tuple(eater_aliases))
        for day, meal_type in slots
    ]
