# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""Guard test for the stress-test / resilience-drill harness: every scenario's
control must respond exactly as designed (fire when it should, hold when it
should). A failure here means a control silently stopped responding to a shock.
"""

from __future__ import annotations

import pytest

from scripts.stress_test import run_scenarios

pytestmark = pytest.mark.unit


def test_all_controls_respond_as_designed():
    results = run_scenarios()
    assert results, "no scenarios ran"
    failed = [r for r in results if not r["ok"]]
    assert not failed, f"controls not responding as designed: {[(r['scenario'], r['control']) for r in failed]}"


def test_covers_key_shock_categories():
    scenarios = {r["scenario"] for r in run_scenarios()}
    for required in ("flash_crash", "liquidity_freeze", "data_outage", "exchange_outage", "chaos_drill"):
        assert required in scenarios
