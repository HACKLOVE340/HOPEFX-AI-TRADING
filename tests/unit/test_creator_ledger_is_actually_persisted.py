"""The creator ledger's persistence must run in production, not merely exist.

`monetization/revenue_split.py` carries a complete write-through persistence
layer for creator sales, balances and payouts: three tables in
`database/models.py`, `_write`/`_upsert_*` on every mutation, and
`_load_from_db` on construction so a restart does not forget what a creator is
owed. Every one of those paths is gated on `self._session_factory`, and the
module singleton the API actually uses was constructed as::

    revenue_engine = RevenueSplitEngine()

with no factory, and nothing anywhere assigned one afterwards — `init_aml_gate`
has a `core/startup_factories.py` caller and a registry entry, the revenue
engine had neither. So `if not self._session_factory: return` was taken on
every write for the life of the module: the tables were never written, the
reload had nothing to read, and a restart still erased every creator balance —
which is the exact defect (F208) the tables were added to fix.

This is the `hopefx-dead-controls` shape: a control that exists, is documented
accurately, and never runs. Reading `revenue_split.py` shows correct
persistence. Only executing it shows that in production it is a no-op.

These tests execute it. They do not grep for the wiring — a text match tests
how code is written, not what it does — they build the registry, call the
factory, and assert a sale survives a rebuild against a real (sqlite) session.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture()
def sqlite_factory(tmp_path):
    """A real session factory over the creator ledger tables."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from database.models import Base

    engine = create_engine(f"sqlite:///{tmp_path}/creator_ledger.db")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _record_sale(engine, *, creator_id="creator-1", amount="200.00"):
    from monetization.revenue_split import TransactionType

    return engine.record_sale(
        strategy_id="strat-1",
        creator_id=creator_id,
        buyer_id="buyer-1",
        gross_amount=Decimal(amount),
        transaction_type=TransactionType.PURCHASE,
    )


class TestTheWiringExists:
    def test_revenue_split_exposes_an_init_that_wires_the_singleton(self, sqlite_factory):
        """There must be a named entry point that gives the singleton a factory.

        Mirrors `compliance.aml.init_aml_gate`, which has had one since it was
        written. Without it there is no way for startup to reach the singleton.
        """
        from monetization import revenue_split

        assert hasattr(revenue_split, "init_revenue_engine"), (
            "monetization.revenue_split has no init_revenue_engine — the singleton's "
            "persistence cannot be wired, so every write is a no-op in production"
        )

        original = revenue_split.revenue_engine._session_factory
        try:
            returned = revenue_split.init_revenue_engine(sqlite_factory)
            assert revenue_split.revenue_engine._session_factory is sqlite_factory
            assert returned is revenue_split.revenue_engine
        finally:
            revenue_split.revenue_engine._session_factory = original

    def test_startup_factories_has_a_revenue_ledger_factory(self, sqlite_factory):
        """`core.startup_factories` must carry a factory that performs the wiring.

        Called for real against a stub app_state, not grepped for.
        """
        import asyncio

        import core.startup_factories as F
        from monetization import revenue_split

        assert hasattr(F, "init_revenue_ledger"), (
            "core.startup_factories has no init_revenue_ledger — nothing at startup "
            "can hand the revenue engine a session factory"
        )

        class _State:
            db_session_factory = sqlite_factory

        original = revenue_split.revenue_engine._session_factory
        try:
            assert asyncio.run(F.init_revenue_ledger(_State())) is True
            assert revenue_split.revenue_engine._session_factory is sqlite_factory
        finally:
            revenue_split.revenue_engine._session_factory = original

    def test_a_missing_factory_is_reported_at_error_not_swallowed(self, caplog):
        """Degrading back to memory mode must be loud.

        If `db_session_factory` is absent the engine silently returns to the
        exact mode this component exists to end — every write still "succeeds"
        and the loss only appears as balances that vanished at the next
        restart. That is the dead control coming back through the door, so the
        factory reports it at ERROR and returns False rather than True.
        """
        import asyncio
        import logging

        import core.startup_factories as F
        from monetization import revenue_split

        class _StateWithNoDatabase:
            db_session_factory = None

        original = revenue_split.revenue_engine._session_factory
        try:
            with caplog.at_level(logging.ERROR):
                assert asyncio.run(F.init_revenue_ledger(_StateWithNoDatabase())) is False
            assert any(r.levelno >= logging.ERROR and "NOT persisted" in r.getMessage() for r in caplog.records), (
                "a revenue ledger that is not persisted must say so at ERROR"
            )
            assert revenue_split.revenue_engine._session_factory is original
        finally:
            revenue_split.revenue_engine._session_factory = original

    def test_the_component_registry_registers_it_after_the_database(self):
        """A factory nobody registers is a factory nobody runs.

        The registry is built for real; `aml` is asserted alongside as a
        positive control, so a registry that stopped registering anything at
        all cannot make this test pass by emptiness.
        """
        from core.startup_factories import build_component_registry

        class _App:
            state = type("S", (), {})()

        registry = build_component_registry(_App(), feature_flags={})
        components = registry.list_components() if hasattr(registry, "list_components") else registry._components

        assert "aml" in components, "registry built nothing — this test cannot measure anything"
        assert "revenue_ledger" in components, (
            "the revenue ledger is never registered, so init_revenue_ledger never runs "
            "and the creator ledger stays write-only in production"
        )
        assert "database" in components["revenue_ledger"].deps, (
            "revenue_ledger must depend on the database, or it wires a factory that does not exist yet"
        )


class TestAWiredEngineActuallyPersists:
    def test_a_sale_survives_a_rebuild(self, sqlite_factory):
        """The point of the tables: what a creator is owed outlives the process."""
        from monetization.revenue_split import RevenueSplitEngine

        engine = RevenueSplitEngine(session_factory=sqlite_factory)
        txn = _record_sale(engine)
        owed = engine.get_creator_balance("creator-1").pending_usd
        assert owed > Decimal("0")

        rebuilt = RevenueSplitEngine(session_factory=sqlite_factory)
        assert txn.transaction_id in rebuilt._transactions
        assert rebuilt.get_creator_balance("creator-1").pending_usd == owed

    def test_the_wired_singleton_persists_through_the_startup_path(self, sqlite_factory):
        """End to end: wire the singleton the way startup does, then restart it."""
        from monetization import revenue_split
        from monetization.revenue_split import RevenueSplitEngine

        original = revenue_split.revenue_engine._session_factory
        try:
            revenue_split.init_revenue_engine(sqlite_factory)
            txn = _record_sale(revenue_split.revenue_engine, creator_id="creator-restart")
            owed = revenue_split.revenue_engine.get_creator_balance("creator-restart").pending_usd

            after_restart = RevenueSplitEngine(session_factory=sqlite_factory)
            assert txn.transaction_id in after_restart._transactions, (
                "the sale was never written to creator_sales — the ledger is write-only"
            )
            assert after_restart.get_creator_balance("creator-restart").pending_usd == owed
        finally:
            revenue_split.revenue_engine._session_factory = original


class TestTheMemoryModeIsStillDeliberate:
    def test_an_engine_with_no_factory_still_runs_in_memory(self):
        """Memory mode is a supported mode, not a failure — do not break it.

        This is the positive control for the fix: it must keep passing, or the
        wiring has been bought by forcing a database on every caller, including
        the tests and paper trading that deliberately have none.
        """
        from monetization.revenue_split import RevenueSplitEngine

        engine = RevenueSplitEngine()
        assert engine._session_factory is None
        txn = _record_sale(engine, creator_id="creator-mem")
        assert txn.transaction_id in engine._transactions
        assert engine.get_creator_balance("creator-mem").pending_usd > Decimal("0")
