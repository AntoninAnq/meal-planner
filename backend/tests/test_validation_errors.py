"""A 422 must say WHICH field it is about.

This exists because of an afternoon spent on one. A discriminated union that
receives a string answers `Input should be a valid dictionary or object to
extract fields from` — a sentence that names no field, is identical whether the
value was a string or null, and is exactly what the interface displayed to the
household. The field name is the whole diagnosis.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.main import _log_validation_error, _shape


class Body(BaseModel):
    slot: dict[str, str]
    count: int


def _client() -> TestClient:
    app = FastAPI()
    app.add_exception_handler(type(_probe_error()), _log_validation_error)  # type: ignore[arg-type]

    @app.post("/thing")
    def thing(body: Body) -> dict[str, str]:  # pragma: no cover - never reached
        return {"ok": "yes"}

    return TestClient(app)


def _probe_error():  # type: ignore[no-untyped-def]
    from fastapi.exceptions import RequestValidationError

    return RequestValidationError([])


def test_a_rejected_field_is_named_in_the_response() -> None:
    response = _client().post("/thing", json={"slot": "lundi", "count": 2})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail[0]["field"] == "body.slot"
    # The original shape survives: every existing client reads `msg` and `loc`.
    assert detail[0]["msg"]
    assert detail[0]["loc"] == ["body", "slot"]


def test_several_bad_fields_are_all_named() -> None:
    response = _client().post("/thing", json={"slot": "lundi", "count": "beaucoup"})

    fields = {error["field"] for error in response.json()["detail"]}
    assert fields == {"body.slot", "body.count"}


def test_the_log_describes_the_shape_and_never_the_value() -> None:
    """The rejected body carries dietary constraints — health data.

    The log needs to know that `scope` arrived as a string; it must never
    record that someone wrote "pas de gluten, ma fille est coeliaque".
    """
    assert _shape("pas de gluten") == "str"
    assert _shape(None) == "NoneType"
    assert _shape({"type": "week", "week_start": "2026-08-17"}) == "dict{type,week_start}"
    assert _shape([{"kind": "avoid", "detail": "poisson"}]) == "list[1] of dict{detail,kind}"
    assert _shape([]) == "list[0] of -"

    rendered = " ".join(
        [
            _shape("pas de gluten"),
            _shape([{"kind": "avoid", "detail": "poisson"}]),
        ]
    )
    assert "gluten" not in rendered
    assert "poisson" not in rendered
