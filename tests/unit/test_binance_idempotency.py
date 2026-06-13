# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""
tests/unit/test_binance_idempotency.py
======================================
Regression: BinanceConnector.place_order sends a caller-supplied client_order_id
as newClientOrderId (so retries dedupe server-side) and treats a -2010 duplicate
response as "already submitted" rather than resubmitting (which risks a second
fill).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from brokers.base import OrderSide

BINANCE_CONFIG = {"api_key": "k", "api_secret": "s", "testnet": True}  # nosec B105  # pragma: allowlist secret


def _resp(json_data, status_code=200):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_data
    r.raise_for_status = MagicMock()
    return r


@patch("brokers.binance.requests.Session")
def test_client_order_id_sent_as_new_client_order_id(mock_session_cls):
    from brokers.binance import BinanceConnector

    sess = MagicMock()
    mock_session_cls.return_value = sess
    sess.post.return_value = _resp(
        {
            "orderId": 1,
            "origQty": "0.001",
            "executedQty": "0.001",
            "cummulativeQuoteQty": "50.0",
            "status": "FILLED",
            "price": "50000",
            "transactTime": 1704067200000,
        }
    )

    broker = BinanceConnector(BINANCE_CONFIG)
    broker.connected = True
    broker.session = sess
    broker.place_order("BTCUSDT", OrderSide.BUY, 0.001, client_order_id="hopefx-abc-123")

    _, kwargs = sess.post.call_args
    assert kwargs["params"]["newClientOrderId"] == "hopefx-abc-123"


@patch("brokers.binance.requests.Session")
def test_duplicate_order_not_resubmitted(mock_session_cls):
    from brokers.binance import BinanceConnector

    sess = MagicMock()
    mock_session_cls.return_value = sess
    # Binance duplicate-clientOrderId rejection.
    sess.post.return_value = _resp({"code": -2010, "msg": "Duplicate order sent."}, status_code=400)

    broker = BinanceConnector(BINANCE_CONFIG)
    broker.connected = True
    broker.session = sess
    out = broker.place_order("BTCUSDT", OrderSide.BUY, 0.001, client_order_id="hopefx-abc-123")

    # Already submitted on a prior attempt → no order object, and crucially the
    # duplicate was not masked into a second submission.
    assert out is None
    assert sess.post.call_count == 1
