"""The pre-filter's ranking and sizing — the parts that are pure.

The SQL half is exercised against the real catalogue; what is checked here is
the logic a mistake would make invisible: a seed that stops being reproducible
(the reserve then stops matching what the model was shown), or a candidate set
sized so tightly that the arbitration has nothing left to arbitrate.
"""

from __future__ import annotations

import uuid
from datetime import date

from app.services.catalogue import (
    CANDIDATE_CEILING,
    CANDIDATE_FLOOR,
    Candidate,
    candidate_count,
    rank,
)


def _ids(n: int) -> list[uuid.UUID]:
    return [uuid.UUID(int=index) for index in range(n)]


# ---------------------------------------------------------------------------
# Sizing
# ---------------------------------------------------------------------------


def test_the_default_week_still_leaves_the_model_a_choice() -> None:
    """9 slots, 2 dishes each — 18 dishes drawn from at least 60 candidates.

    A candidate set barely larger than the answer makes the arbitration
    decorative, which is exactly what §6.1 says this project refuses.
    """
    assert candidate_count(slots=9, dishes_per_slot=2) >= CANDIDATE_FLOOR


def test_a_full_grid_asking_for_three_dishes_is_not_starved() -> None:
    """The case that killed the first sizing: 14 slots x 3 = 42 dishes.

    A 40-candidate set would have been the answer, not a pool.
    """
    assert candidate_count(slots=14, dishes_per_slot=3) > 14 * 3


def test_the_set_is_capped_whatever_the_grid() -> None:
    """31 tokens a line, so the ceiling is what keeps the prompt inside 8 192."""
    assert candidate_count(slots=14, dishes_per_slot=6) == CANDIDATE_CEILING


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------


def test_the_same_week_always_ranks_the_same_way() -> None:
    """The reserve is recomputed, never stored.

    `GET …/alternatives` rebuilds the ranking to find the candidates that were
    set aside. If the seed stopped being reproducible, it would offer
    alternatives the model was never shown — and the eval harness would stop
    being comparable between runs.
    """
    eligible = _ids(50)
    seed = "household-1:2026-08-17"

    first = rank(eligible, last_planned={}, seed=seed)
    second = rank(eligible, last_planned={}, seed=seed)

    assert first == second


def test_the_next_week_draws_differently() -> None:
    """Otherwise 555 recipes behave like 60.

    A deterministic ranking with no seed would show the same head forever, and
    the catalogue work of this phase would buy nothing.
    """
    eligible = _ids(50)

    this_week = rank(eligible, last_planned={}, seed="household-1:2026-08-17")
    next_week = rank(eligible, last_planned={}, seed="household-1:2026-08-24")

    assert this_week[:20] != next_week[:20]


def test_two_households_do_not_see_the_same_week() -> None:
    eligible = _ids(50)

    one = rank(eligible, last_planned={}, seed="household-1:2026-08-17")
    other = rank(eligible, last_planned={}, seed="household-2:2026-08-17")

    assert one[:20] != other[:20]


def test_a_recipe_never_served_comes_before_one_that_was() -> None:
    """The right default on a fresh catalogue, and the anti-repetition signal
    doing its work deterministically before the model ever sees anything."""
    eligible = _ids(4)
    served = {eligible[0]: date(2026, 8, 10), eligible[1]: date(2026, 7, 1)}

    ordered = rank(eligible, last_planned=served, seed="s")

    assert set(ordered[:2]) == {eligible[2], eligible[3]}


def test_among_served_recipes_the_oldest_comes_first() -> None:
    eligible = _ids(3)
    served = {
        eligible[0]: date(2026, 8, 10),
        eligible[1]: date(2026, 6, 1),
        eligible[2]: date(2026, 7, 15),
    }

    ordered = rank(eligible, last_planned=served, seed="s")

    assert ordered == [eligible[1], eligible[2], eligible[0]]


def test_ranking_loses_nothing() -> None:
    """A recipe dropped by the ranking would be invisible and unexplainable."""
    eligible = _ids(30)
    served = {eligible[index]: date(2026, 8, index + 1) for index in range(0, 30, 3)}

    ordered = rank(eligible, last_planned=served, seed="s")

    assert sorted(ordered, key=str) == sorted(eligible, key=str)


# ---------------------------------------------------------------------------
# The candidate line
# ---------------------------------------------------------------------------


def test_a_candidate_line_leads_with_the_handle() -> None:
    """The model answers with this string, and a UUID would cost 15 tokens."""
    candidate = Candidate(
        handle="r_007",
        recipe_id=uuid.UUID(int=7),
        title="Tajine de poulet aux olives",
        ingredients=["Poulet", "Olive verte", "Citron confit", "Oignon", "Coriandre", "Cumin"],
    )

    line = candidate.line()

    assert line.startswith("r_007 — Tajine de poulet aux olives")
    # Capped: the line has to stay near 31 tokens, measured.
    assert "Cumin" not in line


def test_a_candidate_with_no_resolved_ingredient_still_has_a_line() -> None:
    """961 catalogue recipes carry no mapped rubric and some resolve nothing.

    They are still eligible — an empty tail must not produce a dangling dash.
    """
    candidate = Candidate(handle="r_000", recipe_id=uuid.UUID(int=0), title="Soupe", ingredients=[])

    assert candidate.line() == "r_000 — Soupe"
