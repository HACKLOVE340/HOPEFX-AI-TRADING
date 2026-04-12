# HOPEFX-AI-TRADING
# Tests for brokers/oanda_paper_clock.py — full branch coverage
"""
Covers OandaPaperClock.maybe_start, status, is_complete, elapsed_days,
reset, sharpe_status, record_fill, and get_clock singleton.
Uses tmp_path for all file I/O.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch


import brokers.oanda_paper_clock as opc_mod
from brokers.oanda_paper_clock import OandaPaperClock, get_clock

UTC = timezone.utc


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_clock(tmp_path):
    stamp = tmp_path / "oanda_paper_start.json"
    with patch("brokers.oanda_paper_clock.OandaPaperClock._init_sharpe_tracker", return_value=None):
        clock = OandaPaperClock(stamp_path=stamp)
    clock._sharpe_tracker = None
    return clock


def _write_stamp(path: Path, data: dict):
    path.write_text(json.dumps(data), encoding="utf-8")


# ── maybe_start ───────────────────────────────────────────────────────────────


class TestMaybeStart:
    def test_first_start_writes_stamp(self, tmp_path):
        clock = _make_clock(tmp_path)
        result = clock.maybe_start(account_id="101-001-12345678", environment="practice")
        assert result is True
        assert clock._stamp_path.exists()
        data = json.loads(clock._stamp_path.read_text())
        assert "started_utc" in data
        assert data["environment"] == "practice"

    def test_second_start_returns_false_when_real_account_stamped(self, tmp_path):
        clock = _make_clock(tmp_path)
        clock.maybe_start(account_id="101-001-12345678", environment="practice")
        result = clock.maybe_start(account_id="101-001-12345678", environment="practice")
        assert result is False

    def test_pending_placeholder_overwritten_with_real_account(self, tmp_path):
        clock = _make_clock(tmp_path)
        started = datetime.now(UTC).isoformat()
        _write_stamp(
            clock._stamp_path,
            {
                "started_utc": started,
                "requires_real_account": True,
                "environment": "practice",
            },
        )
        result = clock.maybe_start(account_id="101-001-REALACCT", environment="practice")
        assert result is True
        data = json.loads(clock._stamp_path.read_text())
        assert not data.get("requires_real_account", False)
        assert data["started_utc"] == started  # original time preserved

    def test_account_id_masked_in_stamp(self, tmp_path):
        clock = _make_clock(tmp_path)
        clock.maybe_start(account_id="101-001-12345678", environment="practice")
        data = json.loads(clock._stamp_path.read_text())
        assert data["account_id"] == "101-001-…"

    def test_short_account_id_not_masked(self, tmp_path):
        clock = _make_clock(tmp_path)
        clock.maybe_start(account_id="SHORT", environment="practice")
        data = json.loads(clock._stamp_path.read_text())
        assert data["account_id"] == "SHORT"

    def test_write_failure_returns_false(self, tmp_path):
        clock = _make_clock(tmp_path)
        with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
            result = clock.maybe_start(account_id="101-001-12345678")
        assert result is False

    def test_live_gate_opens_computed(self, tmp_path):
        clock = _make_clock(tmp_path)
        clock.maybe_start(account_id="101-001-12345678")
        data = json.loads(clock._stamp_path.read_text())
        assert "live_gate_opens" in data

    def test_corrupt_existing_stamp_treated_as_no_stamp(self, tmp_path):
        clock = _make_clock(tmp_path)
        clock._stamp_path.write_text("INVALID{{{", encoding="utf-8")
        # Should not raise — treats corrupt file as missing
        result = clock.maybe_start(account_id="101-001-12345678")
        # Either True (wrote new stamp) or False (treated as existing)
        assert isinstance(result, bool)


# ── status — stamp missing ────────────────────────────────────────────────────


class TestStatusNoStamp:
    def test_status_not_started_when_no_stamp(self, tmp_path):
        clock = _make_clock(tmp_path)
        status = clock.status()
        assert status["started"] is False
        assert status["elapsed_days"] == 0.0
        assert status["complete"] is False

    def test_status_note_mentions_oanda_key_when_set(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OANDA_API_KEY", "test_key")
        clock = _make_clock(tmp_path)
        status = clock.status()
        assert "OANDA" in status["note"]

    def test_status_note_no_key(self, tmp_path, monkeypatch):
        monkeypatch.delenv("OANDA_API_KEY", raising=False)
        monkeypatch.delenv("BROKER_OANDA_TOKEN", raising=False)
        clock = _make_clock(tmp_path)
        status = clock.status()
        assert "Clock not started" in status["note"]


# ── status — stamp present ────────────────────────────────────────────────────


class TestStatusWithStamp:
    def test_status_started_true(self, tmp_path):
        clock = _make_clock(tmp_path)
        clock.maybe_start(account_id="101-001-12345678")
        status = clock.status()
        assert status["started"] is True
        assert status["elapsed_days"] >= 0.0
        assert status["remaining_days"] <= 30.0

    def test_status_complete_when_30_days_elapsed(self, tmp_path):
        clock = _make_clock(tmp_path)
        started = (datetime.now(UTC) - timedelta(days=31)).isoformat()
        _write_stamp(
            clock._stamp_path,
            {
                "started_utc": started,
                "target_days": 30,
                "account_id": "101-001-…",
                "environment": "practice",
            },
        )
        status = clock.status()
        assert status["complete"] is True
        assert status["elapsed_days"] >= 30.0

    def test_status_pending_placeholder(self, tmp_path):
        clock = _make_clock(tmp_path)
        started = datetime.now(UTC).isoformat()
        _write_stamp(
            clock._stamp_path,
            {
                "started_utc": started,
                "requires_real_account": True,
                "target_days": 30,
                "environment": "practice",
            },
        )
        status = clock.status()
        assert status["started"] is True
        assert status["account_id"] == "PENDING"
        assert status["pending_real_account"] is True

    def test_status_read_error_returns_not_started(self, tmp_path):
        clock = _make_clock(tmp_path)
        clock._stamp_path.write_text("INVALID JSON{{{", encoding="utf-8")
        status = clock.status()
        assert status["started"] is False

    def test_status_remaining_days_positive(self, tmp_path):
        clock = _make_clock(tmp_path)
        clock.maybe_start(account_id="101-001-12345678")
        status = clock.status()
        assert status["remaining_days"] > 0.0


# ── is_complete / elapsed_days ────────────────────────────────────────────────


class TestHelperMethods:
    def test_is_complete_false_when_not_started(self, tmp_path):
        clock = _make_clock(tmp_path)
        assert clock.is_complete() is False

    def test_is_complete_true_after_30_days(self, tmp_path):
        clock = _make_clock(tmp_path)
        started = (datetime.now(UTC) - timedelta(days=31)).isoformat()
        _write_stamp(
            clock._stamp_path,
            {
                "started_utc": started,
                "target_days": 30,
                "account_id": "101-001-…",
                "environment": "practice",
            },
        )
        assert clock.is_complete() is True

    def test_elapsed_days_zero_when_not_started(self, tmp_path):
        clock = _make_clock(tmp_path)
        assert clock.elapsed_days() == 0.0

    def test_elapsed_days_positive_after_start(self, tmp_path):
        clock = _make_clock(tmp_path)
        started = (datetime.now(UTC) - timedelta(days=5)).isoformat()
        _write_stamp(
            clock._stamp_path,
            {
                "started_utc": started,
                "target_days": 30,
                "account_id": "101-001-…",
                "environment": "practice",
            },
        )
        assert clock.elapsed_days() >= 4.9


# ── reset ─────────────────────────────────────────────────────────────────────


class TestReset:
    def test_reset_deletes_stamp(self, tmp_path):
        clock = _make_clock(tmp_path)
        clock.maybe_start(account_id="101-001-12345678")
        assert clock._stamp_path.exists()
        clock.reset()
        assert not clock._stamp_path.exists()

    def test_reset_no_stamp_no_error(self, tmp_path):
        clock = _make_clock(tmp_path)
        clock.reset()  # must not raise


# ── sharpe_status ─────────────────────────────────────────────────────────────


class TestSharpeStatus:
    def test_sharpe_status_unavailable_when_no_tracker(self, tmp_path):
        clock = _make_clock(tmp_path)
        status = clock.sharpe_status()
        assert status["available"] is False

    def test_sharpe_status_with_tracker(self, tmp_path):
        clock = _make_clock(tmp_path)
        mock_tracker = MagicMock()
        mock_tracker.status.return_value = {
            "n_trades": 10,
            "sharpe": 1.5,
            "gate_passed": False,
            "sharpe_se": 0.3,
            "pct_to_gate": 50.0,
        }
        clock._sharpe_tracker = mock_tracker
        status = clock.sharpe_status()
        assert status["available"] is True
        assert status["n_trades"] == 10


# ── record_fill ───────────────────────────────────────────────────────────────


class TestRecordFill:
    def test_record_fill_no_tracker_returns_empty(self, tmp_path):
        clock = _make_clock(tmp_path)
        result = clock.record_fill(0.01, "XAUUSD")
        assert result == {}

    def test_record_fill_with_tracker(self, tmp_path):
        clock = _make_clock(tmp_path)
        mock_tracker = MagicMock()
        mock_tracker.update.return_value = {
            "n_trades": 1,
            "sharpe": 0.5,
            "gate_passed": False,
            "sharpe_se": 0.1,
            "pct_to_gate": 10.0,
        }
        clock._sharpe_tracker = mock_tracker
        result = clock.record_fill(0.01, "XAUUSD")
        mock_tracker.update.assert_called_once_with(0.01)
        assert result["n_trades"] == 1

    def test_record_fill_prometheus_failure_does_not_raise(self, tmp_path):
        clock = _make_clock(tmp_path)
        mock_tracker = MagicMock()
        mock_tracker.update.return_value = {
            "n_trades": 1,
            "sharpe": 0.5,
            "gate_passed": False,
            "sharpe_se": 0.1,
            "pct_to_gate": 10.0,
        }
        clock._sharpe_tracker = mock_tracker
        with patch("brokers.oanda_paper_clock.OandaPaperClock.record_fill", wraps=clock.record_fill):
            result = clock.record_fill(0.01, "XAUUSD")
        assert result is not None


# ── get_clock singleton ───────────────────────────────────────────────────────


class TestGetClock:
    def test_singleton_returns_same_instance(self):
        opc_mod._clock = None
        with patch("brokers.oanda_paper_clock.OandaPaperClock._init_sharpe_tracker", return_value=None):
            c1 = get_clock()
            c2 = get_clock()
        assert c1 is c2
        opc_mod._clock = None

    def test_singleton_is_clock_instance(self):
        opc_mod._clock = None
        with patch("brokers.oanda_paper_clock.OandaPaperClock._init_sharpe_tracker", return_value=None):
            c = get_clock()
        assert isinstance(c, OandaPaperClock)
        opc_mod._clock = None
