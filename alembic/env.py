"""Alembic environment.

The database URL comes from application settings, never from `alembic.ini`, so
local development and production run the identical migration path.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from src.core.config import get_settings
from src.db.models import Base  # noqa: F401 — imported for metadata registration

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    """Choose which database this migration run targets.

    `alembic -x target=liara upgrade head` points the identical migration path at
    the managed Liara database from an operator machine, using the external
    connection URL. Without the flag the run targets `DATABASE_URL` — the local
    compose database in development, and the private-network address inside a
    deployed container. Selecting the target explicitly is deliberate: an
    implicit fallback to production is exactly the accident worth preventing.
    """
    settings = get_settings()
    target = context.get_x_argument(as_dictionary=True).get("target", "default")
    if target == "default":
        return settings.database_url
    if target == "liara":
        if not settings.liara_database_url:
            raise RuntimeError(
                "alembic -x target=liara needs LIARA_DATABASE_URL set to the "
                "external connection URL from the Liara panel"
            )
        return settings.liara_database_url
    raise RuntimeError(f"unknown alembic target {target!r}; expected 'default' or 'liara'")


config.set_main_option("sqlalchemy.url", _database_url())


def _include_object(obj, name, type_, reflected, compare_to) -> bool:  # type: ignore[no-untyped-def]
    # pgvector installs its own tables/types; they are not ours to migrate.
    return not (type_ == "table" and name in {"alembic_version"} and reflected)


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
