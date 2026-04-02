# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
api/payments.py
===============
Crypto payment endpoints — DB-backed, live rate feed, webhook verification.

Routes
------
POST /api/payments/crypto/address          — generate a deposit address
GET  /api/payments/crypto/status/{id}      — poll confirmation status
GET  /api/payments/crypto/rates            — live USD exchange rates
POST /api/payments/webhook                 — on-chain confirmation callback
                                             (HMAC-SHA256 verified)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

UTC = timezone.utc

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/payments", tags=["Payments"])

_CONFIRMATIONS_REQUIRED: dict[str, int] = {
    "BTC": 3,
    "ETH": 12,
    "USDT": 12,
}

ADDRESS_TTL_MINUTES = int(os.getenv("CRYPTO_ADDRESS_TTL_MINUTES", "30"))

# Webhook HMAC secret — set CRYPTO_WEBHOOK_SECRET in env
_WEBHOOK_SECRET = os.getenv("CRYPTO_WEBHOOK_SECRET", "")


# ── Models ────────────────────────────────────────────────────────────────────


class AddressRequest(BaseModel):
    currency: str = Field(..., description="BTC | ETH | USDT")
    network: str | None = Field(None, description="For USDT: TRC20 | ERC20 | BEP20")
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
    rate_usd: float


class PaymentStatusResponse(BaseModel):
    payment_id: str
    status: str  # pending | confirming | complete | expired | failed
    confirmations: int
    confirmations_required: int
    currency: str
    amount_crypto: float
    tx_hash: str | None = None


# ── DB helpers ────────────────────────────────────────────────────────────────


def _get_db_session():
    """Return a SQLAlchemy session from the global app_state, or None."""
    try:
        from app import app_state

        if app_state and app_state.db_session_factory:
            return app_state.db_session_factory()  # pylint: disable=not-callable
    except Exception as _exc:
        logger.debug("Suppressed exception: %s", _exc)
    return None


def _save_payment(payment: dict) -> None:
    """Persist a new payment record to the database."""
    session = _get_db_session()
    if session is None:
        logger.warning("DB unavailable — payment %s not persisted", payment["payment_id"])
        return
    try:
        from database.models import CryptoPayment

        record = CryptoPayment(
            payment_id=payment["payment_id"],
            user_id=payment["user_id"],
            plan_id=payment["plan_id"],
            currency=payment["currency"],
            network=payment["network"],
            address=payment["address"],
            amount_usd=payment["amount_usd"],
            amount_crypto=payment["amount_crypto"],
            rate_usd=payment["rate_usd"],
            status=payment["status"],
            confirmations=payment["confirmations"],
            confirmations_required=payment["confirmations_required"],
            expires_at=datetime.fromisoformat(payment["expires_at"]),
        )
        session.add(record)
        session.commit()
    except Exception as exc:
        session.rollback()
        logger.error("Failed to persist payment %s: %s", payment["payment_id"], exc)
    finally:
        session.close()


def _load_payment(payment_id: str) -> dict | None:
    """Load a payment record from the database."""
    session = _get_db_session()
    if session is None:
        return None
    try:
        from database.models import CryptoPayment

        record = session.query(CryptoPayment).filter(CryptoPayment.payment_id == payment_id).first()
        if record is None:
            return None
        return record.to_dict()
    except Exception as exc:
        logger.error("Failed to load payment %s: %s", payment_id, exc)
        return None
    finally:
        session.close()


def _update_payment(payment_id: str, **kwargs) -> None:
    """Update fields on an existing payment record."""
    session = _get_db_session()
    if session is None:
        return
    try:
        from database.models import CryptoPayment

        record = session.query(CryptoPayment).filter(CryptoPayment.payment_id == payment_id).first()
        if record is None:
            return
        for key, value in kwargs.items():
            setattr(record, key, value)
        session.commit()
    except Exception as exc:
        session.rollback()
        logger.error("Failed to update payment %s: %s", payment_id, exc)
    finally:
        session.close()


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/crypto/address", response_model=AddressResponse)
async def generate_deposit_address(req: AddressRequest):
    """
    Generate a unique deposit address for the requested currency.

    Uses live rates from CoinGecko (with Binance fallback and TTL cache).
    Payment record is persisted to the database — survives pod restarts.
    """
    from payments.crypto.rate_feed import get_rates

    currency = req.currency.upper()
    if currency not in _CONFIRMATIONS_REQUIRED:
        raise HTTPException(status_code=400, detail=f"Unsupported currency: {currency}")

    # Fetch live rate
    try:
        rates = await get_rates()
        rate_usd = rates.get(currency)
        if not rate_usd:
            raise ValueError(f"No rate for {currency}")
    except Exception as exc:
        logger.error("Rate fetch failed: %s", exc)
        raise HTTPException(status_code=503, detail="Exchange rate service unavailable") from exc

    amount_crypto = req.amount_usd / rate_usd
    network = (req.network or currency).upper()
    now = datetime.now(UTC)
    expires_at = (now + timedelta(minutes=ADDRESS_TTL_MINUTES)).isoformat()

    try:
        address = _generate_address(currency, req.user_id, network)
    except Exception as exc:
        logger.warning("Address generation failed: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=f"Address generation unavailable: {exc}",
        ) from exc

    payment_id = f"PAY_{req.user_id}_{currency}_{int(time.time())}"
    payment = {
        "payment_id": payment_id,
        "currency": currency,
        "network": network,
        "address": address,
        "amount_crypto": amount_crypto,
        "amount_usd": req.amount_usd,
        "rate_usd": rate_usd,
        "plan_id": req.plan_id,
        "user_id": req.user_id,
        "status": "pending",
        "confirmations": 0,
        "confirmations_required": _CONFIRMATIONS_REQUIRED[currency],
        "created_at": now.isoformat(),
        "expires_at": expires_at,
    }

    _save_payment(payment)

    return AddressResponse(
        payment_id=payment_id,
        address=address,
        qr_code=address,
        network=network,
        amount_crypto=round(amount_crypto, 8),
        min_deposit=round(amount_crypto, 8),
        confirmations_required=_CONFIRMATIONS_REQUIRED[currency],
        expires_at=expires_at,
        rate_usd=round(rate_usd, 2),
    )


@router.get("/crypto/status/{payment_id}", response_model=PaymentStatusResponse)
async def get_payment_status(payment_id: str):
    """Poll confirmation status for a pending crypto payment."""
    p = _load_payment(payment_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Payment not found")

    # Auto-expire
    if p["status"] == "pending" and p.get("expires_at"):
        expires = datetime.fromisoformat(p["expires_at"])
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        if datetime.now(UTC) > expires:
            _update_payment(payment_id, status="expired")
            p["status"] = "expired"

    return PaymentStatusResponse(
        payment_id=payment_id,
        status=p["status"],
        confirmations=p["confirmations"],
        confirmations_required=p["confirmations_required"],
        currency=p["currency"],
        amount_crypto=p["amount_crypto"],
        tx_hash=p.get("tx_hash"),
    )


@router.get("/crypto/rates")
async def get_rates_endpoint():
    """Return live USD rates for supported cryptocurrencies."""
    from payments.crypto.rate_feed import get_rates

    try:
        rates = await get_rates()
    except Exception as exc:
        logger.error("Rate fetch failed: %s", exc)
        raise HTTPException(status_code=503, detail="Exchange rate service unavailable") from exc

    return {
        "rates": {
            coin: {
                "usd_per_coin": round(price, 2),
                "coin_per_usd": round(1 / price, 8) if price else None,
            }
            for coin, price in rates.items()
        },
        "updated_at": datetime.now(UTC).isoformat(),
        "source": "live",
    }


# ── Webhook endpoint ──────────────────────────────────────────────────────────


def _verify_webhook_hmac(body: bytes, signature: str) -> bool:
    """
    Verify HMAC-SHA256 webhook signature.

    The payment processor signs the raw request body with the shared secret
    (CRYPTO_WEBHOOK_SECRET) and sends the hex digest in X-Webhook-Signature.
    """
    if not _WEBHOOK_SECRET:
        # In production, require the secret to be set
        if os.getenv("APP_ENV", "development") == "production":
            logger.error("CRYPTO_WEBHOOK_SECRET not set in production — rejecting webhook")
            return False
        logger.warning("CRYPTO_WEBHOOK_SECRET not set — skipping HMAC check (dev only)")
        return True

    expected = hmac.new(_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.lower())


@router.post("/webhook", include_in_schema=True, tags=["Payments"])
async def payment_webhook(
    request: Request,
    x_webhook_signature: str | None = Header(None, alias="X-Webhook-Signature"),
):
    """
    Receive on-chain confirmation callbacks from a crypto payment processor
    (BitPay, Coinbase Commerce, or custom).

    Authentication
    --------------
    HMAC-SHA256 over the raw request body using CRYPTO_WEBHOOK_SECRET.
    Signature is passed in the X-Webhook-Signature header (hex digest).
    Set CRYPTO_WEBHOOK_VERIFY=false to disable verification in development.

    Expected payload
    ----------------
    {
        "payment_id": "PAY_...",
        "status": "confirming" | "complete" | "failed",
        "confirmations": 3,
        "tx_hash": "0xabc..."
    }
    """
    raw_body = await request.body()

    verify = os.getenv("CRYPTO_WEBHOOK_VERIFY", "true").lower() != "false"
    if verify:
        if not x_webhook_signature:
            raise HTTPException(status_code=403, detail="Missing X-Webhook-Signature header")
        if not _verify_webhook_hmac(raw_body, x_webhook_signature):
            logger.critical(
                "Crypto webhook SIGNATURE INVALID from %s",
                request.client.host if request.client else "unknown",
            )
            raise HTTPException(status_code=403, detail="Invalid webhook signature")

    try:
        payload = json.loads(raw_body)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from None

    payment_id = payload.get("payment_id")
    if not payment_id:
        raise HTTPException(status_code=400, detail="Missing payment_id in payload")

    p = _load_payment(payment_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Payment not found")

    new_status = payload.get("status", p["status"])
    confirmations = int(payload.get("confirmations", p["confirmations"]))
    tx_hash = payload.get("tx_hash")

    update_kwargs: dict = {
        "status": new_status,
        "confirmations": confirmations,
        "webhook_payload": json.dumps(payload),
    }
    if tx_hash:
        update_kwargs["tx_hash"] = tx_hash
    if new_status == "complete":
        update_kwargs["confirmed_at"] = datetime.now(UTC)

    _update_payment(payment_id, **update_kwargs)

    logger.info(
        "Webhook processed: payment_id=%s status=%s confirmations=%d tx_hash=%s",
        payment_id,
        new_status,
        confirmations,
        tx_hash,
    )

    return {"received": True, "payment_id": payment_id, "status": new_status}


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
        net_enum = USDTNetwork[network] if network in USDTNetwork.__members__ else USDTNetwork.TRC20
        result = client.generate_deposit_address(user_id, net_enum)
        return result["address"]

    raise ValueError(f"Unsupported currency: {currency}")
