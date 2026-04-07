# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""SuperAdmin financial sub-router (revenue, subscriptions, payments, chargebacks, tax reports, reconciliation)."""

import logging
import uuid as _uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import TokenPayload

from ._shared import RefundBody, _log_superadmin_action, _require_superadmin

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
    plan_breakdown: dict = {"free": 0.0, "starter": 0.0, "pro": 0.0, "elite": 0.0}

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
    stats: dict = {"free": 0, "starter": 0, "pro": 0, "elite": 0, "total": 0}
    try:
        from database.connection import SessionLocal
        from database.user_models import User

        db = SessionLocal()
        try:
            stats["total"] = db.query(User).count()
        finally:
            db.close()
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
    chargebacks: list[dict] = []
    total = 0
    try:
        from database.connection import SessionLocal
        from database.models import Chargeback

        db = SessionLocal()
        try:
            q = db.query(Chargeback)
            if status:
                q = q.filter(Chargeback.status == status)
            total = q.count()
            rows = q.order_by(Chargeback.opened_at.desc()).offset(offset).limit(limit).all()
            chargebacks = [r.to_dict() for r in rows]
        finally:
            db.close()
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
    _log_superadmin_action(user, "chargeback_update", f"id={chargeback_id} body={body}")
    allowed_statuses = {"open", "won", "lost", "pending_evidence"}
    new_status = body.get("status")
    if new_status and new_status not in allowed_statuses:
        raise HTTPException(status_code=400, detail=f"status must be one of {allowed_statuses}")
    try:
        from database.connection import SessionLocal
        from database.models import Chargeback

        db = SessionLocal()
        try:
            row = db.query(Chargeback).filter(Chargeback.chargeback_id == chargeback_id).first()
            if not row:
                raise HTTPException(status_code=404, detail="Chargeback not found")
            if new_status:
                row.status = new_status
                if new_status in ("won", "lost"):
                    row.resolved_at = datetime.now(timezone.utc)
            db.commit()
            return row.to_dict()
        finally:
            db.close()
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
    reports: list[dict] = []
    total = 0
    try:
        from database.connection import SessionLocal
        from database.models import TaxReport

        db = SessionLocal()
        try:
            q = db.query(TaxReport)
            if status:
                q = q.filter(TaxReport.status == status)
            total = q.count()
            rows = q.order_by(TaxReport.created_at.desc()).offset(offset).limit(limit).all()
            reports = [r.to_dict() for r in rows]
        finally:
            db.close()
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

    try:
        from database.connection import SessionLocal
        from database.models import TaxReport

        db = SessionLocal()
        try:
            existing = (
                db.query(TaxReport).filter(TaxReport.period == period, TaxReport.jurisdiction == jurisdiction).first()
            )
            if existing:
                existing.status = body.get("status", existing.status)
                existing.total_revenue = body.get("total_revenue", existing.total_revenue)
                existing.taxable_amount = body.get("taxable_amount", existing.taxable_amount)
                existing.tax_rate_pct = body.get("tax_rate_pct", existing.tax_rate_pct)
                existing.tax_owed = body.get("tax_owed", existing.tax_owed)
                db.commit()
                return existing.to_dict()

            report = TaxReport(
                report_id=f"TAX-{_uuid.uuid4().hex[:12].upper()}",
                period=period,
                jurisdiction=jurisdiction,
                total_revenue=float(body.get("total_revenue", 0)),
                taxable_amount=float(body.get("taxable_amount", 0)),
                tax_rate_pct=float(body.get("tax_rate_pct", 0)),
                tax_owed=float(body.get("tax_owed", 0)),
                currency=body.get("currency", "USD"),
                status=body.get("status", "draft"),
            )
            db.add(report)
            db.commit()
            db.refresh(report)
            return report.to_dict()
        finally:
            db.close()
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
    try:
        from database.connection import SessionLocal
        from database.models import TaxReport

        db = SessionLocal()
        try:
            row = db.query(TaxReport).filter(TaxReport.report_id == report_id).first()
            if not row:
                raise HTTPException(status_code=404, detail="Tax report not found")
            if new_status:
                row.status = new_status
                if new_status == "filed":
                    row.filed_at = datetime.now(timezone.utc)
            db.commit()
            return row.to_dict()
        finally:
            db.close()
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
    records: list[dict] = []
    total = 0
    try:
        from database.connection import SessionLocal
        from database.models import ReconciliationRecord

        db = SessionLocal()
        try:
            q = db.query(ReconciliationRecord)
            if status:
                q = q.filter(ReconciliationRecord.status == status)
            if provider:
                q = q.filter(ReconciliationRecord.provider == provider)
            total = q.count()
            rows = q.order_by(ReconciliationRecord.created_at.desc()).offset(offset).limit(limit).all()
            records = [r.to_dict() for r in rows]
        finally:
            db.close()
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
        logger.debug("reconciliation: PaymentProcessor unavailable: %s", exc)

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
            logger.debug("reconciliation: Stripe unavailable: %s", exc)

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
            logger.debug("reconciliation: CryptoPayment DB unavailable: %s", exc)

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
