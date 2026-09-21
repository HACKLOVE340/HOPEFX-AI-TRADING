"""Regression tests: stale market data must not reach sizing.

Round 3 audit findings S5-01, S5-02 and S5-03 (docs/HARDENING_BACKLOG.md).

The data layer's timezone handling and its Redis-cache freshness gate were
found correct. The defect was that **freshness was enforced on that one read
path and on none of the others**:

S5-01 — ``size_order`` passes a 5-second staleness budget to
``enforce_pre_trade``, which resolves the tick timestamp from the first of
``tick_ts``/``tick_timestamp``/``ts``/``timestamp`` that is an ``int``/``float``.
``_MinimalSignal.__slots__`` contains none of those names, and the brain's
``Signal`` carries a ``datetime`` — which the ``isinstance`` test rejects. So
the constitutional invariant "No Unverified AI Decision: never trade on a stale
tick" could not fire on either signal type.

S5-02 — ``GoldTick.quality`` is assigned when the tick is ingested, on a frozen
dataclass, and never re-evaluated. A stalled feed's last tick therefore
reported ``GOOD`` and ``is_valid()`` indefinitely, and ``active_sources()``
used the same predicate — so the health endpoint listed dead feeds as active.

S5-03 — ``GoldFeedManager.get_latest_tick`` returned ``self._consensus_tick``
with no validity or age check at all, and that is the default branch.
"""

from datetime import datetime, timedelta, timezone

import pytest

UTC = timezone.utc


def _tick(age_seconds: float = 0.0, quality=None):
    from data_layer.types import FeedSource, GoldTick, TickQuality

    return GoldTick(
        symbol="XAU_USD",
        timestamp=datetime.now(UTC) - timedelta(seconds=age_seconds),
        bid=3299.9,
        ask=3300.1,
        mid=3300.0,
        source=FeedSource.AGGREGATED,
        quality=quality or TickQuality.GOOD,
        confidence=1.0,
        spread=0.2,
    )


@pytest.mark.unit
class TestTickValidityConsidersAge:
    def test_fresh_tick_is_valid(self):
        """Control case."""
        assert _tick(age_seconds=0.5).is_valid() is True

    def test_stale_tick_is_not_valid(self):
        """quality is a snapshot; is_valid() must still consider age (S5-02)."""
        old = _tick(age_seconds=3600.0)  # an hour old, graded GOOD at ingest
        assert old.quality.value == "good"  # unchanged, as designed
        assert old.is_valid() is False, (
            "A tick graded GOOD an hour ago still reported is_valid() — a stalled "
            "feed's last tick stayed 'valid' forever, and active_sources() used "
            "the same predicate (S5-02)."
        )

    def test_age_bound_is_configurable(self):
        """Callers must be able to apply their own budget."""
        t = _tick(age_seconds=10.0)
        assert t.is_valid(max_age_s=60.0) is True
        assert t.is_valid(max_age_s=5.0) is False


@pytest.mark.unit
class TestConsensusTickIsChecked:
    def test_stale_consensus_tick_is_not_served(self):
        """The default read path had no validity or age check (S5-03)."""
        from data_layer.feeds.gold.manager import GoldFeedManager

        mgr = GoldFeedManager()
        mgr._consensus_tick = _tick(age_seconds=3600.0)

        assert mgr.get_latest_tick() is None, (
            "A one-hour-old consensus tick was returned as the live price. With "
            "Redis down this bypasses the orchestrator's freshness gate entirely "
            "(S5-03)."
        )

    def test_fresh_consensus_tick_is_served(self):
        """Control case: the fix must not break the normal path."""
        from data_layer.feeds.gold.manager import GoldFeedManager

        mgr = GoldFeedManager()
        fresh = _tick(age_seconds=0.5)
        mgr._consensus_tick = fresh

        assert mgr.get_latest_tick() is fresh


@pytest.mark.unit
class TestStalenessInvariantCanFire:
    def test_minimal_signal_carries_a_tick_timestamp(self):
        """_MinimalSignal must expose a timestamp the invariant can read (S5-01)."""
        from risk.manager import _MinimalSignal

        assert "tick_ts" in _MinimalSignal.__slots__, (
            "_MinimalSignal has no timestamp field, so enforce_pre_trade finds "
            "nothing to measure and the staleness budget is silently skipped."
        )

    def test_enforcement_accepts_a_datetime_timestamp(self):
        """A datetime timestamp must not be discarded by the type test (S5-01)."""
        from invariants.enforcement import enforce_pre_trade

        class _Sig:
            confidence = 0.9
            probability = 0.6
            tick_mid = 3300.0
            tick_spread = 0.2
            # datetime, not a float — the brain's Signal shape.
            timestamp = datetime.now(UTC) - timedelta(seconds=600)

        result = enforce_pre_trade(
            _Sig(),
            data_quality=1.0,
            equity=100_000.0,
            now=datetime.now(UTC).timestamp(),
            max_staleness_s=5.0,
        )
        assert any("stale" in v.message.lower() for v in result.violations), (
            "A 600s-old datetime timestamp did not register as stale — the "
            "isinstance(int|float) test discards datetimes (S5-01)."
        )

    def test_stale_tick_blocks_sizing_in_enforce_mode(self, monkeypatch):
        """End-to-end: a stale tick must refuse to size."""
        monkeypatch.setenv("HOPEFX_INVARIANT_MODE", "enforce")
        from risk.manager import RiskManager

        rm = RiskManager()
        rm.update_equity(100_000.0)

        stale_ts = (datetime.now(UTC) - timedelta(seconds=600)).timestamp()
        sizing = rm.calculate_position_size(
            symbol="XAU_USD",
            entry_price=3300.0,
            account_equity=100_000.0,
            signal_strength=0.7,
            probability=0.45,
            tick_ts=stale_ts,
        )
        assert sizing.quantity == 0.0, (
            f"sized {sizing.quantity} against a 10-minute-old tick with a 5-second staleness budget (S5-01)."
        )
