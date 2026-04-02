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
import time
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# ── Prometheus metrics ────────────────────────────────────────────────────────
try:
    from prometheus_client import Counter, Gauge, Histogram

    _NUCLEAR_EVENTS_TOTAL = Counter(
        "hopefx_nuclear_events_total",
        "Total nuclear supervisor events processed",
        ["action"],
    )
    _NUCLEAR_LEVEL_GAUGE = Gauge(
        "hopefx_nuclear_level",
        "Current nuclear escalation level (0=normal 1=pause 2=hedge 3=nuclear)",
    )
    _NUCLEAR_SEVERITY_HIST = Histogram(
        "hopefx_nuclear_severity",
        "Distribution of WORDMAP severity scores",
        buckets=[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    )
    _NUCLEAR_TRADING_PAUSED = Gauge(
        "hopefx_nuclear_trading_paused",
        "1 when trading is paused by the nuclear supervisor, 0 otherwise",
    )
    _PROM_NUCLEAR_AVAILABLE = True
except ImportError:
    _PROM_NUCLEAR_AVAILABLE = False

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
        except ImportError:
            try:
                # Fallback: import the class and instantiate
                from kill_switch import KillSwitch

                _kill_switch = KillSwitch()
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
_DEFAULT_VECNORM_PATH = "ml/rl_models/nuclear_decision_vecnorm.pkl"


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
        model_path: str | Path | None = None,
        wordmap_path: str | Path | None = None,
        vecnorm_path: str | Path | None = None,
        cooldown_seconds: int = 60,
        auto_resume_seconds: int = 300,
    ) -> None:
        self.nuclear_level: int = 0  # 0=normal 1=pause 2=hedge 3=nuclear
        self.trading_paused: bool = False
        self._monitoring_only: bool = False  # True when in nuclear monitoring-only state
        self._monitoring_task_running: bool = False
        self._cooldown_seconds = cooldown_seconds
        self._auto_resume_seconds = auto_resume_seconds
        self._last_trigger_ts: float = 0.0
        self._pause_since_ts: float = 0.0

        # WORDMAP scorer
        self.scorer = NuclearWordMapScorer(wordmap_path=wordmap_path)

        # RL agent + VecNormalize wrapper
        self._model_path = Path(model_path or _DEFAULT_MODEL_PATH)
        self._vecnorm_path = Path(vecnorm_path or _DEFAULT_VECNORM_PATH)
        self.rl_agent = self._load_rl_agent()
        self._vec_normalize = self._load_vec_normalize()

        # Event history for audit trail (last 100 events)
        self._event_history: list[dict[str, Any]] = []

        logger.info(
            "NuclearHopeFXSupervisor ready | rl_agent=%s vecnorm=%s model=%s",
            "loaded" if self.rl_agent is not None else "fallback",
            "loaded" if self._vec_normalize is not None else "none",
            self._model_path,
        )

    # ── RL agent loader ───────────────────────────────────────────────────────

    def _load_rl_agent(self) -> Any | None:
        """Load the trained PPO model. Returns None if unavailable."""
        if not _SB3_AVAILABLE:
            logger.warning("RL agent disabled — stable-baselines3 not installed")
            return None

        if not self._model_path.exists():
            logger.warning(
                "RL model not found at %s — falling back to rule-based. Train with: python ml/train_rl_nuclear.py",
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

    def _load_vec_normalize(self) -> Any | None:
        """
        Load the VecNormalize statistics saved alongside the PPO model.

        The normalizer is applied to every observation before passing it to
        the RL agent so that inference matches the training distribution.
        Returns None if the file is absent or stable-baselines3 is not installed.
        """
        if not _SB3_AVAILABLE:
            return None
        if not self._vecnorm_path.exists():
            logger.debug(
                "VecNormalize stats not found at %s — observations will not be normalised",
                self._vecnorm_path,
            )
            return None
        try:
            from stable_baselines3.common.vec_env import VecNormalize, DummyVecEnv
            import gymnasium as gym
            from gymnasium import spaces

            # Build a minimal env whose observation space exactly matches the
            # 7-dim Box used during PPO training (see module docstring for the
            # observation vector layout).  CartPole has a 4-dim space and would
            # cause a shape mismatch that silently corrupts normalisation.
            class _HopeFXDummyEnv(gym.Env):
                """Minimal env matching the 7-dim observation space of the RL agent."""

                observation_space = spaces.Box(
                    low=np.array([0.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32),
                    high=np.array([1.0, 10.0, 1.0, 1.0, 1.0, 1.0, 1.0], dtype=np.float32),
                    dtype=np.float32,
                )
                action_space = spaces.Discrete(4)  # NORMAL / PAUSE / HEDGE / NUCLEAR

                def reset(self, **kwargs):
                    return self.observation_space.sample(), {}

                def step(self, action):
                    obs = self.observation_space.sample()
                    return obs, 0.0, False, False, {}

            venv = DummyVecEnv([_HopeFXDummyEnv])

            # Load the saved normalizer statistics into the correct env shape
            vn = VecNormalize.load(str(self._vecnorm_path), venv=venv)
            vn.training = False  # freeze running stats
            vn.norm_reward = False  # we only normalise observations
            logger.info("VecNormalize stats loaded from %s", self._vecnorm_path)
            return vn
        except Exception as exc:
            logger.warning(
                "VecNormalize load failed (%s) — observations will not be normalised",
                exc,
            )
            return None

    def _normalize_obs(self, obs: np.ndarray) -> np.ndarray:
        """
        Apply VecNormalize to a single observation vector.

        VecNormalize expects shape (n_envs, obs_dim); we add/remove the
        batch dimension around the call.
        """
        if self._vec_normalize is None:
            return obs
        try:
            # VecNormalize.normalize_obs expects (n_envs, obs_dim)
            batched = obs.reshape(1, -1)
            normalised = self._vec_normalize.normalize_obs(batched)
            return normalised.reshape(-1).astype(np.float32)
        except Exception as exc:
            logger.debug("VecNormalize.normalize_obs failed (%s) — using raw obs", exc)
            return obs

    def reload_rl_agent(self) -> bool:
        """Hot-reload the RL model and VecNormalize stats from disk."""
        self.rl_agent = self._load_rl_agent()
        self._vec_normalize = self._load_vec_normalize()
        return self.rl_agent is not None

    # ── Observation builder ───────────────────────────────────────────────────

    def _build_rl_observation(
        self,
        severity: int,
        vol: float,
        sentiment: float,
        meta: dict,
        current_exposure: float,
    ) -> np.ndarray:
        """Build the 7-dim observation vector the RL agent expects."""
        return np.array(
            [
                severity / 10.0,  # [0] normalised severity
                float(np.clip(vol, 0.0, 5.0)),  # [1] volatility (clipped)
                float(np.clip(sentiment, -1.0, 1.0)),  # [2] sentiment
                float(meta.get("confidence", 0.5)),  # [3] scorer confidence
                float(np.clip(current_exposure, 0.0, 1.0)),  # [4] exposure
                self.nuclear_level / 3.0,  # [5] current nuclear level
                1.0 if self.trading_paused else 0.0,  # [6] paused state
            ],
            dtype=np.float32,
        )

    # ── Main event handler ────────────────────────────────────────────────────

    async def on_new_event(self, event: dict[str, Any]) -> dict[str, Any]:
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
        severity, base_action, score, meta = self.scorer.score_event(news_text, vol, sentiment)

        # ── Step 2: Auto-resume check ─────────────────────────────────────────
        await self._maybe_auto_resume()

        # ── Step 3: Cooldown guard ────────────────────────────────────────────
        now = time.monotonic()
        in_cooldown = (now - self._last_trigger_ts) < self._cooldown_seconds

        # ── Step 4: Decide action ─────────────────────────────────────────────
        rl_action: int | None = None
        action_taken: str = "normal"

        if self.rl_agent is not None:
            obs = self._build_rl_observation(severity, vol, sentiment, meta, current_exposure)
            obs = self._normalize_obs(obs)  # apply VecNormalize if available
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
            "NuclearSupervisor | severity=%d score=%.3f rl=%s action=%s nuclear_level=%d paused=%s",
            severity,
            score,
            _ACTION_NAMES.get(rl_action, "N/A") if rl_action is not None else "rule",
            action_taken,
            self.nuclear_level,
            self.trading_paused,
        )

        # ── Prometheus metrics ────────────────────────────────────────────────
        if _PROM_NUCLEAR_AVAILABLE:
            try:
                _NUCLEAR_EVENTS_TOTAL.labels(action=action_taken).inc()
                _NUCLEAR_LEVEL_GAUGE.set(self.nuclear_level)
                _NUCLEAR_SEVERITY_HIST.observe(severity)
                _NUCLEAR_TRADING_PAUSED.set(1.0 if self.trading_paused else 0.0)
            except Exception as _prom_exc:
                logger.debug("Prometheus nuclear metrics update failed: %s", _prom_exc)

        return record

    # ── Action executor ───────────────────────────────────────────────────────

    async def _execute_action(self, rl_action: int, severity: int, in_cooldown: bool) -> str:
        """Execute the RL-chosen action. Returns the action name string."""
        if rl_action == ACTION_NUCLEAR:
            if not in_cooldown or severity >= 9:
                logger.critical(
                    "☢️ RL NUCLEAR ACTION | severity=%d rl_action=%d",
                    severity,
                    rl_action,
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
            else:
                # severity >= 9 always fires even in cooldown (safety override)
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
            else:
                logger.info("Hedge action suppressed by cooldown (severity=%d)", severity)
                return "hedge_cooldown_suppressed"
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
                    elapsed,
                    self.nuclear_level,
                )
                self.trading_paused = False
                self.nuclear_level = 0
                self._pause_since_ts = 0.0
                notif = _get_notifications()
                if notif:
                    await notif.send_critical_alert("✅ HOPEFX: Trading auto-resumed after pause period")

    # ── Nuclear mode triggers ─────────────────────────────────────────────────

    async def trigger_full_nuclear_mode(self) -> None:
        """
        Full nuclear response — monitoring-only mode.

        The process stays alive so the supervisor can continue watching for
        de-escalation and send status updates.  Trading is blocked via:
          1. Kill switch activation (blocks all order paths in the engine)
          2. RiskOrchestrator max_risk → 0 (secondary block)

        The engine loop keeps running; it will see kill_switch.is_active()
        and skip order execution on every tick.  When severity drops and
        manual_resume() is called, the kill switch is deactivated and trading
        resumes without a process restart.
        """
        self.trading_paused = True
        self._monitoring_only = True  # flag: process alive, trading blocked

        # 1. Activate kill switch — blocks all order paths (fail-safe)
        ks = _get_kill_switch()
        if ks is not None:
            try:
                ks.activate("RL nuclear supervisor: nuclear event detected")
                logger.critical("☢️ KillSwitch activated — process stays alive in monitoring mode")
            except Exception as exc:
                logger.error("kill_switch.activate failed: %s", exc)
        else:
            logger.critical("☢️ NUCLEAR MODE — kill_switch unavailable, manual intervention required")

        # 2. Zero out risk budget (belt-and-suspenders)
        ro = _get_risk_orchestrator()
        if ro is not None:
            try:
                await ro.set_max_risk(0.0)
            except Exception as exc:
                logger.error("risk_orchestrator.set_max_risk(0) failed: %s", exc)

        # 3. Alert
        notif = _get_notifications()
        if notif is not None:
            try:
                await notif.send_critical_alert(
                    "☢️ RL-TRIGGERED NUCLEAR MODE — ALL TRADING HALTED\n"
                    f"Nuclear level: {self.nuclear_level} | "
                    "Process alive in monitoring-only state.\n"
                    "Call manual_resume() or POST /nuclear/resume to restore trading."
                )
            except Exception as exc:
                logger.error("Notification send failed: %s", exc)

        logger.critical(
            "☢️ NUCLEAR MODE ACTIVE | nuclear_level=%d trading_paused=%s "
            "monitoring_only=True — process alive, orders blocked",
            self.nuclear_level,
            self.trading_paused,
        )

        # 4. Start background monitoring loop if not already running
        if not getattr(self, "_monitoring_task_running", False):
            asyncio.create_task(
                self._nuclear_monitoring_loop(),
                name="nuclear_monitoring_loop",
            )

    async def _nuclear_monitoring_loop(self) -> None:
        """
        Background loop that runs while in nuclear/monitoring-only mode.

        Emits a status heartbeat every 60 s so operators know the process
        is alive.  Exits when nuclear_level drops back to 0 (manual_resume
        or auto-resume).
        """
        self._monitoring_task_running = True
        heartbeat_interval = 60  # seconds
        logger.info("Nuclear monitoring loop started")
        try:
            while self._monitoring_only and self.nuclear_level > 0:
                await asyncio.sleep(heartbeat_interval)
                ks = _get_kill_switch()
                ks_active = ks.is_active() if ks else False
                logger.critical(
                    "☢️ NUCLEAR MONITORING | nuclear_level=%d paused=%s kill_switch=%s — awaiting manual_resume()",
                    self.nuclear_level,
                    self.trading_paused,
                    ks_active,
                )
                notif = _get_notifications()
                if notif is not None:
                    try:
                        await notif.send_warning(
                            f"☢️ HOPEFX nuclear monitoring active | "
                            f"level={self.nuclear_level} | "
                            f"kill_switch={ks_active} | "
                            "awaiting manual resume"
                        )
                    except Exception as _exc:
                        logger.debug("Suppressed exception: %s", _exc)
        finally:
            self._monitoring_task_running = False
            logger.info("Nuclear monitoring loop exited (nuclear_level=%d)", self.nuclear_level)

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
                    "⚠️ HOPEFX HEDGE MODE ACTIVATED\nMax risk reduced to 15%. Inverse hedges opened on XAU_USD."
                )
            except Exception as exc:
                logger.error("Notification send failed: %s", exc)

        logger.warning("⚠️ HEDGE MODE ACTIVE | nuclear_level=%d", self.nuclear_level)

    # ── Manual controls ───────────────────────────────────────────────────────

    async def manual_resume(self, deactivation_token: str | None = None) -> None:
        """
        Manually resume trading and reset nuclear level.

        Deactivates the kill switch (requires token if one is configured),
        restores the risk budget, closes hedges, and exits monitoring-only mode.

        Parameters
        ----------
        deactivation_token : str, optional
            Token required by KillSwitch.deactivate().  Pass the value of
            HOPEFX_KILL_SWITCH_TOKEN.  If None, deactivation is attempted
            without a token (works when no token is configured).
        """
        self.nuclear_level = 0
        self.trading_paused = False
        self._monitoring_only = False
        self._pause_since_ts = 0.0
        self._last_trigger_ts = 0.0

        # Deactivate kill switch so the engine can place orders again
        ks = _get_kill_switch()
        if ks is not None and ks.is_active():
            try:
                ks.deactivate(token=deactivation_token)
                logger.info("KillSwitch deactivated by nuclear supervisor manual_resume")
            except PermissionError as exc:
                logger.error(
                    "KillSwitch deactivation refused (%s) — provide HOPEFX_KILL_SWITCH_TOKEN to resume trading",
                    exc,
                )
                # Don't proceed with resume if kill switch can't be cleared
                return
            except Exception as exc:
                logger.error("KillSwitch deactivation failed: %s", exc)

        ro = _get_risk_orchestrator()
        if ro is not None:
            try:
                await ro.set_max_risk(1.0)  # restore full risk budget
                await ro.deactivate_hedge_mode()
            except Exception as exc:
                logger.error("risk_orchestrator resume failed: %s", exc)

        notif = _get_notifications()
        if notif is not None:
            try:
                await notif.send_info("✅ HOPEFX nuclear mode cleared — trading resumed by operator")
            except Exception as _exc:
                logger.debug("Suppressed exception: %s", _exc)

        logger.info("NuclearSupervisor: manual resume — trading restored")

    def get_status(self) -> dict[str, Any]:
        """Return current supervisor state for monitoring."""
        ks = _get_kill_switch()
        return {
            "nuclear_level": self.nuclear_level,
            "trading_paused": self.trading_paused,
            "monitoring_only": self._monitoring_only,
            "monitoring_loop_running": self._monitoring_task_running,
            "kill_switch_active": ks.is_active() if ks else None,
            "kill_switch_reason": ks.reason if ks else None,
            "rl_agent_loaded": self.rl_agent is not None,
            "vecnorm_loaded": self._vec_normalize is not None,
            "model_path": str(self._model_path),
            "cooldown_remaining": max(
                0.0,
                self._cooldown_seconds - (time.monotonic() - self._last_trigger_ts),
            ),
            "pause_elapsed": (time.monotonic() - self._pause_since_ts if self._pause_since_ts > 0 else 0.0),
            "event_history_count": len(self._event_history),
            "last_event": self._event_history[-1] if self._event_history else None,
        }

    def get_event_history(self, n: int = 20) -> list[dict[str, Any]]:
        """Return the last n processed events."""
        return self._event_history[-n:]


# ── Module-level singleton ────────────────────────────────────────────────────

_supervisor_instance: NuclearHopeFXSupervisor | None = None


def get_nuclear_supervisor(
    model_path: str | None = None,
    wordmap_path: str | None = None,
) -> NuclearHopeFXSupervisor:
    """Return the module-level singleton, creating it on first call."""
    global _supervisor_instance
    if _supervisor_instance is None:
        _supervisor_instance = NuclearHopeFXSupervisor(
            model_path=model_path,
            wordmap_path=wordmap_path,
        )
    return _supervisor_instance
