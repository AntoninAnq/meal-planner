"""The household endpoints, over HTTP, because nothing else exercises them.

`app.admin.actions` is well covered — by `test_admin_actions.py`, on the same
functions the CLI calls. What that suite cannot see is the layer added here:
the query parameter, the four status codes, and the shape the browser is handed.
These are the verbs reached for on a bad night, and the failure mode this file
exists for is a route that has never once been called.

The gate itself is checked mechanically next door, in
`test_admin_authorisation.py`. Here it is overridden, so what is under test is
what the routes do once somebody is through it.

SQLite, like the other admin suites: CI runs without a database.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.deps import current_operator, current_owner
from app.config import Settings, get_settings
from app.db.models import (
    Base,
    GenerationLog,
    Household,
    HouseholdAccess,
    Member,
    Operator,
)
from app.db.session import get_db
from app.domain.enums import GenerationKind, OperatorLevel
from app.domain.support_code import support_code
from app.main import app

SUBJECT = "google:117482000000000000000"
TABLES = [
    Household.__table__,
    HouseholdAccess.__table__,
    Member.__table__,
    GenerationLog.__table__,
    Operator.__table__,
]


@pytest.fixture
def db() -> Session:
    # `TestClient` runs the app on a threadpool, and a sync dependency lands on
    # a different thread than the one that built this session. An in-memory
    # SQLite connection refuses that, and would refuse it as a crash inside
    # SQLAlchemy's teardown rather than as a failed assertion — one pool, one
    # connection, shared.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=TABLES)
    return sessionmaker(bind=engine)()


@pytest.fixture
def client(db: Session) -> Iterator[TestClient]:
    owner = Operator(auth_subject="google:operator", level=OperatorLevel.OWNER)

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[current_operator] = lambda: owner
    app.dependency_overrides[current_owner] = lambda: owner
    app.dependency_overrides[get_settings] = lambda: Settings.model_construct(
        generation_daily_limit=50, generation_window_hours=24
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


def _household(db: Session, name: str = "Mon foyer", subject: str = SUBJECT) -> uuid.UUID:
    household = Household(name=name)
    db.add(household)
    db.flush()
    db.add(HouseholdAccess(auth_subject=subject, household_id=household.id))
    db.commit()
    return household.id


def _burn(db: Session, household_id: uuid.UUID, calls: int) -> None:
    for _ in range(calls):
        db.add(GenerationLog(household_id=household_id, kind=GenerationKind.WEEK))
    db.commit()


# -- Reading -----------------------------------------------------------------


def test_the_list_leads_with_the_biggest_spender(client: TestClient, db: Session) -> None:
    quiet = _household(db, "Foyer calme", "google:1")
    loud = _household(db, "Foyer bruyant", "google:2")
    _burn(db, quiet, 2)
    _burn(db, loud, 9)

    body = client.get("/admin/households").json()

    assert [row["name"] for row in body["households"]] == ["Foyer bruyant", "Foyer calme"]
    assert body["households"][0]["calls_in_window"] == 9
    assert str(loud) == body["households"][0]["household_id"]


def test_the_rate_card_travels_with_the_rows(client: TestClient, db: Session) -> None:
    """`limit_override` is null for almost everybody, and null alone says
    nothing. Sent once rather than per row, and never left implicit."""
    _household(db)

    body = client.get("/admin/households").json()

    assert body["default_limit"] == 50
    assert body["window_hours"] == 24
    assert body["households"][0]["limit_override"] is None


def test_a_code_finds_its_household(client: TestClient, db: Session) -> None:
    _household(db, "Cherché", "google:1")
    wanted = _household(db, "Trouvé", "google:2")
    _household(db, "Ignoré", "google:3")

    body = client.get("/admin/households", params={"code": support_code(wanted)}).json()

    assert [row["name"] for row in body["households"]] == ["Trouvé"]


def test_a_code_that_matches_nothing_is_an_empty_list_not_an_error(
    client: TestClient, db: Session
) -> None:
    # An operator mistyping a code should read "no household carries this", not
    # a failure that suggests the instance is broken.
    _household(db)

    response = client.get("/admin/households", params={"code": "0000-0000"})

    assert response.status_code == 200
    assert response.json()["households"] == []


def test_something_that_is_not_a_code_is_refused(client: TestClient) -> None:
    assert client.get("/admin/households", params={"code": "bonjour"}).status_code == 422


def test_live_and_cut_off_identities_are_kept_apart(client: TestClient, db: Session) -> None:
    household_id = _household(db)
    db.add(HouseholdAccess(auth_subject="google:9", household_id=household_id))
    db.commit()
    client.post("/admin/households/access/google:9/revoke")

    row = client.get("/admin/households").json()["households"][0]

    assert row["subjects"] == [SUBJECT]
    assert row["revoked"] == ["google:9"]


# -- Acting ------------------------------------------------------------------


def test_a_ceiling_is_set_and_read_back(client: TestClient, db: Session) -> None:
    household_id = _household(db)

    response = client.put(f"/admin/households/{household_id}/limit", json={"limit": 5000})

    assert response.status_code == 204
    assert client.get("/admin/households").json()["households"][0]["limit_override"] == 5000


def test_zero_is_a_ceiling_and_not_a_clear(client: TestClient, db: Session) -> None:
    """The softest useful sanction, and the one that would be lost if null and
    zero were conflated: generation stops, the weeks already produced stay
    readable, and nobody is cut off."""
    household_id = _household(db)

    client.put(f"/admin/households/{household_id}/limit", json={"limit": 0})

    assert client.get("/admin/households").json()["households"][0]["limit_override"] == 0


def test_omitting_the_ceiling_returns_the_household_to_the_rate_card(
    client: TestClient, db: Session
) -> None:
    household_id = _household(db)
    client.put(f"/admin/households/{household_id}/limit", json={"limit": 0})

    client.put(f"/admin/households/{household_id}/limit", json={"limit": None})

    assert client.get("/admin/households").json()["households"][0]["limit_override"] is None


def test_a_negative_ceiling_never_reaches_the_action(client: TestClient, db: Session) -> None:
    household_id = _household(db)

    response = client.put(f"/admin/households/{household_id}/limit", json={"limit": -1})

    assert response.status_code == 422


def test_a_ceiling_on_a_household_that_does_not_exist_is_named(client: TestClient) -> None:
    response = client.put(f"/admin/households/{uuid.uuid4()}/limit", json={"limit": 10})

    assert response.status_code == 404


def test_cutting_an_access_off_keeps_the_row(client: TestClient, db: Session) -> None:
    """The whole mechanism, and the one a cleanup could undo: `callback`
    provisions a household exactly when it finds no access row, so a delete
    would hand the identity that was just cut off a brand-new one."""
    _household(db)

    assert client.post(f"/admin/households/access/{SUBJECT}/revoke").status_code == 204

    row = db.get(HouseholdAccess, SUBJECT)
    assert row is not None and row.revoked_at is not None


def test_restoring_puts_the_identity_back_on_its_own_household(
    client: TestClient, db: Session
) -> None:
    household_id = _household(db)
    client.post(f"/admin/households/access/{SUBJECT}/revoke")

    client.post(f"/admin/households/access/{SUBJECT}/restore")

    row = db.get(HouseholdAccess, SUBJECT)
    assert row is not None and row.revoked_at is None
    assert row.household_id == household_id


def test_an_identity_nobody_knows_is_a_404_not_a_silent_success(client: TestClient) -> None:
    assert client.post("/admin/households/access/google:nobody/revoke").status_code == 404
    assert client.post("/admin/households/access/google:nobody/restore").status_code == 404
