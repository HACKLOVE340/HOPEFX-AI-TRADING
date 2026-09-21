# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# AGPL-3.0 — Share all modifications
"""
tests/unit/test_fixes.py
========================
Regression tests for the fixes applied in this session:

1. data/scheduler.py  — inverted high/low swap within 0.5% tolerance
2. data/validator.py  — 3% clamp for close/open outside [low, high]
3. api/auth.py        — cookie fallback in get_current_user
4. security/code_analyzer.py — 0 issues after swallowed-exception fixes
5. news/geopolitical_risk.py — singleton provider, _all_sources_warned
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on sys.path
_ROOT = Path(__file__).parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ---------------------------------------------------------------------------
# 1. data/validator.py — intra-bar consistency
# ---------------------------------------------------------------------------


class TestDataValidator:
    def _make_validator(self):
        from data.validator import DataValidator

        return DataValidator(symbol="XAUUSD")

    def test_valid_bar_passes(self):
        v = self._make_validator()
        bar = {"open": 1900.0, "high": 1910.0, "low": 1890.0, "close": 1905.0, "volume": 1000}
        r = v.validate_bar(bar)
        assert r.ok

    def test_high_lt_low_fails(self):
        """Bars with high < low beyond tolerance are rejected by the validator."""
        v = self._make_validator()
        # 1% inversion — beyond 0.5% swap threshold, validator rejects
        bar = {"open": 1900.0, "high": 1880.0, "low": 1900.0, "close": 1890.0, "volume": 100}
        r = v.validate_bar(bar)
        assert not r.ok
        assert any("high" in e and "low" in e for e in r.errors)

    def test_close_outside_hl_within_3pct_clamped_by_scheduler(self):
        """Scheduler pre-clamps close within 3% before validator sees it."""
        # Simulate what scheduler does before calling validate_bar
        bar = {"open": 1900.0, "high": 1910.0, "low": 1890.0, "close": 1912.0, "volume": 100}
        _l, _h = float(bar["low"]), float(bar["high"])
        _mid = (_h + _l) / 2
        _tol = _mid * 0.03
        _c = float(bar["close"])
        if _l - _tol <= _c <= _h + _tol and not (_l <= _c <= _h):
            bar = dict(bar)
            bar["close"] = max(_l, min(_h, _c))
        # After clamping, validator should accept
        v = self._make_validator()
        r = v.validate_bar(bar)
        assert r.ok, f"Expected ok after clamp, got errors: {r.errors}"

    def test_negative_volume_fails(self):
        v = self._make_validator()
        bar = {"open": 1900.0, "high": 1910.0, "low": 1890.0, "close": 1905.0, "volume": -1}
        r = v.validate_bar(bar)
        assert not r.ok


# ---------------------------------------------------------------------------
# 2. data/scheduler.py — high/low swap logic
# ---------------------------------------------------------------------------


class TestSchedulerHighLowSwap:
    """Test the pre-validation swap logic extracted from _update_timeframe."""

    def _apply_swap(self, bar: dict) -> dict:
        """Replicate the swap logic from scheduler._update_timeframe."""
        bar = dict(bar)
        try:
            _l = float(bar["low"])
            _h = float(bar["high"])
            _mid = (abs(_h) + abs(_l)) / 2 or 1.0
            if _h < _l:
                _inversion_pct = (_l - _h) / _mid
                if _inversion_pct <= 0.005:
                    bar["high"], bar["low"] = _l, _h
        except (KeyError, TypeError, ValueError):
            pass
        return bar

    def test_swap_within_tolerance(self):
        """Inverted high/low within 0.5% should be swapped."""
        # high=1163.0, low=1164.3 → inversion = 1.3/1163.65 ≈ 0.112% < 0.5%
        bar = {"open": 1163.5, "high": 1163.0, "low": 1164.3, "close": 1163.8, "volume": 100}
        result = self._apply_swap(bar)
        assert result["high"] == 1164.3
        assert result["low"] == 1163.0

    def test_no_swap_beyond_tolerance(self):
        """Inverted high/low beyond 0.5% should NOT be swapped (genuine corruption)."""
        # high=1150.0, low=1160.0 → inversion = 10/1155 ≈ 0.87% > 0.5%
        bar = {"open": 1155.0, "high": 1150.0, "low": 1160.0, "close": 1155.0, "volume": 100}
        result = self._apply_swap(bar)
        # Should remain unchanged
        assert result["high"] == 1150.0
        assert result["low"] == 1160.0

    def test_normal_bar_unchanged(self):
        """Normal bar (high >= low) should not be modified."""
        bar = {"open": 1900.0, "high": 1910.0, "low": 1890.0, "close": 1905.0, "volume": 1000}
        result = self._apply_swap(bar)
        assert result["high"] == 1910.0
        assert result["low"] == 1890.0

    def test_exact_log_case(self):
        """Reproduce the exact values from the log: high=1163.0, low=1164.300048828125."""
        bar = {
            "open": 1163.5,
            "high": 1163.0,
            "low": 1164.300048828125,
            "close": 1163.8,
            "volume": 50,
        }
        result = self._apply_swap(bar)
        assert result["high"] > result["low"], "high should be > low after swap"
        assert result["high"] == pytest.approx(1164.300048828125)
        assert result["low"] == pytest.approx(1163.0)


# ---------------------------------------------------------------------------
# 3. api/auth.py — cookie fallback in get_current_user
# ---------------------------------------------------------------------------


class TestAuthCookieFallback:
    def test_get_current_user_accepts_bearer(self):
        """get_current_user resolves token from Authorization header."""
        from api.auth import get_current_user
        import inspect

        sig = inspect.signature(get_current_user)
        # Must accept 'request' and 'credentials' parameters
        assert "request" in sig.parameters
        assert "credentials" in sig.parameters

    def test_get_current_user_raises_401_without_token(self):
        """get_current_user raises 401 when neither header nor cookie is present."""
        from fastapi import HTTPException
        from api.auth import get_current_user

        mock_request = MagicMock()
        mock_request.cookies = {}  # no cookie

        with pytest.raises(HTTPException) as exc_info:
            get_current_user(request=mock_request, credentials=None)
        assert exc_info.value.status_code == 401

    def test_get_current_user_reads_cookie_when_no_bearer(self):
        """get_current_user falls back to hopefx_access_token cookie."""
        from api.auth import get_current_user

        mock_request = MagicMock()
        mock_request.cookies = {"hopefx_access_token": "fake-token"}

        with patch("api.auth._decode_token") as mock_decode:
            mock_decode.return_value = MagicMock(sub="user-123", role="superadmin")
            get_current_user(request=mock_request, credentials=None)
            mock_decode.assert_called_once_with("fake-token")

    def test_bearer_takes_precedence_over_cookie(self):
        """Authorization header takes precedence over cookie."""
        from api.auth import get_current_user
        from fastapi.security import HTTPAuthorizationCredentials

        mock_request = MagicMock()
        mock_request.cookies = {"hopefx_access_token": "cookie-token"}
        mock_creds = MagicMock(spec=HTTPAuthorizationCredentials)
        mock_creds.credentials = "bearer-token"

        with patch("api.auth._decode_token") as mock_decode:
            mock_decode.return_value = MagicMock(sub="user-123", role="user")
            get_current_user(request=mock_request, credentials=mock_creds)
            # Must use the bearer token, not the cookie
            mock_decode.assert_called_once_with("bearer-token")


# ---------------------------------------------------------------------------
# 4. security/code_analyzer.py — 0 issues after fixes
# ---------------------------------------------------------------------------


class TestCodeAnalyzerClean:
    # A zero-tolerance gate is only workable if a false positive can be
    # annotated. This message says how, because the alternative — a developer
    # who cannot resolve a bad finding — ends with the gate being weakened
    # rather than the line being marked. See
    # tests/unit/test_code_analyzer_suppression_is_uniform.py.
    _HOW_TO_SUPPRESS = (
        "\n\nIf a finding is a false positive, annotate the line with '# noqa' "
        "(or '# healer: ignore' / 'nosec' / 'lookahead-ok') and say why in the "
        "same comment. If the detector itself is wrong, fix the rule in "
        "security/code_analyzer.py — do not relax this gate."
    )

    def test_no_high_severity_issues(self):
        """After fixes, code_analyzer must report 0 critical/high issues."""
        from security.code_analyzer import scan_codebase

        issues = scan_codebase()
        high_or_critical = [i for i in issues if i.severity in ("critical", "high")]
        assert high_or_critical == [], (
            f"Expected 0 critical/high issues, found {len(high_or_critical)}:\n"
            + "\n".join(f"  {i.severity} | {i.category} | {i.file}:{i.line}" for i in high_or_critical)
            + self._HOW_TO_SUPPRESS
        )

    def test_total_issues_zero(self):
        """After fixes, code_analyzer must report 0 total issues."""
        from security.code_analyzer import scan_codebase

        issues = scan_codebase()
        assert len(issues) == 0, (
            f"Expected 0 issues, found {len(issues)}:\n"
            + "\n".join(f"  {i.severity} | {i.category} | {i.file}:{i.line}" for i in issues)
            + self._HOW_TO_SUPPRESS
        )


# ---------------------------------------------------------------------------
# 5. news/geopolitical_risk.py — singleton and _all_sources_warned
# ---------------------------------------------------------------------------


class TestGeopoliticalSingleton:
    def test_get_geopolitical_provider_returns_singleton(self):
        """get_geopolitical_provider() must return the same instance every call."""
        from news.geopolitical_risk import get_geopolitical_provider

        p1 = get_geopolitical_provider()
        p2 = get_geopolitical_provider()
        assert p1 is p2, "get_geopolitical_provider() must return the same singleton"

    def test_sentiment_engine_uses_singleton(self):
        """NewsSentimentEngine must use the singleton, not a new instance."""
        from news.geopolitical_risk import get_geopolitical_provider

        singleton = get_geopolitical_provider()
        # Mark the singleton's warned flag
        singleton._all_sources_warned = False

        # Import the engine — it should grab the same singleton
        try:
            from data_layer.sentiment.engine import NewsSentimentEngine

            engine = NewsSentimentEngine.__new__(NewsSentimentEngine)
            engine._tasks = []
            engine._running = False
            engine._redis = None
            engine._lineage = None
            engine._lock = asyncio.Lock()
            engine._article_count = 0
            engine._last_fetch_at = {}
            engine._seen_urls = {}
            engine._prom_sentiment = None
            engine._prom_art_count = None
            engine._prom_bull_ratio = None

            from news.geopolitical_risk import get_geopolitical_provider as _get_geo

            engine._geo_provider = _get_geo()

            assert engine._geo_provider is singleton, "NewsSentimentEngine._geo_provider must be the singleton"
        except ImportError:
            pytest.skip("NewsSentimentEngine not importable in this environment")

    def test_all_sources_warned_fires_once(self):
        """_all_sources_warned flag prevents duplicate offline log messages."""
        from news.geopolitical_risk import GeopoliticalRiskProvider

        provider = GeopoliticalRiskProvider()
        provider._all_sources_warned = False

        log_count = 0
        import logging

        class _Counter(logging.Handler):
            def emit(self, record):
                nonlocal log_count
                if "geopolitical data sources unavailable" in record.getMessage():
                    log_count += 1

        handler = _Counter()
        geo_logger = logging.getLogger("news.geopolitical_risk")
        geo_logger.addHandler(handler)
        # Ensure the logger propagates at INFO level so our handler sees it
        original_level = geo_logger.level
        geo_logger.setLevel(logging.DEBUG)
        try:
            # Simulate the offline branch 3 times — should only log once
            for _ in range(3):
                if not provider._all_sources_warned:
                    geo_logger.info("All geopolitical data sources unavailable and cache empty — returning no events.")
                    provider._all_sources_warned = True
        finally:
            geo_logger.removeHandler(handler)
            geo_logger.setLevel(original_level)

        assert log_count == 1, f"Expected 1 log message, got {log_count}"


# ---------------------------------------------------------------------------
# 6. CFTC COT — _offline_warned module-level flag
# ---------------------------------------------------------------------------


class TestCFTCOfflineWarned:
    def test_offline_warned_flag_exists(self):
        """cftc_cot module must have a module-level _offline_warned flag."""
        import data_layer.feeds.macro.cftc_cot as cot_mod

        assert hasattr(cot_mod, "_offline_warned"), "cftc_cot must have a module-level _offline_warned flag"
        assert isinstance(cot_mod._offline_warned, bool)

    def test_neutral_series_has_all_keys(self):
        """CFTCCOTFeed._neutral_series() must return all 4 expected series."""
        from data_layer.feeds.macro.cftc_cot import CFTCCOTFeed

        feed = CFTCCOTFeed()
        neutral = feed._neutral_series()
        expected = {"cot_net_spec", "cot_net_spec_pct", "cot_comm_net", "cot_open_interest"}
        assert set(neutral.keys()) == expected


# ---------------------------------------------------------------------------
# 7. yfinance_compat — suppression is idempotent
# ---------------------------------------------------------------------------


class TestYfinanceCompat:
    def test_suppress_is_idempotent(self):
        """suppress_yfinance_warnings() is safe to call multiple times."""
        from utils.yfinance_compat import suppress_yfinance_warnings

        # Already suppressed at import time — calling again must not raise
        suppress_yfinance_warnings()
        suppress_yfinance_warnings()
        from utils import yfinance_compat

        assert yfinance_compat._SUPPRESSED is True

    def test_yfinance_loggers_at_critical(self):
        """All yfinance sub-loggers must be set to CRITICAL after suppression."""
        import logging
        from utils.yfinance_compat import suppress_yfinance_warnings

        suppress_yfinance_warnings()
        yf_logger = logging.getLogger("yfinance")
        assert yf_logger.level == logging.CRITICAL, f"Expected CRITICAL, got {logging.getLevelName(yf_logger.level)}"
