# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
Unit tests for scripts/fill_tracker.py

Tests ledger management, deduplication, gate logic, and gate file output
without making real OANDA API calls.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is importable
_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

import scripts.fill_tracker as ft

# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def tmp_data_dir(tmp_path, monkeypatch):
    """Redirect all file I/O to a temp directory."""
    monkeypatch.setattr(ft, "DATA_DIR", tmp_path)
    monkeypatch.setattr(ft, "FILL_LEDGER", tmp_path / "fill_tracker.json")
    monkeypatch.setattr(ft, "GATE_FILE", tmp_path / "paper_trading_gate.json")
    monkeypatch.setattr(ft, "FILL_GATE_TARGET", 500)
    return tmp_path


def _make_fill(txn_id: int, instrument: str = "XAU_USD", pl: str = "10.00") -> dict:
    return {
        "id": txn_id,
        "time": f"2026-03-{txn_id:02d}T12:00:00Z",
        "instrument": instrument,
        "units": "1",
        "price": "2000.00",
        "pl": pl,
        "account_balance": "100000.00",
        "order_id": str(txn_id * 10),
        "trade_id": str(txn_id * 10 + 1),
        "reason": "MARKET_ORDER",
    }


# ── ledger load/save ──────────────────────────────────────────────────────────


def test_load_ledger_returns_empty_when_missing():
    ledger = ft._load_ledger()
    assert ledger["fill_count"] == 0
    assert ledger["fills"] == []
    assert ledger["last_transaction_id"] is None


def test_save_and_reload_ledger():
    ledger = ft._load_ledger()
    ledger["fills"].append(_make_fill(1))
    ledger["fill_count"] = 1
    ledger["last_transaction_id"] = 1
    ft._save_ledger(ledger)

    reloaded = ft._load_ledger()
    assert reloaded["fill_count"] == 1
    assert reloaded["fills"][0]["id"] == 1
    assert reloaded["last_sync_at"] is not None


def test_save_ledger_is_atomic(tmp_path):
    """Verify .tmp file is replaced, not left behind."""
    ledger = ft._load_ledger()
    ft._save_ledger(ledger)
    tmp_file = ft.FILL_LEDGER.with_suffix(".tmp")
    assert not tmp_file.exists()
    assert ft.FILL_LEDGER.exists()


# ── sync_fills deduplication ──────────────────────────────────────────────────


def test_sync_fills_adds_new_fills():
    client = MagicMock()
    client.fetch_fills_since.return_value = [_make_fill(1), _make_fill(2)]

    ledger = ft._load_ledger()
    added = ft.sync_fills(client, ledger)

    assert added == 2
    assert ledger["fill_count"] == 2
    assert ledger["last_transaction_id"] == 2


def test_sync_fills_deduplicates():
    """Re-syncing the same fills must not double-count."""
    client = MagicMock()
    client.fetch_fills_since.return_value = [_make_fill(1), _make_fill(2)]

    ledger = ft._load_ledger()
    ft.sync_fills(client, ledger)

    # Second sync returns same fills
    client.fetch_fills_since.return_value = [
        _make_fill(1),
        _make_fill(2),
        _make_fill(3),
    ]
    added = ft.sync_fills(client, ledger)

    assert added == 1  # only fill 3 is new
    assert ledger["fill_count"] == 3


def test_sync_fills_empty_response():
    client = MagicMock()
    client.fetch_fills_since.return_value = []

    ledger = ft._load_ledger()
    added = ft.sync_fills(client, ledger)

    assert added == 0
    assert ledger["fill_count"] == 0


def test_sync_fills_passes_last_id_to_client():
    """Subsequent syncs must pass the last known transaction ID."""
    client = MagicMock()
    client.fetch_fills_since.return_value = [_make_fill(42)]

    ledger = ft._load_ledger()
    ledger["last_transaction_id"] = 41
    ft.sync_fills(client, ledger)

    client.fetch_fills_since.assert_called_once_with(41)


def test_sync_fills_sorts_by_id():
    client = MagicMock()
    # Return fills out of order
    client.fetch_fills_since.return_value = [
        _make_fill(3),
        _make_fill(1),
        _make_fill(2),
    ]

    ledger = ft._load_ledger()
    ft.sync_fills(client, ledger)

    ids = [f["id"] for f in ledger["fills"]]
    assert ids == sorted(ids)


# ── gate file ─────────────────────────────────────────────────────────────────


def test_gate_file_not_passed_below_target():
    ledger = ft._load_ledger()
    ledger["fills"] = [_make_fill(i) for i in range(1, 101)]  # 100 fills
    ledger["fill_count"] = 100
    ledger["last_sync_at"] = "2026-03-28T00:00:00Z"
    ft._update_gate_file(ledger)

    gate = json.loads(ft.GATE_FILE.read_text())
    assert gate["fill_count"] == 100
    assert gate["fill_gate_passed"] is False
    assert gate["fill_gate_pct"] == 20.0
    assert gate["phase3_enabled_at"] is None


def test_gate_file_passed_at_target():
    ledger = ft._load_ledger()
    ledger["fills"] = [_make_fill(i) for i in range(1, 501)]  # 500 fills
    ledger["fill_count"] = 500
    ledger["first_fill_at"] = "2026-01-01T00:00:00Z"
    ledger["last_sync_at"] = "2026-03-28T00:00:00Z"
    ft._update_gate_file(ledger)

    gate = json.loads(ft.GATE_FILE.read_text())
    assert gate["fill_gate_passed"] is True
    assert gate["fill_gate_pct"] == 100.0
    assert gate["phase3_enabled_at"] is not None


def test_gate_file_preserves_existing_fields():
    """Existing gate file fields (e.g. run_start_utc) must not be wiped."""
    ft.GATE_FILE.write_text(
        json.dumps(
            {
                "run_start_utc": "2026-03-26T17:02:47Z",
                "sharpe_before": None,
            }
        )
    )

    ledger = ft._load_ledger()
    ledger["last_sync_at"] = "2026-03-28T00:00:00Z"
    ft._update_gate_file(ledger)

    gate = json.loads(ft.GATE_FILE.read_text())
    assert gate["run_start_utc"] == "2026-03-26T17:02:47Z"
    assert "fill_count" in gate


def test_gate_file_phase3_not_overwritten_once_set():
    """phase3_enabled_at must not be reset on subsequent syncs."""
    first_enabled = "2026-03-01T00:00:00Z"
    ft.GATE_FILE.write_text(
        json.dumps(
            {
                "phase3_enabled_at": first_enabled,
                "fill_count": 500,
            }
        )
    )

    ledger = ft._load_ledger()
    ledger["fills"] = [_make_fill(i) for i in range(1, 501)]
    ledger["fill_count"] = 500
    ledger["last_sync_at"] = "2026-03-28T00:00:00Z"
    ft._update_gate_file(ledger)

    gate = json.loads(ft.GATE_FILE.read_text())
    assert gate["phase3_enabled_at"] == first_enabled


# ── main() exit codes ─────────────────────────────────────────────────────────


def test_main_report_only_exits_1_when_gate_not_passed(capsys):
    """--report with empty ledger exits 1 (gate not passed)."""
    with patch("sys.argv", ["fill_tracker.py", "--report"]):
        code = ft.main()
    assert code == 1


def test_main_report_exits_0_when_gate_passed(capsys):
    """--report exits 0 when fill_count >= target."""
    ledger = ft._load_ledger()
    ledger["fills"] = [_make_fill(i) for i in range(1, 501)]
    ledger["fill_count"] = 500
    ledger["last_sync_at"] = "2026-03-28T00:00:00Z"
    ft._save_ledger(ledger)

    with patch("sys.argv", ["fill_tracker.py", "--report"]):
        code = ft.main()
    assert code == 0


def test_main_reset_clears_ledger(tmp_path):
    """--reset removes the ledger file."""
    ft.FILL_LEDGER.write_text(json.dumps({"fill_count": 99}))
    with patch("sys.argv", ["fill_tracker.py", "--reset"]):
        code = ft.main()
    assert code == 0
    assert not ft.FILL_LEDGER.exists()


def test_main_missing_credentials_exits_2(capsys):
    """Missing OANDA_API_KEY exits 2."""
    with (
        patch.dict("os.environ", {"OANDA_API_KEY": "", "OANDA_ACCOUNT_ID": ""}),
        patch("sys.argv", ["fill_tracker.py"]),
    ):
        code = ft.main()
    assert code == 2
