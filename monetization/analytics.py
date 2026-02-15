"""
Revenue Analytics Module

This module provides:
- Revenue tracking and reporting
- Subscription analytics
- Commission analytics
- Affiliate program analytics
- Marketplace analytics
- Growth metrics and projections
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, Dict, List, Any
from enum import Enum
from dataclasses import dataclass

from .pricing import SubscriptionTier, BillingCycle

logger = logging.getLogger(__name__)


class RevenueSource(str, Enum):
    """Revenue source categories"""
    SUBSCRIPTION = "subscription"
    COMMISSION = "commission"
    MARKETPLACE = "marketplace"
    AFFILIATE = "affiliate"
    ONE_TIME = "one_time"


class TimePeriod(str, Enum):
    """Time period for analytics"""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


@dataclass
class RevenueMetric:
    """Revenue metric data point"""
    period_start: datetime
    period_end: datetime
    source: RevenueSource
    amount: Decimal
    count: int
    metadata: Dict[str, Any]


@dataclass
class GrowthMetrics:
    """Growth-related metrics"""
    mrr: Decimal  # Monthly Recurring Revenue
    arr: Decimal  # Annual Recurring Revenue
    mrr_growth_rate: float  # Month-over-month growth
    churn_rate: float
    ltv: Decimal  # Customer Lifetime Value
    cac: Decimal  # Customer Acquisition Cost
    ltv_cac_ratio: float
    net_revenue_retention: float


@dataclass
class SubscriptionMetrics:
    """Subscription-related metrics"""
    total_subscriptions: int
    active_subscriptions: int
    new_subscriptions: int
    cancelled_subscriptions: int
    churned_subscriptions: int
    upgrades: int
    downgrades: int
    tier_distribution: Dict[str, int]
    avg_subscription_value: Decimal


class RevenueEntry:
    """Single revenue entry"""

    def __init__(
        self,
        entry_id: str,
        source: RevenueSource,
        amount: Decimal,
        user_id: Optional[str] = None,
        tier: Optional[SubscriptionTier] = None,
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.entry_id = entry_id
        self.source = source
        self.amount = amount
        self.user_id = user_id
        self.tier = tier
        self.description = description
        self.metadata = metadata or {}
        self.created_at = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'entry_id': self.entry_id,
            'source': self.source.value,
            'amount': float(self.amount),
            'user_id': self.user_id,
            'tier': self.tier.value if self.tier else None,
            'description': self.description,
            'metadata': self.metadata,
            'created_at': self.created_at.isoformat()
        }


class RevenueAnalytics:
    """Revenue analytics and reporting"""

    def __init__(self):
        self._entries: Dict[str, RevenueEntry] = {}
        self._subscription_events: List[Dict[str, Any]] = []
        self._daily_snapshots: Dict[str, Dict[str, Any]] = {}

    def record_revenue(
        self,
        source: RevenueSource,
        amount: Decimal,
        user_id: Optional[str] = None,
        tier: Optional[SubscriptionTier] = None,
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None
    ) -> RevenueEntry:
        """Record a revenue entry"""
        import uuid

        entry_id = f"REV-{uuid.uuid4().hex[:12].upper()}"
        
        entry = RevenueEntry(
            entry_id=entry_id,
            source=source,
            amount=amount,
            user_id=user_id,
            tier=tier,
            description=description,
            metadata=metadata
        )

        self._entries[entry_id] = entry
        
        # Update daily snapshot
        self._update_daily_snapshot(entry)
        
        logger.info(f"Recorded revenue: {source.value} - ${amount}")
        return entry

    def record_subscription_event(
        self,
        event_type: str,
        user_id: str,
        tier: SubscriptionTier,
        billing_cycle: BillingCycle,
        amount: Decimal,
        previous_tier: Optional[SubscriptionTier] = None
    ) -> None:
        """Record subscription event (new, upgrade, downgrade, cancel)"""
        event = {
            'event_type': event_type,
            'user_id': user_id,
            'tier': tier.value,
            'billing_cycle': billing_cycle.value,
            'amount': float(amount),
            'previous_tier': previous_tier.value if previous_tier else None,
            'timestamp': datetime.utcnow().isoformat()
        }
        self._subscription_events.append(event)
        
        # Record revenue for new/upgrade subscriptions
        if event_type in ['new', 'upgrade', 'renewal']:
            self.record_revenue(
                source=RevenueSource.SUBSCRIPTION,
                amount=amount,
                user_id=user_id,
                tier=tier,
                description=f"Subscription {event_type}",
                metadata={'billing_cycle': billing_cycle.value}
            )

    def _update_daily_snapshot(self, entry: RevenueEntry) -> None:
        """Update daily revenue snapshot"""
        date_key = entry.created_at.strftime('%Y-%m-%d')
        
        if date_key not in self._daily_snapshots:
            self._daily_snapshots[date_key] = {
                'date': date_key,
                'total_revenue': Decimal("0.00"),
                'by_source': {},
                'by_tier': {},
                'transaction_count': 0
            }

        snapshot = self._daily_snapshots[date_key]
        snapshot['total_revenue'] += entry.amount
        snapshot['transaction_count'] += 1

        # Update by source
        source_key = entry.source.value
        if source_key not in snapshot['by_source']:
            snapshot['by_source'][source_key] = Decimal("0.00")
        snapshot['by_source'][source_key] += entry.amount

        # Update by tier
        if entry.tier:
            tier_key = entry.tier.value
            if tier_key not in snapshot['by_tier']:
                snapshot['by_tier'][tier_key] = Decimal("0.00")
            snapshot['by_tier'][tier_key] += entry.amount

    def get_revenue_by_period(
        self,
        period: TimePeriod,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        source: Optional[RevenueSource] = None
    ) -> List[RevenueMetric]:
        """Get revenue aggregated by time period"""
        entries = list(self._entries.values())
        
        # Filter by date range
        if start_date:
            entries = [e for e in entries if e.created_at >= start_date]
        if end_date:
            entries = [e for e in entries if e.created_at <= end_date]
        if source:
            entries = [e for e in entries if e.source == source]

        # Group by period
        grouped: Dict[str, List[RevenueEntry]] = {}
        
        for entry in entries:
            if period == TimePeriod.DAILY:
                key = entry.created_at.strftime('%Y-%m-%d')
            elif period == TimePeriod.WEEKLY:
                # ISO week
                key = entry.created_at.strftime('%Y-W%W')
            elif period == TimePeriod.MONTHLY:
                key = entry.created_at.strftime('%Y-%m')
            elif period == TimePeriod.QUARTERLY:
                quarter = (entry.created_at.month - 1) // 3 + 1
                key = f"{entry.created_at.year}-Q{quarter}"
            else:  # YEARLY
                key = str(entry.created_at.year)

            if key not in grouped:
                grouped[key] = []
            grouped[key].append(entry)

        # Create metrics
        metrics = []
        for period_key, period_entries in sorted(grouped.items()):
            total_amount = sum(e.amount for e in period_entries)
            source_breakdown = {}
            for e in period_entries:
                src = e.source.value
                if src not in source_breakdown:
                    source_breakdown[src] = Decimal("0.00")
                source_breakdown[src] += e.amount

            metrics.append(RevenueMetric(
                period_start=min(e.created_at for e in period_entries),
                period_end=max(e.created_at for e in period_entries),
                source=source or RevenueSource.SUBSCRIPTION,
                amount=total_amount,
                count=len(period_entries),
                metadata={'breakdown': {k: float(v) for k, v in source_breakdown.items()}}
            ))

        return metrics

    def get_mrr(self, as_of: Optional[datetime] = None) -> Decimal:
        """Calculate Monthly Recurring Revenue"""
        as_of = as_of or datetime.utcnow()
        
        # Get subscription revenue from last 30 days
        start_date = as_of - timedelta(days=30)
        
        subscription_entries = [
            e for e in self._entries.values()
            if (e.source == RevenueSource.SUBSCRIPTION and
                e.created_at >= start_date and
                e.created_at <= as_of)
        ]
        
        return sum(e.amount for e in subscription_entries)

    def get_arr(self, as_of: Optional[datetime] = None) -> Decimal:
        """Calculate Annual Recurring Revenue"""
        return self.get_mrr(as_of) * 12

    def get_growth_metrics(self) -> GrowthMetrics:
        """Get comprehensive growth metrics"""
        now = datetime.utcnow()
        
        # Current MRR
        current_mrr = self.get_mrr(now)
        
        # Previous month MRR
        previous_mrr = self.get_mrr(now - timedelta(days=30))
        
        # MRR growth rate
        mrr_growth = (
            float((current_mrr - previous_mrr) / previous_mrr * 100)
            if previous_mrr > 0 else 0.0
        )
        
        # Calculate churn from subscription events
        total_subs = len([
            e for e in self._subscription_events 
            if e['event_type'] == 'new'
        ])
        cancelled = len([
            e for e in self._subscription_events 
            if e['event_type'] == 'cancel'
        ])
        churn_rate = (cancelled / total_subs * 100) if total_subs > 0 else 0.0

        # Estimate LTV (simplified)
        avg_revenue_per_user = current_mrr / max(total_subs - cancelled, 1)
        avg_lifetime_months = 12 / max(churn_rate / 100, 0.01)  # Avoid division by zero
        ltv = avg_revenue_per_user * Decimal(str(min(avg_lifetime_months, 60)))

        # Placeholder CAC (would come from marketing data)
        cac = Decimal("500.00")

        return GrowthMetrics(
            mrr=current_mrr,
            arr=current_mrr * 12,
            mrr_growth_rate=mrr_growth,
            churn_rate=churn_rate,
            ltv=ltv,
            cac=cac,
            ltv_cac_ratio=float(ltv / cac) if cac > 0 else 0.0,
            net_revenue_retention=100 - churn_rate + mrr_growth
        )

    def get_subscription_metrics(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> SubscriptionMetrics:
        """Get subscription-related metrics"""
        events = self._subscription_events
        
        if start_date:
            events = [
                e for e in events 
                if datetime.fromisoformat(e['timestamp']) >= start_date
            ]
        if end_date:
            events = [
                e for e in events 
                if datetime.fromisoformat(e['timestamp']) <= end_date
            ]

        new_subs = len([e for e in events if e['event_type'] == 'new'])
        cancelled = len([e for e in events if e['event_type'] == 'cancel'])
        upgrades = len([e for e in events if e['event_type'] == 'upgrade'])
        downgrades = len([e for e in events if e['event_type'] == 'downgrade'])

        # Tier distribution
        tier_dist = {}
        for tier in SubscriptionTier:
            tier_dist[tier.value] = len([
                e for e in events 
                if e['event_type'] == 'new' and e['tier'] == tier.value
            ])

        # Average subscription value
        sub_entries = [
            e for e in self._entries.values()
            if e.source == RevenueSource.SUBSCRIPTION
        ]
        avg_value = (
            sum(e.amount for e in sub_entries) / len(sub_entries)
            if sub_entries else Decimal("0.00")
        )

        return SubscriptionMetrics(
            total_subscriptions=new_subs,
            active_subscriptions=new_subs - cancelled,
            new_subscriptions=new_subs,
            cancelled_subscriptions=cancelled,
            churned_subscriptions=cancelled,
            upgrades=upgrades,
            downgrades=downgrades,
            tier_distribution=tier_dist,
            avg_subscription_value=avg_value
        )

    def get_revenue_by_source(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, Decimal]:
        """Get revenue breakdown by source"""
        entries = list(self._entries.values())
        
        if start_date:
            entries = [e for e in entries if e.created_at >= start_date]
        if end_date:
            entries = [e for e in entries if e.created_at <= end_date]

        breakdown = {}
        for source in RevenueSource:
            source_entries = [e for e in entries if e.source == source]
            breakdown[source.value] = sum(e.amount for e in source_entries)

        return breakdown

    def get_revenue_by_tier(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, Decimal]:
        """Get revenue breakdown by subscription tier"""
        entries = [
            e for e in self._entries.values()
            if e.tier is not None
        ]
        
        if start_date:
            entries = [e for e in entries if e.created_at >= start_date]
        if end_date:
            entries = [e for e in entries if e.created_at <= end_date]

        breakdown = {}
        for tier in SubscriptionTier:
            tier_entries = [e for e in entries if e.tier == tier]
            breakdown[tier.value] = sum(e.amount for e in tier_entries)

        return breakdown

    def get_top_customers(
        self,
        limit: int = 10,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """Get top customers by revenue"""
        entries = [e for e in self._entries.values() if e.user_id]
        
        if start_date:
            entries = [e for e in entries if e.created_at >= start_date]
        if end_date:
            entries = [e for e in entries if e.created_at <= end_date]

        # Aggregate by user
        user_revenue: Dict[str, Decimal] = {}
        for entry in entries:
            if entry.user_id not in user_revenue:
                user_revenue[entry.user_id] = Decimal("0.00")
            user_revenue[entry.user_id] += entry.amount

        # Sort and return top customers
        sorted_users = sorted(
            user_revenue.items(),
            key=lambda x: x[1],
            reverse=True
        )

        return [
            {
                'rank': idx + 1,
                'user_id': user_id,
                'total_revenue': float(amount)
            }
            for idx, (user_id, amount) in enumerate(sorted_users[:limit])
        ]

    def get_cohort_analysis(
        self,
        cohort_period: TimePeriod = TimePeriod.MONTHLY
    ) -> Dict[str, Any]:
        """Get cohort analysis for subscription retention"""
        # Group users by signup cohort
        cohorts: Dict[str, List[str]] = {}
        
        for event in self._subscription_events:
            if event['event_type'] != 'new':
                continue
                
            timestamp = datetime.fromisoformat(event['timestamp'])
            if cohort_period == TimePeriod.MONTHLY:
                cohort_key = timestamp.strftime('%Y-%m')
            elif cohort_period == TimePeriod.WEEKLY:
                cohort_key = timestamp.strftime('%Y-W%W')
            else:
                cohort_key = timestamp.strftime('%Y-%m-%d')

            if cohort_key not in cohorts:
                cohorts[cohort_key] = []
            cohorts[cohort_key].append(event['user_id'])

        # Calculate retention for each cohort
        cohort_retention = {}
        for cohort_key, users in cohorts.items():
            # Find cancellations
            cancelled_users = set()
            for event in self._subscription_events:
                if event['event_type'] == 'cancel' and event['user_id'] in users:
                    cancelled_users.add(event['user_id'])

            retained = len(users) - len(cancelled_users)
            retention_rate = (retained / len(users) * 100) if users else 0

            cohort_retention[cohort_key] = {
                'total_users': len(users),
                'retained_users': retained,
                'churned_users': len(cancelled_users),
                'retention_rate': retention_rate
            }

        return {
            'cohort_period': cohort_period.value,
            'cohorts': cohort_retention
        }

    def generate_report(
        self,
        period: TimePeriod = TimePeriod.MONTHLY,
        include_projections: bool = True
    ) -> Dict[str, Any]:
        """Generate comprehensive revenue report"""
        now = datetime.utcnow()
        
        # Determine date range based on period
        if period == TimePeriod.DAILY:
            start_date = now - timedelta(days=1)
        elif period == TimePeriod.WEEKLY:
            start_date = now - timedelta(weeks=1)
        elif period == TimePeriod.MONTHLY:
            start_date = now - timedelta(days=30)
        elif period == TimePeriod.QUARTERLY:
            start_date = now - timedelta(days=90)
        else:
            start_date = now - timedelta(days=365)

        growth = self.get_growth_metrics()
        subs = self.get_subscription_metrics(start_date, now)
        revenue_by_source = self.get_revenue_by_source(start_date, now)
        revenue_by_tier = self.get_revenue_by_tier(start_date, now)
        top_customers = self.get_top_customers(5, start_date, now)

        report = {
            'generated_at': now.isoformat(),
            'period': period.value,
            'date_range': {
                'start': start_date.isoformat(),
                'end': now.isoformat()
            },
            'summary': {
                'mrr': float(growth.mrr),
                'arr': float(growth.arr),
                'mrr_growth_rate': growth.mrr_growth_rate,
                'churn_rate': growth.churn_rate,
                'ltv': float(growth.ltv),
                'ltv_cac_ratio': growth.ltv_cac_ratio
            },
            'subscriptions': {
                'total': subs.total_subscriptions,
                'active': subs.active_subscriptions,
                'new': subs.new_subscriptions,
                'cancelled': subs.cancelled_subscriptions,
                'upgrades': subs.upgrades,
                'downgrades': subs.downgrades,
                'tier_distribution': subs.tier_distribution,
                'avg_value': float(subs.avg_subscription_value)
            },
            'revenue': {
                'by_source': {k: float(v) for k, v in revenue_by_source.items()},
                'by_tier': {k: float(v) for k, v in revenue_by_tier.items()},
                'total': float(sum(revenue_by_source.values()))
            },
            'top_customers': top_customers
        }

        if include_projections:
            # Simple linear projection
            monthly_growth_rate = 1 + (growth.mrr_growth_rate / 100)
            projections = []
            projected_mrr = float(growth.mrr)
            
            for month in range(1, 13):
                projected_mrr *= monthly_growth_rate
                projections.append({
                    'month': month,
                    'projected_mrr': round(projected_mrr, 2),
                    'projected_arr': round(projected_mrr * 12, 2)
                })
            
            report['projections'] = projections

        return report

    def get_dashboard_data(self) -> Dict[str, Any]:
        """Get data for revenue dashboard"""
        growth = self.get_growth_metrics()
        now = datetime.utcnow()
        
        # Get daily revenue for last 30 days
        daily_revenue = []
        for i in range(30):
            date = now - timedelta(days=i)
            date_key = date.strftime('%Y-%m-%d')
            snapshot = self._daily_snapshots.get(date_key, {
                'total_revenue': Decimal("0.00"),
                'transaction_count': 0
            })
            daily_revenue.append({
                'date': date_key,
                'revenue': float(snapshot.get('total_revenue', Decimal("0.00"))),
                'transactions': snapshot.get('transaction_count', 0)
            })

        return {
            'mrr': float(growth.mrr),
            'arr': float(growth.arr),
            'growth_rate': growth.mrr_growth_rate,
            'churn_rate': growth.churn_rate,
            'ltv_cac_ratio': growth.ltv_cac_ratio,
            'daily_revenue': list(reversed(daily_revenue)),
            'revenue_by_source': {
                k: float(v) 
                for k, v in self.get_revenue_by_source(
                    now - timedelta(days=30), now
                ).items()
            }
        }


# Global revenue analytics instance
revenue_analytics = RevenueAnalytics()
