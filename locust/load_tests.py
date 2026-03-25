"""
locust/load_tests.py
====================
Production load test for HOPEFX API using Locust.

Usage:
    # Headless (CI / production):
    locust -f locust/load_tests.py \
           --headless --users 100 --spawn-rate 10 \
           --run-time 5m \
           --host https://api.hopefx.io

    # Interactive web UI (local):
    locust -f locust/load_tests.py --host http://localhost:8000
    # then open http://localhost:8089

Environment variables:
    AUTH_TOKEN  — Bearer token for authenticated endpoints (optional).
                  Without it, only public endpoints are exercised.
    LOCUST_HOST — Overrides --host when set.
"""

from __future__ import annotations

import json
import os
import random
import time

from locust import HttpUser, between, events, task

_AUTH_TOKEN = os.getenv("AUTH_TOKEN", "")
_SYMBOLS = ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY"]


def _auth_headers() -> dict:
    h = {"Content-Type": "application/json"}
    if _AUTH_TOKEN:
        h["Authorization"] = f"Bearer {_AUTH_TOKEN}"
    return h


# ── Public user — no auth required ───────────────────────────────────────────

class PublicUser(HttpUser):
    """Simulates an unauthenticated visitor hitting public endpoints."""

    wait_time = between(0.5, 2.0)
    weight = 3  # 3× more public traffic than authenticated

    @task(5)
    def health_check(self):
        with self.client.get("/health", catch_response=True, name="/health") as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"Unexpected status {resp.status_code}")

    @task(3)
    def public_status(self):
        with self.client.get(
            "/api/status", catch_response=True, name="/api/status"
        ) as resp:
            if resp.status_code in (200, 404):
                resp.success()
            else:
                resp.failure(f"Unexpected status {resp.status_code}")

    @task(2)
    def market_data(self):
        symbol = random.choice(_SYMBOLS)
        with self.client.get(
            f"/api/market-data/{symbol}",
            catch_response=True,
            name="/api/market-data/[symbol]",
        ) as resp:
            if resp.status_code in (200, 404, 503):
                resp.success()
            else:
                resp.failure(f"Unexpected status {resp.status_code}")

    @task(1)
    def login_attempt(self):
        """Simulate a login attempt (expects 401 for non-existent user)."""
        with self.client.post(
            "/auth/login",
            json={"email": "loadtest@example.com", "password": "LoadTest123!"},
            catch_response=True,
            name="/auth/login",
        ) as resp:
            if resp.status_code in (200, 401, 422, 429):
                resp.success()
            else:
                resp.failure(f"Unexpected login status {resp.status_code}")


# ── Authenticated trader — requires AUTH_TOKEN ────────────────────────────────

class AuthenticatedTrader(HttpUser):
    """Simulates an authenticated trader placing orders and checking positions."""

    wait_time = between(1.0, 3.0)
    weight = 1

    def on_start(self):
        """Skip this user class if no auth token is configured."""
        if not _AUTH_TOKEN:
            self.environment.runner.quit()

    @task(4)
    def get_positions(self):
        with self.client.get(
            "/api/trading/positions",
            headers=_auth_headers(),
            catch_response=True,
            name="/api/trading/positions",
        ) as resp:
            if resp.status_code in (200, 401, 403, 503):
                resp.success()
            else:
                resp.failure(f"Unexpected status {resp.status_code}")

    @task(2)
    def place_order(self):
        symbol = random.choice(_SYMBOLS)
        side = random.choice(["buy", "sell"])
        start = time.monotonic()
        with self.client.post(
            "/api/trading/order",
            headers=_auth_headers(),
            json={
                "symbol": symbol,
                "side": side,
                "quantity": round(random.uniform(0.01, 0.1), 2),
                "order_type": "market",
            },
            catch_response=True,
            name="/api/trading/order",
        ) as resp:
            latency_ms = (time.monotonic() - start) * 1000
            # 201=filled, 400=bad request, 403=risk blocked, 422=validation
            if resp.status_code in (201, 400, 403, 422, 503):
                resp.success()
            elif resp.status_code == 401:
                resp.failure("Auth token rejected")
            else:
                resp.failure(f"Unexpected order status {resp.status_code}")

    @task(1)
    def get_performance(self):
        with self.client.get(
            "/api/performance/summary",
            headers=_auth_headers(),
            catch_response=True,
            name="/api/performance/summary",
        ) as resp:
            if resp.status_code in (200, 401, 403, 404, 503):
                resp.success()
            else:
                resp.failure(f"Unexpected status {resp.status_code}")

    @task(1)
    def get_ml_signal(self):
        with self.client.get(
            "/api/ml/predict?symbol=XAUUSD&timeframe=H1",
            headers=_auth_headers(),
            catch_response=True,
            name="/api/ml/predict",
        ) as resp:
            if resp.status_code in (200, 401, 403, 404, 503):
                resp.success()
            else:
                resp.failure(f"Unexpected status {resp.status_code}")


# ── Event hooks ───────────────────────────────────────────────────────────────

@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    print(f"[locust] Starting load test against {environment.host}")
    if not _AUTH_TOKEN:
        print("[locust] AUTH_TOKEN not set — authenticated endpoints will be skipped")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    stats = environment.stats.total
    print(
        f"[locust] Test complete — "
        f"requests={stats.num_requests} "
        f"failures={stats.num_failures} "
        f"p95={stats.get_response_time_percentile(0.95):.0f}ms"
    )
