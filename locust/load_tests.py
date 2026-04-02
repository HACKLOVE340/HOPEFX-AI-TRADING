# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
locust/load_tests.py
====================
Production load test for HOPEFX API using Locust.

User classes
------------
  PublicUser          — unauthenticated visitor (weight 3)
  MLResearcher        — user polling ML/signal endpoints (weight 2)
  AuthenticatedTrader — authenticated trader placing orders (weight 1)

Usage
-----
  # Headless CI run
  locust -f locust/load_tests.py \
         --headless --users 100 --spawn-rate 10 \
         --run-time 5m \
         --host https://api.hopefx.io

  # Interactive web UI (local)
  locust -f locust/load_tests.py --host http://localhost:8000
  # then open http://localhost:8089

  # CSV output for CI artefacts
  locust -f locust/load_tests.py \
         --headless --users 50 --spawn-rate 5 --run-time 2m \
         --csv results/locust \
         --host http://localhost:8000

  # HTML report
  locust -f locust/load_tests.py \
         --headless --users 50 --spawn-rate 5 --run-time 2m \
         --html results/locust_report.html \
         --host http://localhost:8000

Environment variables
---------------------
  AUTH_TOKEN    Bearer token for authenticated endpoints (optional).
  LOCUST_HOST   Overrides --host when set.
  THINK_TIME    Float multiplier for wait_time (default: 1.0).
  SIGNAL_SYMBOL Symbol for ML/signal tests (default: XAUUSD).
"""

from __future__ import annotations

import os
import random

from locust import HttpUser, between, events, task
from locust.exception import StopUser

_AUTH_TOKEN = os.getenv("AUTH_TOKEN", "")
_THINK_TIME = float(os.getenv("THINK_TIME", "1.0"))
_SYMBOLS = ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "AUDUSD"]
_SIGNAL_SYM = os.getenv("SIGNAL_SYMBOL", "XAUUSD")


def _auth_headers() -> dict[str, str]:
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if _AUTH_TOKEN:
        h["Authorization"] = f"Bearer {_AUTH_TOKEN}"
    return h


def _check(resp, name: str, allowed=(200,)) -> bool:
    """Mark response success/failure. Returns True if OK."""
    if resp.status_code in allowed:
        resp.success()
        return True
    if resp.status_code in (500, 502, 503, 504):
        resp.failure(f"{name}: server error {resp.status_code}")
        return False
    resp.success()
    return True


# ── Public user ───────────────────────────────────────────────────────────────


class PublicUser(HttpUser):
    """Unauthenticated visitor hitting public endpoints."""

    wait_time = between(0.5 * _THINK_TIME, 2.0 * _THINK_TIME)
    weight = 3

    @task(5)
    def health_check(self):
        with self.client.get("/health", catch_response=True, name="/health") as r:
            _check(r, "health", (200,))

    @task(3)
    def public_status(self):
        with self.client.get("/api/status", catch_response=True, name="/api/status") as r:
            _check(r, "status", (200, 404))

    @task(4)
    def market_data(self):
        symbol = random.choice(_SYMBOLS)  # nosec B311 - load test symbol selection, not cryptographic
        with self.client.get(
            f"/api/market-data/{symbol}",
            catch_response=True,
            name="/api/market-data/[symbol]",
        ) as r:
            _check(r, "market_data", (200, 404, 503))

    @task(2)
    def prometheus_metrics(self):
        with self.client.get("/metrics", catch_response=True, name="/metrics") as r:
            _check(r, "prometheus", (200, 403, 404))

    @task(2)
    def risk_status(self):
        with self.client.get(
            "/api/risk/status",
            headers=_auth_headers(),
            catch_response=True,
            name="/api/risk/status",
        ) as r:
            _check(r, "risk_status", (200, 401, 403, 404, 503))

    @task(1)
    def auth_login_attempt(self):
        """Test login endpoint responds — 401 expected for non-existent user."""
        with self.client.post(
            "/auth/login",
            json={"email": "loadtest@example.com", "password": "LoadTest123!"},  # nosec B105 - load-test probe, 401 expected
            catch_response=True,
            name="/auth/login",
        ) as r:
            _check(r, "auth_login", (200, 201, 401, 422))


# ── ML researcher ─────────────────────────────────────────────────────────────


class MLResearcher(HttpUser):
    """User polling ML predictions and signal endpoints."""

    wait_time = between(1.0 * _THINK_TIME, 4.0 * _THINK_TIME)
    weight = 2

    @task(4)
    def ml_status(self):
        with self.client.get(
            "/api/ml/status",
            headers=_auth_headers(),
            catch_response=True,
            name="/api/ml/status",
        ) as r:
            _check(r, "ml_status", (200, 401, 403, 404, 503))

    @task(4)
    def ml_predict(self):
        with self.client.get(
            f"/api/ml/predict/{_SIGNAL_SYM}",
            headers=_auth_headers(),
            catch_response=True,
            name="/api/ml/predict/[symbol]",
        ) as r:
            _check(r, "ml_predict", (200, 401, 403, 404, 503))

    @task(3)
    def ml_accuracy(self):
        with self.client.get(
            "/api/ml/accuracy",
            headers=_auth_headers(),
            catch_response=True,
            name="/api/ml/accuracy",
        ) as r:
            _check(r, "ml_accuracy", (200, 401, 403, 404, 503))

    @task(3)
    def signal_latest(self):
        with self.client.get(
            f"/api/signals/latest?symbol={_SIGNAL_SYM}",
            headers=_auth_headers(),
            catch_response=True,
            name="/api/signals/latest",
        ) as r:
            _check(r, "signal_latest", (200, 401, 403, 404, 503))

    @task(2)
    def ml_models_list(self):
        with self.client.get(
            "/api/ml/models",
            headers=_auth_headers(),
            catch_response=True,
            name="/api/ml/models",
        ) as r:
            _check(r, "ml_models", (200, 401, 403, 404, 503))

    @task(1)
    def feature_groups(self):
        with self.client.get(
            "/api/ml/features/groups",
            headers=_auth_headers(),
            catch_response=True,
            name="/api/ml/features/groups",
        ) as r:
            _check(r, "feature_groups", (200, 401, 403, 404, 503))


# ── Authenticated trader ──────────────────────────────────────────────────────


class AuthenticatedTrader(HttpUser):
    """Authenticated trader placing orders and checking positions."""

    wait_time = between(1.0 * _THINK_TIME, 3.0 * _THINK_TIME)
    weight = 1

    def on_start(self):
        if not _AUTH_TOKEN:
            raise StopUser()

    @task(5)
    def get_positions(self):
        with self.client.get(
            "/api/trading/positions",
            headers=_auth_headers(),
            catch_response=True,
            name="/api/trading/positions",
        ) as r:
            _check(r, "positions", (200, 401, 403, 503))

    @task(3)
    def get_account_info(self):
        with self.client.get(
            "/api/trading/account",
            headers=_auth_headers(),
            catch_response=True,
            name="/api/trading/account",
        ) as r:
            _check(r, "account_info", (200, 401, 403, 404, 503))

    @task(2)
    def place_order(self):
        symbol = random.choice(_SYMBOLS)  # nosec B311 - load test symbol selection, not cryptographic
        side = random.choice(["buy", "sell"])  # nosec B311 - load test side selection, not cryptographic
        qty = round(random.uniform(0.01, 0.1), 2)  # nosec B311 - load test quantity, not cryptographic

        with self.client.post(
            "/api/trading/order",
            headers=_auth_headers(),
            json={
                "symbol": symbol,
                "side": side,
                "quantity": qty,
                "order_type": "market",
            },
            catch_response=True,
            name="/api/trading/order",
        ) as r:
            if r.status_code in (201, 400, 403, 422, 429, 503):
                r.success()
            elif r.status_code == 401:  # noqa: PLR2004
                r.failure("Auth token rejected")
            elif r.status_code == 500:  # noqa: PLR2004
                r.failure(f"Server error placing order: {r.text[:200]}")
            else:
                r.success()

    @task(2)
    def get_performance_summary(self):
        with self.client.get(
            "/api/performance/summary",
            headers=_auth_headers(),
            catch_response=True,
            name="/api/performance/summary",
        ) as r:
            _check(r, "performance_summary", (200, 401, 403, 404, 503))

    @task(1)
    def get_risk_metrics(self):
        with self.client.get(
            "/api/risk/metrics",
            headers=_auth_headers(),
            catch_response=True,
            name="/api/risk/metrics",
        ) as r:
            _check(r, "risk_metrics", (200, 401, 403, 404, 503))

    @task(1)
    def get_trade_history(self):
        with self.client.get(
            "/api/trading/history?limit=20",
            headers=_auth_headers(),
            catch_response=True,
            name="/api/trading/history",
        ) as r:
            _check(r, "trade_history", (200, 401, 403, 404, 503))


# ── Event hooks ───────────────────────────────────────────────────────────────


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    print(f"[locust] Starting load test against {environment.host}")
    if not _AUTH_TOKEN:
        print("[locust] AUTH_TOKEN not set — AuthenticatedTrader users will be skipped")
    print(f"[locust] THINK_TIME multiplier: {_THINK_TIME}x")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    stats = environment.stats.total
    p95 = stats.get_response_time_percentile(0.95) or 0
    p99 = stats.get_response_time_percentile(0.99) or 0
    failure_rate = stats.num_failures / stats.num_requests * 100 if stats.num_requests > 0 else 0
    print(
        f"[locust] Test complete — "
        f"requests={stats.num_requests} "
        f"failures={stats.num_failures} ({failure_rate:.1f}%) "
        f"p95={p95:.0f}ms "
        f"p99={p99:.0f}ms "
        f"rps={stats.current_rps:.1f}"
    )
    if failure_rate > 1.0:
        print(f"[locust] FAIL: error rate {failure_rate:.1f}% exceeds 1% threshold")
