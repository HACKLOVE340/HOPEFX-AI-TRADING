# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
The test suite must not read whoever's `.env` happens to be on the box.

F241 recorded that the suite read the developer's `.env`, and the fix
neutralised `dotenv.load_dotenv` for the whole session in the root
`conftest.py`. That closed one reader. **pydantic-settings has its own**:

    config/settings.py:377
        model_config = SettingsConfigDict(
            env_file=".env",
            ...

`DotEnvSettingsSource` opens `.env` directly and never goes through
`load_dotenv`, so the neutralisation did not reach it.

Proven, not inferred. The repository's own `.env` carries a bare

    BROKER=

at line 1891, and `Settings.broker` is a nested model, so pydantic tries to
JSON-parse the empty string:

    SettingsError: error parsing value for field "broker" from source
                   "DotEnvSettingsSource"
    json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)

while `Settings(_env_file=None)` constructs cleanly.

Two tests (`test_core.py::test_settings_validation` and `::test_settings_production`)
therefore pass or fail according to a gitignored file. That is why they were
green in every fresh-worktree verification — a worktree has no `.env` — and red
under the CI environment. A suite whose result depends on an untracked file is
not measuring the code.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_settings_construct_regardless_of_the_local_env_file(monkeypatch):
    """The requirement, stated directly.

    `BROKER` is cleared first, and that is not a workaround — it is the scope of
    this test. The claim here is that the *file* cannot break Settings. A real
    `BROKER` env var breaking it is a separate defect with its own test below;
    an earlier version of this test asserted both at once and failed in the full
    suite whenever another test had set `BROKER=paper`, which several do
    legitimately.
    """
    monkeypatch.delenv("BROKER", raising=False)
    from config.settings import Settings

    settings = Settings()
    assert settings.broker is not None


def test_an_empty_broker_variable_does_not_break_settings(monkeypatch):
    """`.env` ships a bare `BROKER=`.

    Every sub-settings field on `Settings` is a nested model, so
    pydantic-settings looks for an env var of the same name — `DB`, `REDIS`,
    `BROKER`, `ML`, `RISK` — and JSON-parses whatever it finds. An empty string
    is not JSON, so shipping `BROKER=` made the entire Settings object
    unconstructable with a JSONDecodeError naming a field nobody had touched
    (F264). `env_ignore_empty` makes an unset variable mean unset.
    """
    monkeypatch.setenv("BROKER", "")
    from config.settings import Settings

    assert Settings().broker is not None


def test_a_non_json_broker_variable_still_breaks_settings(monkeypatch):
    """Recorded, not fixed — and pinned so it is not mistaken for working.

    `BROKER=paper` is a plausible value: `.env` documents the variable,
    `tests/unit/test_nuclear_supervisor.py` and `tests/e2e/` both set it, and
    `BROKER_TYPE=paper` is the canonical spelling elsewhere. Pydantic still tries
    to JSON-parse it for the nested `broker` model and raises.

    Fixing it properly means changing how `Settings` maps environment variables
    onto its sub-models — an API decision, not a bug fix, and out of scope for
    getting CI green. This test documents the boundary: if someone changes that
    mapping, this test tells them what the old behaviour was.
    """
    monkeypatch.setenv("BROKER", "paper")
    from config.settings import Settings

    with pytest.raises(Exception) as excinfo:
        Settings(_env_file=None)
    assert "broker" in str(excinfo.value).lower()


def test_the_env_file_source_is_disabled_under_test():
    """`load_dotenv` was neutralised; this is the other reader."""
    from config.settings import Settings

    assert Settings.model_config.get("env_file") is None, (
        "config.settings.Settings still reads .env during tests — the suite's result "
        "depends on a gitignored file (F241, second path)"
    )


def test_the_repository_env_file_would_have_broken_it():
    """Pins the mechanism, so the neutralisation is not quietly removed as
    unnecessary later. Skips when there is no local `.env` — a fresh worktree,
    which is exactly the environment that hid this."""
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        pytest.skip("no local .env — this is the environment that masked the defect")

    lines = env_file.read_text(encoding="utf-8", errors="replace").splitlines()
    bare_complex = [
        line
        for line in lines
        if line.strip() in {"BROKER=", "BROKER ="}  # a nested model field, empty
    ]
    if not bare_complex:
        pytest.skip("this .env no longer carries the bare BROKER= that triggered it")

    from pydantic_settings import BaseSettings, SettingsConfigDict

    from config.settings import BrokerSettings

    class _ReadsDotEnv(BaseSettings):
        model_config = SettingsConfigDict(env_file=str(env_file), env_file_encoding="utf-8", extra="ignore")
        broker: BrokerSettings = BrokerSettings()

    with pytest.raises(Exception) as excinfo:
        _ReadsDotEnv()
    assert "broker" in str(excinfo.value).lower()
