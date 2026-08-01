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

import hashlib
import hmac
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

UTC = timezone.utc

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from api.auth import TokenPayload, get_current_user, require_kyc
from monetization.activation import UnknownPlanError, activate_paid_plan, resolve_plan_price_usd

# ── Withdrawal rate limit ─────────────────────────────────────────────────────
# Enforced via Depends() on the /withdraw route so it appears in OpenAPI docs
# and is applied before the handler body runs.
try:
    from rate_limiting.advanced import rate_limit_dependency as _rl_dep
    from rate_limiting_configuration import WITHDRAWAL_RATE as _WITHDRAWAL_RATE  # type: ignore[import]

    _withdraw_rate_limit = _rl_dep(_WITHDRAWAL_RATE)
except Exception:  # pragma: no cover — rate limiting optional in dev

    async def _withdraw_rate_limit(request: Request) -> None:  # type: ignore[misc]
        # Rate limiting unavailable (optional dependency not installed) — allow request
        return None


from pydantic import BaseModel, Field


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/payments", tags=["Payments"])

_CONFIRMATIONS_REQUIRED: dict[str, int] = {
    "BTC": 3,
    "ETH": 12,
    "USDT": 12,
}

ADDRESS_TTL_MINUTES = int(os.getenv("CRYPTO_ADDRESS_TTL_MINUTES", "30"))

# Defensive upper bound on a single fiat deposit/withdrawal request (USD).
# Rejects absurd / overflow inputs before they reach disbursement or ledger
# arithmetic. Tunable per-deployment; generous default leaves real flows intact.
MAX_FIAT_AMOUNT_USD = float(os.getenv("MAX_FIAT_AMOUNT_USD", "1_000_000"))

# Webhook HMAC secret — set CRYPTO_WEBHOOK_SECRET in env
_WEBHOOK_SECRET = os.getenv("CRYPTO_WEBHOOK_SECRET", "")


# ── Models ────────────────────────────────────────────────────────────────────


class AddressRequest(BaseModel):
    """Request body for generating a deposit address.

    `amount_usd` and `user_id` are deliberately absent. The price is derived from
    `plan_id` server-side and the payer comes from the auth token. Accepting the
    first let a caller set their own price; the second was already ignored in
    favour of `user.sub` but stayed declared, which reads as though it were
    honoured.
    """

    currency: str = Field(..., description="BTC | ETH | USDT")
    network: str | None = Field(None, description="For USDT: TRC20 | ERC20 | BEP20")
    plan_id: str = Field(..., description="Plan being purchased — determines the charge amount")


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
    amount_usd: float  # echo the server-derived price so the client can display it


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
    """Return a SQLAlchemy session from app_state or SessionLocal fallback."""
    try:
        from core.app_state import app_state

        if app_state and app_state.db_session_factory:
            return app_state.db_session_factory()  # pylint: disable=not-callable
    except Exception as _exc:
        logger.warning("payments: app_state db_session_factory unavailable: %s", _exc)
    try:
        from database.connection import SessionLocal

        return SessionLocal()
    except Exception as _exc2:
        logger.warning("payments: SessionLocal fallback failed: %s", _exc2)
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
async def generate_deposit_address(req: AddressRequest, user: TokenPayload = Depends(get_current_user)):
    """
    Generate a unique deposit address for the requested currency.

    Uses live rates from CoinGecko (with Binance fallback and TTL cache).
    Payment record is persisted to the database — survives pod restarts.
    """
    from payments.crypto.rate_feed import get_rates

    currency = req.currency.upper()
    if currency not in _CONFIRMATIONS_REQUIRED:
        raise HTTPException(status_code=400, detail=f"Unsupported currency: {currency}")

    # Resolve the price from the catalogue BEFORE any other work, so an invalid
    # plan fails fast and never reaches address generation.
    try:
        amount_usd = resolve_plan_price_usd(req.plan_id)
    except UnknownPlanError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    # Fetch live rate
    try:
        rates = await get_rates()
        rate_usd = rates.get(currency)
        if not rate_usd:
            raise ValueError(f"No rate for {currency}")
    except Exception as exc:
        logger.error("Rate fetch failed: %s", exc)
        raise HTTPException(status_code=503, detail="Exchange rate service unavailable") from None

    amount_crypto = amount_usd / rate_usd
    network = (req.network or currency).upper()
    now = datetime.now(UTC)
    expires_at = (now + timedelta(minutes=ADDRESS_TTL_MINUTES)).isoformat()

    try:
        # Use the AUTHENTICATED user id, never the client-supplied req.user_id
        # (IDOR: a caller could mint deposit/credit records against any account).
        address = _generate_address(currency, user.sub, network)
    except Exception as exc:
        logger.warning("Address generation failed: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Address generation unavailable — check server logs",
        ) from None

    # UUID-based payment_id eliminates timestamp collision when two requests
    # arrive in the same second (e.g. client double-tap or network retry).
    payment_id = f"PAY_{uuid.uuid4().hex}"
    payment = {
        "payment_id": payment_id,
        "currency": currency,
        "network": network,
        "address": address,
        "amount_crypto": amount_crypto,
        "amount_usd": amount_usd,
        "rate_usd": rate_usd,
        "plan_id": req.plan_id,
        "user_id": user.sub,
        "status": "pending",
        "confirmations": 0,
        "confirmations_required": _CONFIRMATIONS_REQUIRED[currency],
        "created_at": now.isoformat(),
        "expires_at": expires_at,
    }

    _save_payment(payment)

    logger.info(
        "Deposit address issued: payment_id=%s user_id=%s plan_id=%s amount_usd=%.2f currency=%s",
        payment_id,
        user.sub,
        req.plan_id,
        amount_usd,
        currency,
    )

    return AddressResponse(
        payment_id=payment_id,
        address=address,
        # `qr_code` carries the address for the CLIENT to encode locally. Do not
        # send this value to a third-party QR image service: whoever controls
        # that response controls where the customer's funds go.
        qr_code=address,
        network=network,
        amount_crypto=round(amount_crypto, 8),
        min_deposit=round(amount_crypto, 8),
        confirmations_required=_CONFIRMATIONS_REQUIRED[currency],
        expires_at=expires_at,
        rate_usd=round(rate_usd, 2),
        amount_usd=round(amount_usd, 2),
    )


@router.get("/crypto/status/{payment_id}", response_model=PaymentStatusResponse)
async def get_payment_status(payment_id: str, user: TokenPayload = Depends(get_current_user)):
    """Poll confirmation status for a pending crypto payment."""
    p = _load_payment(payment_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Payment not found")

    # Only the payer may poll their own payment. 404 rather than 403 so the route
    # cannot be used to confirm that a payment id exists.
    if p.get("user_id") and p["user_id"] != user.sub:
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
async def get_rates_endpoint(user: TokenPayload = Depends(get_current_user)):
    """Return live USD rates for supported cryptocurrencies."""
    from payments.crypto.rate_feed import get_rates

    try:
        rates = await get_rates()
    except Exception as exc:
        logger.error("Rate fetch failed: %s", exc)
        raise HTTPException(status_code=503, detail="Exchange rate service unavailable") from None

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
    """Verify HMAC-SHA256 webhook signature.

    The payment processor signs the raw request body with the shared secret
    (CRYPTO_WEBHOOK_SECRET) and sends the hex digest in X-Webhook-Signature.

    In development, set CRYPTO_WEBHOOK_VERIFY=false to bypass verification.
    In production, CRYPTO_WEBHOOK_SECRET must be set (enforced by startup_validator).
    """
    _is_prod = os.getenv("APP_ENV", "development").lower() == "production"

    if not _WEBHOOK_SECRET:
        if _is_prod:
            # startup_validator should have caught this — belt-and-suspenders
            logger.critical(
                "CRYPTO_WEBHOOK_SECRET not set in production — rejecting webhook. "
                "Set CRYPTO_WEBHOOK_SECRET to a 32+ char random hex string."
            )
            return False
        # Dev/staging: allow bypass only when explicitly opted in
        if os.getenv("CRYPTO_WEBHOOK_VERIFY", "true").lower() != "false":
            logger.error(
                "CRYPTO_WEBHOOK_SECRET not set and CRYPTO_WEBHOOK_VERIFY!=false — "
                "rejecting webhook. Set CRYPTO_WEBHOOK_VERIFY=false to bypass in dev."
            )
            return False
        logger.warning("CRYPTO_WEBHOOK_SECRET not set — HMAC check bypassed (CRYPTO_WEBHOOK_VERIFY=false)")
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

    # Idempotency guard: if the payment is already in a terminal state
    # (complete / failed / expired), do not re-process.  Duplicate webhook
    # delivery is common — payment processors retry on non-2xx or timeouts.
    #
    # This guard is also why activate_paid_plan must never raise. If activation
    # threw and we returned 5xx, the processor would retry, the row would already
    # be terminal, and the retry would skip activation entirely — losing the
    # grant silently.
    _terminal_states = {"complete", "failed", "expired"}
    if p.get("status") in _terminal_states:
        logger.info(
            "Webhook duplicate: payment_id=%s already in terminal state=%s — skipping re-processing",
            payment_id,
            p["status"],
        )
        return {"received": True, "payment_id": payment_id, "status": p["status"], "idempotent": True}

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

    # Deliver what was paid for. Until this existed, completion updated the
    # payment row and nothing else: the customer sent real cryptocurrency, saw
    # "your subscription is now active", and stayed on the Free tier.
    activated: bool | None = None
    if new_status == "complete":
        activated = activate_paid_plan(
            p.get("user_id", ""),
            p.get("plan_id", ""),
            source="crypto",
            reference=payment_id,
        )

    logger.info(
        "Webhook processed: payment_id=%s status=%s confirmations=%d tx_hash=%s activated=%s",
        payment_id,
        new_status,
        confirmations,
        tx_hash,
        activated,
    )

    return {
        "received": True,
        "payment_id": payment_id,
        "status": new_status,
        **({"subscription_activated": activated} if activated is not None else {}),
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
        net_enum = USDTNetwork[network] if network in USDTNetwork.__members__ else USDTNetwork.TRC20
        result = client.generate_deposit_address(user_id, net_enum)
        return result["address"]

    raise ValueError(f"Unsupported currency: {currency}")


# =============================================================================
# FIAT DEPOSIT / WITHDRAWAL  (Wallet.tsx)
# =============================================================================


class FiatDepositRequest(BaseModel):
    amount: float = Field(..., gt=0, le=MAX_FIAT_AMOUNT_USD, description="Amount in USD to deposit")
    method: str = Field("bank_transfer", description="Payment method: bank_transfer | card")


class FiatWithdrawRequest(BaseModel):
    amount: float = Field(..., gt=0, le=MAX_FIAT_AMOUNT_USD, description="Amount in USD to withdraw")
    destination: str = Field("bank_account", description="Destination: bank_account | card")
    bank_reference: str = Field("", description="Optional bank reference / account last-4")


@router.post(
    "/deposit",
    response_model=None,
    status_code=202,
    summary="Initiate a fiat deposit",
)
async def fiat_deposit(
    req: FiatDepositRequest,
    user: TokenPayload = Depends(get_current_user),
):
    """
    Initiate a fiat (USD) deposit.

    Returns wire / card instructions and a `DEP-…` reference.

    WARNING — NOT YET PERSISTED. Despite the reference it generates, this creates
    no deposit record: nothing is written to `wallet_transactions`, so
    `/billing/transactions` will not show it and no balance changes. The customer
    is told where to send money and the system will not recognise it arriving.
    Making this real is tracked separately; until then do not present it as a
    completed action in the UI.
    """

    # Re-import here to avoid circular at module load time
    return await _fiat_deposit_impl(req)


async def _fiat_deposit_impl(req: FiatDepositRequest) -> dict:
    provider = os.getenv("FIAT_PROVIDER", "manual")
    # UUID-based reference prevents collision when two deposits are initiated
    # in the same second (e.g. double-tap, network retry).
    reference = f"DEP-{uuid.uuid4().hex[:16].upper()}"
    logger.info(
        "Fiat deposit initiated (NOT PERSISTED): amount=%.2f method=%s ref=%s",
        req.amount,
        req.method,
        reference,
    )

    if provider == "stripe":
        try:
            import stripe

            stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
            intent = stripe.PaymentIntent.create(
                amount=int(req.amount * 100),
                currency="usd",
                payment_method_types=["card"],
                metadata={"reference": reference},
            )
            return {
                "status": "pending",
                "reference": reference,
                "client_secret": intent.client_secret,
                "provider": "stripe",
            }
        except Exception as exc:
            logger.warning("Stripe deposit failed, falling back to manual: %s", exc)

    # Manual / bank-transfer fallback
    return {
        "status": "pending",
        "reference": reference,
        "method": req.method,
        "instructions": {
            "bank_name": os.getenv("FIAT_BANK_NAME", "HOPEFX Settlement Bank"),
            "account_number": os.getenv("FIAT_ACCOUNT_NUMBER", "****"),
            "routing_number": os.getenv("FIAT_ROUTING_NUMBER", "****"),
            "reference": reference,
            "amount_usd": req.amount,
        },
        "message": f"Please transfer ${req.amount:.2f} with reference {reference}. "
        "Funds credited within 1-3 business days.",
    }


@router.post(
    "/withdraw",
    response_model=None,
    status_code=202,
    summary="Initiate a fiat withdrawal",
)
async def fiat_withdraw(
    req: FiatWithdrawRequest,
    user: TokenPayload = Depends(require_kyc),
    _rl: None = Depends(_withdraw_rate_limit),
):
    """
    Initiate a fiat (USD) withdrawal to bank account or card.

    Minimum withdrawal and KYC verification are enforced server-side.

    WARNING — NOT YET PERSISTED. No withdrawal record is created and nothing is
    queued: the response reports `status: "pending"` against a reference that
    exists only in this response body. Actual disbursement additionally requires
    FIAT_PROVIDER to be configured.
    """
    min_withdrawal = float(os.getenv("FIAT_MIN_WITHDRAWAL_USD", "10.0"))
    if req.amount < min_withdrawal:
        raise HTTPException(
            status_code=422,
            detail=f"Minimum withdrawal is ${min_withdrawal:.2f}",
        )

    reference = f"WDR-{uuid.uuid4().hex[:16].upper()}"
    logger.info(
        "Fiat withdrawal initiated (NOT PERSISTED): amount=%.2f dest=%s ref=%s",
        req.amount,
        req.destination,
        reference,
    )
    return {
        "status": "pending",
        "reference": reference,
        "destination": req.destination,
        "amount_usd": req.amount,
        "estimated_arrival": "1-5 business days",
        "message": f"Withdrawal of ${req.amount:.2f} queued with reference {reference}.",
    }
