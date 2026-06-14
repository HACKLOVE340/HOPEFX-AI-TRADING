# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/test_k6_load_tests.py
============================
Validates the k6 load test configuration without requiring k6 to be installed.

Checks
------
1. k6/load_tests.js exists and is non-empty.
2. All required scenarios are defined (smoke, load, soak, spike, stress, breakpoint).
3. All required thresholds are present (p95 latency, error_rate, http_req_failed).
4. All tested endpoint paths are present (including macro endpoints).
5. Rate-limit probe is present.
6. WebSocket test is present.
7. k6/run_load_test.sh exists and is executable.
8. k6/results/ directory exists (for CI artifact storage).
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]  # repo root (test lives in tests/unit/)
K6_SCRIPT = ROOT / "k6" / "load_tests.js"
K6_RUNNER = ROOT / "k6" / "run_load_test.sh"
K6_RESULTS = ROOT / "k6" / "results"


@pytest.fixture(scope="module")
def k6_source() -> str:
    assert K6_SCRIPT.exists(), f"k6/load_tests.js not found at {K6_SCRIPT}"
    return K6_SCRIPT.read_text()


# ── file existence ────────────────────────────────────────────────────────────


def test_k6_script_exists():
    assert K6_SCRIPT.exists()
    assert K6_SCRIPT.stat().st_size > 1000, "k6/load_tests.js appears empty"


def test_k6_runner_exists():
    assert K6_RUNNER.exists(), "k6/run_load_test.sh not found"


def test_k6_runner_is_executable():
    mode = K6_RUNNER.stat().st_mode
    assert mode & stat.S_IXUSR, "k6/run_load_test.sh is not executable"


def test_k6_results_dir_exists():
    assert K6_RESULTS.exists(), "k6/results/ directory not found"


# ── scenarios ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("scenario", ["smoke", "load", "soak", "spike", "stress", "breakpoint"])
def test_scenario_defined(k6_source, scenario):
    assert scenario + ":" in k6_source, f"Scenario '{scenario}' not defined in load_tests.js"


# ── thresholds ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "threshold",
    [
        "http_req_duration",
        "order_latency_ms",
        "signal_latency_ms",
        "ml_latency_ms",
        "macro_latency_ms",
        "error_rate",
        "http_req_failed",
    ],
)
def test_threshold_defined(k6_source, threshold):
    assert threshold in k6_source, f"Threshold '{threshold}' not defined in load_tests.js"


# ── endpoint coverage ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "endpoint",
    [
        "/health",
        "/api/status",
        "/api/signals/latest",
        "/api/ml/predict/",
        "/api/ml/status",
        "/api/macro/snapshot",
        "/api/macro/store",
        "/api/macro/features",
        "/api/trading/order",
        "/api/trading/positions",
        "/api/trading/account",
        "/api/risk/status",
        "/metrics",
        "/auth/login",
        "/ws/live",
    ],
)
def test_endpoint_covered(k6_source, endpoint):
    assert endpoint in k6_source, f"Endpoint '{endpoint}' not covered in load_tests.js"


# ── advanced features ─────────────────────────────────────────────────────────


def test_rate_limit_probe_present(k6_source):
    assert "rate_limit_probe" in k6_source or "rateLimitHits" in k6_source, (
        "Rate-limit probe not found in load_tests.js"
    )


def test_websocket_test_present(k6_source):
    assert "ws.connect" in k6_source or "testWebSocket" in k6_source, "WebSocket test not found in load_tests.js"


def test_custom_metrics_defined(k6_source):
    for metric in [
        "errorRate",
        "orderLatency",
        "signalLatency",
        "mlLatency",
        "macroLatency",
    ]:
        assert metric in k6_source, f"Custom metric '{metric}' not defined"


def test_setup_and_teardown_present(k6_source):
    assert "export function setup" in k6_source
    assert "export function teardown" in k6_source


def test_think_time_configurable(k6_source):
    assert "THINK_TIME" in k6_source, "THINK_TIME env var not used"


def test_auth_token_configurable(k6_source):
    assert "AUTH_TOKEN" in k6_source, "AUTH_TOKEN env var not used"


# ── runner script ─────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def runner_source() -> str:
    return K6_RUNNER.read_text()


def test_runner_handles_missing_k6(runner_source):
    assert "k6 not found" in runner_source or "not found" in runner_source


def test_runner_validates_scenario(runner_source):
    assert "VALID_SCENARIOS" in runner_source or "Unknown scenario" in runner_source


def test_runner_writes_results(runner_source):
    assert "RESULTS_DIR" in runner_source or "results" in runner_source


def test_runner_exports_summary(runner_source):
    assert "summary-export" in runner_source or "summary_export" in runner_source
