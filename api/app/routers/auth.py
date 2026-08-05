"""Authentication endpoints (docs/ARCHITECTURE.md §11.1)."""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import CurrentSubject
from app.auth.google import (
    GoogleAuthError,
    build_authorize_url,
    exchange_code,
    verify_id_token,
)
from app.auth.session import (
    OAUTH_STATE_COOKIE_NAME,
    OAUTH_STATE_MAX_AGE_SECONDS,
    issue_oauth_state,
    issue_session,
    read_oauth_state,
)
from app.config import Settings, get_settings
from app.db.models import HouseholdAccess
from app.db.session import get_db
from app.services.provisioning import provision_household

router = APIRouter(prefix="/auth", tags=["auth"])

SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[Session, Depends(get_db)]


def _safe_next(path: str | None) -> str:
    """Only ever redirect within our own origin."""
    if not path or not path.startswith("/") or path.startswith("//"):
        return "/"
    return path


@router.get("/login")
def login(settings: SettingsDep, next: Annotated[str | None, Query()] = None) -> RedirectResponse:
    if not settings.google_client_id:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "google oauth is not configured")

    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)

    response = RedirectResponse(
        build_authorize_url(
            client_id=settings.google_client_id,
            redirect_uri=settings.oauth_redirect_uri,
            state=state,
            nonce=nonce,
        ),
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )
    response.set_cookie(
        OAUTH_STATE_COOKIE_NAME,
        issue_oauth_state(settings, state=state, nonce=nonce, next_path=_safe_next(next)),
        max_age=OAUTH_STATE_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    return response


@router.get("/callback")
def callback(
    request: Request,
    settings: SettingsDep,
    db: DbDep,
    code: Annotated[str, Query()],
    state: Annotated[str, Query()],
) -> RedirectResponse:
    raw_state = request.cookies.get(OAUTH_STATE_COOKIE_NAME)
    stored = read_oauth_state(settings, raw_state) if raw_state else None
    if stored is None or not secrets.compare_digest(stored["state"], state):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "oauth state mismatch")

    try:
        id_token = exchange_code(
            code=code,
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            redirect_uri=settings.oauth_redirect_uri,
        )
        identity = verify_id_token(
            id_token=id_token,
            client_id=settings.google_client_id,
            nonce=stored["nonce"],
        )
    except GoogleAuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    known = db.scalar(
        select(HouseholdAccess).where(HouseholdAccess.auth_subject == identity.subject)
    )
    if known is None:
        provision_household(db, auth_subject=identity.subject)

    response = RedirectResponse(
        _safe_next(stored.get("next")), status_code=status.HTTP_303_SEE_OTHER
    )
    response.set_cookie(
        settings.session_cookie_name,
        issue_session(settings, identity.subject),
        max_age=settings.session_max_age_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    response.delete_cookie(OAUTH_STATE_COOKIE_NAME, path="/")
    return response


@router.post("/logout")
def logout(settings: SettingsDep) -> Response:
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(settings.session_cookie_name, path="/")
    return response


@router.get("/me")
def me(subject: CurrentSubject) -> dict[str, str]:
    """Who is signed in. Returns the prefixed subject, never a household id."""
    return {"auth_subject": subject}
