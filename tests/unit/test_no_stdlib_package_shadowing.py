# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_no_stdlib_package_shadowing.py
==============================================
Round 3 audit, Slice 13 (docs/HARDENING_BACKLOG.md S13-01).

A top-level package in the repo root shadows any third-party distribution of
the same name, because the repo root is on ``sys.path`` ahead of site-packages.

This is not a style complaint. The repo shipped a dead ``websocket/`` package
(a standalone server superseded by ``api/ws_live.py``), which shadowed the
``websocket-client`` library that ``market_data/mt5_live_feed.py`` imports.
The consequence was worse than a missing import:

    try:
        import websocket           # ← got the local dead package
        WEBSOCKET_AVAILABLE = True # ← so this was True even with the real
    except ImportError:            #   library absent
        WEBSOCKET_AVAILABLE = False

`WEBSOCKET_AVAILABLE` gated the REST fallback. With the shadow in place the
guard could never fire, so instead of degrading to REST the feed reached
``websocket.WebSocketApp(...)`` and died on ``AttributeError``. The fallback
existed and was unreachable.

These tests fail if a shadowing package is ever reintroduced.
"""

from __future__ import annotations

import importlib
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

#: Distributions this codebase imports that a same-named local package would
#: silently replace.
SHADOWABLE_DISTRIBUTIONS = ("websocket", "src", "backtest")


@pytest.mark.parametrize("name", SHADOWABLE_DISTRIBUTIONS)
def test_repo_root_has_no_shadowing_package(name: str) -> None:
    """No repo-root package may share a name with an installed distribution."""
    if name == "backtest":
        # `backtest/` is a deliberate re-export shim for `backtesting/` and
        # collides with nothing on PyPI that this project depends on.
        pytest.skip("backtest/ is an intentional in-repo shim, not a shadow")
    pkg = REPO_ROOT / name
    assert not (pkg / "__init__.py").exists(), (
        f"{name}/ at the repo root shadows the '{name}' distribution for every "
        f"import in this project — see the module docstring for how this made "
        f"an ImportError fallback unreachable"
    )


def test_websocket_import_is_the_real_client_or_absent() -> None:
    """`import websocket` must yield websocket-client, or fail cleanly.

    The failure mode this pins is the *middle* state: an importable module
    named `websocket` that is not the client library. That state makes every
    `except ImportError` fallback around it dead code.
    """
    try:
        mod = importlib.import_module("websocket")
    except ImportError:
        return  # library genuinely not installed — the guard works

    assert hasattr(mod, "WebSocketApp"), (
        f"`import websocket` resolved to {getattr(mod, '__file__', '?')}, which is "
        f"not websocket-client. Any `except ImportError` fallback guarding it is "
        f"now unreachable, and callers will fail on AttributeError instead."
    )


def test_mt5_live_feed_availability_flag_is_truthful() -> None:
    """WEBSOCKET_AVAILABLE must mean the API the module actually calls exists."""
    feed = pytest.importorskip("market_data.mt5_live_feed")

    if not feed.WEBSOCKET_AVAILABLE:
        return  # correctly reported absent; REST fallback is live

    import websocket

    assert hasattr(websocket, "WebSocketApp"), (
        "mt5_live_feed reports WEBSOCKET_AVAILABLE=True but websocket.WebSocketApp "
        "does not exist, so _connect() raises AttributeError instead of falling "
        "back to REST"
    )
