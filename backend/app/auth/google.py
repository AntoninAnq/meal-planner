"""Google OAuth.

Chosen over magic links because a magic link drags in an email sending service,
a domain with SPF/DKIM and deliverability to monitor — and deliverability is
precisely the piece you have the least grip on. A login email in the spam folder
is a user locked out, discovered through a message rather than an alert.

Scope is `openid email profile` (non-sensitive), so Google's verification stays
light and is not required at all below 100 test users.

The `sub` claim becomes `google:<sub>` in `household_access.auth_subject`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlencode

import httpx
import jwt
from jwt import PyJWKClient

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
VALID_ISSUERS = ("https://accounts.google.com", "accounts.google.com")

SUBJECT_PREFIX = "google"

#: Tolerance on time-based claims (`iat`, `nbf`, `exp`).
#:
#: Two servers never agree on the time to the second. Even with NTP running and
#: reporting "synchronized", a couple of seconds of residual drift is ordinary —
#: and verifying `iat` with zero tolerance turns that into a hard login failure
#: ("The token is not yet valid (iat)"). Clock skew is a fact of distributed
#: systems, not an anomaly to be fixed at the machine level.
#:
#: 60 seconds is the usual figure: wide enough to absorb real drift, narrow
#: enough that it changes nothing about the security of the check — the
#: signature, issuer, audience and nonce are what actually authenticate the
#: token.
CLOCK_SKEW_LEEWAY = timedelta(seconds=60)

_jwk_client = PyJWKClient(JWKS_URL, cache_keys=True)


class GoogleAuthError(Exception):
    """The provider round trip failed, or the identity could not be trusted."""


@dataclass(frozen=True)
class GoogleIdentity:
    subject: str  # already prefixed, ready for household_access
    email: str | None


def build_authorize_url(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    nonce: str,
) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        # We only need identity, never offline access: no refresh token to store.
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def exchange_code(
    *,
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    timeout_seconds: float = 15.0,
) -> str:
    """Swap the authorization code for an ID token."""
    try:
        response = httpx.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=timeout_seconds,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise GoogleAuthError(f"token exchange failed: {exc}") from exc

    id_token = response.json().get("id_token")
    if not isinstance(id_token, str):
        raise GoogleAuthError("token response carried no id_token")
    return id_token


def verify_id_token(*, id_token: str, client_id: str, nonce: str) -> GoogleIdentity:
    """Verify signature, issuer, audience and nonce, then extract the subject."""
    try:
        signing_key = _jwk_client.get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            leeway=CLOCK_SKEW_LEEWAY,
            audience=client_id,
            issuer=list(VALID_ISSUERS),
            options={"require": ["exp", "iat", "aud", "iss", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise GoogleAuthError(f"id_token rejected: {exc}") from exc

    if claims.get("nonce") != nonce:
        raise GoogleAuthError("nonce mismatch")

    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise GoogleAuthError("id_token carried no usable subject")

    return GoogleIdentity(subject=f"{SUBJECT_PREFIX}:{subject}", email=claims.get("email"))
