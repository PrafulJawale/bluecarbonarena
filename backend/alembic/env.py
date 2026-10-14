"""Alembic environment for BLUECARBON ARENA.

Resolves the database URL in this order:
1. ALEMBIC_DATABASE_URL / DATABASE_URL environment variable (set in .env or shell)
2. alembic.ini sqlalchemy.url (development default: local SQLite)

Production uses PostgreSQL (+ optionally PostGIS). See docs/DATABASE_SCHEMA.md
for the documented SQLite-vs-PostGIS capabilities gap.
"""
from logging.config import fileConfig
import os, sys, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from sqlalchemy import engine_from_config, pool
from alembic import context
from app.db import Base
from app import models  # noqa: F401  (register all tables on Base.metadata)

config = context.config

url = os.environ.get("ALEMBIC_DATABASE_URL") or os.environ.get("DATABASE_URL")
if url:
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"),
                      target_metadata=target_metadata, literal_binds=True,
                      dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}),
                                     prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
