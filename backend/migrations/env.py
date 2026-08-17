from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import get_settings
from app.db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The URL comes from the environment, never from alembic.ini (invariant I8).
#
# `%` is doubled because Alembic keeps its options in a ConfigParser, which runs
# ITS OWN `%(name)s` interpolation over every value it is handed. A URL-encoded
# password — `%21`, `%25` — is then read as broken interpolation syntax and
# raises before the first migration. Two escaping schemes meeting on the same
# string, and the fix is to speak the second one where it applies.
config.set_main_option("sqlalchemy.url", get_settings().sqlalchemy_url.replace("%", "%%"))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
