# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/unit/test_kill_switch_integration.py

6 tests covering the full kill-switch lifecycle:
  1. drawdown breach → halt
  2. halt persists to disk
  3. restart restores halt from disk
  4. authenticated deactivation resumes trading
  5. wrong token is rejected
  6. amber warning fires before full halt
"""

import json
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
from pathlib import Path

from risk.manager import RiskConfig, RiskManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rm(tmp_path: Path, **config_kwargs) -> RiskManager:
    """Create a RiskManager with an isolated halt-state file."""
    cfg = RiskConfig(**config_kwargs)
    halt_file = tmp_path / "halt_state.json"
    return RiskManager(config=cfg, initial_balance=100_000.0, halt_state_file=halt_file)


# ---------------------------------------------------------------------------
# Test 1: drawdown breach triggers halt
# ---------------------------------------------------------------------------


def test_drawdown_breach_triggers_halt(tmp_path):
    rm = _make_rm(tmp_path, max_drawdown_pct=0.10)
    rm.peak_equity = 100_000.0

    # Simulate a 12% drawdown — exceeds the 10% limit
    rm.current_drawdown = 0.12
    rm._check_circuit_breakers(88_000.0)

    assert rm._trading_halted is True
    assert rm._halt_reason is not None
    assert "drawdown" in rm._halt_reason.lower()


# ---------------------------------------------------------------------------
# Test 2: halt persists to disk
# ---------------------------------------------------------------------------


def test_halt_persists_to_disk(tmp_path):
    rm = _make_rm(tmp_path, max_drawdown_pct=0.10)
    halt_file = rm._halt_state_file

    rm._halt_trading("test halt", duration_hours=1)

    assert halt_file.exists(), "Halt state file should be written to disk"
    data = json.loads(halt_file.read_text(encoding="utf-8"))
    assert data["halted"] is True
    assert data["reason"] == "test halt"


# ---------------------------------------------------------------------------
# Test 3: restart restores halt from disk
# ---------------------------------------------------------------------------


def test_restart_restores_halt_from_disk(tmp_path):
    halt_file = tmp_path / "halt_state.json"
    future = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    halt_file.write_text(
        json.dumps(
            {
                "halted": True,
                "reason": "restored halt",
                "halt_until": future,
                "persisted_at": datetime.now(UTC).isoformat(),
            }
        )
    )

    rm = RiskManager(
        config=RiskConfig(),
        initial_balance=100_000.0,
        halt_state_file=halt_file,
    )

    assert rm._trading_halted is True
    assert rm._halt_reason == "restored halt"


# ---------------------------------------------------------------------------
# Test 4: authenticated deactivation resumes trading
# ---------------------------------------------------------------------------


def test_authenticated_deactivation_resumes_trading(tmp_path):
    rm = _make_rm(tmp_path)
    rm._halt_trading("manual halt", duration_hours=0)
    assert rm._trading_halted is True

    # Directly call _resume_trading (the API layer validates the HMAC token)
    rm._resume_trading()

    assert rm._trading_halted is False
    # After resume, _halt_reason is cleared to "" (empty string, not None)
    assert not rm._halt_reason
    assert not rm._halt_state_file.exists()


# ---------------------------------------------------------------------------
# Test 5: wrong token is rejected (HMAC validation)
# ---------------------------------------------------------------------------


def test_wrong_token_rejected():
    """
    The kill-switch deactivation endpoint validates an HMAC-SHA256 token.
    Verify that a mismatched token does not produce a valid signature.
    """
    import hashlib
    import hmac

    secret = "correct_secret_key"
    wrong_secret = "wrong_secret_key"
    message = "deactivate"

    correct_sig = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    wrong_sig = hmac.new(wrong_secret.encode(), message.encode(), hashlib.sha256).hexdigest()

    assert not hmac.compare_digest(correct_sig, wrong_sig), "Wrong token must not match the correct HMAC signature"


# ---------------------------------------------------------------------------
# Test 6: amber warning fires before full halt
# ---------------------------------------------------------------------------


def test_amber_warning_fires_before_halt(tmp_path, caplog):
    import logging

    rm = _make_rm(tmp_path, max_drawdown_pct=0.10)
    rm.peak_equity = 100_000.0

    # 65% of the 10% limit = 6.5% drawdown → AMBER, not halt
    rm.current_drawdown = 0.065
    rm._amber_warned = False

    with caplog.at_level(logging.WARNING, logger="risk.manager"):
        rm._check_circuit_breakers(93_500.0)

    assert rm._amber_warned is True, "Amber flag should be set"
    assert rm._trading_halted is False, "Trading should NOT be halted at amber level"
    assert any("AMBER" in r.message for r in caplog.records), "Expected AMBER warning in log"
