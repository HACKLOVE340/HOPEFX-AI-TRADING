# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""
brain/nuclear_supervisor.py
============================
NuclearHopeFXSupervisor — RL-powered nuclear event response system.

Combines two decision layers:

  1. NuclearWordMapScorer  — fast, deterministic WORDMAP keyword scoring
     that produces a severity [0–10] and base action recommendation.

  2. PPO RL agent (nuclear_decision_ppo.zip) — trained on a synthetic
     Gymnasium environment to map a 7-dim observation to one of four
     discrete actions:
         0 = NORMAL   — continue trading
         1 = PAUSE    — halt new entries, keep existing positions
         2 = HEDGE    — reduce max risk to 15 %, open inverse hedges
         3 = NUCLEAR  — full liquidation + trading halt

  If the RL model is unavailable the supervisor falls back to the
  deterministic WORDMAP severity thresholds.

Observation vector (7 dims):
    [0] severity / 10.0          normalised WORDMAP severity
    [1] volatility               current market vol (1.0 = normal)
    [2] sentiment                news sentiment [-1, 1]
    [3] confidence               scorer confidence [0, 1]
    [4] current_exposure         portfolio risk exposure [0, 1]
    [5] nuclear_level / 3.0      current escalation level
    [6] trading_paused           1.0 if paused, 0.0 otherwise

Wiring (connect_to_life.py):
    supervisor = NuclearHopeFXSupervisor()
    async def event_callback(event):
        await supervisor.on_new_event(event)

Event dict schema:
    {
        "text":             str,    # raw news headline + body
        "volatility":       float,  # 1.0 = normal (optional, default 1.0)
        "sentiment":        float,  # [-1, 1] (optional, default 0.0)
        "current_exposure": float,  # [0, 1] from risk engine (optional, default 0.5)
    }
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ── Optional RL imports ───────────────────────────────────────────────────────
try:
    from stable_baselines3 import PPO
    _SB3_AVAILABLE = True
except ImportError:
    PPO = None  # type: ignore
    _SB3_AVAILABLE = False
    logger.warning("stable-baselines3 not installed — RL agent disabled, using rule-based fallback")

# ── Internal imports ──────────────────────────────────────────────────────────
from news.nuclear_wordmap_scorer import NuclearWordMapScorer

# Lazy imports to avoid circular dependencies at module load time
_kill_switch = None
_risk_orchestrator = None
_notifications = None


def _get_kill_switch():
    global _kill_switch
    if _kill_switch is None:
        try:
            from kill_switch import kill_switch as ks
            _kill_switch = ks
        except Exception as exc:
            logger.warning("kill_switch import failed: %s", exc)
    return _kill_switch


def _get_risk_orchestrator():
    global _risk_orchestrator
    if _risk_orchestrator is None:
        try:
            from risk.orchestrator import risk_orchestrator as ro
            _risk_orchestrator = ro
        except Exception as exc:
            logger.warning("risk_orchestrator import failed: %s", exc)
    return _risk_orchestrator


def _get_notifications():
    global _notifications
    if _notifications is None:
        try:
            from notifications import notifications as notif
            _notifications = notif
        except Exception as exc:
            logger.warning("notifications import failed: %s", exc)
    return _notifications


# ── Action constants ──────────────────────────────────────────────────────────
ACTION_NORMAL = 0
ACTION_PAUSE = 1
ACTION_HEDGE = 2
ACTION_NUCLEAR = 3

_ACTION_NAMES = {
    ACTION_NORMAL: "NORMAL",
    ACTION_PAUSE: "PAUSE",
    ACTION_HEDGE: "HEDGE",
    ACTION_NUCLEAR: "NUCLEAR",
}

# Default RL model path (relative to project root)
_DEFAULT_MODEL_PATH = "ml/rl_models/nuclear_decision_ppo.zip"


class NuclearHopeFXSupervisor:
    """
    RL-powered supervisor that responds to nuclear/geopolitical/macro events.

    Parameters
    ----------
    model_path : str | Path, optional
        Path to the trained PPO model zip.  Defaults to
        ``ml/rl_models/nuclear_decision_ppo.zip``.
    wordmap_path : str | Path, optional
        Path to WORDMAP.json.  Passed to NuclearWordMapScorer.
    cooldown_seconds : int
        Minimum seconds between consecutive nuclear/hedge triggers to
        prevent rapid oscillation.  Default 60.
    auto_resume_seconds : int
        Seconds after which a PAUSE state auto-resumes if no new high-
        severity event arrives.  0 = never auto-resume.  Default 300.
    """

    def __init__(
        self,
        model_path: Optional[str | Path] = None,
        wordmap_path: Optional[str | Path] = None,
        cooldown_seconds: int = 60,
        auto_resume_seconds: int = 300,
    ) -> None:
        self.nuclear_level: int = 0          # 0=normal 1=pause 2=hedge 3=nuclear
        self.trading_paused: bool = False
        self._cooldown_seconds = cooldown_seconds
        self._auto_resume_seconds = auto_resume_seconds
        self._last_trigger_ts: float = 0.0
        self._pause_since_ts: float = 0.0

        # WORDMAP scorer
        self.scorer = NuclearWordMapScorer(wordmap_path=wordmap_path)

        # RL agent
        self._model_path = Path(model_path or _DEFAULT_MODEL_PATH)
        self.rl_agent = self._load_rl_agent()

        # Event history for audit trail (last 100 events)
        self._event_history: list[Dict[str, Any]] = []

        logger.info(
            "NuclearHopeFXSupervisor ready | rl_agent=%s model=%s",
            "loaded" if self.rl_agent is not None else "fallback",
            self._model_path,
        )

    # ── RL agent loader ───────────────────────────────────────────────────────

    def _load_rl_agent(self) -> Optional[Any]:
        """Load the trained PPO model. Returns None if unavailable."""
        if not _SB3_AVAILABLE:
            logger.warning("RL agent disabled — stable-baselines3 not installed")
            return None

        if not self._model_path.exists():
            logger.warning(
                "RL model not found at %s — falling back to rule-based. "
                "Train with: python ml/train_rl_nuclear.py",
                self._model_path,
            )
            return None

        try:
            agent = PPO.load(str(self._model_path))
            logger.info("RL agent loaded from %s", self._model_path)
            return agent
        except Exception as exc:
            logger.warning("RL agent load failed (%s) — falling back to rule-based", exc)
            return None

    def reload_rl_agent(self) -> bool:
        """Hot-reload the RL model from disk. Returns True on success."""
        self.rl_agent = self._load_rl_agent()
        return self.rl_agent is not None

    # ── Observation builder ───────────────────────────────────────────────────

    def _build_rl_observation(
        self,
        severity: int,
        vol: float,
        sentiment: float,
        meta: Dict,
        current_exposure: float,
    ) -> np.ndarray:
        """Build the 7-dim observation vector the RL agent expects."""
        return np.array(
            [
                severity / 10.0,                        # [0] normalised severity
                float(np.clip(vol, 0.0, 5.0)),          # [1] volatility (clipped)
                float(np.clip(sentiment, -1.0, 1.0)),   # [2] sentiment
                float(meta.get("confidence", 0.5)),     # [3] scorer confidence
                float(np.clip(current_exposure, 0.0, 1.0)),  # [4] exposure
                self.nuclear_level / 3.0,               # [5] current nuclear level
                1.0 if self.trading_paused else 0.0,    # [6] paused state
            ],
            dtype=np.float32,
        )

    # ── Main event handler ────────────────────────────────────────────────────

    async def on_new_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a news/market event and take the appropriate action.

        Parameters
        ----------
        event : dict
            Keys: text, volatility (opt), sentiment (opt), current_exposure (opt)

        Returns
        -------
        dict with keys: severity, action_taken, rl_action, nuclear_level,
                        trading_paused, score, meta
        """
        news_text = event.get("text", "")
        vol = float(event.get("volatility", 1.0))
        sentiment = float(event.get("sentiment", 0.0))
        current_exposure = float(event.get("current_exposure", 0.5))

        # ── Step 1: WORDMAP scoring ───────────────────────────────────────────
        severity, base_action, score, meta = self.scorer.score_event(
            news_text, vol, sentiment
        )

        # ── Step 2: Auto-resume check ─────────────────────────────────────────
        await self._maybe_auto_resume()

        # ── Step 3: Cooldown guard ────────────────────────────────────────────
        now = time.monotonic()
        in_cooldown = (now - self._last_trigger_ts) < self._cooldown_seconds

        # ── Step 4: Decide action ─────────────────────────────────────────────
        rl_action: Optional[int] = None
        action_taken: str = "normal"

        if self.rl_agent is not None:
            obs = self._build_rl_observation(severity, vol, sentiment, meta, current_exposure)
            raw_action, _ = self.rl_agent.predict(obs, deterministic=True)
            rl_action = int(raw_action)

            # Severity override: RL cannot downgrade a critical event
            if severity >= 9:
                rl_action = max(rl_action, ACTION_NUCLEAR)
            elif severity >= 7:
                rl_action = max(rl_action, ACTION_HEDGE)
            elif severity >= 5:
                rl_action = max(rl_action, ACTION_PAUSE)

            action_taken = await self._execute_action(rl_action, severity, in_cooldown)
        else:
            # Rule-based fallback
            action_taken = await self._rule_based_fallback(severity, in_cooldown)

        # ── Step 5: Audit trail ───────────────────────────────────────────────
        record = {
            "ts": time.time(),
            "severity": severity,
            "score": score,
            "base_action": base_action,
            "rl_action": _ACTION_NAMES.get(rl_action, "N/A") if rl_action is not None else "N/A",
            "action_taken": action_taken,
            "nuclear_level": self.nuclear_level,
            "trading_paused": self.trading_paused,
            "vol": vol,
            "sentiment": sentiment,
            "exposure": current_exposure,
            "matched_terms": [t["term"] for t in meta.get("matched_terms", [])[:5]],
        }
        self._event_history.append(record)
        if len(self._event_history) > 100:
            self._event_history.pop(0)

        logger.info(
            "NuclearSupervisor | severity=%d score=%.3f rl=%s action=%s "
            "nuclear_level=%d paused=%s",
            severity, score,
            _ACTION_NAMES.get(rl_action, "N/A") if rl_action is not None else "rule",
            action_taken, self.nuclear_level, self.trading_paused,
        )

        return record

    # ── Action executor ───────────────────────────────────────────────────────

    async def _execute_action(
        self, rl_action: int, severity: int, in_cooldown: bool
    ) -> str:
        """Execute the RL-chosen action. Returns the action name string."""
        if rl_action == ACTION_NUCLEAR:
            if not in_cooldown or severity >= 9:
                logger.critical(
                    "☢️ RL NUCLEAR ACTION | severity=%d rl_action=%d",
                    severity, rl_action,
                )
                self.nuclear_level = 3
                self._last_trigger_ts = time.monotonic()
                await self.trigger_full_nuclear_mode()
                return "nuclear"
            else:
                logger.info("Nuclear action suppressed by cooldown (severity=%d)", severity)
                return "nuclear_cooldown_suppressed"

        elif rl_action == ACTION_HEDGE:
            if not in_cooldown or severity >= 7:
                logger.warning("⚠️ RL HEDGE MODE | severity=%d", severity)
                self.nuclear_level = 2
                self._last_trigger_ts = time.monotonic()
                await self.trigger_hedge_mode()
                return "hedge"
            else:
                return "hedge_cooldown_suppressed"

        elif rl_action == ACTION_PAUSE:
            logger.info("RL PAUSE | severity=%d", severity)
            self.nuclear_level = max(self.nuclear_level, 1)
            self.trading_paused = True
            self._pause_since_ts = time.monotonic()
            return "pause"

        else:  # ACTION_NORMAL
            if self.nuclear_level > 0 and severity < 3:
                # Gradual de-escalation
                self.nuclear_level = max(0, self.nuclear_level - 1)
                if self.nuclear_level == 0:
                    self.trading_paused = False
            logger.debug("RL NORMAL | severity=%d nuclear_level=%d", severity, self.nuclear_level)
            return "normal"

    async def _rule_based_fallback(self, severity: int, in_cooldown: bool) -> str:
        """Deterministic fallback when RL model is unavailable."""
        if severity >= 9:
            if not in_cooldown:
                self.nuclear_level = 3
                self._last_trigger_ts = time.monotonic()
                await self.trigger_full_nuclear_mode()
            return "nuclear"
        elif severity >= 7:
            if not in_cooldown:
                self.nuclear_level = 2
                self._last_trigger_ts = time.monotonic()
                await self.trigger_hedge_mode()
            return "hedge"
        elif severity >= 5:
            self.nuclear_level = max(self.nuclear_level, 1)
            self.trading_paused = True
            self._pause_since_ts = time.monotonic()
            return "pause"
        else:
            if self.nuclear_level > 0 and severity < 3:
                self.nuclear_level = max(0, self.nuclear_level - 1)
                if self.nuclear_level == 0:
                    self.trading_paused = False
            return "normal"

    # ── Auto-resume ───────────────────────────────────────────────────────────

    async def _maybe_auto_resume(self) -> None:
        """Resume trading if paused longer than auto_resume_seconds."""
        if (
            self._auto_resume_seconds > 0
            and self.trading_paused
            and self.nuclear_level <= 1
            and self._pause_since_ts > 0
        ):
            elapsed = time.monotonic() - self._pause_since_ts
            if elapsed >= self._auto_resume_seconds:
                logger.info(
                    "Auto-resuming trading after %.0fs pause (nuclear_level=%d)",
                    elapsed, self.nuclear_level,
                )
                self.trading_paused = False
                self.nuclear_level = 0
                self._pause_since_ts = 0.0
                notif = _get_notifications()
                if notif:
                    await notif.send_critical_alert(
                        "✅ HOPEFX: Trading auto-resumed after pause period"
                    )

    # ── Nuclear mode triggers ─────────────────────────────────────────────────

    async def trigger_full_nuclear_mode(self) -> None:
        """
        Full nuclear response:
          1. Activate system-wide kill switch (liquidate all + halt)
          2. Set risk orchestrator max risk to 0
          3. Send critical alert
        """
        self.trading_paused = True

        ks = _get_kill_switch()
        if ks is not None:
            try:
                await ks.trigger_nuclear_mode()
            except Exception as exc:
                logger.error("kill_switch.trigger_nuclear_mode failed: %s", exc)
        else:
            logger.critical("☢️ NUCLEAR MODE — kill_switch unavailable, manual intervention required")

        ro = _get_risk_orchestrator()
        if ro is not None:
            try:
                await ro.set_max_risk(0.0)
            except Exception as exc:
                logger.error("risk_orchestrator.set_max_risk(0) failed: %s", exc)

        notif = _get_notifications()
        if notif is not None:
            try:
                await notif.send_critical_alert(
                    "☢️ RL-TRIGGERED NUCLEAR MODE — ALL TRADING HALTED\n"
                    f"Nuclear level: {self.nuclear_level} | "
                    f"Paused: {self.trading_paused}"
                )
            except Exception as exc:
                logger.error("Notification send failed: %s", exc)

        logger.critical(
            "☢️ NUCLEAR MODE ACTIVE | nuclear_level=%d trading_paused=%s",
            self.nuclear_level, self.trading_paused,
        )

    async def trigger_hedge_mode(self) -> None:
        """
        Hedge response:
          1. Set risk orchestrator max risk to 15 %
          2. Send warning alert
        """
        ro = _get_risk_orchestrator()
        if ro is not None:
            try:
                await ro.set_max_risk(0.15)
                await ro.activate_hedge_mode(symbol="XAU_USD")
            except Exception as exc:
                logger.error("risk_orchestrator hedge failed: %s", exc)

        notif = _get_notifications()
        if notif is not None:
            try:
                await notif.send_critical_alert(
                    "⚠️ HOPEFX HEDGE MODE ACTIVATED\n"
                    "Max risk reduced to 15%. Inverse hedges opened on XAU_USD."
                )
            except Exception as exc:
                logger.error("Notification send failed: %s", exc)

        logger.warning(
            "⚠️ HEDGE MODE ACTIVE | nuclear_level=%d", self.nuclear_level
        )

    # ── Manual controls ───────────────────────────────────────────────────────

    async def manual_resume(self) -> None:
        """Manually resume trading and reset nuclear level."""
        self.nuclear_level = 0
        self.trading_paused = False
        self._pause_since_ts = 0.0
        self._last_trigger_ts = 0.0

        ro = _get_risk_orchestrator()
        if ro is not None:
            try:
                await ro.set_max_risk(1.0)  # restore full risk budget
                await ro.deactivate_hedge_mode()
            except Exception as exc:
                logger.error("risk_orchestrator resume failed: %s", exc)

        logger.info("NuclearSupervisor: manual resume — trading restored")

    def get_status(self) -> Dict[str, Any]:
        """Return current supervisor state for monitoring."""
        return {
            "nuclear_level": self.nuclear_level,
            "trading_paused": self.trading_paused,
            "rl_agent_loaded": self.rl_agent is not None,
            "model_path": str(self._model_path),
            "cooldown_remaining": max(
                0.0,
                self._cooldown_seconds - (time.monotonic() - self._last_trigger_ts),
            ),
            "pause_elapsed": (
                time.monotonic() - self._pause_since_ts
                if self._pause_since_ts > 0 else 0.0
            ),
            "event_history_count": len(self._event_history),
            "last_event": self._event_history[-1] if self._event_history else None,
        }

    def get_event_history(self, n: int = 20) -> list[Dict[str, Any]]:
        """Return the last n processed events."""
        return self._event_history[-n:]


# ── Module-level singleton ────────────────────────────────────────────────────

_supervisor_instance: Optional[NuclearHopeFXSupervisor] = None


def get_nuclear_supervisor(
    model_path: Optional[str] = None,
    wordmap_path: Optional[str] = None,
) -> NuclearHopeFXSupervisor:
    """Return the module-level singleton, creating it on first call."""
    global _supervisor_instance
    if _supervisor_instance is None:
        _supervisor_instance = NuclearHopeFXSupervisor(
            model_path=model_path,
            wordmap_path=wordmap_path,
        )
    return _supervisor_instance
