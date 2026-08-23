# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""SuperAdmin financial sub-router (revenue, subscriptions, payments, chargebacks, tax reports, reconciliation)."""

import logging
import uuid as _uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import TokenPayload

from ._shared import RefundBody, _get_config_store, _log_superadmin_action, _require_superadmin

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Financial ─────────────────────────────────────────────────────────────────


@router.get("/financial/revenue")
async def get_revenue_stats(
    period: str = Query("mtd"),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Return real revenue KPIs from RevenueAnalytics and SubscriptionManager."""
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    period_starts = {
        "today": now.replace(hour=0, minute=0, second=0, microsecond=0),
        "mtd": now.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
        "ytd": now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0),
        "30d": now - timedelta(days=30),
        "90d": now - timedelta(days=90),
    }
    start = period_starts.get(period, period_starts["mtd"])

    mrr = arr = revenue_today = revenue_mtd = revenue_ytd = 0.0
    churn_rate_pct = ltv_avg = 0.0
    new_subs_mtd = cancelled_mtd = 0
    plan_breakdown: dict = {"free": 0.0, "starter": 0.0, "professional": 0.0, "enterprise": 0.0, "elite": 0.0}

    try:
        from monetization.analytics import revenue_analytics

        mrr = float(revenue_analytics.get_mrr())
        arr = float(revenue_analytics.get_arr())

        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        mtd_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        ytd_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)

        rev_today = revenue_analytics.get_revenue_by_period(today_start, now)
        rev_mtd = revenue_analytics.get_revenue_by_period(mtd_start, now)
        rev_ytd = revenue_analytics.get_revenue_by_period(ytd_start, now)

        revenue_today = float(sum(rev_today.values())) if isinstance(rev_today, dict) else float(rev_today or 0)
        revenue_mtd = float(sum(rev_mtd.values())) if isinstance(rev_mtd, dict) else float(rev_mtd or 0)
        revenue_ytd = float(sum(rev_ytd.values())) if isinstance(rev_ytd, dict) else float(rev_ytd or 0)

        growth = revenue_analytics.get_growth_metrics()
        churn_rate_pct = float(growth.churn_rate)
        ltv_avg = float(growth.ltv)

        tier_rev = revenue_analytics.get_revenue_by_tier(start, now)
        for tier_key, amount in tier_rev.items():
            plan_breakdown[tier_key] = float(amount)

        sub_metrics = revenue_analytics.get_subscription_metrics(mtd_start, now)
        new_subs_mtd = sub_metrics.new_subscriptions
        cancelled_mtd = sub_metrics.cancelled_subscriptions
    except Exception as exc:
        logger.debug("get_revenue_stats: analytics unavailable: %s", exc)

    if mrr == 0.0:
        try:
            from monetization.stripe_live import get_stripe_client

            client = get_stripe_client()
            if hasattr(client, "get_mrr"):
                mrr = float(client.get_mrr() or 0)
                arr = mrr * 12
        except Exception as exc:
            logger.debug("get_revenue_stats: Stripe MRR unavailable: %s", exc)

    return {
        "mrr": round(mrr, 2),
        "arr": round(arr, 2),
        "revenue_today": round(revenue_today, 2),
        "revenue_mtd": round(revenue_mtd, 2),
        "revenue_ytd": round(revenue_ytd, 2),
        "currency": "USD",
        "plan_breakdown": {k: round(v, 2) for k, v in plan_breakdown.items()},
        "churn_rate_pct": round(churn_rate_pct, 4),
        "ltv_avg": round(ltv_avg, 2),
        "new_subs_mtd": new_subs_mtd,
        "cancelled_mtd": cancelled_mtd,
    }


@router.get("/financial/subscriptions")
async def get_subscription_stats(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    import asyncio as _aio

    stats: dict = {"free": 0, "starter": 0, "professional": 0, "enterprise": 0, "elite": 0, "total": 0}
    try:
        from database.connection import SessionLocal
        from database.user_models import User

        def _count_users():
            db = SessionLocal()
            try:
                return db.query(User).count()
            finally:
                db.close()

        stats["total"] = await _aio.to_thread(_count_users)
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)
    try:
        from monetization.subscription import subscription_manager

        all_subs = (
            subscription_manager.get_all_subscriptions()
            if hasattr(subscription_manager, "get_all_subscriptions")
            else []
        )
        for sub in all_subs:
            tier = sub.tier.value if hasattr(sub.tier, "value") else str(sub.tier)
            if tier in stats:
                stats[tier] += 1
    except Exception as exc:
        logger.debug("get_subscription_stats: subscription_manager unavailable: %s", exc)
    return stats


@router.get("/financial/payments")
async def get_payment_history(
    period: str | None = Query(None),
    page: int = Query(1, ge=1),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    try:
        from api.billing import list_payments

        return await list_payments(period=period, page=page, user=user)
    except Exception as exc:
        logger.warning("get_payment_history error: %s", exc)
        return {"payments": [], "total": 0, "page": page, "page_size": 50}


@router.post("/financial/payments/{payment_id}/refund")
async def refund_payment(payment_id: str, body: RefundBody, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    _log_superadmin_action(user, "refund", f"payment={payment_id} reason={body.reason}")
    from api.billing import process_refund

    return await process_refund(payment_id=payment_id, reason=body.reason, user=user)


# ── Refund policy ─────────────────────────────────────────────────────────────
# Where a creator's money comes from when a sale is refunded after it has already
# been paid out. Three answers are defensible and the choice is the operator's,
# so it is a setting rather than a constant. See monetization/refund_policy.py.


@router.get("/financial/refund-policy")
async def get_refund_policy(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    """Return the refund policy in force plus every option and what it means.

    The option descriptions come from monetization.refund_policy rather than the
    frontend, so the wording that explains where money goes has one source.
    """
    from monetization.refund_policy import describe_policies, resolve_refund_policy

    store = _get_config_store()
    policy = resolve_refund_policy(store=store) if store is not None else resolve_refund_policy()
    return {
        "policy": policy.value,
        "options": describe_policies(),
        "applies_to": "refunds of sales that have already been settled by a payout",
        "note": (
            "Changing this affects new refunds only. The policy applied to a "
            "refund is recorded on that refund and is never re-derived."
        ),
    }


@router.put("/financial/refund-policy")
async def set_refund_policy(body: dict, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    """Set the refund policy.

    Refuses anything that is not one of the three policies, and refuses when the
    store could not persist the change. Returning success for a setting that did
    not save would leave the operator believing money is being handled one way
    while it is handled another.
    """
    from monetization.refund_policy import REFUND_POLICY_KEY, RefundPolicy, describe_policies

    raw = (body or {}).get("policy")
    try:
        policy = RefundPolicy(raw)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=422,
            detail=f"Unknown refund policy {raw!r}. Expected one of {[p.value for p in RefundPolicy]}.",
        ) from None

    store = _get_config_store()
    if store is None:
        raise HTTPException(
            status_code=503,
            detail="Configuration store unavailable — refund policy not changed.",
        )

    actor = user if isinstance(user, str) else getattr(user, "sub", "unknown")
    if not store.set(REFUND_POLICY_KEY, policy.value, changed_by=actor):
        raise HTTPException(
            status_code=503,
            detail="Configuration store rejected the write — refund policy not changed.",
        )

    # Only audited once the write is known to have landed.
    _log_superadmin_action(user, "refund_policy_change", f"policy={policy.value}")
    logger.warning("Refund policy changed to %s by %s", policy.value, actor)

    return {"policy": policy.value, "options": describe_policies()}


@router.get("/financial/affiliates")
async def get_affiliate_stats(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    from api.billing import get_affiliate_stats as _gas

    return await _gas(user=user)


# ── Chargebacks ───────────────────────────────────────────────────────────────


@router.get("/financial/chargebacks")
async def list_chargebacks(
    status: str | None = Query(None, description="Filter by status: open|won|lost|pending_evidence"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Return chargeback records from the database."""
    import asyncio as _aio

    chargebacks: list[dict] = []
    total = 0
    try:
        from database.connection import SessionLocal
        from database.models import Chargeback

        _status = status
        _offset = offset
        _limit = limit

        def _fetch():
            db = SessionLocal()
            try:
                q = db.query(Chargeback)
                if _status:
                    q = q.filter(Chargeback.status == _status)
                _total = q.count()
                rows = q.order_by(Chargeback.opened_at.desc()).offset(_offset).limit(_limit).all()
                return [r.to_dict() for r in rows], _total
            finally:
                db.close()

        chargebacks, total = await _aio.to_thread(_fetch)
    except Exception as exc:
        logger.warning("list_chargebacks DB error: %s", exc)
    return {"chargebacks": chargebacks, "total": total, "limit": limit, "offset": offset}


@router.patch("/financial/chargebacks/{chargeback_id}")
async def update_chargeback(
    chargeback_id: str,
    body: dict,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Update chargeback status (e.g. mark as won/lost after submitting evidence)."""
    import asyncio as _aio

    _log_superadmin_action(user, "chargeback_update", f"id={chargeback_id} body={body}")
    allowed_statuses = {"open", "won", "lost", "pending_evidence"}
    new_status = body.get("status")
    if new_status and new_status not in allowed_statuses:
        raise HTTPException(status_code=400, detail=f"status must be one of {allowed_statuses}")
    try:
        from database.connection import SessionLocal
        from database.models import Chargeback

        _cid = chargeback_id
        _ns = new_status

        def _update():
            db = SessionLocal()
            try:
                row = db.query(Chargeback).filter(Chargeback.chargeback_id == _cid).first()
                if not row:
                    return None
                if _ns:
                    row.status = _ns
                    if _ns in ("won", "lost"):
                        row.resolved_at = datetime.now(timezone.utc)
                db.commit()
                return row.to_dict()
            finally:
                db.close()

        result = await _aio.to_thread(_update)
        if result is None:
            raise HTTPException(status_code=404, detail="Chargeback not found")
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("update_chargeback error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to update chargeback") from None


# ── Tax Reports ───────────────────────────────────────────────────────────────


@router.get("/financial/tax-reports")
async def list_tax_reports(
    status: str | None = Query(None, description="Filter by status: draft|filed|paid|overdue"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Return tax report records from the database."""
    import asyncio as _aio

    reports: list[dict] = []
    total = 0
    try:
        from database.connection import SessionLocal
        from database.models import TaxReport

        _status = status
        _offset = offset
        _limit = limit

        def _fetch():
            db = SessionLocal()
            try:
                q = db.query(TaxReport)
                if _status:
                    q = q.filter(TaxReport.status == _status)
                _total = q.count()
                rows = q.order_by(TaxReport.created_at.desc()).offset(_offset).limit(_limit).all()
                return [r.to_dict() for r in rows], _total
            finally:
                db.close()

        reports, total = await _aio.to_thread(_fetch)
    except Exception as exc:
        logger.warning("list_tax_reports DB error: %s", exc)
    return {"reports": reports, "total": total, "limit": limit, "offset": offset}


@router.post("/financial/tax-reports")
async def create_tax_report(
    body: dict,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Create or regenerate a tax report for a given period and jurisdiction."""
    _log_superadmin_action(
        user, "tax_report_create", f"period={body.get('period')} jurisdiction={body.get('jurisdiction')}"
    )
    period = body.get("period", "")
    jurisdiction = body.get("jurisdiction", "")
    if not period or not jurisdiction:
        raise HTTPException(status_code=400, detail="period and jurisdiction are required")

    import asyncio as _aio

    try:
        from database.connection import SessionLocal
        from database.models import TaxReport

        _period = period
        _jurisdiction = jurisdiction
        _body = body

        def _upsert():
            db = SessionLocal()
            try:
                existing = (
                    db.query(TaxReport)
                    .filter(TaxReport.period == _period, TaxReport.jurisdiction == _jurisdiction)
                    .first()
                )
                if existing:
                    existing.status = _body.get("status", existing.status)
                    existing.total_revenue = _body.get("total_revenue", existing.total_revenue)
                    existing.taxable_amount = _body.get("taxable_amount", existing.taxable_amount)
                    existing.tax_rate_pct = _body.get("tax_rate_pct", existing.tax_rate_pct)
                    existing.tax_owed = _body.get("tax_owed", existing.tax_owed)
                    db.commit()
                    return existing.to_dict()

                report = TaxReport(
                    report_id=f"TAX-{_uuid.uuid4().hex[:12].upper()}",
                    period=_period,
                    jurisdiction=_jurisdiction,
                    total_revenue=float(_body.get("total_revenue", 0)),
                    taxable_amount=float(_body.get("taxable_amount", 0)),
                    tax_rate_pct=float(_body.get("tax_rate_pct", 0)),
                    tax_owed=float(_body.get("tax_owed", 0)),
                    currency=_body.get("currency", "USD"),
                    status=_body.get("status", "draft"),
                )
                db.add(report)
                db.commit()
                db.refresh(report)
                return report.to_dict()
            finally:
                db.close()

        return await _aio.to_thread(_upsert)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("create_tax_report error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to create tax report") from None


@router.patch("/financial/tax-reports/{report_id}")
async def update_tax_report(
    report_id: str,
    body: dict,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Update a tax report (e.g. mark as filed or paid)."""
    _log_superadmin_action(user, "tax_report_update", f"id={report_id} status={body.get('status')}")
    allowed_statuses = {"draft", "filed", "paid", "overdue"}
    new_status = body.get("status")
    if new_status and new_status not in allowed_statuses:
        raise HTTPException(status_code=400, detail=f"status must be one of {allowed_statuses}")
    import asyncio as _aio

    try:
        from database.connection import SessionLocal
        from database.models import TaxReport

        _rid = report_id
        _ns = new_status

        def _update():
            db = SessionLocal()
            try:
                row = db.query(TaxReport).filter(TaxReport.report_id == _rid).first()
                if not row:
                    return None
                if _ns:
                    row.status = _ns
                    if _ns == "filed":
                        row.filed_at = datetime.now(timezone.utc)
                db.commit()
                return row.to_dict()
            finally:
                db.close()

        result = await _aio.to_thread(_update)
        if result is None:
            raise HTTPException(status_code=404, detail="Tax report not found")
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("update_tax_report error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to update tax report") from None


# ── Reconciliation ────────────────────────────────────────────────────────────


@router.get("/financial/reconciliation")
async def list_reconciliation(
    status: str | None = Query(None, description="Filter: matched|discrepancy|pending|resolved"),
    provider: str | None = Query(None, description="Filter by provider: stripe|flutterwave|crypto"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Return reconciliation records from the database."""
    import asyncio as _aio

    records: list[dict] = []
    total = 0
    try:
        from database.connection import SessionLocal
        from database.models import ReconciliationRecord

        _status = status
        _provider = provider
        _offset = offset
        _limit = limit

        def _fetch():
            db = SessionLocal()
            try:
                q = db.query(ReconciliationRecord)
                if _status:
                    q = q.filter(ReconciliationRecord.status == _status)
                if _provider:
                    q = q.filter(ReconciliationRecord.provider == _provider)
                _total = q.count()
                rows = q.order_by(ReconciliationRecord.created_at.desc()).offset(_offset).limit(_limit).all()
                return [r.to_dict() for r in rows], _total
            finally:
                db.close()

        records, total = await _aio.to_thread(_fetch)
    except Exception as exc:
        logger.warning("list_reconciliation DB error: %s", exc)
    return {"records": records, "total": total, "limit": limit, "offset": offset}


@router.post("/financial/reconciliation/run")
async def run_reconciliation(
    body: dict,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Trigger a reconciliation run for a given period and provider."""
    period = body.get("period", "")
    provider = body.get("provider", "stripe")
    if not period:
        raise HTTPException(status_code=400, detail="period is required (e.g. '2025-01')")

    _log_superadmin_action(user, "reconciliation_run", f"period={period} provider={provider}")

    try:
        year, month = int(period[:4]), int(period[5:7])
        start_dt = datetime(year, month, 1, tzinfo=timezone.utc)
        if month == 12:
            end_dt = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            end_dt = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    except Exception:
        raise HTTPException(status_code=400, detail="period must be in YYYY-MM format") from None

    expected_amount = 0.0
    actual_amount = 0.0
    tx_count = 0

    try:
        from monetization.payment_processor import payment_processor, PaymentStatus

        for p in payment_processor._payments.values():
            if p.created_at and start_dt <= p.created_at < end_dt and p.status == PaymentStatus.SUCCEEDED:
                expected_amount += float(p.amount)
                tx_count += 1
    except Exception as exc:
        logger.warning("reconciliation: PaymentProcessor unavailable: %s", exc)

    if provider == "stripe":
        try:
            from monetization.stripe_live import get_stripe_client

            client = get_stripe_client()
            if hasattr(client, "list_customer_charges"):
                charges = client.list_customer_charges(user_id=None, limit=500)
                for c in charges:
                    created = c.get("created")
                    if isinstance(created, int | float):
                        dt = datetime.fromtimestamp(created, tz=timezone.utc)
                        if start_dt <= dt < end_dt and c.get("status") == "succeeded":
                            actual_amount += (c.get("amount", 0) or 0) / 100
        except Exception as exc:
            logger.warning("reconciliation: Stripe unavailable: %s", exc)

    if provider == "crypto":
        try:
            from database.connection import SessionLocal
            from database.models import CryptoPayment

            db = SessionLocal()
            try:
                rows = (
                    db.query(CryptoPayment)
                    .filter(
                        CryptoPayment.status == "complete",
                        CryptoPayment.confirmed_at >= start_dt,
                        CryptoPayment.confirmed_at < end_dt,
                    )
                    .all()
                )
                actual_amount = sum(r.amount_usd for r in rows)
                tx_count = len(rows)
            finally:
                db.close()
        except Exception as exc:
            logger.warning("reconciliation: CryptoPayment DB unavailable: %s", exc)

    discrepancy = round(actual_amount - expected_amount, 4)
    status_val = "matched" if abs(discrepancy) < 0.01 else "discrepancy"

    try:
        from database.connection import SessionLocal
        from database.models import ReconciliationRecord

        db = SessionLocal()
        try:
            existing = (
                db.query(ReconciliationRecord)
                .filter(
                    ReconciliationRecord.period == period,
                    ReconciliationRecord.provider == provider,
                )
                .first()
            )
            if existing:
                existing.expected_amount = expected_amount
                existing.actual_amount = actual_amount
                existing.discrepancy = discrepancy
                existing.transaction_count = tx_count
                existing.status = status_val
                db.commit()
                result = existing.to_dict()
            else:
                record = ReconciliationRecord(
                    recon_id=f"RECON-{_uuid.uuid4().hex[:12].upper()}",
                    period=period,
                    provider=provider,
                    expected_amount=expected_amount,
                    actual_amount=actual_amount,
                    discrepancy=discrepancy,
                    transaction_count=tx_count,
                    status=status_val,
                )
                db.add(record)
                db.commit()
                db.refresh(record)
                result = record.to_dict()
        finally:
            db.close()
    except Exception as exc:
        logger.warning("reconciliation: DB write failed: %s", exc)
        result = {
            "recon_id": f"RECON-{_uuid.uuid4().hex[:12].upper()}",
            "period": period,
            "provider": provider,
            "expected_amount": expected_amount,
            "actual_amount": actual_amount,
            "discrepancy": discrepancy,
            "transaction_count": tx_count,
            "status": status_val,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "resolved_at": None,
        }

    return result


@router.patch("/financial/reconciliation/{recon_id}")
async def resolve_reconciliation(
    recon_id: str,
    body: dict,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Mark a reconciliation record as resolved with optional notes."""
    _log_superadmin_action(user, "reconciliation_resolve", f"id={recon_id}")
    try:
        from database.connection import SessionLocal
        from database.models import ReconciliationRecord

        db = SessionLocal()
        try:
            row = db.query(ReconciliationRecord).filter(ReconciliationRecord.recon_id == recon_id).first()
            if not row:
                raise HTTPException(status_code=404, detail="Reconciliation record not found")
            row.status = "resolved"
            row.resolved_at = datetime.now(timezone.utc)
            row.resolved_by = user.sub
            if "notes" in body:
                row.notes = body["notes"]
            db.commit()
            return row.to_dict()
        finally:
            db.close()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("resolve_reconciliation error: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to resolve reconciliation record") from None


# ── Wallets ───────────────────────────────────────────────────────────────────


@router.get("/financial/wallets")
async def list_wallets(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Platform wallet balances and transaction summaries."""
    try:
        from database.connection import get_db_manager

        mgr = get_db_manager()
        if mgr:
            with mgr.session() as db:
                from database.models import WalletTransaction

                offset = (page - 1) * page_size
                rows = (
                    db.query(WalletTransaction)
                    .order_by(WalletTransaction.created_at.desc())
                    .offset(offset)
                    .limit(page_size)
                    .all()
                )
                total = db.query(WalletTransaction).count()
                wallets = [
                    {
                        "id": str(r.id),
                        "user_id": str(r.user_id) if r.user_id else None,
                        "currency": r.currency or "USD",
                        "amount": float(r.amount or 0),
                        "type": r.transaction_type or "unknown",
                        "status": r.status or "completed",
                        "created_at": r.created_at.isoformat() if r.created_at else None,
                        "reference": r.reference or "",
                    }
                    for r in rows
                ]
                return {"wallets": wallets, "total": total, "page": page, "page_size": page_size}
    except Exception as exc:
        logger.warning("wallets db: %s", exc)
    return {"wallets": [], "total": 0, "page": page, "page_size": page_size}


@router.get("/financial/payouts")
async def list_payouts(
    status: str = Query("all"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Affiliate and withdrawal payout queue."""
    try:
        from database.connection import get_db_manager

        mgr = get_db_manager()
        if mgr:
            with mgr.session() as db:
                from database.models import WalletTransaction

                q = db.query(WalletTransaction).filter(WalletTransaction.transaction_type == "payout")
                if status != "all":
                    q = q.filter(WalletTransaction.status == status)
                total = q.count()
                offset = (page - 1) * page_size
                rows = q.order_by(WalletTransaction.created_at.desc()).offset(offset).limit(page_size).all()
                # ``WalletTransaction`` has no ``metadata`` column. On a
                # declarative model ``r.metadata`` is SQLAlchemy's MetaData
                # object — truthy, so the ``if r.metadata`` guard never fired
                # and ``.get()`` raised AttributeError on the first row. The
                # outer except caught it and this endpoint returned an empty
                # payout queue no matter how many payouts were pending.
                #
                # ``method`` and ``processed_at`` were never persisted by
                # anything: payments/wallet.py writes transaction_id, type,
                # amount, balance_after, currency, reference, status and notes.
                # Reporting the columns that exist rather than inventing two.
                payouts = [
                    {
                        "id": str(r.id),
                        "transaction_id": r.transaction_id,
                        "user_id": str(r.user_id) if r.user_id else None,
                        "amount": float(r.amount or 0),
                        "currency": r.currency or "USD",
                        "status": r.status or "pending",
                        "reference": r.reference,
                        "notes": r.notes,
                        "created_at": r.created_at.isoformat() if r.created_at else None,
                    }
                    for r in rows
                ]
                return {"payouts": payouts, "total": total, "page": page, "page_size": page_size}
    except Exception as exc:
        logger.warning("payouts db: %s", exc)
    return {"payouts": [], "total": 0, "page": page, "page_size": page_size}


@router.get("/financial/fee-config")
async def get_fee_config(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    """Platform-wide fee configuration."""
    try:
        from config.config_manager import ConfigManager

        cfg = ConfigManager()
        fees = cfg.get("fees", {})
        if fees:
            return {"fees": fees}
    except Exception as exc:
        logger.debug("fee_config config_manager: %s", exc)
    # Fallback: read from the DB `configurations` table.
    #
    # This used to hand-roll its own query against Configuration.key/.value —
    # neither of which is a column (they are config_key/config_value). Building
    # that query raised AttributeError *inside* db_manager.session(), whose
    # `except Exception` books any error as a DATABASE failure; five of those
    # tripped the circuit breaker and took /api/health, /health/ready and
    # /health/deep to 503. api.db_store already owns this table correctly —
    # right column names, JSON coding, and a plain SessionLocal() that cannot
    # feed the breaker — so go through it instead of re-deriving the mapping.
    try:
        from api.db_store import db_get

        fees = db_get("fee_config")
        if fees:
            return {"fees": fees}
    except Exception as exc:
        logger.warning("fee_config db: %s", exc)
    return {
        "fees": {
            "trading_commission_pct": 0.1,
            "spread_markup_pips": 0.5,
            "withdrawal_flat_usd": 5.0,
            "inactivity_monthly_usd": 10.0,
            "overnight_swap_pct": 0.02,
            "affiliate_revenue_share_pct": 30.0,
        }
    }


@router.patch("/financial/fee-config")
async def update_fee_config(body: dict, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    """Update platform fee configuration."""
    _log_superadmin_action(user, "fee_config_update", str(body))
    # Same table, same reason as the reader above. The hand-rolled version was
    # doubly broken on write: Configuration(key=..., value=...) raises TypeError
    # because neither is a column, and `environment` is NOT NULL and was never
    # set, so the INSERT could not have succeeded either way. db_set handles all
    # of that.
    saved = False
    try:
        from api.db_store import db_set

        saved = db_set("fee_config", body, changed_by=getattr(user, "sub", "superadmin"))
    except Exception as exc:
        logger.warning("fee_config update: %s", exc)

    if not saved:
        # Reporting ok=True on a failed write told the operator their fee change
        # was live when it had not been stored at all. On a money-moving system
        # that is the wrong way to be wrong: say so and let the caller retry.
        raise HTTPException(
            status_code=503,
            detail="Fee configuration could not be persisted — not applied.",
        )
    return {"ok": True, "fees": body}
