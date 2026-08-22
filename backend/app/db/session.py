"""Database session wiring."""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """`pool_pre_ping` is not optional against a hosted database.

    A managed Postgres, and anything between it and here, closes idle
    connections on its own schedule. Without the ping, the first request after
    a quiet stretch is served a dead connection and answers 500 — the failure
    that looks random and is not.

    `prepare_threshold=None` disables psycopg's server-side prepared statements,
    and only when the deployment says it is behind a transaction-mode pooler.
    See `Settings.database_pooled`: it is a correctness setting, not a
    performance one.
    """
    settings = get_settings()
    return create_engine(
        settings.sqlalchemy_url,
        pool_pre_ping=True,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        connect_args={"prepare_threshold": None} if settings.database_pooled else {},
        future=True,
    )


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    with get_session_factory()() as session:
        yield session
