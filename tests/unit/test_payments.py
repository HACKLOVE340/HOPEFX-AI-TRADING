# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
tests/unit/test_payments.py
===========================
Unit tests for:
- payments/crypto/rate_feed.py  — live rate feed with TTL cache
- api/payments.py               — address generation, status polling,
                                  webhook HMAC verification
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from datetime import datetime, timedelta, timezone
UTC = timezone.utc
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Rate feed tests ───────────────────────────────────────────────────────────


class TestRateFeed:
    """payments/crypto/rate_feed.py"""

    def setup_method(self):
        """Reset module-level cache before each test."""
        import payments.crypto.rate_feed as rf

        rf._cached_rates = {}
        rf._cache_ts = 0.0

    @pytest.mark.asyncio
    async def test_get_rates_returns_dict_with_expected_coins(self):
        """get_rates() returns a dict with BTC, ETH, USDT keys."""
        mock_rates = {"BTC": 67_500.0, "ETH": 3_200.0, "USDT": 1.0}

        with patch(
            "payments.crypto.rate_feed._fetch_coingecko",
            new_callable=AsyncMock,
            return_value=mock_rates,
        ):
            from payments.crypto.rate_feed import get_rates

            rates = await get_rates(force_refresh=True)

        assert "BTC" in rates
        assert "ETH" in rates
        assert "USDT" in rates
        assert rates["BTC"] == 67_500.0

    @pytest.mark.asyncio
    async def test_get_rates_uses_cache_within_ttl(self):
        """get_rates() returns cached value without calling CoinGecko."""
        import payments.crypto.rate_feed as rf

        rf._cached_rates = {"BTC": 65_000.0, "ETH": 3_000.0, "USDT": 1.0}
        rf._cache_ts = time.monotonic()  # fresh cache

        with patch(
            "payments.crypto.rate_feed._fetch_coingecko",
            new_callable=AsyncMock,
        ) as mock_cg:
            from payments.crypto.rate_feed import get_rates

            rates = await get_rates()

        mock_cg.assert_not_called()
        assert rates["BTC"] == 65_000.0

    @pytest.mark.asyncio
    async def test_get_rates_falls_back_to_binance_on_coingecko_failure(self):
        """Falls back to Binance when CoinGecko raises."""
        binance_rates = {"BTC": 66_000.0, "ETH": 3_100.0, "USDT": 1.0}

        with (
            patch(
                "payments.crypto.rate_feed._fetch_coingecko",
                new_callable=AsyncMock,
                side_effect=Exception("CoinGecko timeout"),
            ),
            patch(
                "payments.crypto.rate_feed._fetch_binance_fallback",
                new_callable=AsyncMock,
                return_value=binance_rates,
            ),
        ):
            from payments.crypto.rate_feed import get_rates

            rates = await get_rates(force_refresh=True)

        assert rates["BTC"] == 66_000.0

    @pytest.mark.asyncio
    async def test_get_rates_uses_stale_cache_when_all_feeds_fail(self):
        """Returns stale cache when both CoinGecko and Binance fail."""
        import payments.crypto.rate_feed as rf

        rf._cached_rates = {"BTC": 64_000.0, "ETH": 2_900.0, "USDT": 1.0}
        rf._cache_ts = time.monotonic() - 999  # expired

        with (
            patch(
                "payments.crypto.rate_feed._fetch_coingecko",
                new_callable=AsyncMock,
                side_effect=Exception("down"),
            ),
            patch(
                "payments.crypto.rate_feed._fetch_binance_fallback",
                new_callable=AsyncMock,
                side_effect=Exception("down"),
            ),
        ):
            from payments.crypto.rate_feed import get_rates

            rates = await get_rates(force_refresh=True)

        assert rates["BTC"] == 64_000.0

    @pytest.mark.asyncio
    async def test_get_rates_uses_hardcoded_fallback_when_no_cache(self):
        """Returns hardcoded fallback when all feeds fail and cache is empty."""
        import payments.crypto.rate_feed as rf

        rf._cached_rates = {}
        rf._cache_ts = 0.0

        with (
            patch(
                "payments.crypto.rate_feed._fetch_coingecko",
                new_callable=AsyncMock,
                side_effect=Exception("down"),
            ),
            patch(
                "payments.crypto.rate_feed._fetch_binance_fallback",
                new_callable=AsyncMock,
                side_effect=Exception("down"),
            ),
        ):
            from payments.crypto.rate_feed import get_rates

            rates = await get_rates(force_refresh=True)

        assert "BTC" in rates
        assert rates["BTC"] > 0

    @pytest.mark.asyncio
    async def test_coin_per_usd_converts_correctly(self):
        """coin_per_usd() returns correct amount for given USD value."""
        mock_rates = {"BTC": 50_000.0, "ETH": 2_500.0, "USDT": 1.0}

        with patch(
            "payments.crypto.rate_feed._fetch_coingecko",
            new_callable=AsyncMock,
            return_value=mock_rates,
        ):
            from payments.crypto.rate_feed import coin_per_usd

            btc_amount = await coin_per_usd("BTC", 1000.0)

        assert abs(btc_amount - 0.02) < 1e-8  # 1000 / 50000 = 0.02

    @pytest.mark.asyncio
    async def test_coin_per_usd_raises_for_unsupported_coin(self):
        """coin_per_usd() raises ValueError for unknown coins."""
        from payments.crypto.rate_feed import coin_per_usd

        with pytest.raises(ValueError, match="Unsupported coin"):
            await coin_per_usd("DOGE", 100.0)

    def test_coin_per_usd_sync_uses_cached_rates(self):
        """coin_per_usd_sync() uses the in-process cache."""
        import payments.crypto.rate_feed as rf

        rf._cached_rates = {"BTC": 40_000.0}
        from payments.crypto.rate_feed import coin_per_usd_sync

        result = coin_per_usd_sync("BTC", 400.0)
        assert abs(result - 0.01) < 1e-8

    def test_coin_per_usd_sync_returns_none_for_unknown_coin(self):
        """coin_per_usd_sync() returns None for unknown coins with no fallback."""
        import payments.crypto.rate_feed as rf

        rf._cached_rates = {}
        from payments.crypto.rate_feed import coin_per_usd_sync

        result = coin_per_usd_sync("UNKNOWN", 100.0)
        assert result is None


# ── Payments API tests ────────────────────────────────────────────────────────


class TestPaymentsWebhook:
    """api/payments.py — webhook HMAC verification."""

    def _make_signature(self, secret: str, body: bytes) -> str:
        return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    def test_verify_webhook_hmac_valid_signature(self):
        """Valid HMAC signature passes verification."""

        secret = "test-webhook-secret-abc123"
        body = b'{"payment_id":"PAY_1","status":"complete"}'
        sig = self._make_signature(secret, body)

        with patch.dict(os.environ, {"CRYPTO_WEBHOOK_SECRET": secret}):
            # Re-import to pick up env var
            import api.payments as pm

            pm._WEBHOOK_SECRET = secret
            result = pm._verify_webhook_hmac(body, sig)

        assert result is True

    def test_verify_webhook_hmac_invalid_signature(self):
        """Invalid HMAC signature fails verification."""
        import api.payments as pm

        pm._WEBHOOK_SECRET = "correct-secret"
        body = b'{"payment_id":"PAY_1","status":"complete"}'
        bad_sig = "deadbeef" * 8  # wrong signature

        result = pm._verify_webhook_hmac(body, bad_sig)
        assert result is False

    def test_verify_webhook_hmac_no_secret_dev_mode(self):
        """No secret in dev mode returns True (verification skipped)."""
        import api.payments as pm

        pm._WEBHOOK_SECRET = ""  # nosec B105 - test file
        body = b'{"payment_id":"PAY_1"}'

        with patch.dict(os.environ, {"APP_ENV": "development"}):
            result = pm._verify_webhook_hmac(body, "any-sig")

        assert result is True

    def test_verify_webhook_hmac_no_secret_production_blocks(self):
        """No secret in production mode returns False."""
        import api.payments as pm

        pm._WEBHOOK_SECRET = ""  # nosec B105 - test file
        body = b'{"payment_id":"PAY_1"}'

        with patch.dict(os.environ, {"APP_ENV": "production"}):
            result = pm._verify_webhook_hmac(body, "any-sig")

        assert result is False


class TestPaymentDBHelpers:
    """api/payments.py — DB persistence helpers."""

    def _make_payment(self, payment_id: str = "PAY_test_BTC_1234") -> dict:
        now = datetime.now(UTC)
        return {
            "payment_id": payment_id,
            "user_id": "user_123",
            "plan_id": "pro_monthly",
            "currency": "BTC",
            "network": "BTC",
            "address": "bc1qtest123",
            "amount_usd": 99.0,
            "amount_crypto": 0.00147,
            "rate_usd": 67_500.0,
            "status": "pending",
            "confirmations": 0,
            "confirmations_required": 3,
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(minutes=30)).isoformat(),
        }

    def test_save_payment_logs_warning_when_db_unavailable(self, caplog):
        """_save_payment() logs a warning when DB session is None."""
        import logging

        from api.payments import _save_payment

        with (
            patch("api.payments._get_db_session", return_value=None),
            caplog.at_level(logging.WARNING, logger="api.payments"),
        ):
            _save_payment(self._make_payment())

        assert "not persisted" in caplog.text.lower() or "unavailable" in caplog.text.lower()

    def test_load_payment_returns_none_when_db_unavailable(self):
        """_load_payment() returns None when DB session is None."""
        from api.payments import _load_payment

        with patch("api.payments._get_db_session", return_value=None):
            result = _load_payment("PAY_nonexistent")

        assert result is None

    def test_save_and_load_payment_roundtrip(self):
        """_save_payment() + _load_payment() roundtrip via mock DB."""
        from api.payments import _load_payment

        payment = self._make_payment("PAY_roundtrip_001")

        # Mock DB record
        mock_record = MagicMock()
        mock_record.to_dict.return_value = payment

        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_record

        with patch("api.payments._get_db_session", return_value=mock_session):
            result = _load_payment("PAY_roundtrip_001")

        assert result is not None
        assert result["payment_id"] == "PAY_roundtrip_001"
        assert result["currency"] == "BTC"
        assert result["status"] == "pending"

    def test_update_payment_sets_fields(self):
        """_update_payment() sets the given fields on the DB record."""
        from api.payments import _update_payment

        mock_record = MagicMock()
        mock_record.payment_id = "PAY_update_001"

        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = mock_record

        with patch("api.payments._get_db_session", return_value=mock_session):
            _update_payment("PAY_update_001", status="complete", confirmations=3)

        assert mock_record.status == "complete"
        assert mock_record.confirmations == 3
        mock_session.commit.assert_called_once()

    def test_update_payment_rolls_back_on_error(self):
        """_update_payment() rolls back the session on exception."""
        from api.payments import _update_payment

        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.side_effect = Exception("DB error")

        with patch("api.payments._get_db_session", return_value=mock_session):
            _update_payment("PAY_err_001", status="failed")

        mock_session.rollback.assert_called_once()


class TestPaymentStatusAutoExpiry:
    """api/payments.py — auto-expiry on status poll."""

    @pytest.mark.asyncio
    async def test_expired_payment_status_updated(self):
        """get_payment_status() marks expired payments as 'expired'."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api.payments import router

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        expired_payment = {
            "payment_id": "PAY_expired_001",
            "user_id": "user_1",
            "plan_id": "basic",
            "currency": "BTC",
            "network": "BTC",
            "address": "bc1qtest",
            "amount_usd": 50.0,
            "amount_crypto": 0.00074,
            "rate_usd": 67_500.0,
            "status": "pending",
            "confirmations": 0,
            "confirmations_required": 3,
            "tx_hash": None,
            "created_at": (datetime.now(UTC) - timedelta(hours=2)).isoformat(),
            "expires_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
            "confirmed_at": None,
        }

        with (
            patch("api.payments._load_payment", return_value=expired_payment),
            patch("api.payments._update_payment") as mock_update,
        ):
            response = client.get("/api/payments/crypto/status/PAY_expired_001")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "expired"
        mock_update.assert_called_once_with("PAY_expired_001", status="expired")


class TestPaymentRatesEndpoint:
    """api/payments.py — GET /api/payments/crypto/rates."""

    @pytest.mark.asyncio
    async def test_rates_endpoint_returns_live_rates(self):
        """GET /crypto/rates returns live rates with correct structure."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api.payments import router

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        mock_rates = {"BTC": 67_500.0, "ETH": 3_200.0, "USDT": 1.0}

        with patch(
            "payments.crypto.rate_feed.get_rates",
            new_callable=AsyncMock,
            return_value=mock_rates,
        ):
            response = client.get("/api/payments/crypto/rates")

        assert response.status_code == 200
        data = response.json()
        assert "rates" in data
        assert "BTC" in data["rates"]
        assert data["rates"]["BTC"]["usd_per_coin"] == 67_500.0
        assert data["rates"]["BTC"]["coin_per_usd"] == round(1 / 67_500.0, 8)
        assert data["source"] == "live"

    @pytest.mark.asyncio
    async def test_rates_endpoint_returns_503_on_feed_failure(self):
        """GET /crypto/rates returns 503 when rate feed fails."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from api.payments import router

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        with patch(
            "payments.crypto.rate_feed.get_rates",
            new_callable=AsyncMock,
            side_effect=Exception("feed down"),
        ):
            response = client.get("/api/payments/crypto/rates")

        assert response.status_code == 503
