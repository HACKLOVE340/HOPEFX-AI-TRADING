"""What an affiliate is owed must outlive the process that recorded it.

F31/F32 had two halves. The money-conservation half landed first: commissions
are now conserved and serialised, `commission_paid` is an amount rather than a
flag, and both payout paths hold the manager lock across the whole
read-modify-write (`tests/unit/test_affiliate_commissions_conserve.py`).

The other half is this one. `AffiliateManager` kept every affiliate, referral
and payout in five module dictionaries with nothing behind them, so a restart
erased what every affiliate was owed, and each worker in a multi-worker
deployment held its own disjoint copy of the ledger — two workers could each
approve a withdrawal the other could not see.

The pattern followed here is the creator ledger's, which is the same defect one
module over (F208): exact-decimal money columns, an append-only referral and
payout record, a write-through on every mutation, a reload on construction, and
a named startup entry point with a registry entry — because a persistence layer
nothing wires is a persistence layer that never runs, which is how the creator
ledger spent months reading FIXED while writing nothing.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture()
def sqlite_factory(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from database.models import Base

    engine = create_engine(f"sqlite:///{tmp_path}/affiliate_ledger.db")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _earn(manager, *, user_id="aff-user", referred="buyer-1", amount="500.00"):
    """Create an approved affiliate and convert one referral against it."""
    from monetization.affiliate import SubscriptionTier

    affiliate = manager.create_affiliate(user_id=user_id)
    manager.approve_affiliate(affiliate.affiliate_id)
    manager.create_referral(affiliate.code, referred)
    commission = manager.convert_referral(referred, SubscriptionTier.PROFESSIONAL, Decimal(amount))
    assert commission is not None and commission > Decimal("0")
    return affiliate, commission


class TestTheTablesExist:
    def test_the_three_affiliate_tables_are_declared(self):
        from database.models import AffiliateRow, AffiliateReferralRow, AffiliatePayoutRow

        assert AffiliateRow.__tablename__ == "affiliates"
        assert AffiliateReferralRow.__tablename__ == "affiliate_referrals"
        assert AffiliatePayoutRow.__tablename__ == "affiliate_payouts"

    def test_money_columns_are_exact_decimal_not_float(self):
        """Numeric, not Float — the creator ledger set this precedent (F235).

        A commission that cannot round-trip is a commission that drifts against
        what was actually paid.
        """
        from sqlalchemy import Numeric

        from database.models import AffiliateReferralRow, AffiliateRow, AffiliatePayoutRow

        money = {
            AffiliateRow: ("total_revenue", "total_commissions"),
            AffiliateReferralRow: ("subscription_amount", "commission_amount", "commission_paid"),
            AffiliatePayoutRow: ("amount",),
        }
        for table, columns in money.items():
            for name in columns:
                column = table.__table__.columns[name]
                assert isinstance(column.type, Numeric) and not isinstance(column.type, type(None)), (
                    f"{table.__tablename__}.{name} is {column.type!r}, not Numeric — money must round-trip exactly"
                )
                assert column.type.scale == 2, f"{table.__tablename__}.{name} must be Numeric(_, 2)"


class TestAWiredManagerPersists:
    def test_a_commission_survives_a_restart(self, sqlite_factory):
        """The defect this whole slice exists to fix."""
        from monetization.affiliate import AffiliateManager

        manager = AffiliateManager(session_factory=sqlite_factory)
        affiliate, commission = _earn(manager)
        owed = manager._calculate_pending_commission(affiliate.affiliate_id)
        assert owed == commission

        restarted = AffiliateManager(session_factory=sqlite_factory)
        assert restarted.get_affiliate(affiliate.affiliate_id) is not None, (
            "the affiliate was never written — a restart erases the account itself"
        )
        assert restarted._calculate_pending_commission(affiliate.affiliate_id) == owed, (
            "the commission did not survive the restart — this is exactly what F31/F32 reported"
        )

    def test_the_affiliate_is_reachable_by_code_and_by_user_after_a_restart(self, sqlite_factory):
        """The lookup indexes are part of the state, not a convenience.

        `create_referral` resolves by code and `get_user_affiliate` by user id.
        A reload that restores the affiliates but not the two indexes leaves
        every referral link broken while looking healthy.
        """
        from monetization.affiliate import AffiliateManager

        manager = AffiliateManager(session_factory=sqlite_factory)
        affiliate, _ = _earn(manager, user_id="aff-indexed", referred="buyer-indexed")

        restarted = AffiliateManager(session_factory=sqlite_factory)
        assert restarted.get_affiliate_by_code(affiliate.code) is not None
        assert restarted.get_user_affiliate("aff-indexed") is not None

    def test_a_settled_withdrawal_is_not_repayable_after_a_restart(self, sqlite_factory):
        """Settlement state must persist, or a restart pays the same commission twice.

        This is the money-losing direction of the same defect: `commission_paid`
        lives on the referral, so a reload that drops it restores the full
        outstanding balance for commissions that were already paid out.
        """
        from monetization.affiliate import AffiliateManager

        manager = AffiliateManager(session_factory=sqlite_factory)
        # Above MIN_PAYOUT (100.00): a 10% commission needs a subscription over
        # 1,000 before a withdrawal is allowed at all.
        affiliate, commission = _earn(manager, user_id="aff-paid", referred="buyer-paid", amount="2000.00")

        payout = manager.request_withdrawal(affiliate.affiliate_id, float(commission))
        assert payout is not None
        assert manager._calculate_pending_commission(affiliate.affiliate_id) == Decimal("0.00")

        restarted = AffiliateManager(session_factory=sqlite_factory)
        assert restarted._calculate_pending_commission(affiliate.affiliate_id) == Decimal("0.00"), (
            "a paid commission came back as outstanding after a restart — it would be paid twice"
        )
        assert restarted.get_affiliate_payouts(affiliate.affiliate_id), "the payout itself was not recorded"

    def test_the_commission_round_trips_exactly(self, sqlite_factory):
        """No float anywhere in the round trip."""
        from monetization.affiliate import AffiliateManager

        manager = AffiliateManager(session_factory=sqlite_factory)
        affiliate, commission = _earn(manager, user_id="aff-exact", referred="buyer-exact", amount="333.33")

        restarted = AffiliateManager(session_factory=sqlite_factory)
        reloaded = restarted._calculate_pending_commission(affiliate.affiliate_id)
        assert isinstance(reloaded, Decimal)
        assert reloaded == commission, f"{reloaded} != {commission} — the commission drifted through storage"


class TestTheWiringRuns:
    def test_affiliate_exposes_an_init_that_wires_the_singleton(self, sqlite_factory):
        from monetization import affiliate as affiliate_module

        assert hasattr(affiliate_module, "init_affiliate_manager")

        original = affiliate_module.affiliate_manager._session_factory
        try:
            returned = affiliate_module.init_affiliate_manager(sqlite_factory)
            assert affiliate_module.affiliate_manager._session_factory is sqlite_factory
            assert returned is affiliate_module.affiliate_manager
        finally:
            affiliate_module.affiliate_manager._session_factory = original

    def test_startup_factories_wires_it_and_reports_a_missing_database(self, sqlite_factory):
        """Called for real, both ways — wired, and degraded."""
        import asyncio
        import logging

        import core.startup_factories as F
        from monetization import affiliate as affiliate_module

        assert hasattr(F, "init_affiliate_ledger")

        original = affiliate_module.affiliate_manager._session_factory
        try:

            class _Wired:
                db_session_factory = sqlite_factory

            assert asyncio.run(F.init_affiliate_ledger(_Wired())) is True
            assert affiliate_module.affiliate_manager._session_factory is sqlite_factory

            affiliate_module.affiliate_manager._session_factory = original

            class _NoDatabase:
                db_session_factory = None

            import pytest as _pytest  # local alias; caplog is not available on this method

            del _pytest
            records: list[logging.LogRecord] = []

            class _Capture(logging.Handler):
                def emit(self, record):
                    records.append(record)

            handler = _Capture(level=logging.ERROR)
            logging.getLogger("core.startup_factories").addHandler(handler)
            try:
                assert asyncio.run(F.init_affiliate_ledger(_NoDatabase())) is False
            finally:
                logging.getLogger("core.startup_factories").removeHandler(handler)

            assert any("NOT persisted" in r.getMessage() for r in records), (
                "an affiliate ledger that is not persisted must say so at ERROR, not degrade silently"
            )
        finally:
            affiliate_module.affiliate_manager._session_factory = original

    def test_the_component_registry_registers_it_after_the_database(self):
        from core.startup_factories import build_component_registry

        class _App:
            state = type("S", (), {})()

        registry = build_component_registry(_App(), feature_flags={})
        components = registry._components

        assert "aml" in components, "registry built nothing — this test cannot measure anything"
        assert "affiliate_ledger" in components, (
            "nothing registers the affiliate ledger, so its persistence never runs in production"
        )
        assert "database" in components["affiliate_ledger"].deps


class TestMemoryModeIsStillSupported:
    def test_a_manager_with_no_factory_still_works(self):
        """Tests and paper trading deliberately have no database."""
        from monetization.affiliate import AffiliateManager

        manager = AffiliateManager()
        assert manager._session_factory is None
        affiliate, commission = _earn(manager, user_id="aff-mem", referred="buyer-mem")
        assert manager._calculate_pending_commission(affiliate.affiliate_id) == commission
