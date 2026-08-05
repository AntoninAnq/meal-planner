"""Authentication dependencies — the single place identity becomes a household.

Invariant I6: `household_id` is derived from the authenticated identity, never
accepted from a request body or URL. It appears in no endpoint signature.

Why the API authenticates rather than the proxy: a proxy that authenticates and
injects `X-Auth-User` leaves the API taking that header on trust. The `api`
container is reachable another way — on the Docker network, and on the port
published locally — so forging the header would grant full access. And in
development one hits the API directly, meaning the auth path would never run in
dev: months of work on a system without auth, first real execution in
production. Same failure mode as a validator never exercised.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.session import read_session
from app.config import Settings, get_settings
from app.db.models import HouseholdAccess
from app.db.session import get_db


def current_auth_subject(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> str:
    cookie = request.cookies.get(settings.session_cookie_name)
    if not cookie:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")

    subject = read_session(settings, cookie)
    if subject is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session invalid or expired")
    return subject


def current_household_id(
    subject: Annotated[str, Depends(current_auth_subject)],
    db: Annotated[Session, Depends(get_db)],
) -> uuid.UUID:
    household_id = db.scalar(
        select(HouseholdAccess.household_id).where(HouseholdAccess.auth_subject == subject)
    )
    if household_id is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no household linked to this identity")
    return household_id


CurrentHousehold = Annotated[uuid.UUID, Depends(current_household_id)]
CurrentSubject = Annotated[str, Depends(current_auth_subject)]
