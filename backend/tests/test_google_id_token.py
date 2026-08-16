"""ID token verification, and its tolerance to clock skew.

Regression test for a real failure: a login rejected with "The token is not yet
valid (iat)" on a machine whose clock was 2.6 seconds behind Google's — with NTP
running and reporting itself synchronized.

Two servers never agree on the time to the second. Verifying `iat` with zero
tolerance turns ordinary drift into a hard login failure, so the leeway is part
of the contract, not a workaround.

No network: the JWKS lookup is replaced by a locally generated key pair.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth import google
from app.auth.google import CLOCK_SKEW_LEEWAY, GoogleAuthError, verify_id_token

CLIENT_ID = "1234.apps.googleusercontent.com"
NONCE = "a-nonce"
SUBJECT = "117482900000000000000"

_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)


@dataclass
class _StubSigningKey:
    key: Any


@pytest.fixture(autouse=True)
def _local_jwks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        google._jwk_client,
        "get_signing_key_from_jwt",
        lambda _token: _StubSigningKey(_key.public_key()),
    )


def _token(**overrides: Any) -> str:
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": SUBJECT,
        "email": "antonin@example.com",
        "nonce": NONCE,
        "iat": now,
        "exp": now + timedelta(hours=1),
    }
    claims.update(overrides)
    return jwt.encode(claims, _key, algorithm="RS256")


def _verify(token: str) -> google.GoogleIdentity:
    return verify_id_token(id_token=token, client_id=CLIENT_ID, nonce=NONCE)


def test_a_well_formed_token_is_accepted() -> None:
    identity = _verify(_token())

    # The subject is prefixed by its mechanism, so adding another one later
    # cannot collide with it.
    assert identity.subject == f"google:{SUBJECT}"
    assert identity.email == "antonin@example.com"


def test_a_token_issued_slightly_in_the_future_is_accepted() -> None:
    """The actual regression: ordinary drift must not break the login."""
    ahead = datetime.now(UTC) + timedelta(seconds=5)
    assert _verify(_token(iat=ahead)).subject == f"google:{SUBJECT}"


def test_drift_beyond_the_leeway_is_still_rejected() -> None:
    """Tolerance, not blindness: a token from far in the future stays invalid."""
    far_ahead = datetime.now(UTC) + CLOCK_SKEW_LEEWAY + timedelta(minutes=5)
    with pytest.raises(GoogleAuthError):
        _verify(_token(iat=far_ahead))


def test_an_expired_token_is_rejected() -> None:
    past = datetime.now(UTC) - timedelta(hours=2)
    with pytest.raises(GoogleAuthError):
        _verify(_token(iat=past, exp=past + timedelta(minutes=1)))


def test_a_token_for_another_audience_is_rejected() -> None:
    with pytest.raises(GoogleAuthError):
        _verify(_token(aud="someone-elses-client-id"))


def test_a_token_from_another_issuer_is_rejected() -> None:
    with pytest.raises(GoogleAuthError):
        _verify(_token(iss="https://evil.example.com"))


def test_a_replayed_token_with_the_wrong_nonce_is_rejected() -> None:
    """The nonce is what ties the token to the login this browser started."""
    with pytest.raises(GoogleAuthError):
        _verify(_token(nonce="a-different-nonce"))


def test_a_token_without_a_subject_is_rejected() -> None:
    with pytest.raises(GoogleAuthError):
        _verify(_token(sub=""))
