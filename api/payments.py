# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026 Opeyemi (HACKLOVE340)
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/payments.py
===============
Crypto payment endpoints.

Routes
------
POST /api/payments/crypto/address  — generate a deposit address for BTC/ETH/USDT
GET  /api/payments/crypto/status   — check confirmation status for a pending payment
GET  /api/payments/crypto/rates    — current USD exchange rates for supported coins
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/payments", tags=["Payments"])

# In-memory pending payments store (replace with DB in production)
_pending: Dict[str, dict] = {}

# Approximate rates — replace with live feed in production
_RATES_USD: Dict[str, float] = {
    "BTC": 0.000016,  # ~$62,500/BTC
    "ETH": 0.00033,  # ~$3,000/ETH
    "USDT": 1.0,
}

_CONFIRMATIONS_REQUIRED: Dict[str, int] = {
    "BTC": 3,
    "ETH": 12,
    "USDT": 12,
}

ADDRESS_TTL_MINUTES = 30


# ── Models ────────────────────────────────────────────────────────────────────


class AddressRequest(BaseModel):
    currency: str = Field(..., description="BTC | ETH | USDT")
    network: Optional[str] = Field(None, description="For USDT: TRC20 | ERC20 | BEP20")
    plan_id: str
    amount_usd: float = Field(..., gt=0)
    user_id: str


class AddressResponse(BaseModel):
    payment_id: str
    address: str
    qr_code: str
    network: str
    amount_crypto: float
    min_deposit: float
    confirmations_required: int
    expires_at: str


class PaymentStatusResponse(BaseModel):
    payment_id: str
    status: str  # pending | confirming | complete | expired
    confirmations: int
    confirmations_required: int
    currency: str
    amount_crypto: float


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/crypto/address", response_model=AddressResponse)
async def generate_deposit_address(req: AddressRequest):
    """
    Generate a unique deposit address for the requested currency.
    Delegates to the appropriate crypto client (BTC/ETH/USDT).
    """
    currency = req.currency.upper()
    if currency not in _RATES_USD:
        raise HTTPException(status_code=400, detail=f"Unsupported currency: {currency}")

    rate = _RATES_USD[currency]
    amount_crypto = req.amount_usd * rate
    network = (req.network or currency).upper()
    expires_at = (
        datetime.now(timezone.utc) + timedelta(minutes=ADDRESS_TTL_MINUTES)
    ).isoformat()

    try:
        address = _generate_address(currency, req.user_id, network)
    except Exception as exc:
        logger.warning("Address generation failed: %s", exc)
        raise HTTPException(
            status_code=503, detail=f"Address generation unavailable: {exc}"
        )

    payment_id = f"PAY_{req.user_id}_{currency}_{int(time.time())}"
    _pending[payment_id] = {
        "payment_id": payment_id,
        "currency": currency,
        "network": network,
        "address": address,
        "amount_crypto": amount_crypto,
        "amount_usd": req.amount_usd,
        "plan_id": req.plan_id,
        "user_id": req.user_id,
        "status": "pending",
        "confirmations": 0,
        "confirmations_required": _CONFIRMATIONS_REQUIRED[currency],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": expires_at,
    }

    return AddressResponse(
        payment_id=payment_id,
        address=address,
        qr_code=address,
        network=network,
        amount_crypto=round(amount_crypto, 8),
        min_deposit=round(amount_crypto, 8),
        confirmations_required=_CONFIRMATIONS_REQUIRED[currency],
        expires_at=expires_at,
    )


@router.get("/crypto/status/{payment_id}", response_model=PaymentStatusResponse)
async def get_payment_status(payment_id: str):
    """Poll confirmation status for a pending crypto payment."""
    if payment_id not in _pending:
        raise HTTPException(status_code=404, detail="Payment not found")
    p = _pending[payment_id]
    return PaymentStatusResponse(
        payment_id=payment_id,
        status=p["status"],
        confirmations=p["confirmations"],
        confirmations_required=p["confirmations_required"],
        currency=p["currency"],
        amount_crypto=p["amount_crypto"],
    )


@router.get("/crypto/rates")
async def get_rates():
    """Return current USD rates for supported cryptocurrencies."""
    return {
        "rates": {
            k: {"usd_per_coin": round(1 / v, 2), "coin_per_usd": v}
            for k, v in _RATES_USD.items()
        },
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Address generation helpers ────────────────────────────────────────────────


def _generate_address(currency: str, user_id: str, network: str) -> str:
    """Delegate to the appropriate crypto client."""
    if currency == "BTC":
        from payments.crypto.bitcoin import BitcoinClient

        client = BitcoinClient()
        result = client.generate_deposit_address(user_id)
        return result["address"]

    if currency == "ETH":
        from payments.crypto.ethereum import EthereumClient

        client = EthereumClient()
        result = client.generate_deposit_address(user_id)
        return result["address"]

    if currency == "USDT":
        from payments.crypto.usdt import USDTClient, USDTNetwork

        client = USDTClient()
        net_enum = (
            USDTNetwork[network]
            if network in USDTNetwork.__members__
            else USDTNetwork.TRC20
        )
        result = client.generate_deposit_address(user_id, net_enum)
        return result["address"]

    raise ValueError(f"Unsupported currency: {currency}")
