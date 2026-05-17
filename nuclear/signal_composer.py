# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
nuclear/signal_composer.py
============================
Signal composer — final assembly of a production-ready NuclearSignal.

Takes raw StrategySignal + BacktestResult + RegimeResult + ITOS cone
and produces a fully-specified NuclearSignal with:

  - Entry/exit rules (precise price levels, order types)
  - Risk parameters (position size, max loss, Kelly fraction)
  - Confidence score (composite: strategy + backtest + cone + regime)
  - Approval gate (minimum confidence threshold before execution)
  - Human-readable explanation for the dashboard

Confidence scoring model
------------------------
  base_conf     = strategy signal confidence (0–1)
  backtest_adj  = backtest.confidence_score × 0.30
  cone_adj      = cone alignment bonus/penalty × 0.15
  regime_adj    = regime confidence × 0.20
  macro_adj     = macro environment bonus/penalty × 0.10
  final_conf    = clip(base_conf × 0.25 + backtest_adj + cone_adj
                       + regime_adj + macro_adj, 0, 1)

Risk parameters
---------------
  risk_pct      = base 1% of account, scaled by confidence
  kelly_f       = (win_rate × avg_win - loss_rate × avg_loss) / avg_win
  position_size = risk_pct × kelly_fraction (capped at 2% per trade)
  atr_stop      = entry ± 1.5 × ATR(14) daily
  rr_min        = 1.5 (minimum risk/reward to approve)

Approval gate
-------------
  APPROVED  confidence ≥ 0.60 AND rr ≥ 1.5 AND backtest trades ≥ 3
  PENDING   confidence ≥ 0.45 (human review required)
  REJECTED  confidence < 0.45 OR rr < 1.5

Usage
-----
    composer = SignalComposer()
    nuclear_signal = composer.compose(
        raw_signal, backtest_result, regime, cone_merged, mtf_features
    )
    if nuclear_signal.approval_status == 'APPROVED':
        # send to execution engine
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from nuclear.feature_builder import MultiTimeframeFeatures
from nuclear.regime_classifier import RegimeResult
from nuclear.shadow_backtest import BacktestResult
from nuclear.strategy_engine import LONG, SHORT, StrategySignal

UTC = timezone.utc
logger = logging.getLogger(__name__)

# ── Approval thresholds ───────────────────────────────────────────────────────
_CONF_APPROVED = 0.60
_CONF_PENDING = 0.45
_RR_MIN = 1.5
_MIN_BACKTEST_TRADES = 3
_MAX_RISK_PCT = 0.02  # 2% max per trade
_BASE_RISK_PCT = 0.01  # 1% base risk
_KELLY_CAP = 0.25  # cap Kelly fraction at 25%


@dataclass
class RiskParameters:
    """Position sizing and risk management parameters."""

    risk_pct: float  # fraction of account to risk (e.g. 0.01 = 1%)
    kelly_fraction: float  # Kelly criterion fraction
    position_size_pct: float  # final position size as % of account
    atr_stop_distance: float  # ATR-based stop distance in price units
    max_loss_pct: float  # max loss if SL hit (= risk_pct)
    rr_ratio: float  # risk/reward ratio

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk_pct": round(self.risk_pct, 4),
            "kelly_fraction": round(self.kelly_fraction, 4),
            "position_size_pct": round(self.position_size_pct, 4),
            "atr_stop_distance": round(self.atr_stop_distance, 4),
            "max_loss_pct": round(self.max_loss_pct, 4),
            "rr_ratio": round(self.rr_ratio, 3),
        }


@dataclass
class EntryRules:
    """Precise entry execution rules."""

    order_type: str  # "market" / "limit" / "stop_limit"
    entry_price: float  # target entry price
    limit_offset_pct: float  # for limit orders: offset from current price
    entry_window_bars: int  # bars to wait for limit fill before cancelling
    scale_in: bool  # whether to scale in (3 tranches)
    scale_in_levels: list[float] = field(default_factory=list)  # price levels

    def to_dict(self) -> dict[str, Any]:
        return {
            "order_type": self.order_type,
            "entry_price": round(self.entry_price, 4),
            "limit_offset_pct": round(self.limit_offset_pct, 6),
            "entry_window_bars": self.entry_window_bars,
            "scale_in": self.scale_in,
            "scale_in_levels": [round(p, 4) for p in self.scale_in_levels],
        }


@dataclass
class ExitRules:
    """Precise exit execution rules."""

    stop_loss: float
    stop_type: str  # "hard" / "trailing"
    trailing_atr_mult: float  # for trailing stops: ATR multiplier
    take_profit_1: float  # 50% of position
    take_profit_2: float  # 30% of position
    take_profit_3: float  # 20% of position (runner)
    tp1_size_pct: float = 0.50
    tp2_size_pct: float = 0.30
    tp3_size_pct: float = 0.20
    max_hold_bars: int = 48  # force-close after N bars

    def to_dict(self) -> dict[str, Any]:
        return {
            "stop_loss": round(self.stop_loss, 4),
            "stop_type": self.stop_type,
            "trailing_atr_mult": round(self.trailing_atr_mult, 2),
            "take_profit_1": round(self.take_profit_1, 4),
            "take_profit_2": round(self.take_profit_2, 4),
            "take_profit_3": round(self.take_profit_3, 4),
            "tp1_size_pct": self.tp1_size_pct,
            "tp2_size_pct": self.tp2_size_pct,
            "tp3_size_pct": self.tp3_size_pct,
            "max_hold_bars": self.max_hold_bars,
        }


@dataclass
class NuclearSignal:
    """
    Production-ready signal output from the Nuclear Strategy Agent.

    This is the final artifact passed to the execution engine.
    Brokers are called ONLY after approval_status == 'APPROVED'.
    """

    signal_id: str
    symbol: str
    direction: str
    strategy: str
    regime: str
    timeframe: str

    # Confidence
    confidence: float
    confidence_breakdown: dict[str, float]

    # Approval
    approval_status: str  # "APPROVED" / "PENDING" / "REJECTED"
    approval_reason: str

    # Levels
    entry_rules: EntryRules
    exit_rules: ExitRules
    risk_params: RiskParameters

    # Context
    cone_bias: str
    cone_vol_regime: str
    cone_aligned: bool
    macro_regime: str
    backtest_confidence: float
    backtest_trades: int
    backtest_win_rate: float
    backtest_sharpe: float

    # Explanation
    explanation: str
    reasoning: list[str]

    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def is_approved(self) -> bool:
        return self.approval_status == "APPROVED"

    @property
    def is_actionable(self) -> bool:
        return self.approval_status in ("APPROVED", "PENDING")

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "symbol": self.symbol,
            "direction": self.direction,
            "strategy": self.strategy,
            "regime": self.regime,
            "timeframe": self.timeframe,
            "confidence": round(self.confidence, 3),
            "confidence_breakdown": {k: round(v, 3) for k, v in self.confidence_breakdown.items()},
            "approval_status": self.approval_status,
            "approval_reason": self.approval_reason,
            "entry_rules": self.entry_rules.to_dict(),
            "exit_rules": self.exit_rules.to_dict(),
            "risk_params": self.risk_params.to_dict(),
            "cone_bias": self.cone_bias,
            "cone_vol_regime": self.cone_vol_regime,
            "cone_aligned": self.cone_aligned,
            "macro_regime": self.macro_regime,
            "backtest_confidence": round(self.backtest_confidence, 3),
            "backtest_trades": self.backtest_trades,
            "backtest_win_rate": round(self.backtest_win_rate, 4),
            "backtest_sharpe": round(self.backtest_sharpe, 3),
            "explanation": self.explanation,
            "reasoning": self.reasoning,
            "generated_at": self.generated_at.isoformat(),
        }


# ── SignalComposer ────────────────────────────────────────────────────────────


class SignalComposer:
    """
    Assembles a NuclearSignal from raw strategy output + backtest + context.

    All inputs come from internal components — no broker APIs.
    """

    def __init__(
        self,
        conf_approved: float = _CONF_APPROVED,
        conf_pending: float = _CONF_PENDING,
        rr_min: float = _RR_MIN,
        min_backtest_trades: int = _MIN_BACKTEST_TRADES,
        base_risk_pct: float = _BASE_RISK_PCT,
    ) -> None:
        self._conf_approved = conf_approved
        self._conf_pending = conf_pending
        self._rr_min = rr_min
        self._min_bt_trades = min_backtest_trades
        self._base_risk = base_risk_pct
        self._signal_counter = 0

    # ── Public API ────────────────────────────────────────────────────────────

    def compose(
        self,
        raw_signal: StrategySignal,
        backtest: BacktestResult,
        regime: RegimeResult,
        cone_merged: dict[str, Any] | None,
        mtf: MultiTimeframeFeatures,
    ) -> NuclearSignal:
        """
        Compose a NuclearSignal from all available context.

        Parameters
        ----------
        raw_signal : StrategySignal
            Output from NuclearStrategyEngine.generate().
        backtest : BacktestResult
            Output from ShadowBacktestEngine.run().
        regime : RegimeResult
            Output from RegimeClassifier.classify().
        cone_merged : dict, optional
            Merged ITOS cone from ItosConeEngine.merge_cones().
        mtf : MultiTimeframeFeatures
            Full feature set from FeatureBuilder.build_all().

        Returns
        -------
        NuclearSignal
        """
        self._signal_counter += 1
        signal_id = f"NSA-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{self._signal_counter:04d}"

        # ── Confidence scoring ────────────────────────────────────────────────
        conf_breakdown, final_conf = self._score_confidence(raw_signal, backtest, regime, cone_merged, mtf)

        # ── Risk parameters ───────────────────────────────────────────────────
        risk_params = self._compute_risk(raw_signal, backtest, final_conf, mtf)

        # ── Entry rules ───────────────────────────────────────────────────────
        entry_rules = self._build_entry_rules(raw_signal, regime, final_conf)

        # ── Exit rules ────────────────────────────────────────────────────────
        exit_rules = self._build_exit_rules(raw_signal, mtf, regime)

        # ── Approval gate ─────────────────────────────────────────────────────
        approval_status, approval_reason = self._evaluate_approval(
            final_conf, raw_signal.risk_reward, backtest.total_trades
        )

        # ── Explanation ───────────────────────────────────────────────────────
        explanation = self._build_explanation(raw_signal, regime, cone_merged, backtest, final_conf, approval_status)

        cone_bias = cone_merged.get("bias", "neutral") if cone_merged else "neutral"
        cone_vol = cone_merged.get("vol_regime", "normal_vol") if cone_merged else "normal_vol"

        signal = NuclearSignal(
            signal_id=signal_id,
            symbol=mtf.symbol,
            direction=raw_signal.direction,
            strategy=raw_signal.strategy,
            regime=regime.regime,
            timeframe=raw_signal.timeframe,
            confidence=final_conf,
            confidence_breakdown=conf_breakdown,
            approval_status=approval_status,
            approval_reason=approval_reason,
            entry_rules=entry_rules,
            exit_rules=exit_rules,
            risk_params=risk_params,
            cone_bias=cone_bias,
            cone_vol_regime=cone_vol,
            cone_aligned=raw_signal.cone_aligned,
            macro_regime=regime.macro_regime,
            backtest_confidence=backtest.confidence_score,
            backtest_trades=backtest.total_trades,
            backtest_win_rate=backtest.win_rate,
            backtest_sharpe=backtest.sharpe_ratio,
            explanation=explanation,
            reasoning=raw_signal.reasoning + regime.reasoning[:5],
        )

        logger.info(
            "SignalComposer: %s %s %s conf=%.2f status=%s RR=%.2f",
            signal_id,
            raw_signal.direction,
            raw_signal.strategy,
            final_conf,
            approval_status,
            raw_signal.risk_reward,
        )
        return signal

    # ── Confidence scoring ────────────────────────────────────────────────────

    def _score_confidence(
        self,
        raw: StrategySignal,
        bt: BacktestResult,
        regime: RegimeResult,
        cone: dict[str, Any] | None,
        mtf: MultiTimeframeFeatures,
    ) -> tuple[dict[str, float], float]:
        """
        Compute composite confidence score.

        Components:
          strategy_base   raw signal confidence × 0.25
          backtest        backtest confidence_score × 0.30
          cone_alignment  ±0.15 based on cone alignment
          regime          regime confidence × 0.20
          macro           macro environment × 0.10
        """
        # Strategy base
        strategy_comp = raw.confidence * 0.25

        # Backtest component
        bt_comp = bt.confidence_score * 0.30

        # Cone alignment
        cone_comp = 0.15 if raw.cone_aligned else -0.05  # penalty for misalignment

        # Regime confidence
        regime_comp = regime.confidence * 0.20

        # Macro component
        macro = mtf.macro
        if macro is None:
            macro_comp = 0.0
        elif (macro.gold_bullish_macro and raw.direction == LONG) or (
            macro.gold_bearish_macro and raw.direction == SHORT
        ):
            macro_comp = 0.10
        elif macro.risk_off and raw.direction == LONG:
            macro_comp = 0.05  # partial alignment
        elif not macro.risk_off and raw.direction == SHORT:
            macro_comp = 0.05
        else:
            macro_comp = 0.0

        total = strategy_comp + bt_comp + cone_comp + regime_comp + macro_comp
        final = float(max(0.0, min(total, 1.0)))

        breakdown = {
            "strategy_base": round(strategy_comp, 3),
            "backtest": round(bt_comp, 3),
            "cone_alignment": round(cone_comp, 3),
            "regime": round(regime_comp, 3),
            "macro": round(macro_comp, 3),
            "total": round(final, 3),
        }
        return breakdown, final

    # ── Risk parameters ───────────────────────────────────────────────────────

    def _compute_risk(
        self,
        raw: StrategySignal,
        bt: BacktestResult,
        confidence: float,
        mtf: MultiTimeframeFeatures,
    ) -> RiskParameters:
        """Compute position sizing using Kelly criterion + confidence scaling."""
        # Kelly fraction from backtest stats
        wr = bt.win_rate if bt.total_trades >= self._min_bt_trades else 0.5
        avg_win = abs(bt.avg_win_pct) if bt.avg_win_pct != 0 else 0.01
        avg_loss = abs(bt.avg_loss_pct) if bt.avg_loss_pct != 0 else 0.005
        loss_rate = 1.0 - wr

        kelly = (wr * avg_win - loss_rate * avg_loss) / avg_win if avg_win > 0 else 0.0
        kelly = max(0.0, min(kelly, _KELLY_CAP))

        # Scale risk by confidence
        risk_pct = self._base_risk * (0.5 + confidence * 0.5)
        risk_pct = min(risk_pct, _MAX_RISK_PCT)

        # Position size = risk_pct × kelly (half-Kelly for safety)
        position_size = risk_pct * (kelly * 0.5 + 0.5)
        position_size = min(position_size, _MAX_RISK_PCT)

        # ATR stop distance from daily features
        daily = mtf.get("daily")
        atr = daily.atr if daily and daily.atr > 0 else raw.entry_price * 0.005
        atr_stop = 1.5 * atr

        return RiskParameters(
            risk_pct=risk_pct,
            kelly_fraction=kelly,
            position_size_pct=position_size,
            atr_stop_distance=atr_stop,
            max_loss_pct=risk_pct,
            rr_ratio=raw.risk_reward,
        )

    # ── Entry rules ───────────────────────────────────────────────────────────

    def _build_entry_rules(
        self,
        raw: StrategySignal,
        regime: RegimeResult,
        confidence: float,
    ) -> EntryRules:
        """
        Determine order type and entry parameters.

        High confidence + trending → market order
        Medium confidence → limit order at slight discount
        Breakout → stop-limit above/below breakout level
        """
        if regime.regime in ("breakout", "high_vol"):
            order_type = "stop_limit"
            offset = 0.0005  # 0.05% above/below breakout
        elif confidence >= 0.70:
            order_type = "market"
            offset = 0.0
        else:
            order_type = "limit"
            offset = 0.001  # 0.1% better than current price

        # Scale-in for high-confidence trending signals
        scale_in = confidence >= 0.75 and regime.is_trending
        if scale_in:
            price = raw.entry_price
            if raw.direction == LONG:
                levels = [price, price * 0.998, price * 0.996]
            else:
                levels = [price, price * 1.002, price * 1.004]
        else:
            levels = [raw.entry_price]

        return EntryRules(
            order_type=order_type,
            entry_price=raw.entry_price,
            limit_offset_pct=offset,
            entry_window_bars=3 if order_type == "limit" else 1,
            scale_in=scale_in,
            scale_in_levels=levels,
        )

    # ── Exit rules ────────────────────────────────────────────────────────────

    def _build_exit_rules(
        self,
        raw: StrategySignal,
        mtf: MultiTimeframeFeatures,
        regime: RegimeResult,
    ) -> ExitRules:
        """Build exit rules with trailing stop for trending regimes."""
        # Trailing stop for trending regimes
        if regime.is_trending:
            stop_type = "trailing"
            trailing_mult = 2.0
        else:
            stop_type = "hard"
            trailing_mult = 0.0

        # Max hold: shorter for mean-reversion, longer for trend
        if regime.is_ranging:
            max_hold = 12  # 12 bars
        elif regime.is_trending:
            max_hold = 96  # 96 bars
        else:
            max_hold = 48

        return ExitRules(
            stop_loss=raw.stop_loss,
            stop_type=stop_type,
            trailing_atr_mult=trailing_mult,
            take_profit_1=raw.take_profit_1,
            take_profit_2=raw.take_profit_2,
            take_profit_3=raw.take_profit_3,
            max_hold_bars=max_hold,
        )

    # ── Approval gate ─────────────────────────────────────────────────────────

    def _evaluate_approval(
        self,
        confidence: float,
        rr: float,
        bt_trades: int,
    ) -> tuple[str, str]:
        """Evaluate whether signal meets execution criteria."""
        reasons: list[str] = []

        if rr < self._rr_min:
            reasons.append(f"RR {rr:.2f} < minimum {self._rr_min}")
            return "REJECTED", "; ".join(reasons)

        if confidence < self._conf_pending:
            reasons.append(f"confidence {confidence:.2f} < {self._conf_pending}")
            return "REJECTED", "; ".join(reasons)

        if confidence >= self._conf_approved and bt_trades >= self._min_bt_trades:
            return "APPROVED", f"conf={confidence:.2f} RR={rr:.2f} bt_trades={bt_trades}"

        if confidence >= self._conf_pending:
            if bt_trades < self._min_bt_trades:
                reasons.append(f"backtest trades {bt_trades} < {self._min_bt_trades}")
            reasons.append(f"confidence {confidence:.2f} < {self._conf_approved} threshold")
            return "PENDING", "; ".join(reasons)

        return "REJECTED", f"confidence {confidence:.2f} below all thresholds"

    # ── Explanation builder ───────────────────────────────────────────────────

    @staticmethod
    def _build_explanation(
        raw: StrategySignal,
        regime: RegimeResult,
        cone: dict[str, Any] | None,
        bt: BacktestResult,
        confidence: float,
        status: str,
    ) -> str:
        """Build a human-readable explanation for the dashboard."""
        direction_word = "LONG" if raw.direction == LONG else "SHORT"
        cone_bias = cone.get("bias", "neutral") if cone else "neutral"
        cone_vol = cone.get("vol_regime", "normal_vol") if cone else "normal_vol"

        lines = [
            f"{status} {direction_word} {raw.strategy.upper().replace('_', '/')} signal",
            f"Regime: {regime.regime} (conf={regime.confidence:.0%})",
            f"ITOS cone: {cone_bias} drift, {cone_vol}",
            f"Entry: {raw.entry_price:.2f} | SL: {raw.stop_loss:.2f} | TP1: {raw.take_profit_1:.2f}",
            f"RR: {raw.risk_reward:.2f}x | Signal confidence: {confidence:.0%}",
        ]

        if bt.total_trades > 0:
            lines.append(
                f"Backtest ({bt.total_trades} trades): WR={bt.win_rate:.0%} "
                f"Sharpe={bt.sharpe_ratio:.2f} MDD={bt.max_drawdown_pct:.1%}"
            )
        else:
            lines.append("Backtest: insufficient data (< 3 trades)")

        if raw.cone_aligned:
            lines.append(f"Cone-aligned: YES ({cone_bias})")
        else:
            lines.append("Cone-aligned: NO — confidence reduced")

        return " | ".join(lines)


# ── Singleton ─────────────────────────────────────────────────────────────────

_composer_instance: SignalComposer | None = None


def get_signal_composer() -> SignalComposer:
    """Return the process-wide SignalComposer singleton."""
    global _composer_instance
    if _composer_instance is None:
        _composer_instance = SignalComposer()
    return _composer_instance
