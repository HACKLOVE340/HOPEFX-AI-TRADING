# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
health/health_check_service.py
==============================
Lightweight health-check service used by /health endpoints and the
aggregate_health_status() utility.

Dependencies (db_connection, cache_service, broker) are injected via the
constructor so aggregate_health_status() never calls methods on None.
When a dependency is not provided its check reports "unconfigured" rather
than False, which is distinct from a genuine failure.
"""

import json
import logging
from typing import Any

import psutil
import requests

logger = logging.getLogger(__name__)


class HealthCheckService:
    def __init__(
        self,
        db_connection: Any | None = None,
        cache_service: Any | None = None,
        broker: Any | None = None,
        api_url: str = "http://localhost:8000",
    ):
        self.db_connection = db_connection
        self.cache_service = cache_service
        self.broker = broker
        self.api_url = api_url
        self.alerts: list = []

    # ── individual checks ────────────────────────────────────────────────────

    def check_api(self, url: str) -> bool:
        try:
            response = requests.get(url, timeout=5)
            return response.status_code == 200
        except Exception as exc:
            self.alerts.append(f"API check failed: {exc}")
            return False

    def check_database(self, db_connection: Any | None = None) -> bool | str:
        conn = db_connection or self.db_connection
        if conn is None:
            return "unconfigured"
        try:
            conn.ping()
            return True
        except Exception as exc:
            self.alerts.append(f"Database check failed: {exc}")
            return False

    def check_cache(self, cache_service: Any | None = None) -> bool | str:
        svc = cache_service or self.cache_service
        if svc is None:
            return "unconfigured"
        try:
            svc.ping()
            return True
        except Exception as exc:
            self.alerts.append(f"Cache check failed: {exc}")
            return False

    def check_broker_connections(self, broker: Any | None = None) -> bool | str:
        b = broker or self.broker
        if b is None:
            return "unconfigured"
        try:
            b.check_connection()
            return True
        except Exception as exc:
            self.alerts.append(f"Broker connection check failed: {exc}")
            return False

    def check_market_data_feed(self, market_data_url: str | None = None) -> bool:
        return self.check_api(market_data_url or self.api_url)

    def monitor_system_resources(self) -> dict:
        return {
            "cpu": psutil.cpu_percent(),
            "memory": psutil.virtual_memory().percent,
            "disk": psutil.disk_usage("/").percent,
        }

    # ── aggregate ────────────────────────────────────────────────────────────

    def aggregate_health_status(self) -> dict:
        """
        Return a status dict for all subsystems.

        Values are True (healthy), False (failed), or "unconfigured"
        (dependency not injected — not a failure, just not checked).
        """
        self.alerts = []  # reset per call
        status = {
            "api": self.check_api(self.api_url),
            "db": self.check_database(),
            "cache": self.check_cache(),
            "broker": self.check_broker_connections(),
            "market_data": self.check_market_data_feed(),
            "system_resources": self.monitor_system_resources(),
            "alerts": self.alerts,
        }
        return status


if __name__ == "__main__":
    service = HealthCheckService()
    health_status = service.aggregate_health_status()
    logger.info(json.dumps(health_status, indent=4))
