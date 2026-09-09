"""No route under `/admin` may be reachable without being an operator.

Checked mechanically, over every route the application actually registers,
because this is the failure that does not announce itself. A back office is new
surface reachable from the internet; the route left unguarded is never the one
being looked at, and it stays open until someone finds it.

The same shape as `test_catalog_boundaries.py`: a rule the build enforces, so
the day somebody adds an endpoint and forgets, the suite says so rather than
production.

`current_operator` is asked for INSTEAD of `CurrentHousehold`, never in
addition — the reasoning `enforce_quota` already records: two dependencies are
two chances to wire one and forget the other, and the one forgotten is always
the check.
"""

from __future__ import annotations

from fastapi.dependencies.utils import get_dependant

from app.auth.deps import current_household_id, current_operator, current_owner
from app.main import app

#: Everything the gate is expected to protect.
ADMIN_PREFIX = "/admin"


def _admin_routes() -> list[object]:
    return [
        route
        for route in app.routes
        if getattr(route, "path", "").startswith(ADMIN_PREFIX)
    ]


def _dependencies(route: object) -> set[object]:
    """Every callable the route resolves, however deeply nested."""
    dependant = get_dependant(path=route.path, call=route.endpoint)  # type: ignore[attr-defined]
    found: set[object] = set()

    def walk(node: object) -> None:
        for sub in node.dependencies:  # type: ignore[attr-defined]
            if sub.call is not None:
                found.add(sub.call)
            walk(sub)

    walk(dependant)
    return found


def test_there_are_admin_routes_to_check() -> None:
    # Guards the guard: a rename of the prefix would otherwise make every
    # assertion below vacuously true.
    assert _admin_routes()


def test_every_admin_route_goes_through_the_operator_gate() -> None:
    unguarded = [
        route.path  # type: ignore[attr-defined]
        for route in _admin_routes()
        if current_operator not in _dependencies(route)
    ]

    assert unguarded == [], f"reachable without being an operator: {unguarded}"


def test_no_admin_route_asks_for_a_household() -> None:
    """Operating the instance is not a property of owning a household.

    A route asking for both would also refuse an operator who never generated a
    week — and would suggest the two rights are related, which is the confusion
    the separate table exists to prevent.
    """
    coupled = [
        route.path  # type: ignore[attr-defined]
        for route in _admin_routes()
        if current_household_id in _dependencies(route)
    ]

    assert coupled == []


def test_the_owner_gate_includes_the_operator_gate() -> None:
    # `current_owner` depends on `current_operator`, so a route asking only for
    # an owner is still gated. Stated here because the test above relies on it.
    assert current_operator in _dependencies_of(current_owner)


def _dependencies_of(call: object) -> set[object]:
    dependant = get_dependant(path="/", call=call)  # type: ignore[arg-type]
    found: set[object] = set()

    def walk(node: object) -> None:
        for sub in node.dependencies:  # type: ignore[attr-defined]
            if sub.call is not None:
                found.add(sub.call)
            walk(sub)

    walk(dependant)
    return found


#: Routes that change WHO MAY OPERATE. Not "every write": retagging a recipe is
#: a write, and it is the exact work the back office exists to delegate.
PRIVILEGE_PREFIX = "/admin/operators"


def test_changing_who_may_operate_requires_an_owner() -> None:
    """The one asymmetry the two levels encode.

    A contributor who could grant could make themselves an owner, or remove the
    person who invited them. Reading the list stays open to any operator:
    someone changing the catalogue should see who else can.
    """
    for route in _admin_routes():
        if not route.path.startswith(PRIVILEGE_PREFIX):  # type: ignore[attr-defined]
            continue
        if getattr(route, "methods", set()) & {"POST", "PUT", "PATCH", "DELETE"}:
            assert current_owner in _dependencies(route), route.path  # type: ignore[attr-defined]


def test_catalogue_work_does_not_require_an_owner() -> None:
    """Otherwise the two levels buy nothing.

    The whole point of a contributor is that they can retag without being
    handed the keys; a queue only an owner can work is a queue with one worker.
    """
    catalogue = [
        route
        for route in _admin_routes()
        if not route.path.startswith(PRIVILEGE_PREFIX)  # type: ignore[attr-defined]
    ]
    assert catalogue, "no catalogue route to check"
    for route in catalogue:
        assert current_owner not in _dependencies(route), route.path  # type: ignore[attr-defined]
