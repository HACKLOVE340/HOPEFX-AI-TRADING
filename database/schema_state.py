# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""Whether the database schema really is what the migrations build.

Startup (``core/startup_factories.py::init_database``) used to answer a failed
``alembic upgrade head`` by stamping the database at head and running
``create_all()``. A PostgreSQL database treated that way reports head having
run no migration, so every later upgrade is a no-op and the damage is permanent.
The owner decided on 2026-09-25 that startup refuses instead. This module holds
the three pieces that decision needs:

* :func:`create_all_is_schema_source` -- the only environments in which
  ``create_all()`` may stand in for the migrations (local development and
  tests), decided by ``utils.production_guard.current_env``, which reads an
  UNSET ``APP_ENV`` as production;
* :func:`missing_head_objects` -- head by content, not by the version table: on
  PostgreSQL, the objects the head migration creates must exist;
* :class:`SchemaRefused` -- what startup raises. It is a ``SystemExit`` on
  purpose: ``ComponentRegistry.start_all`` and ``app.startup_event`` catch
  ``Exception``, and an ``Exception`` there leaves the API serving with
  ``initialized=False``. ``app._on_startup_task_done`` turns anything else into
  ``os._exit``, so the pod is reported failed instead of healthy.

Recovery for a database the old behaviour already stamped is
``docs/runbooks/database-restore.md`` §6a.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

RUNBOOK = "docs/runbooks/database-restore.md §6a"

#: Environments where ``create_all()`` may be the schema source. The same set
#: payments/crypto/address_generator.py uses for a throwaway wallet: anything
#: else -- staging, a typo, an unset APP_ENV -- is treated as production.
CREATE_ALL_ENVS = frozenset({"development", "dev", "test", "testing", "local"})

#: The migration that creates the crypto HD-index sequences, and those
#: sequences. A copy of payments/crypto/address_generator.py::_SEQUENCE's
#: values and of d9e0f1a2b3c4's SEQUENCES; tests hold the three equal.
HD_INDEX_REVISION = "d9e0f1a2b3c4"  # pragma: allowlist secret
HD_INDEX_SEQUENCES: tuple[str, ...] = (
    "crypto_hd_index_btc",
    "crypto_hd_index_eth",
    "crypto_hd_index_trc20",
)


def create_all_is_schema_source() -> bool:
    """True only where APP_ENV says explicitly this is local development or a test."""
    from utils.production_guard import current_env

    return current_env().strip() in CREATE_ALL_ENVS


def create_all_for_local_use(metadata: Any, engine: Any, *, caller: str) -> bool:
    """``metadata.create_all()`` where it may be the schema source; elsewhere nothing.

    For operator tools (create_admin, create_superadmin, ``cli.py``) that used to
    run ``create_all()`` on whatever ``DATABASE_URL`` named. On an empty
    production database that made ``create_all()`` the schema source. Outside
    development/test this builds nothing and says so: a tool run against a
    database the migrations have not built then fails on its first query,
    which is the truthful outcome. Returns whether it built anything.
    """
    import logging

    from utils.production_guard import current_env

    if not create_all_is_schema_source():
        logging.getLogger(__name__).info(
            "%s: APP_ENV=%s — not running create_all(); the schema comes from `alembic upgrade head` (%s).",
            caller,
            current_env(),
            RUNBOOK,
        )
        return False
    metadata.create_all(engine, checkfirst=True)
    return True


@dataclass(frozen=True)
class SchemaState:
    """What startup established about the schema, for ``/ready`` and ``/health``.

    ``verified`` is True only when the version table is at head AND, where
    there is content to check, the head migration's objects exist.
    """

    verified: bool
    current: str | None
    head: str | None
    source: str
    detail: str = ""


class SchemaRefused(SystemExit):
    """Startup refuses to serve on this schema. Exits the process non-zero."""

    def __init__(self, message: str) -> None:
        super().__init__(1)
        self.message = message

    def __str__(self) -> str:
        return self.message


def missing_head_objects(conn: Any, script: Any, current_rev: str | None) -> list[str]:
    """Objects the migrations up to *current_rev* create that this database lacks.

    Only PostgreSQL is checked: the HD-index sequences are created there alone
    (SQLite keeps the file counter). ``to_regclass`` resolves a name the way
    ``nextval()`` in address issuing does, through the search path.
    """
    if conn.dialect.name != "postgresql" or not current_rev:
        return []
    applied = {rev.revision for rev in script.iterate_revisions(current_rev, "base")}
    if HD_INDEX_REVISION not in applied:
        return []
    from sqlalchemy import text

    missing = []
    for name in HD_INDEX_SEQUENCES:
        found = conn.execute(
            text("SELECT c.relkind FROM pg_class c WHERE c.oid = to_regclass(:n)"),
            {"n": name},
        ).scalar()
        if found != "S":
            missing.append(name)
    return missing
