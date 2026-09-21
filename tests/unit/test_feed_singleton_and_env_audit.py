# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_feed_singleton_and_env_audit.py
===============================================
Two more "the report is wrong, not the system".

**"Data feed singleton has not been initialised" on a running feed.**

``core/startup_factories.py`` constructed ``MultiSourceTickFeed(...)`` directly.
``get_feed_status()`` reads the module-level ``_feed_instance``, which only
``get_multi_source_feed()`` ever sets — so the singleton stayed ``None`` and
every consumer of that accessor reported::

    data_feeds_module  WARNING
    Data feed singleton has not been initialised

on a deployment whose feed was constructed, started and polling. The writer and
the reader were looking at different objects. That is the third instance of this
exact shape in one session — after ``ml:model:status`` (written through the
async Redis client, read through the sync one) and the audit trail (written with
one set of field names, read with another).

**"MISSING" in red for variables that are optional.**

The Environment Variable Audit rendered ``SECRET_KEY`` and ``DB_MAX_OVERFLOW``
as ``✗ MISSING`` in red on a healthy deployment. Neither is a fault:
``DB_MAX_OVERFLOW`` defaults to 20 in ``database/async_connection.py``, and
``SECRET_KEY`` is read only by ``security_service.py``, which **nothing in the
codebase imports** — its sole reference is inside its own docstring.

The audit now reports what actually happens when a variable is absent, and the
page shows required-and-missing differently from optional-and-unset.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


# ── The feed singleton ───────────────────────────────────────────────────────


def test_startup_constructs_the_feed_through_the_factory():
    """Constructing the class directly leaves the module singleton unset, and
    the singleton is what every status accessor reads."""
    import inspect

    import core.startup_factories as sf
    from tests.support.source_text import code_only

    src = code_only(sf)
    assert "get_multi_source_feed(symbols=symbols)" in src, (
        "the feed is constructed directly again — get_feed_status() will report it as uninitialised"
    )
    assert "feed = MultiSourceTickFeed(symbols=symbols)" not in src

    del inspect  # only imported to make the intent obvious above


def test_the_factory_sets_the_singleton_the_status_reads(tmp_path):
    """Pins the coupling: if get_multi_source_feed stops assigning
    _feed_instance, the fix above stops working silently."""
    import yaml

    import data_feed.multi_source_feed as msf

    cfg = tmp_path / "feed.yaml"
    cfg.write_text(yaml.safe_dump({"multi_source_feed": {"symbols": {"XAUUSD": {"yfinance_ticker": "GC=F"}}}}))

    original = msf._feed_instance
    try:
        msf._feed_instance = None
        assert msf.get_feed_status()["running"] is False
        assert "not been initialised" in msf.get_feed_status()["message"]

        msf.get_multi_source_feed(config_path=cfg)
        status = msf.get_feed_status()
        assert "message" not in status or "not been initialised" not in status.get("message", "")
    finally:
        msf._feed_instance = original


def test_an_uninitialised_feed_still_reports_honestly(tmp_path):
    """The warning itself is correct and must stay — the defect was that it
    fired on a feed that WAS initialised."""
    import data_feed.multi_source_feed as msf

    original = msf._feed_instance
    try:
        msf._feed_instance = None
        status = msf.get_feed_status()
        assert status["running"] is False
        assert status["healthy"] is False
    finally:
        msf._feed_instance = original


# ── The env audit ────────────────────────────────────────────────────────────


async def _audit() -> dict:
    from api.superadmin.reliability import get_env_audit

    return await get_env_audit(user=None)


async def test_a_required_variable_that_is_missing_is_an_error(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    groups = (await _audit())["groups"]
    entry = groups["database"]["DATABASE_URL"]
    assert entry["required"] is True
    assert entry["severity"] == "error"
    assert "cannot run" in entry["effect"]


async def test_an_optional_variable_with_a_default_is_not_an_error(monkeypatch):
    """DB_MAX_OVERFLOW defaults to 20. Rendering it as a red MISSING says the
    deployment is broken when it is not."""
    monkeypatch.delenv("DB_MAX_OVERFLOW", raising=False)
    entry = (await _audit())["groups"]["database"]["DB_MAX_OVERFLOW"]
    assert entry["required"] is False
    assert entry["severity"] == "info"
    assert "defaults to 20" in entry["effect"]


async def test_a_variable_nothing_reads_says_so(monkeypatch):
    """SECRET_KEY is read only by security_service.py, whose only reference in
    the whole codebase is inside its own docstring."""
    monkeypatch.delenv("SECRET_KEY", raising=False)
    entry = (await _audit())["groups"]["auth"]["SECRET_KEY"]
    assert entry["severity"] == "info"
    assert "no effect" in entry["effect"]


async def test_security_service_is_still_unimported():
    """Pins the claim above. If something starts importing it, SECRET_KEY stops
    being inert and the audit entry must change with it."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[2]
    pattern = re.compile(r"^\s*(from security_service import|import security_service)", re.M)
    importers = [
        p
        for p in root.rglob("*.py")
        if p.name != "security_service.py"
        and "test" not in p.parts
        and ".venv" not in p.parts
        and pattern.search(p.read_text(encoding="utf-8", errors="ignore"))
    ]
    assert importers == [], (
        f"security_service is now imported by {[str(p) for p in importers]} — SECRET_KEY is no longer inert"
    )


async def test_a_set_variable_is_ok(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    entry = (await _audit())["groups"]["redis"]["REDIS_URL"]
    assert entry["set"] is True
    assert entry["severity"] == "ok"


async def test_every_entry_explains_itself():
    """The point of the change: an operator should not need the source to tell
    a fault from a default."""
    groups = (await _audit())["groups"]
    for group, entries in groups.items():
        for key, entry in entries.items():
            assert entry.get("effect"), f"{group}.{key} has no effect description"
            assert entry.get("severity") in ("ok", "info", "error"), f"{group}.{key}: {entry.get('severity')}"


def test_the_page_shows_optional_and_required_differently():
    """A neutral background with a red '✗ MISSING' label still reads as broken."""
    import pathlib

    from tests.support.source_text import code_only

    root = pathlib.Path(__file__).resolve().parents[2]
    src = code_only(root / "frontend/src/pages/superadmin/SystemReliabilitySection.tsx")

    assert "info.required ? '✗ MISSING' : '— not set'" in src or "'— not set'" in src, (
        "optional variables still render as MISSING"
    )
    assert "color: info.set ? '#22c55e' : '#ef4444'" not in src, "the label is red regardless of severity again"
