"""Metering the model calls a household makes, and bounding them.

Signing up is open by design (`provision_household`): any Google identity that
arrives gets its own household. That decision was taken with the alternative on
the table — an invite list — and rejected, so that a stranger who finds the
product can try it. What it costs is that the API is metered and the door is
not, and this module is the whole of what closes the gap.

Two operations, deliberately separate:

  * `WithinQuota` refuses BEFORE the call, because a limit checked afterwards
    has already paid for the thing it was meant to prevent.
  * `record` writes AFTER it, because the token count does not exist until the
    provider has answered.

Nothing here is a fairness rule between households. It is a ceiling on what one
of them can spend in a day, and the number that sets it lives in `Settings`
(I8) because it is derived from a rate card that will change.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import current_household_id
from app.config import Settings, get_settings
from app.db.models import GenerationLog
from app.db.session import get_db
from app.domain.enums import GenerationKind

#: What the browser is told. It names the limit and the window because a refusal
#: that says only "too many requests" is indistinguishable, to the person
#: reading it, from the product being broken.
QUOTA_EXCEEDED = (
    "this household has reached its limit of {limit} suggestions per {hours} h — "
    "it frees up progressively, try again later"
)


def _window_start(settings: Settings, now: datetime) -> datetime:
    return now - timedelta(hours=settings.generation_window_hours)


def _as_utc(moment: datetime) -> datetime:
    """A timestamp read back from storage, as UTC.

    Every write goes through `now()` into a `timestamptz` column, so Postgres
    hands one back carrying its zone. SQLite has none to hand back — and the
    test suite runs on SQLite, because CI deliberately has no database. The
    column's contract is UTC either way; this states it rather than letting the
    subtraction below raise on a naive value in the one environment that proves
    the mechanism works.
    """
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def calls_since(db: Session, household_id: uuid.UUID, since: datetime) -> int:
    """How many model calls this household has paid for since `since`.

    Failed calls count. They cost tokens — a generation that exhausts its three
    attempts costs MORE than one that succeeds — and a quota that only counted
    successes would leave the cheapest way to burn an API key uncounted.
    """
    return (
        db.scalar(
            select(func.count())
            .select_from(GenerationLog)
            .where(
                GenerationLog.household_id == household_id,
                GenerationLog.created_at >= since,
            )
        )
        or 0
    )


def enforce_quota(
    household_id: Annotated[uuid.UUID, Depends(current_household_id)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> uuid.UUID:
    """Refuse with 429 and a `Retry-After` the caller can act on.

    Returns the household id so an endpoint can depend on this INSTEAD of
    `CurrentHousehold` rather than in addition to it. Two dependencies would be
    two chances to wire one and forget the other, and the one that gets
    forgotten is always the check.

    **Deliberately not locked.** Two requests arriving together can both read a
    count below the limit and both go through, so the real ceiling is the limit
    plus the number of calls in flight. At 50 a day, from a browser, that is one
    or two calls of slippage — and the row lock or advisory lock that would
    close it costs a serialisation point on every generation, forever, to
    recover a cent.
    """
    now = datetime.now(UTC)
    used = calls_since(db, household_id, _window_start(settings, now))
    if used < settings.generation_daily_limit:
        return household_id

    # When the oldest call in the window ages out — that is the first moment
    # this household regains a slot. Absent (the window emptied between the
    # count and here) means the whole window.
    oldest = db.scalar(
        select(func.min(GenerationLog.created_at)).where(
            GenerationLog.household_id == household_id,
            GenerationLog.created_at >= _window_start(settings, now),
        )
    )
    window = timedelta(hours=settings.generation_window_hours)
    frees_at = (_as_utc(oldest) + window) if oldest else (now + window)
    raise HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        QUOTA_EXCEEDED.format(
            limit=settings.generation_daily_limit,
            hours=settings.generation_window_hours,
        ),
        headers={"Retry-After": str(max(1, int((frees_at - now).total_seconds())))},
    )


def record(
    db: Session,
    *,
    household_id: uuid.UUID,
    kind: GenerationKind,
    input_tokens: int = 0,
    output_tokens: int = 0,
    attempts: int = 1,
    model_id: str = "",
    succeeded: bool = True,
) -> None:
    """Append one row and commit it on its own.

    Its own transaction on purpose: on the failure path the caller has just
    rolled back a half-written plan, and the accounting of a call that really
    happened must not be discarded along with it.
    """
    db.add(
        GenerationLog(
            household_id=household_id,
            kind=kind,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            attempts=attempts,
            model_id=model_id,
            succeeded=succeeded,
        )
    )
    db.commit()


WithinQuota = Annotated[uuid.UUID, Depends(enforce_quota)]
