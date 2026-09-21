# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_load_tests_target_real_routes.py
=================================================
Regression test for finding S-11: the load tests measured 404s.

`k6/load_tests.js` and `locust/load_tests.py` exercised endpoints that are not
registered anywhere:

    GET /api/market-data/<symbol>   both    — OHLCV is /api/trading/ohlcv/<symbol>
    GET /api/risk/status            both    — the metrics snapshot is /api/trading/risk
    GET /api/risk/metrics           locust  — found by this test once it existed

The /api/risk prefix belongs to ``api/prop_firm.py`` and
``api/risk_calculator.py``; neither declares ``status`` or ``metrics``.

Both scenarios listed ``404`` among their acceptable statuses, so nothing
failed. They simply reported comfortable latency for routes that do no work —
which is worse than not testing them, because the numbers look like coverage.
`tests/unit/test_k6_load_tests.py` checked that the paths appear *in the script*
and could not catch this.

This test closes the gap the other one leaves: every `/api/...` path either
script requests must correspond to a route the application actually registers.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_K6 = _REPO_ROOT / "k6" / "load_tests.js"
_LOCUST = _REPO_ROOT / "locust" / "load_tests.py"

_PREFIX_RE = re.compile(r'APIRouter\(\s*prefix="([^"]+)"')
_ROUTE_RE = re.compile(r'@router\.(?:get|post|put|patch|delete)\(\s*\n?\s*"([^"]*)"')

# Paths the scripts hit that are not FastAPI routes: /metrics is the Prometheus
# scrape endpoint mounted by the instrumentator, not a @router declaration.
_NOT_ROUTER_DECLARED = {"/metrics"}


def _registered_paths() -> set[str]:
    paths: set[str] = set()
    for source_file in _REPO_ROOT.rglob("*.py"):
        text = str(source_file)
        if "/.venv/" in text or "node_modules" in text or "/tests/" in text:
            continue
        try:
            source = source_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "@router." not in source:
            continue
        prefix_match = _PREFIX_RE.search(source)
        prefix = prefix_match.group(1) if prefix_match else ""
        for path in _ROUTE_RE.findall(source):
            paths.add(_normalise(prefix + path))
    return paths


def _normalise(path: str) -> str:
    """Drop the query string and collapse path parameters."""
    path = path.split("?", 1)[0]
    path = re.sub(r"\{[^}]*\}", "{}", path)
    return path.rstrip("/") or "/"


def _requested_paths(source: str) -> set[str]:
    """Every literal /api/... path a load script requests.

    Both scripts build URLs by concatenating a literal with a symbol variable,
    e.g. ``'/api/trading/ohlcv/' + symbol`` or an f-string. The literal prefix
    is what identifies the route; the interpolated tail is the path parameter,
    so it normalises to the same ``{}`` the route declaration does.
    """
    found: set[str] = set()
    for literal in re.findall(r"""["'`](/api/[^"'`]*)["'`]""", source):
        # Locust's `name="/api/trading/ohlcv/[symbol]"` is a *display label* for
        # its statistics table, not a URL. Bracketed segments mark those.
        if "[" in literal:
            continue
        # A literal ending in "/" is the prefix half of a concatenation
        # (`'/api/x/' + symbol`); the loop below records it with its parameter.
        if literal.endswith("/"):
            continue
        found.add(_normalise(re.sub(r"\{[^}]*\}", "{}", literal)))
    # concatenation form: '/api/x/' + symbol   →  /api/x/{}
    for literal in re.findall(r"""["'](/api/[^"']*/)["']\s*\+""", source):
        found.add(_normalise(literal + "{}"))
    return found


@pytest.mark.unit
class TestLoadScriptsHitRealEndpoints:
    def test_route_extraction_works(self):
        registered = _registered_paths()
        assert "/api/trading/order" in registered, "route extraction is broken"
        assert "/api/trading/risk" in registered

    def test_the_two_dead_paths_are_gone(self):
        for script in (_K6, _LOCUST):
            source = script.read_text(encoding="utf-8")
            for line in source.splitlines():
                if "/api/market-data/" in line or "/api/risk/status" in line:
                    assert line.lstrip().startswith(("//", "#")), (
                        f"{script.name} still requests a dead path:\n  {line.strip()}\n"
                        "Only the explanatory comments may mention them (S-11)."
                    )

    @pytest.mark.parametrize("script", [_K6, _LOCUST], ids=["k6", "locust"])
    def test_every_requested_api_path_is_registered(self, script):
        registered = _registered_paths()
        requested = _requested_paths(script.read_text(encoding="utf-8"))
        assert requested, f"parsed no /api paths out of {script.name}"

        missing = sorted(path for path in requested if path not in registered and path not in _NOT_ROUTER_DECLARED)

        assert not missing, (
            f"{script.name} load-tests endpoints that do not exist: {missing}. "
            "A 404 in an accepted-status list makes the scenario report latency "
            "for a route that does no work (S-11)."
        )
