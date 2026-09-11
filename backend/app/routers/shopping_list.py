"""The shopping list, entirely a read.

No table, no migration, no state: the selection of meals lives in the request,
because it is a decision about one trip to the shops and not something the
household keeps. Re-opening the drawer tomorrow should start from "what is
left", not from what was ticked last Tuesday.

Meal by meal rather than day by day. A day holds a lunch AND a dinner, and
"mardi midi je mange au bureau" has to be sayable.

`household_id` appears in no signature — it comes from the session (I6).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.auth.deps import CurrentHousehold
from app.db.session import get_db
from app.domain.days import parse_slot
from app.schemas import ShoppingListOut
from app.services.planning_service import load_plan
from app.services.shopping_list import build

router = APIRouter(prefix="/shopping-list", tags=["shopping-list"])

DbDep = Annotated[Session, Depends(get_db)]


@router.get("", response_model=ShoppingListOut | None)
def shopping_list(
    db: DbDep,
    household_id: CurrentHousehold,
    week_start: Annotated[date, Query()],
    slot: Annotated[list[str], Query()] = [],  # noqa: B006
) -> ShoppingListOut | None:
    """Null when the week has no plan — there is nothing to shop for, and the
    interface does not offer the button at all in that case."""
    plan = load_plan(db, household_id, week_start)
    if plan is None:
        return None

    try:
        slots = {(day, meal.value) for day, meal in (parse_slot(key) for key in slot)}
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    return build(db, household_id=household_id, plan=plan, slots=slots)
