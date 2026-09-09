"""The short name a household can read out when something is broken.

The problem it solves is narrow and real: someone reports a bug, and the
operator has to find their household. Nothing else in the system can do that.
`household_access` holds an auth subject and no email, deliberately, and the
household name is a display name — not unique, changeable, and "Mon foyer" by
default on every account that never renamed itself.

**Derived, never stored.** It is the head of the household's own id, so there is
no new column, no second identifier to keep in step, and no new personal data —
the whole point of this route rather than "ask people for their address".

**Not a secret and not a credential.** Authorisation runs on the session cookie
to an auth subject; knowing a support code grants nothing. It is safe to print
on screen, read over the phone, and paste into a bug report — which is the
entire job.

Eight hex characters, upper case, split by a dash. Long enough that an operator
with a few thousand households sees collisions essentially never, short enough
to be dictated without losing one's place. Collisions are survivable by design:
this is a lookup aid, and `admin find` shows every match rather than guessing.
"""

from __future__ import annotations

import uuid

#: How many hex characters of the id the code keeps.
LENGTH = 8

#: Where the dash goes. Reading eight characters in one run is where people
#: lose their place; two groups of four is a phone number's rhythm.
GROUP = 4


def support_code(household_id: uuid.UUID) -> str:
    """`335c58f8-…` becomes `335C-58F8`."""
    head = household_id.hex[:LENGTH].upper()
    return f"{head[:GROUP]}-{head[GROUP:]}"


def looks_like_code(value: str) -> bool:
    """Whether this is worth matching against ids at all.

    The operator types what a user dictated, so the dash may be missing, the
    case wrong, or a stray space attached. Anything that normalises to the right
    number of hex characters is worth a lookup; anything else is a typo worth
    saying so about, rather than a query that quietly returns nothing.
    """
    cleaned = normalise(value)
    return len(cleaned) == LENGTH and all(c in "0123456789ABCDEF" for c in cleaned)


def normalise(value: str) -> str:
    """What the user meant, whatever they typed."""
    return value.strip().replace("-", "").replace(" ", "").upper()
