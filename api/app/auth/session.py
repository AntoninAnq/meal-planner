"""Session cookie (docs/ARCHITECTURE.md §11.1).

Signed, `HttpOnly`, `SameSite=Lax`, `Secure` outside dev. Never a token in
`localStorage`: that is readable by any injected script, and there is health
data behind this door.

Single origin behind the proxy keeps the cookie first-party — no CORS with
credentials, no `SameSite=None`, no fighting browser protections that harden
every year.
"""

from __future__ import annotations

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import Settings

_SESSION_SALT = "meal-planner.session"
_OAUTH_STATE_SALT = "meal-planner.oauth-state"

#: The OAuth round trip is a browser redirect; a few minutes is generous.
OAUTH_STATE_MAX_AGE_SECONDS = 600
OAUTH_STATE_COOKIE_NAME = "mp_oauth"


def _serializer(settings: Settings, salt: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.session_secret, salt=salt)


def issue_session(settings: Settings, auth_subject: str) -> str:
    return _serializer(settings, _SESSION_SALT).dumps({"sub": auth_subject})


def read_session(settings: Settings, cookie_value: str) -> str | None:
    """Return the auth subject, or None if the cookie is absent, forged or stale."""
    try:
        payload = _serializer(settings, _SESSION_SALT).loads(
            cookie_value, max_age=settings.session_max_age_seconds
        )
    except (BadSignature, SignatureExpired):
        return None
    subject = payload.get("sub")
    return subject if isinstance(subject, str) else None


def issue_oauth_state(settings: Settings, *, state: str, nonce: str, next_path: str) -> str:
    return _serializer(settings, _OAUTH_STATE_SALT).dumps(
        {"state": state, "nonce": nonce, "next": next_path}
    )


def read_oauth_state(settings: Settings, cookie_value: str) -> dict[str, str] | None:
    try:
        payload = _serializer(settings, _OAUTH_STATE_SALT).loads(
            cookie_value, max_age=OAUTH_STATE_MAX_AGE_SECONDS
        )
    except (BadSignature, SignatureExpired):
        return None
    return payload if isinstance(payload, dict) else None
