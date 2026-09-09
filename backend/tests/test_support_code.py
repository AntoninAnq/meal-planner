"""The identifier a bug report travels with.

Two properties matter and neither is cryptographic: the same household always
reads out the same code, and whatever the user actually types comes back to the
same thing. A code that changes between two screens sends the operator hunting;
a lookup that fails on a missing dash makes the mechanism useless at the one
moment it is used.
"""

from __future__ import annotations

import uuid

from app.domain.support_code import LENGTH, looks_like_code, normalise, support_code

HOUSEHOLD = uuid.UUID("335c58f8-2a24-42d3-9815-db48f39fb362")


def test_the_code_is_the_head_of_the_id_made_readable() -> None:
    assert support_code(HOUSEHOLD) == "335C-58F8"


def test_the_same_household_always_reads_the_same() -> None:
    # Derived, not stored: there is no second identifier that could drift.
    assert support_code(HOUSEHOLD) == support_code(HOUSEHOLD)


def test_two_households_do_not_share_a_code() -> None:
    other = uuid.UUID("1bd33d27-cc52-459e-af10-ed70eba1d635")
    assert support_code(other) != support_code(HOUSEHOLD)


def test_it_is_dictated_back_however_it_was_typed() -> None:
    # What a person reads out loses its dash, its case, or gains a space.
    for typed in ("335C-58F8", "335c58f8", " 335c-58F8 ", "335C 58F8"):
        assert normalise(typed) == "335C58F8"


def test_something_that_is_not_a_code_is_recognised_as_such() -> None:
    # Better a named typo than a lookup that quietly returns nothing.
    assert looks_like_code("335C-58F8")
    assert not looks_like_code("335C-58")
    assert not looks_like_code("Mon foyer")
    assert not looks_like_code(str(HOUSEHOLD))


def test_the_code_is_a_prefix_of_the_id_so_a_lookup_can_use_it() -> None:
    assert HOUSEHOLD.hex.upper().startswith(normalise(support_code(HOUSEHOLD)))
    assert len(normalise(support_code(HOUSEHOLD))) == LENGTH
