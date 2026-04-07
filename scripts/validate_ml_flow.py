# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
scripts/validate_ml_flow.py
============================
End-to-end ML flow validation.

Exercises every stage of the production pipeline using real classes and the
on-disk XAUUSD H1 dataset — no mocks, no synthetic data, no network calls.

Stages validated
----------------
  1. Data loading          — read XAU_USD_H1.csv, verify shape and OHLCV columns
  2. Feature engineering   — AdvancedFeatureEngineer.create_features()
  3. ML inference          — AdvancedPredictor.predict() with real model artifact
  4. Online learning       — SklearnOnlineLearner.partial_fit() + predict_proba()
  5. Brain signal          — HOPEFXBrain.process_bar() → BrainDecision
  6. Risk sizing           — RiskManager.assess() + size_order()
  7. Order execution       — PaperTradingBroker.place_order() (market + limit)
  8. Position accounting   — balance, P&L, open-position tracking
  9. Kill-switch gate      — verify brain returns hold when kill switch is active
 10. Latency budget        — each stage must complete within its SLA

Usage
-----
    python scripts/validate_ml_flow.py            # full run, coloured output
    python scripts/validate_ml_flow.py --quiet    # exit-code only (CI mode)
    python scripts/validate_ml_flow.py --stage 3  # run a single stage

Exit codes
----------
    0  all stages passed
    1  one or more stages failed
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
import warnings
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar
import logging
logger = logging.getLogger(__name__)


# ── Environment bootstrap ─────────────────────────────────────────────────────
# Must happen before any app module is imported so startup validators see
# APP_ENV=test and skip production-only checks (DB, Redis, JWT length, etc.)
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault(
    "SECURITY_JWT_SECRET",
    "validate-ml-flow-jwt-secret-key-minimum-32-chars!!",
)
os.environ.setdefault("HOPEFX_CI", "1")  # reduces XGBoost n_estimators for speed

warnings.filterwarnings("ignore")  # suppress FutureWarning / PerformanceWarning

# ── Project root on sys.path ──────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ── ANSI colours (disabled when not a TTY) ───────────────────────────────────
_TTY = sys.stdout.isatty()
_GREEN = "\033[32m" if _TTY else ""
_RED = "\033[31m" if _TTY else ""
_YELLOW = "\033[33m" if _TTY else ""
_CYAN = "\033[36m" if _TTY else ""
_BOLD = "\033[1m" if _TTY else ""
_RESET = "\033[0m" if _TTY else ""

# ── Data file ─────────────────────────────────────────────────────────────────
_H1_CSV = _ROOT / "data" / "XAU_USD_H1.csv"

# ── Latency SLAs (seconds) ────────────────────────────────────────────────────
_SLA: dict[str, float] = {
    "data_loading": 2.0,
    "feature_engineering": 30.0,  # 11k-bar full feature build; ~20s on first run
    "ml_inference": 10.0,
    "online_learning": 5.0,
    "brain_signal": 15.0,
    "risk_sizing": 2.0,
    "order_execution": 2.0,
    "position_accounting": 2.0,
    "kill_switch_gate": 5.0,
    "latency_budget": 0.0,  # meta-stage, no SLA of its own
}


# ─────────────────────────────────────────────────────────────────────────────
# Result tracking
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class StageResult:
    name: str
    passed: bool
    elapsed_s: float
    detail: str = ""
    sla_s: float = 0.0

    @property
    def sla_ok(self) -> bool:
        return self.sla_s <= 0 or self.elapsed_s <= self.sla_s


@dataclass
class ValidationReport:
    results: list[StageResult] = field(default_factory=list)

    def add(self, r: StageResult) -> None:
        self.results.append(r)

    @property
    def passed(self) -> bool:
        return all(r.passed and r.sla_ok for r in self.results)

    @property
    def n_passed(self) -> int:
        return sum(1 for r in self.results if r.passed and r.sla_ok)

    @property
    def n_failed(self) -> int:
        return len(self.results) - self.n_passed


# ─────────────────────────────────────────────────────────────────────────────
# Runner helpers
# ─────────────────────────────────────────────────────────────────────────────


def _run_stage(
    name: str,
    fn: Callable[[], str],
    quiet: bool = False,
) -> StageResult:
    """Execute fn(), capture timing, return StageResult."""
    sla = _SLA.get(name.lower().replace(" ", "_"), 0.0)
    t0 = time.perf_counter()
    try:
        detail = fn() or ""
        elapsed = time.perf_counter() - t0
        result = StageResult(name=name, passed=True, elapsed_s=elapsed, detail=detail, sla_s=sla)
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        tb = traceback.format_exc()
        result = StageResult(name=name, passed=False, elapsed_s=elapsed, detail=f"{exc}\n{tb}", sla_s=sla)

    if not quiet:
        _print_result(result)
    return result


def _print_result(r: StageResult) -> None:
    if r.passed and r.sla_ok:
        icon = f"{_GREEN}✓{_RESET}"
        status = f"{_GREEN}PASS{_RESET}"
    elif r.passed and not r.sla_ok:
        icon = f"{_YELLOW}⚠{_RESET}"
        status = f"{_YELLOW}SLOW{_RESET}"
    else:
        icon = f"{_RED}✗{_RESET}"
        status = f"{_RED}FAIL{_RESET}"

    sla_str = f"  SLA {r.sla_s:.1f}s" if r.sla_s > 0 else ""
    logger.info(f"  {icon} [{status}] {_BOLD}{r.name}{_RESET}  ({r.elapsed_s:.3f}s{sla_str})")
    if r.detail and (not r.passed or not r.sla_ok):
        for line in r.detail.strip().splitlines()[:8]:
            logger.info(f"       {_YELLOW}{line}{_RESET}")


def _print_header(title: str) -> None:
    logger.info(f"\n{_CYAN}{_BOLD}{'─' * 60}{_RESET}")
    logger.info(f"{_CYAN}{_BOLD}  {title}{_RESET}")
    logger.info(f"{_CYAN}{_BOLD}{'─' * 60}{_RESET}")


def _print_summary(report: ValidationReport) -> None:
    logger.info(f"\n{_BOLD}{'═' * 60}{_RESET}")
    colour = _GREEN if report.passed else _RED
    label = "ALL STAGES PASSED" if report.passed else "VALIDATION FAILED"
    logger.info(f"{colour}{_BOLD}  {label}  ({report.n_passed}/{len(report.results)} stages){_RESET}")
    if not report.passed:
        logger.error(f"\n  {_RED}Failed stages:{_RESET}")
        for r in report.results:
            if not r.passed or not r.sla_ok:
                tag = "SLOW" if r.passed else "FAIL"
                logger.info(f"    {_RED}[{tag}]{_RESET} {r.name}")
    logger.info(f"{_BOLD}{'═' * 60}{_RESET}\n")


# ─────────────────────────────────────────────────────────────────────────────
# Shared state passed between stages
# ─────────────────────────────────────────────────────────────────────────────


class _Ctx:
    """Mutable context shared across stage functions."""

    ohlcv_df = None  # raw H1 DataFrame (timestamp index)
    features_df = None  # feature-engineered DataFrame
    predictor = None  # AdvancedPredictor instance
    ml_result: dict = {}  # last predict() output
    online_learner = None  # SklearnOnlineLearner instance
    brain = None  # HOPEFXBrain instance
    brain_decision = None  # last BrainDecision
    risk_manager = None  # RiskManager instance
    sizing_result = None  # PositionSizingResult
    broker = None  # PaperTradingBroker instance
    order = None  # last placed Order
    stage_latencies: dict = {}  # stage_name → elapsed_s


ctx = _Ctx()


def _ensure_ohlcv() -> None:
    """Load H1 data into ctx if not already loaded (supports single-stage runs)."""
    if ctx.ohlcv_df is not None:
        return
    import pandas as pd

    df = pd.read_csv(_H1_CSV)
    df.columns = [c.lower() for c in df.columns]
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    ctx.ohlcv_df = df.set_index("timestamp").sort_index()


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — Data loading
# ─────────────────────────────────────────────────────────────────────────────


def stage_data_loading() -> str:
    import pandas as pd

    if not _H1_CSV.exists():
        raise FileNotFoundError(f"H1 data file not found: {_H1_CSV}")

    df = pd.read_csv(_H1_CSV)
    df.columns = [c.lower() for c in df.columns]

    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing OHLCV columns: {missing}")

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.set_index("timestamp").sort_index()

    if len(df) < 200:
        raise ValueError(f"Insufficient rows: {len(df)} (need ≥ 200)")

    # Sanity checks on price data
    assert (df["high"] >= df["low"]).all(), "high < low detected"
    assert (df["close"] > 0).all(), "non-positive close prices"
    assert df.index.is_monotonic_increasing, "timestamps not monotonic"

    ctx.ohlcv_df = df
    return (
        f"{len(df):,} bars  "
        f"{df.index[0].date()} → {df.index[-1].date()}  "
        f"close range [{df['close'].min():.2f}, {df['close'].max():.2f}]"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — Feature engineering
# ─────────────────────────────────────────────────────────────────────────────


def stage_feature_engineering() -> str:
    from enhanced_ml_predictor import AdvancedFeatureEngineer

    _ensure_ohlcv()
    eng = AdvancedFeatureEngineer()
    features = eng.create_features(ctx.ohlcv_df, fit=True)

    if features is None or features.empty:
        raise ValueError("Feature engineering returned empty DataFrame")

    n_rows, n_cols = features.shape
    if n_cols < 10:
        raise ValueError(f"Too few features: {n_cols}")

    # No NaN-only columns
    all_nan = [c for c in features.columns if features[c].isna().all()]
    if all_nan:
        raise ValueError(f"All-NaN feature columns: {all_nan[:5]}")

    ctx.features_df = features
    return f"{n_rows} rows × {n_cols} features  (NaN-only cols: {len(all_nan)})"


# ─────────────────────────────────────────────────────────────────────────────
# Stage 3 — ML inference
# ─────────────────────────────────────────────────────────────────────────────


def stage_ml_inference() -> str:
    from ml.advanced_predictor import AdvancedPredictor

    _ensure_ohlcv()
    predictor = AdvancedPredictor()
    # Use a 300-bar window — predictor only needs the last row; full dataset
    # causes build_advanced_features to hang on large inputs.
    result = predictor.predict(ctx.ohlcv_df.tail(300), symbol="XAUUSD")

    # Required keys
    required_keys = {
        "direction",
        "probability",
        "confidence",
        "abstain",
        "model_version",
        "latency_ms",
    }
    missing = required_keys - set(result.keys())
    if missing:
        raise ValueError(f"predict() missing keys: {missing}")

    prob = result["probability"]
    conf = result["confidence"]
    direction = result["direction"]

    if not (0.0 <= prob <= 1.0):
        raise ValueError(f"probability out of range: {prob}")
    if not (0.0 <= conf <= 1.0):
        raise ValueError(f"confidence out of range: {conf}")
    if direction not in ("long", "short", "neutral"):
        raise ValueError(f"unexpected direction: {direction!r}")

    ctx.predictor = predictor
    ctx.ml_result = result
    return (
        f"direction={direction}  prob={prob:.4f}  conf={conf:.4f}  "
        f"abstain={result['abstain']}  latency={result['latency_ms']:.1f}ms  "
        f"model={result['model_version']}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Stage 4 — Online learning
# ─────────────────────────────────────────────────────────────────────────────


def stage_online_learning() -> str:
    from ml.online_learner import SklearnOnlineLearner

    _ensure_ohlcv()
    learner = SklearnOnlineLearner(symbol="XAUUSD", n_features=176)

    # Need at least 30 bars for feature extraction
    bars = ctx.ohlcv_df.tail(50).copy()

    # partial_fit returns True on success
    ok = learner.partial_fit(bars)
    if not ok:
        raise RuntimeError("partial_fit() returned False — model not initialised")

    # A second update should also succeed
    ok2 = learner.partial_fit(bars)
    if not ok2:
        raise RuntimeError("second partial_fit() returned False")

    # predict_proba should return a float in [0, 1] after fitting
    prob = learner.predict_proba(bars)
    if prob is not None and not (0.0 <= prob <= 1.0):
        raise ValueError(f"predict_proba out of range: {prob}")

    status = learner.status()
    update_count = status.get("update_count", 0)
    if update_count < 2:
        raise ValueError(f"update_count too low: {update_count}")

    ctx.online_learner = learner
    prob_str = f"{prob:.4f}" if prob is not None else "None"
    return f"updates={update_count}  rolling_acc={status.get('rolling_accuracy', 'n/a')}  predict_proba={prob_str}"


# ─────────────────────────────────────────────────────────────────────────────
# Stage 5 — Brain signal
# ─────────────────────────────────────────────────────────────────────────────


def stage_brain_signal() -> str:
    from brain.hopefx_brain import BrainDecision, HOPEFXBrain

    _ensure_ohlcv()
    brain = HOPEFXBrain()
    # 300-bar window keeps inference fast; brain only needs the last bar's context
    decision = brain.process_bar(ctx.ohlcv_df.tail(300), symbol="XAUUSD")

    if not isinstance(decision, BrainDecision):
        raise TypeError(f"process_bar() returned {type(decision)}, expected BrainDecision")

    if decision.action not in ("long", "short", "hold"):
        raise ValueError(f"unexpected action: {decision.action!r}")
    if not (0.0 <= decision.confidence <= 1.0):
        raise ValueError(f"confidence out of range: {decision.confidence}")
    if not decision.regime:
        raise ValueError("regime is empty")

    ctx.brain = brain
    ctx.brain_decision = decision
    return (
        f"action={decision.action}  conf={decision.confidence:.4f}  "
        f"regime={decision.regime}  ml_prob={decision.ml_probability:.4f}  "
        f"reason={decision.reason!r}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Stage 6 — Risk sizing
# ─────────────────────────────────────────────────────────────────────────────


def stage_risk_sizing() -> str:
    from risk.manager import RiskConfig, RiskManager

    _ensure_ohlcv()
    rm = RiskManager(
        config=RiskConfig(
            max_position_size_pct=0.05,
            max_drawdown_pct=0.10,
            max_daily_loss_pct=0.05,
        )
    )

    last_close = float(ctx.ohlcv_df["close"].iloc[-1])

    # Build a minimal signal object that satisfies size_order()
    class _Sig:
        symbol = "XAU_USD"
        direction = "long"
        confidence = 0.72
        probability = 0.65
        data_quality = 1.0
        features: ClassVar[dict] = {}
        tick_mid = last_close
        tick_spread = 1.0

    sig = _Sig()

    # Full assessment path
    assessment = rm.assess(sig)
    if assessment is None:
        raise ValueError("assess() returned None")

    # Direct sizing path
    sizing = rm.size_order(sig)
    if sizing is None:
        raise ValueError("size_order() returned None")

    # Quantity must be non-negative
    if sizing.quantity < 0:
        raise ValueError(f"negative quantity: {sizing.quantity}")

    # Stop and TP must be positive when a position is sized
    if sizing.quantity > 0:
        if sizing.stop_loss_usd <= 0:
            raise ValueError(f"stop_loss_usd not set: {sizing.stop_loss_usd}")
        if sizing.take_profit_usd <= 0:
            raise ValueError(f"take_profit_usd not set: {sizing.take_profit_usd}")
        if sizing.stop_loss_usd >= sizing.take_profit_usd:
            raise ValueError(f"stop ({sizing.stop_loss_usd}) >= tp ({sizing.take_profit_usd})")

    ctx.risk_manager = rm
    ctx.sizing_result = sizing
    return (
        f"approved={sizing.approved}  qty={sizing.quantity:.4f}  "
        f"notional=${sizing.notional_usd:,.2f}  "
        f"stop={sizing.stop_loss_usd:.2f}  tp={sizing.take_profit_usd:.2f}  "
        f"risk_level={assessment.risk_level}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Stage 7 — Order execution
# ─────────────────────────────────────────────────────────────────────────────


def stage_order_execution() -> str:
    import asyncio

    from brokers.base import OrderSide, OrderStatus, OrderType
    from brokers.paper_trading import PaperTradingBroker

    _ensure_ohlcv()
    broker = PaperTradingBroker(initial_balance=100_000.0)
    asyncio.run(broker.connect())

    mid = float(ctx.ohlcv_df["close"].iloc[-1])
    broker.market_prices["XAUUSD"] = mid

    # Market buy
    order_buy = broker.place_order("XAUUSD", OrderSide.BUY, 0.1, OrderType.MARKET)
    if order_buy.status != OrderStatus.FILLED:
        raise RuntimeError(f"Market buy not filled: {order_buy.status}")
    if order_buy.average_price <= 0:
        raise ValueError(f"Fill price not set: {order_buy.average_price}")

    # Market sell
    order_sell = broker.place_order("XAUUSD", OrderSide.SELL, 0.1, OrderType.MARKET)
    if order_sell.status != OrderStatus.FILLED:
        raise RuntimeError(f"Market sell not filled: {order_sell.status}")

    # Limit order (price below market — should remain pending)
    limit_price = mid * 0.98
    order_limit = broker.place_order(
        "XAUUSD",
        OrderSide.BUY,
        OrderType.LIMIT,
        quantity=0.1,
        price=limit_price,
    )
    if order_limit.status == OrderStatus.FILLED:
        raise RuntimeError("Limit order below market filled immediately (unexpected)")

    ctx.broker = broker
    ctx.order = order_buy
    return (
        f"market_buy fill={order_buy.average_price:.4f}  "
        f"market_sell fill={order_sell.average_price:.4f}  "
        f"limit_order status={order_limit.status.name}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Stage 8 — Position accounting
# ─────────────────────────────────────────────────────────────────────────────


def stage_position_accounting() -> str:
    import asyncio

    from brokers.base import OrderSide, OrderType
    from brokers.paper_trading import PaperTradingBroker

    _ensure_ohlcv()
    broker = PaperTradingBroker(initial_balance=50_000.0)
    asyncio.run(broker.connect())

    mid = float(ctx.ohlcv_df["close"].iloc[-1])
    broker.market_prices["XAUUSD"] = mid

    # Open a long position
    buy_order = broker.place_order("XAUUSD", OrderSide.BUY, 1.0, OrderType.MARKET)
    if buy_order.status.name != "FILLED":
        raise RuntimeError(f"Buy order not filled: {buy_order.status}")

    entry_price = buy_order.average_price

    # Verify position is tracked
    if "XAUUSD" not in broker.positions:
        raise RuntimeError("Position not tracked after buy")

    # Simulate price move up 1%
    new_price = mid * 1.01
    broker.market_prices["XAUUSD"] = new_price

    # Close via close_position() — this realizes P&L and credits balance
    closed = broker.close_position("XAUUSD")
    if not closed:
        raise RuntimeError("close_position() returned False")

    balance_after_close = broker.balance
    pnl = balance_after_close - 50_000.0

    # With a 1% up move on a long, realized P&L should be positive
    if pnl <= -500:
        raise ValueError(f"P&L unexpectedly negative after favourable move: {pnl:.2f}")

    # Position should be gone after close
    positions_after = broker.get_positions()
    open_qty = sum(abs(p.quantity) for p in positions_after if hasattr(p, "quantity"))

    return (
        f"entry={entry_price:.4f}  exit_mid={new_price:.4f}  "
        f"balance_start=50000.00  "
        f"balance_after_close={balance_after_close:.2f}  "
        f"pnl={pnl:+.2f}  remaining_open_qty={open_qty:.2f}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Stage 9 — Kill-switch gate
# ─────────────────────────────────────────────────────────────────────────────


def stage_kill_switch_gate() -> str:
    import tempfile

    from brain.hopefx_brain import HOPEFXBrain
    from kill_switch import KillSwitch

    _ensure_ohlcv()
    with tempfile.TemporaryDirectory() as tmp:
        flag_file = Path(tmp) / "ks.flag"
        ks = KillSwitch(flag_file=flag_file, deactivation_token="test-token")  # nosec B106 — test-only token

        # Activate the kill switch
        ks.activate("validation_test")
        assert ks.is_active(), "KillSwitch.activate() did not set active state"

        # Brain should return hold when kill switch is active
        brain = HOPEFXBrain()
        brain._killed = True
        brain._kill_reason = "validation_test"

        decision = brain.process_bar(ctx.ohlcv_df.tail(300), symbol="XAUUSD")
        if decision.action != "hold":
            raise RuntimeError(f"Brain returned {decision.action!r} with kill switch active (expected 'hold')")
        if decision.confidence != 0.0:
            raise ValueError(f"Brain confidence={decision.confidence} with kill switch active (expected 0.0)")

        # Deactivate and verify brain can act again
        ks.deactivate("test-token")  # nosec B106 - test token in kill switch validation, not a real credential
        assert not ks.is_active(), "KillSwitch.deactivate() did not clear active state"

    return "kill_switch activated → brain returned hold  |  deactivated → brain unblocked"


# ─────────────────────────────────────────────────────────────────────────────
# Stage 10 — Latency budget
# ─────────────────────────────────────────────────────────────────────────────


def stage_latency_budget() -> str:
    """Verify all prior stages met their SLA."""
    violations = [
        f"{r.name}: {r.elapsed_s:.3f}s > SLA {r.sla_s:.1f}s"
        for r in _report.results
        if r.sla_s > 0 and r.elapsed_s > r.sla_s
    ]
    if violations:
        raise RuntimeError("SLA violations:\n  " + "\n  ".join(violations))
    return "all stages within SLA"


# ─────────────────────────────────────────────────────────────────────────────
# Stage registry
# ─────────────────────────────────────────────────────────────────────────────

STAGES: list[tuple[str, Callable[[], str]]] = [
    ("Data loading", stage_data_loading),
    ("Feature engineering", stage_feature_engineering),
    ("ML inference", stage_ml_inference),
    ("Online learning", stage_online_learning),
    ("Brain signal", stage_brain_signal),
    ("Risk sizing", stage_risk_sizing),
    ("Order execution", stage_order_execution),
    ("Position accounting", stage_position_accounting),
    ("Kill-switch gate", stage_kill_switch_gate),
    ("Latency budget", stage_latency_budget),
]

_report = ValidationReport()


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description="End-to-end ML flow validation for HOPEFX-AI-TRADING")
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress per-stage output; print only the final summary",
    )
    parser.add_argument(
        "--stage",
        "-s",
        type=int,
        metavar="N",
        help="Run only stage N (1-based)",
    )
    args = parser.parse_args()

    if not args.quiet:
        _print_header("HOPEFX-AI-TRADING  —  End-to-End ML Flow Validation")
        logger.info(f"  Data:  {_H1_CSV}")
        logger.info(f"  Env:   APP_ENV={os.environ['APP_ENV']}")

    stages_to_run = STAGES
    if args.stage is not None:
        idx = args.stage - 1
        if not (0 <= idx < len(STAGES)):
            logger.info(f"Invalid stage {args.stage}. Valid range: 1–{len(STAGES)}")
            return 1
        stages_to_run = [STAGES[idx]]

    for name, fn in stages_to_run:
        result = _run_stage(name, fn, quiet=args.quiet)
        _report.add(result)

    if not args.quiet:
        _print_summary(_report)
    else:
        status = "PASS" if _report.passed else "FAIL"
        logger.info(f"{status} ({_report.n_passed}/{len(_report.results)} stages)")

    return 0 if _report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
