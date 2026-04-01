# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_paper_trading_gate.py
=================================
Tests for the OANDA paper trading gate and its API wiring.

Covers
------
1. PaperTradingGate state persistence (load/save round-trip).
2. set_run_start() sets the clock.
3. elapsed_days computed correctly.
4. record_fill() increments counter and persists.
5. phase2_ready() — time gate (30 days).
6. phase2_ready() — Sharpe gate.
7. phase3_ready() — fill count gate (500 fills).
8. phase3_ready() — time gate (90 days).
9. status() returns all expected keys.
10. API: GET /api/status/paper-trading/gate returns gate status.
11. API: POST /api/status/paper-trading/gate/fill records a fill.
12. validate_oanda.py --gate flag runs without error.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from research.pipeline.paper_trading_gate import (
    PHASE3_MIN_FILLS,
    PaperTradingGate,
)


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def gate(tmp_path):
    """Fresh PaperTradingGate backed by a temp file."""
    return PaperTradingGate(state_path=str(tmp_path / "gate.json"))


@pytest.fixture
def gate_started(tmp_path):
    """Gate with run start set to 31 days ago."""
    g = PaperTradingGate(state_path=str(tmp_path / "gate.json"))
    past = datetime.now(UTC) - timedelta(days=31)
    g.set_run_start(past)
    return g


@pytest.fixture
def gate_phase3_ready(tmp_path):
    """Gate with 91 days elapsed and 500 fills."""
    g = PaperTradingGate(state_path=str(tmp_path / "gate.json"))
    past = datetime.now(UTC) - timedelta(days=91)
    g.set_run_start(past)
    # Bulk-set fill count directly in state
    g._state["fill_count"] = PHASE3_MIN_FILLS
    g._save_state()
    return g


# ── unit: state persistence ───────────────────────────────────────────────────


def test_state_persists_across_instances(tmp_path):
    path = str(tmp_path / "gate.json")
    g1 = PaperTradingGate(state_path=path)
    g1.set_run_start()
    g1.record_fill(pnl=10.0)

    g2 = PaperTradingGate(state_path=path)
    assert g2.fill_count == 1
    assert g2.run_start is not None


def test_state_file_created_on_save(tmp_path):
    path = tmp_path / "gate.json"
    g = PaperTradingGate(state_path=str(path))
    g.set_run_start()
    assert path.exists()
    data = json.loads(path.read_text())
    assert "run_start_utc" in data


# ── unit: set_run_start ───────────────────────────────────────────────────────


def test_set_run_start_defaults_to_now(gate):
    before = datetime.now(UTC)
    gate.set_run_start()
    after = datetime.now(UTC)
    assert gate.run_start is not None
    assert before <= gate.run_start <= after


def test_set_run_start_accepts_explicit_datetime(gate):
    ts = datetime(2025, 1, 1, tzinfo=UTC)
    gate.set_run_start(ts)
    assert gate.run_start == ts


# ── unit: elapsed_days ────────────────────────────────────────────────────────


def test_elapsed_days_zero_when_not_started(gate):
    assert gate.elapsed_days == 0


def test_elapsed_days_correct(gate):
    past = datetime.now(UTC) - timedelta(days=15)
    gate.set_run_start(past)
    assert 14 <= gate.elapsed_days <= 16


# ── unit: record_fill ─────────────────────────────────────────────────────────


def test_record_fill_increments_counter(gate):
    gate.set_run_start()
    assert gate.record_fill(pnl=5.0) == 1
    assert gate.record_fill(pnl=-2.0) == 2
    assert gate.fill_count == 2


def test_record_fill_persists(tmp_path):
    path = str(tmp_path / "gate.json")
    g1 = PaperTradingGate(state_path=path)
    g1.set_run_start()
    g1.record_fill(pnl=10.0)
    g1.record_fill(pnl=20.0)

    g2 = PaperTradingGate(state_path=path)
    assert g2.fill_count == 2


# ── unit: phase2_ready ────────────────────────────────────────────────────────


def test_phase2_not_ready_when_not_started(gate):
    ok, reason = gate.phase2_ready()
    assert not ok
    assert "not set" in reason.lower() or "start" in reason.lower()


def test_phase2_not_ready_before_30_days(gate):
    gate.set_run_start(datetime.now(UTC) - timedelta(days=10))
    ok, reason = gate.phase2_ready()
    assert not ok
    assert "remaining" in reason.lower() or "days" in reason.lower()


def test_phase2_ready_after_30_days(gate_started):
    ok, reason = gate_started.phase2_ready()
    assert ok, f"Expected phase2 ready, got: {reason}"


def test_phase2_sharpe_gate_blocks_on_large_drop(gate_started):
    gate_started.record_sharpe(before=1.5, after=1.0)  # drop = 0.5 > 0.2
    ok, reason = gate_started.phase2_ready()
    assert not ok
    assert "sharpe" in reason.lower()


def test_phase2_sharpe_gate_passes_on_small_drop(gate_started):
    gate_started.record_sharpe(before=1.5, after=1.4)  # drop = 0.1 < 0.2
    ok, reason = gate_started.phase2_ready()
    assert ok, f"Expected phase2 ready, got: {reason}"


# ── unit: phase3_ready ────────────────────────────────────────────────────────


def test_phase3_not_ready_insufficient_fills(gate_started):
    ok, reason = gate_started.phase3_ready()
    assert not ok
    assert "fill" in reason.lower()


def test_phase3_not_ready_insufficient_days(tmp_path):
    g = PaperTradingGate(state_path=str(tmp_path / "gate.json"))
    g.set_run_start(datetime.now(UTC) - timedelta(days=31))
    g._state["fill_count"] = PHASE3_MIN_FILLS
    g._save_state()
    ok, reason = g.phase3_ready()
    assert not ok
    assert "days" in reason.lower() or "remaining" in reason.lower()


def test_phase3_ready_when_all_gates_pass(gate_phase3_ready):
    ok, reason = gate_phase3_ready.phase3_ready()
    assert ok, f"Expected phase3 ready, got: {reason}"


# ── unit: status dict ─────────────────────────────────────────────────────────


def test_status_contains_all_keys(gate_started):
    s = gate_started.status()
    required_keys = [
        "run_start_utc",
        "elapsed_days",
        "fill_count",
        "phase2_ready",
        "phase2_reason",
        "phase3_ready",
        "phase3_reason",
        "phase2_min_days",
        "phase3_min_days",
        "phase3_min_fills",
        "phase2_max_sharpe_drop",
    ]
    for key in required_keys:
        assert key in s, f"Missing key: {key}"


# ── integration: API endpoints ────────────────────────────────────────────────


@pytest.fixture(scope="module")
def api_client(tmp_path_factory):
    """TestClient with status router mounted."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.status import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_gate_endpoint_returns_200(api_client):
    resp = api_client.get("/api/status/paper-trading/gate")
    assert resp.status_code == 200
    data = resp.json()
    assert "phase2_ready" in data
    assert "phase3_ready" in data


def test_gate_fill_endpoint_records_fill(api_client, monkeypatch, tmp_path):
    """POST /api/status/paper-trading/gate/fill increments fill count."""
    from research.pipeline import paper_trading_gate as _ptg

    fresh_gate = PaperTradingGate(state_path=str(tmp_path / "api_gate.json"))
    fresh_gate.set_run_start()
    monkeypatch.setattr(_ptg, "_gate", fresh_gate)

    resp = api_client.post("/api/status/paper-trading/gate/fill?pnl=15.5")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "recorded"
    assert data["fill_count"] == 1
    assert data["pnl"] == pytest.approx(15.5)


def test_paper_trading_status_endpoint(api_client):
    resp = api_client.get("/api/status/paper-trading")
    assert resp.status_code == 200
    data = resp.json()
    assert "started" in data
    assert "elapsed_days" in data


# ── validate_oanda.py --gate flag ─────────────────────────────────────────────


def test_validate_oanda_gate_flag_runs(capsys):
    """--gate flag prints gate status without crashing."""
    from scripts.validate_oanda import validate_gate

    validate_gate()  # should not raise
    captured = capsys.readouterr()
    assert "Phase" in captured.out or "Gate" in captured.out or "gate" in captured.out.lower()
