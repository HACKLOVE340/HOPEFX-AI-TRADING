# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""Alembic migration environment.

Imports all SQLAlchemy models so autogenerate can detect schema changes.
DATABASE_URL env var overrides the ini file URL.
"""

import logging
import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# Make project root importable
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Import all models so their metadata is registered on Base
from database.models import Base

logger = logging.getLogger(__name__)

try:
    # Import user models so their metadata is registered on Base for autogenerate
    import database.user_models as _user_models

    _ = _user_models  # ensure the module is loaded
except Exception as _exc:
    logger.debug("Suppressed exception: %s", _exc)

config = context.config

# Allow DATABASE_URL env var to override alembic.ini.
# Normalise async/cloud driver prefixes so Alembic uses a sync engine:
#   sqlite+aiosqlite:///       → sqlite:///
#   postgresql+asyncpg://      → postgresql://
#   postgres://                → postgresql://   (Heroku / Railway style)
db_url = os.getenv("DATABASE_URL")
if db_url:
    db_url = (
        db_url
        .replace("sqlite+aiosqlite:///", "sqlite:///")
        .replace("postgresql+asyncpg://", "postgresql://")
        .replace("postgresql+aiopg://", "postgresql://")
        # Heroku/Railway use "postgres://" which SQLAlchemy 1.4+ rejects
        .replace("postgres://", "postgresql://", 1)
    )
    config.set_main_option("sqlalchemy.url", db_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
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
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
