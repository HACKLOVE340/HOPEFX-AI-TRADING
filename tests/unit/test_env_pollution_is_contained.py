# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Environment changes must not escape the test that made them.

``tests/conftest.py`` has always had a ``_restore_critical_env_vars`` fixture
whose docstring says it "prevents test-ordering pollution from tests that mutate
env vars". It restored a hardcoded list of seven keys. Everything else leaked.

The concrete failure that exposed it: ``core/main_loop.py`` calls
``load_dotenv()`` inside ``MainLoop.run()``, so a test exercising the main loop
injects the *developer's* ``.env`` into ``os.environ`` for the rest of the
session. That file sets ``PAPER_RAISE_ON_STALE=true``, and every later test that
places a paper order then died on ``StalePriceError``:

    pytest tests/unit/test_trading_auth.py                       -> 36 passed
    pytest tests/unit/test_core_main_loop.py \\
           tests/unit/test_trading_auth.py                       -> 5 failed

Two things made this expensive. It only reproduces in company, so it was
invisible to anyone running one file. And ``.env`` is gitignored, so CI — which
has no such file — stayed green while local runs went red, which reads as
"something is wrong with your machine" rather than "a test leaked state".

These tests are ordered pairs: the first mutates, the second checks the mutation
did not survive. They are worth nothing if run individually, which is the point.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.unit

_SENTINEL = "HOPEFX_ENV_POLLUTION_SENTINEL"
_PRESET = "HOPEFX_ENV_PRESET_SENTINEL"


def test_a_sets_an_arbitrary_env_var_without_monkeypatch():
    """Deliberately antisocial: no monkeypatch, no cleanup — like the real code
    paths that call load_dotenv() or os.environ[...] = ... directly."""
    os.environ[_SENTINEL] = "leaked"
    assert os.environ[_SENTINEL] == "leaked"


def test_b_the_arbitrary_env_var_did_not_survive():
    """
    The general property. The old fixture restored only a named list, so any
    variable outside it — PAPER_RAISE_ON_STALE among them — leaked into every
    subsequent test.
    """
    assert _SENTINEL not in os.environ, (
        f"{_SENTINEL} survived the test that set it — environment pollution "
        "escapes into every test that runs afterwards"
    )


@pytest.fixture(scope="module", autouse=True)
def _preset():
    """A variable that exists *before* these tests run must still exist after."""
    os.environ[_PRESET] = "original"
    yield
    os.environ.pop(_PRESET, None)


def test_c_overwrites_a_preexisting_env_var():
    os.environ[_PRESET] = "changed"


def test_d_the_preexisting_value_was_restored_not_deleted():
    """Restoring must put back the prior value, not simply unset the key —
    otherwise the fixture trades one kind of pollution for another."""
    assert os.environ.get(_PRESET) == "original"


def test_e_deletes_a_preexisting_env_var():
    os.environ.pop(_PRESET, None)


def test_f_the_deleted_var_came_back():
    assert os.environ.get(_PRESET) == "original", (
        "a test that deletes an env var leaves it missing for everything after it"
    )


def test_the_paper_broker_stale_flag_specifically_is_contained():
    """The variable that actually caused the outage in the suite.

    Named explicitly because it is read once in ``PaperTradingBroker.__init__``
    from the environment, so a broker constructed after the leak refuses every
    fill for the rest of the session.
    """
    os.environ["PAPER_RAISE_ON_STALE"] = "true"


def test_the_paper_broker_stale_flag_did_not_leak():
    assert os.environ.get("PAPER_RAISE_ON_STALE") in (None, "false"), (
        "PAPER_RAISE_ON_STALE leaked; every later paper order will raise StalePriceError"
    )


# ---------------------------------------------------------------------------
# Cached brokers outlive the environment that configured them
# ---------------------------------------------------------------------------


def test_g_a_broker_built_under_a_polluted_env_is_cached():
    """
    Restoring os.environ is not enough on its own.

    ``PaperTradingBroker`` reads ``PAPER_RAISE_ON_STALE`` **once, in __init__**,
    and ``core/account_registry.py`` caches one broker per user in a
    process-wide singleton. A broker constructed while the flag was set keeps
    ``_raise_on_stale=True`` for the rest of the session, and no amount of
    environment restoration reaches an object that already captured the value.

    ``reset_account_registry()`` has existed all along, with the docstring "For
    tests and shutdown". conftest.py never called it.
    """
    import os

    from core.account_registry import get_account_registry

    os.environ["PAPER_RAISE_ON_STALE"] = "true"
    registry = get_account_registry()
    registry._brokers["pollution-probe"] = object()
    assert "pollution-probe" in registry._brokers


def test_h_the_cached_broker_did_not_survive():
    from core.account_registry import get_account_registry

    registry = get_account_registry()
    assert "pollution-probe" not in registry._brokers, (
        "a broker cached by an earlier test is still live; it carries that "
        "test's configuration, balance and positions into every later test"
    )


# ---------------------------------------------------------------------------
# The developer's .env must never reach the test session
# ---------------------------------------------------------------------------


def test_importing_the_app_does_not_load_the_developers_dotenv():
    """
    ``app.py`` calls ``load_dotenv(override=False)`` at module import. That is
    right for production — app.py is the entrypoint — and wrong for tests.

    Several test modules do ``from app import app`` at module scope, so the load
    happens during **collection**, before any test runs and therefore before any
    per-test environment snapshot exists. Every snapshot then contains the
    developer's values and nothing ever removes them: the per-test restore
    cannot undo pollution that predates it.

    The concrete damage: ``.env`` sets ``PAPER_RAISE_ON_STALE=true``, and
    ``PaperTradingBroker`` reads that once in ``__init__``. Every paper order
    placed anywhere in the session then raised ``StalePriceError`` and the
    endpoint returned 400 instead of 201.

    ``.env`` is gitignored, so CI — which has no such file — was unaffected.
    The same commit passed remotely and failed locally, which reads as a broken
    machine rather than a leaking import.
    """
    import app  # noqa: F401  — the import is the thing under test

    assert os.environ.get("PAPER_RAISE_ON_STALE") in (None, "false"), (
        "importing app loaded the developer's .env into the test session; "
        "tests now depend on a gitignored file that CI does not have"
    )


def test_dotenv_loading_is_neutralised_for_the_whole_session():
    """The guard is on ``dotenv.load_dotenv`` itself, not on one variable, so it
    also covers whatever ``.env`` gains next."""
    import dotenv

    before = dict(os.environ)
    dotenv.load_dotenv()
    dotenv.load_dotenv(override=True)
    assert dict(os.environ) == before, "load_dotenv() still mutates the test environment"
