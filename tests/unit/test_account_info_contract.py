"""Regression tests for the AccountInfo contract on the live money path.

Round 3 audit findings S1-01 and S1-02 (docs/HARDENING_BACKLOG.md).

S1-01: ``brokers/oanda.py`` defined a *second* ``AccountInfo`` dataclass with
no ``.get()`` and no ``equity`` field. ``AsyncOANDAConnector`` is an alias for
``OANDABroker``, so ``BROKER_TYPE=oanda`` wired the broker whose
``get_account_info()`` returned that type. Both consumers on the live path use
dict-style access:

  * ``risk/manager.py`` ``assess_risk``      → ``account_info.get("equity")``
  * ``api/ws_live.py`` equity broadcaster    → ``acct.get("equity", 0.0)``

so every phase-3 risk assessment raised ``AttributeError``, was swallowed by
the broad handler in ``HOPEFXDecisionEngine._phase3_risk``, and surfaced as
``RISK_BLOCKED`` — i.e. the system silently refused to trade and blamed a risk
limit. Paper trading was unaffected because ``PaperTradingBroker`` returns the
*base* ``AccountInfo``, so this only appeared when switching to live OANDA.

S1-02: the decision engine defaulted a missing equity to ``100_000.0``, twenty
lines after a comment refusing to "fabricate a $100k account". Because
``AccountInfo.get`` is ``getattr(self, key, default)``, a *missing field*
returns the default — so the natural fix for S1-01 (adding a ``.get()`` shim to
the oanda-local class, which has ``nav`` rather than ``equity``) would have
converted a fail-closed bug into 50x oversizing on a small account.

These tests pin the contract both fixes rely on.
"""

from datetime import timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

UTC = timezone.utc


def _async_cm(mock_resp):
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_resp)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


# ---------------------------------------------------------------------------
# S1-01 — one AccountInfo type, usable by the live money path
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestAccountInfoIsSingleType:
    def test_oanda_module_does_not_define_its_own_account_info(self):
        """brokers.oanda must reuse brokers.base.AccountInfo, not shadow it.

        Two dataclasses of the same name in the same domain is the root cause
        of S1-01; this asserts the duplicate stays deleted.
        """
        import brokers.base
        import brokers.oanda

        assert brokers.oanda.AccountInfo is brokers.base.AccountInfo

    def test_base_account_info_supports_dict_access(self):
        """The live path reads account info with .get() and [] — both must work."""
        from brokers.base import AccountInfo

        info = AccountInfo(
            balance=2_000.0,
            equity=1_950.0,
            margin_used=100.0,
            margin_available=1_850.0,
            positions_count=1,
        )
        assert info.get("equity") == 1_950.0
        assert info["equity"] == 1_950.0
        assert info.get("does_not_exist", "fallback") == "fallback"

    @pytest.mark.asyncio
    async def test_oanda_account_info_exposes_equity_from_nav(self):
        """OANDA reports NAV; the money path reads `equity`. They must be equal.

        NAV (balance + unrealised P&L) is the correct equity figure — using
        `balance` alone would leave the drawdown gate blind to floating losses
        on open positions.
        """
        from brokers.oanda import OANDABroker

        broker = OANDABroker(
            api_key="test-key",  # pragma: allowlist secret
            account_id="101-001-12345678-001",
            server="practice",
        )
        broker.connected = True

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = AsyncMock(
            return_value={
                "account": {
                    "currency": "USD",
                    "balance": "2000.00",
                    "NAV": "1950.00",
                    "unrealizedPL": "-50.00",
                    "marginUsed": "100.00",
                    "marginAvailable": "1850.00",
                    "openPositionCount": 1,
                }
            }
        )
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=_async_cm(mock_resp))
        broker._session = mock_session

        info = await broker.get_account_info()

        assert info is not None
        # The exact access pattern risk/manager.py:assess_risk uses.
        assert info.get("equity") == 1_950.0
        assert info.get("balance") == 2_000.0
        assert info.get("unrealized_pnl") == -50.0

    @pytest.mark.asyncio
    async def test_oanda_account_info_survives_risk_assess(self):
        """End-to-end: the object OANDA returns must not raise in assess_risk.

        This is the exact call that raised AttributeError and was misreported
        as a risk-limit block.
        """
        from brokers.oanda import OANDABroker
        from risk.manager import RiskManager

        broker = OANDABroker(
            api_key="test-key",  # pragma: allowlist secret
            account_id="101-001-12345678-001",
            server="practice",
        )
        broker.connected = True

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = AsyncMock(
            return_value={
                "account": {
                    "currency": "USD",
                    "balance": "100000.00",
                    "NAV": "100000.00",
                    "unrealizedPL": "0.00",
                    "marginUsed": "0.00",
                    "marginAvailable": "100000.00",
                    "openPositionCount": 0,
                }
            }
        )
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=_async_cm(mock_resp))
        broker._session = mock_session

        info = await broker.get_account_info()

        rm = RiskManager()
        assessment = rm.assess_risk(info, [])  # must not raise
        assert assessment.can_trade is True


# ---------------------------------------------------------------------------
# S1-02 — never size against a fabricated account
# ---------------------------------------------------------------------------
@pytest.mark.unit
class TestNoFabricatedEquity:
    def test_missing_equity_is_not_defaulted_to_100k(self):
        """A broker object without an equity field must not read as $100,000.

        AccountInfo.get() is getattr-based, so a *missing field* silently
        returns the caller's default. The decision engine must therefore not
        supply a positive default.
        """
        import inspect

        from core.decision import HOPEFXDecisionEngine as mod

        src = inspect.getsource(mod)
        assert "100_000.0" not in src and "100000.0" not in src, (
            "Decision engine must not carry a fabricated equity default — "
            "block the trade when equity is unavailable (S1-02)."
        )

    def _engine_with(self, account_obj):
        """Build a decision engine whose broker returns *account_obj*.

        Every gate upstream of the equity read is configured to **pass**, so the
        only thing that can block the trade is the equity check itself. Without
        that, a mocked ``assess_risk`` returning ``can_trade=False`` would block
        first and the test would pass on the unfixed code too.
        """
        from core.decision.HOPEFXDecisionEngine import HOPEFXDecisionEngine

        class _Signal:
            signal_type = "BUY"
            confidence = 0.9
            symbol = "XAU_USD"

        brain = MagicMock()
        brain.analyze_joint = MagicMock(return_value={"consensus_reached": True, "consensus_signal": _Signal()})

        gate = MagicMock()
        gate.evaluate = AsyncMock(return_value=MagicMock(passed=True))

        broker = MagicMock()
        broker.get_account_info = AsyncMock(return_value=account_obj)
        broker.get_positions = AsyncMock(return_value=[])

        executor = MagicMock()
        executor.broker = broker
        executor.execute_signal = AsyncMock(
            return_value=MagicMock(
                success=True,
                order_id="ord-1",
                filled_quantity=1.0,
                average_price=3300.0,
                commission=0.0,
            )
        )

        risk = MagicMock()
        # Risk gate PASSES — so it cannot be the thing that blocks.
        risk.assess_risk = MagicMock(return_value=MagicMock(can_trade=True, messages=""))
        risk.calculate_position_size = MagicMock(return_value=MagicMock(approved=True, recommended_size=1.0, reason=""))

        engine = HOPEFXDecisionEngine(
            brain=brain,
            risk_manager=risk,
            gatekeeper=gate,
            trade_executor=executor,
            event_bus=MagicMock(publish_signal=AsyncMock()),
            ml_predictor=None,
        )
        return engine, executor, risk

    @staticmethod
    def _tick():
        return {
            "close": 3300.0,
            "open": 3300.0,
            "high": 3305.0,
            "low": 3295.0,
            "volume": 1.0,
        }

    @pytest.mark.asyncio
    async def test_account_object_without_equity_field_blocks(self):
        """The S1-02 scenario: an account object that has no `equity` attribute.

        This is what the old oanda-local AccountInfo looked like (it had `nav`).
        With a getattr-based ``.get()`` and a 100_000.0 default, this sized a
        full position against a fabricated six-figure balance while every other
        gate passed. It must block instead.
        """
        from core.decision.HOPEFXDecisionEngine import DecisionOutcome

        class _NoEquityAccount:
            """Mimics a broker account object lacking an `equity` field."""

            balance = 2_000.0
            nav = 1_950.0

            def get(self, key, default=None):
                return getattr(self, key, default)

        engine, executor, _ = self._engine_with(_NoEquityAccount())
        result = await engine.process_tick(self._tick(), symbol="XAU_USD")

        assert result.outcome == DecisionOutcome.RISK_BLOCKED
        assert "account_info_unavailable" in result.gate_reason
        executor.execute_signal.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_zero_equity_blocks(self):
        """A real but empty account must block rather than size against a default."""
        from core.decision.HOPEFXDecisionEngine import DecisionOutcome

        engine, executor, _ = self._engine_with({"balance": 0.0, "equity": 0.0})
        result = await engine.process_tick(self._tick(), symbol="XAU_USD")

        assert result.outcome == DecisionOutcome.RISK_BLOCKED
        executor.execute_signal.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_broker_returning_none_blocks(self):
        """Brokers return None when disconnected — that must not reach sizing."""
        from core.decision.HOPEFXDecisionEngine import DecisionOutcome

        engine, executor, risk = self._engine_with(None)
        result = await engine.process_tick(self._tick(), symbol="XAU_USD")

        assert result.outcome == DecisionOutcome.RISK_BLOCKED
        assert "account_info_unavailable" in result.gate_reason
        risk.calculate_position_size.assert_not_called()
        executor.execute_signal.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_real_equity_is_used_and_trade_proceeds(self):
        """Control case: a valid account must size against its *real* equity.

        Guards against over-correcting S1-02 into blocking everything.
        """
        from core.decision.HOPEFXDecisionEngine import DecisionOutcome
        from brokers.base import AccountInfo

        account = AccountInfo(
            balance=2_000.0,
            equity=1_950.0,
            margin_used=0.0,
            margin_available=1_950.0,
            positions_count=0,
        )
        engine, executor, risk = self._engine_with(account)
        result = await engine.process_tick(self._tick(), symbol="XAU_USD")

        assert result.outcome == DecisionOutcome.EXECUTED
        executor.execute_signal.assert_awaited_once()
        # The real equity reached sizing — not a fabricated 100_000.
        assert risk.calculate_position_size.call_args.kwargs["account_equity"] == 1_950.0


# ── S1-01b: the same defect, second instance ──────────────────────────────────


class TestNoBrokerLocalAccountInfo:
    """Every broker must return the canonical ``brokers.base.AccountInfo``.

    S1-01 was found on the OANDA path: ``brokers/oanda.py`` defined its own
    ``AccountInfo`` dataclass with ``nav`` instead of ``equity`` and no
    ``.get()``. ``RiskManager.assess_risk`` reads
    ``account_info.get("equity")``, so live OANDA raised ``AttributeError`` and
    blocked 100% of trades.

    Re-verifying that fix turned up a **second** copy in ``brokers/ibkr.py``
    with exactly the same two problems. `execution/execution.py` imports
    ``IBKRBroker``, so it was a live path too. These tests fail if any broker
    module grows a third.
    """

    def test_no_broker_module_defines_its_own_account_info(self):
        import ast
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[2] / "brokers"
        offenders = []
        for path in root.rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ClassDef) and node.name == "AccountInfo":
                    rel = path.relative_to(root.parent)
                    if str(rel) != "brokers/base.py":
                        offenders.append(f"{rel}:{node.lineno}")

        assert not offenders, (
            f"broker-local AccountInfo definition(s) at {offenders}. "
            f"RiskManager.assess_risk calls account_info.get('equity'); a plain "
            f"dataclass has no .get(), so the risk gate raises AttributeError and "
            f"blocks every trade on that broker (S1-01)."
        )

    def test_ibkr_account_info_satisfies_the_risk_gate_contract(self):
        """The exact call the risk gate makes must work on IBKR's return type."""
        import brokers.ibkr as ibkr_mod
        from brokers.base import AccountInfo

        assert ibkr_mod.AccountInfo is AccountInfo

        account = AccountInfo(
            account_id="DU123",
            currency="USD",
            balance=10_000.0,
            equity=12_500.0,
            margin_used=1_000.0,
            margin_available=8_000.0,
            positions_count=1,
            unrealized_pnl=2_500.0,
        )
        # This is risk/manager.py::assess_risk verbatim.
        equity = float(account.get("equity") or account.get("balance") or 0.0)
        assert equity == pytest.approx(12_500.0)
        # IBKR's own name for the same quantity must still resolve.
        assert account.nav == pytest.approx(12_500.0)
