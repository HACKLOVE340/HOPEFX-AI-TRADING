# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""`create_admin.py` / `create_superadmin.py` must not invent a default
environment that the rest of the platform does not have.

`utils/production_guard.py::current_env` treats an unset `APP_ENV` as
**production** -- deliberately fail-safe, because the alternative silently
grants dev-only behaviour to a process that forgot to configure itself.
Both admin-seed scripts instead ran::

    os.environ.setdefault("APP_ENV", "development")

before importing anything else. That does not just make the SCRIPT think it
is in development -- it MUTATES the process environment, so every downstream
consumer of `current_env()` sees "development" too. The one that matters is
`database.schema_state.create_all_for_local_use`, which both scripts call: it
runs `metadata.create_all()` (the dev/test schema path) only when
`current_env()` says development or test. An operator who runs either script
against a real deployment without first exporting `APP_ENV` -- exactly the
"forgot to configure itself" case fail-safe defaults exist for -- got
`create_all()` run against it instead of being refused, which is the opposite
of every other unset-`APP_ENV` codepath in this platform.

Each script is imported fresh (its `if __name__ == "__main__":` guard keeps
`main()` from running) with `APP_ENV` deleted from the environment, mirroring
how the platform-wide convention is proven elsewhere.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]


def _import_fresh(script_path: Path):
    """Execute a script's module-level code in isolation, main() guarded off."""
    mod_name = f"_probe_{script_path.stem}_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(mod_name, script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(mod_name, None)
    return module


@pytest.mark.parametrize(
    "script_name",
    ["create_admin.py", "create_superadmin.py"],
)
def test_an_unset_app_env_is_not_forced_to_development(script_name, monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    # Both scripts default DATABASE_URL to sqlite if unset -- keep that so
    # import does not require a real database configured.
    monkeypatch.delenv("DATABASE_URL", raising=False)

    _import_fresh(REPO_ROOT / "scripts" / script_name)

    from utils.production_guard import current_env

    assert current_env() == "production", (
        f"{script_name} left an unset APP_ENV reading as {current_env()!r} instead of the "
        "platform-wide fail-safe default 'production' — it is overriding os.environ"
    )
    assert os.environ.get("APP_ENV") != "development", (
        f"{script_name} wrote APP_ENV=development into the process environment for an operator who never set it"
    )


@pytest.mark.parametrize(
    "script_name",
    ["create_admin.py", "create_superadmin.py"],
)
def test_an_explicit_app_env_is_respected(script_name, monkeypatch):
    """The fix must not stop an operator from explicitly asking for development."""
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    _import_fresh(REPO_ROOT / "scripts" / script_name)

    from utils.production_guard import current_env

    assert current_env() == "development"
