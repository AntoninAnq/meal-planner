"""The ORM mapping configures cleanly.

SQLAlchemy resolves relationships lazily, on first use. A relationship declared
on one side only therefore stays invisible until some code path happens to touch
it — which, for a `back_populates` typo, means the first real request rather than
the test suite.

`configure_mappers()` forces the resolution. It needs no database and runs in
milliseconds, and it is the cheapest guard there is against a whole class of
mistakes that would otherwise surface in production.
"""

from sqlalchemy.orm import configure_mappers

import app.db.models  # noqa: F401  (registers every mapper)


def test_every_relationship_resolves() -> None:
    configure_mappers()


def test_constraints_relationship_is_bidirectional() -> None:
    """A household-wide aversion has no member, so the link must be optional."""
    from app.db.models import DietaryConstraint, Member

    configure_mappers()

    assert "member" in DietaryConstraint.__mapper__.relationships
    assert "constraints" in Member.__mapper__.relationships
    assert DietaryConstraint.__mapper__.columns["member_id"].nullable is True
