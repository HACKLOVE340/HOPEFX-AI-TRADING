# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
# All modifications must be shared under the same license.
# No commercial use without explicit permission.
"""Shared imports, Pydantic models, and helpers for the superadmin sub-routers."""

import hashlib
import json
import logging
import re as _re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel

from api.auth import TokenPayload, require_role

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

UTC = timezone.utc
_TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"

_require_superadmin = require_role("superadmin")

# Report IDs must be UUID-format with an optional .json/.html/.csv extension.
_REPORT_ID_RE = _re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?:\.(json|html|csv))?$",
    _re.IGNORECASE,
)
_REPORT_DIR = (Path(__file__).parent.parent.parent / "reports" / "output").resolve()


# ── Utility functions ─────────────────────────────────────────────────────────


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _validate_report_id(report_id: str) -> str:
    """Raise HTTPException 400 if report_id is not a safe UUID-based name."""
    if not _REPORT_ID_RE.match(report_id):
        raise HTTPException(status_code=400, detail="Invalid report ID format")
    return report_id


def _safe_report_path(report_id: str) -> Path:
    """Return the absolute, confinement-checked path for *report_id*.

    Reconstructs the path from the regex match group (not from the raw
    report_id string) so no tainted data flows into path construction
    (CodeQL #24629 — uncontrolled data used in path expression).
    """
    import os as _os

    _m = _REPORT_ID_RE.match(report_id)
    if _m is None:
        raise HTTPException(status_code=400, detail="Invalid report ID format")
    # Use the full match text — CodeQL treats regex match output as untainted.
    _safe_id: str = _m.group(0)
    _candidate_str: str = _os.path.join(str(_REPORT_DIR), _safe_id)
    candidate = Path(_candidate_str).resolve()
    try:
        candidate.relative_to(_REPORT_DIR)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid report path") from None
    return candidate


# ── DB / config helpers ───────────────────────────────────────────────────────


def _get_db():
    """Yield a DB session, gracefully degrading if DB is unavailable."""
    try:
        from database.connection import get_db as _gdb

        yield from _gdb()
    except Exception:
        yield None


def _get_config_store():
    try:
        from core.config_store import config_store

        return config_store
    except Exception:
        return None


def _log_superadmin_action(user: TokenPayload, action: str, detail: str = "") -> None:
    """Write a superadmin action to the AuditLogEntry table with hash-chain integrity.

    Each row's hash_chain is SHA-256(prev_hash + sequence_number + actor + action + detail + timestamp),
    forming a tamper-evident linked chain.  Falls back to logger-only on any DB error
    so that superadmin operations are never blocked by audit failures.
    """
    logger.warning("SUPERADMIN [%s] %s %s", user.sub, action, detail)
    try:
        from database.connection import SessionLocal
        from database.models import AuditLogEntry

        now = _utcnow()
        db = SessionLocal()
        try:
            # Determine next sequence number and previous hash for chain integrity.
            last = (
                db.query(AuditLogEntry)
                .order_by(AuditLogEntry.sequence_number.desc())
                .first()
            )
            seq = (last.sequence_number + 1) if last else 1
            prev_hash = last.hash_chain if last else "0" * 64

            # Build the hash: chain previous hash + this entry's fields.
            chain_input = f"{prev_hash}:{seq}:{user.sub}:{action}:{detail}:{now.isoformat()}"
            new_hash = hashlib.sha256(chain_input.encode()).hexdigest()

            entry = AuditLogEntry(
                sequence_number=seq,
                timestamp=now,
                created_at=now,
                level="COMPLIANCE",
                category="SUPERADMIN",
                actor=user.sub,
                action=action,
                data_json=json.dumps({"detail": detail}) if detail else None,
                hash_chain=new_hash,
                # New columns added by migration k1l2m3n4o5p6
                event_type=f"superadmin.{action}",
                user_id=user.sub,
                detail=detail or None,
                ip_address=None,  # IP not available in this context; set by callers that have it
            )
            db.add(entry)
            db.commit()
        finally:
            db.close()
    except Exception as exc:
        # Never block a superadmin operation due to audit DB failure.
        logger.error("SUPERADMIN audit DB write failed (action still executed): %s", exc)


# ── Pydantic request/response models ─────────────────────────────────────────


class UpdateUserBody(BaseModel):
    username: str | None = None
    email: str | None = None
    status: str | None = None


class SetRoleBody(BaseModel):
    role: str


class SetPlanBody(BaseModel):
    plan: str


class BanUserBody(BaseModel):
    reason: str = "Policy violation"


class BulkUserBody(BaseModel):
    user_ids: list[str]
    reason: str | None = None


class MaintenanceBody(BaseModel):
    enabled: bool
    message: str | None = None


class BroadcastBody(BaseModel):
    title: str
    body: str
    type: str = "info"


class PlatformConfigBody(BaseModel):
    # Platform identity
    platform_name: str | None = None
    support_email: str | None = None
    max_users: int | None = None
    allow_registrations: bool | None = None
    require_email_verification: bool | None = None
    default_new_user_plan: str | None = None
    default_new_user_role: str | None = None
    session_timeout_minutes: int | None = None
    max_api_keys_per_user: int | None = None
    rate_limit_per_minute: int | None = None
    maintenance_mode: bool | None = None
    maintenance_message: str | None = None
    announcement_enabled: bool | None = None
    announcement_text: str | None = None
    announcement_type: str | None = None
    force_2fa_for_admins: bool | None = None
    ip_whitelist_enabled: bool | None = None
    ip_whitelist: str | None = None
    # SMTP
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    smtp_from_name: str | None = None
    smtp_tls: bool | None = None
    smtp_enabled: bool | None = None
    # Monitoring
    sentry_dsn: str | None = None
    sentry_environment: str | None = None
    sentry_traces_sample_rate: float | None = None
    sentry_profiles_sample_rate: float | None = None
    prometheus_port: int | None = None
    prometheus_scrape_interval_seconds: int | None = None
    prometheus_url: str | None = None
    alertmanager_smtp_host: str | None = None
    alertmanager_smtp_from: str | None = None
    alertmanager_smtp_to: str | None = None
    # Celery
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None
    celery_task_serializer: str | None = None
    celery_result_expires: int | None = None
    celery_worker_concurrency: int | None = None
    celery_max_tasks_per_child: int | None = None
    # Compliance
    kyc_required_for_live: bool | None = None
    aml_transaction_threshold: float | None = None
    aml_daily_volume_threshold: float | None = None
    sanctions_check_enabled: bool | None = None
    gdpr_data_retention_days: int | None = None
    gdpr_erasure_grace_days: int | None = None
    regulatory_reporting_enabled: bool | None = None
    # LSTM
    lstm_enabled: bool | None = None
    lstm_sequence_length: int | None = None
    lstm_hidden_size: int | None = None
    lstm_num_layers: int | None = None
    lstm_dropout: float | None = None
    lstm_learning_rate: float | None = None
    lstm_batch_size: int | None = None
    lstm_epochs: int | None = None
    lstm_retrain_interval_hours: int | None = None
    lstm_min_train_samples: int | None = None
    lstm_use_attention: bool | None = None
    lstm_bidirectional: bool | None = None
    lstm_clip_grad_norm: float | None = None
    lstm_weight_decay: float | None = None
    lstm_scheduler: str | None = None
    # AI Brain
    brain_enabled: bool | None = None
    brain_model: str | None = None
    brain_temperature: float | None = None
    brain_max_tokens: int | None = None
    brain_strategy_timeout_s: int | None = None
    brain_max_strategies_per_day: int | None = None
    brain_auto_deploy: bool | None = None
    brain_min_backtest_sharpe: float | None = None
    brain_min_backtest_winrate: float | None = None
    brain_sandbox_enabled: bool | None = None
    # Allocator
    allocator_enabled: bool | None = None
    allocator_method: str | None = None
    allocator_rebalance_interval_hours: int | None = None
    allocator_min_weight: float | None = None
    allocator_max_weight: float | None = None
    allocator_risk_budget: float | None = None
    allocator_lookback_days: int | None = None
    allocator_transaction_cost_bps: float | None = None
    allocator_target_volatility: float | None = None
    allocator_use_black_litterman: bool | None = None
    allocator_use_hrp: bool | None = None
    # Anomaly detection
    anomaly_enabled: bool | None = None
    anomaly_model: str | None = None
    anomaly_contamination: float | None = None
    anomaly_window: int | None = None
    anomaly_threshold: float | None = None
    anomaly_action: str | None = None
    anomaly_retrain_interval_hours: int | None = None
    anomaly_min_samples: int | None = None
    anomaly_alert_cooldown_s: int | None = None
    # Macro overlay
    macro_enabled: bool | None = None
    macro_fred_api_key: str | None = None
    macro_refresh_interval_hours: int | None = None
    macro_lookback_days: int | None = None
    macro_weight_in_signal: float | None = None
    macro_vix_threshold: float | None = None
    macro_dxy_threshold: float | None = None
    macro_yield_spread_threshold: float | None = None
    macro_wgc_enabled: bool | None = None
    macro_wgc_refresh_hours: int | None = None
    # Online learner
    online_learner_enabled: bool | None = None
    online_learner_lr: float | None = None
    online_learner_batch_size: int | None = None
    online_learner_update_interval_s: int | None = None
    online_learner_max_buffer: int | None = None
    online_learner_algorithm: str | None = None
    online_learner_forgetting_factor: float | None = None
    online_learner_min_samples_before_update: int | None = None
    online_learner_feature_drift_check: bool | None = None
    # Sharpe circuit breaker
    sharpe_cb_window_trades: int | None = None
    sharpe_cb_min_sharpe: float | None = None
    sharpe_cb_consecutive: int | None = None
    sharpe_cb_eval_interval_s: int | None = None
    sharpe_cb_min_trades: int | None = None
    sharpe_cb_reset_after_s: int | None = None
    # Regime detection
    regime_enabled: bool | None = None
    regime_model: str | None = None
    regime_lookback_bars: int | None = None
    regime_n_states: int | None = None
    regime_retrain_interval_hours: int | None = None
    regime_confidence_threshold: float | None = None
    regime_use_hmm: bool | None = None
    regime_use_kmeans: bool | None = None
    regime_feature_set: str | None = None
    regime_transition_smoothing: float | None = None
    # Signal engine
    signal_engine_enabled: bool | None = None
    signal_engine_mode: str | None = None
    signal_engine_ensemble_method: str | None = None
    signal_engine_min_model_agreement: float | None = None
    signal_engine_use_lstm: bool | None = None
    signal_engine_use_xgb: bool | None = None
    signal_engine_use_rf: bool | None = None
    signal_engine_use_lgbm: bool | None = None
    signal_engine_use_regime: bool | None = None
    signal_engine_use_macro: bool | None = None
    signal_engine_use_sentiment: bool | None = None
    signal_engine_cooldown_s: int | None = None
    signal_engine_max_signals_per_hour: int | None = None
    # TCA
    tca_enabled: bool | None = None
    tca_alert_threshold_bps: float | None = None
    tca_alert_window: int | None = None
    tca_persist_redis: bool | None = None
    tca_persist_db: bool | None = None
    tca_max_memory_records: int | None = None
    tca_benchmark: str | None = None
    tca_slippage_model: str | None = None
    tca_impact_model: str | None = None
    tca_report_interval_hours: int | None = None
    tca_min_records_for_report: int | None = None
    # Backtest engine
    backtest_engine: str | None = None
    backtest_default_initial_capital: float | None = None
    backtest_default_commission_pct: float | None = None
    backtest_default_slippage_pct: float | None = None
    backtest_default_spread_pct: float | None = None
    backtest_max_duration_s: int | None = None
    backtest_max_concurrent: int | None = None
    backtest_data_source: str | None = None
    backtest_use_tick_data: bool | None = None
    backtest_walk_forward_folds: int | None = None
    backtest_oos_ratio: float | None = None
    backtest_min_trades_for_validity: int | None = None
    backtest_min_sharpe_for_deploy: float | None = None
    # Feature flags
    feature_nuclear_enabled: bool | None = None
    feature_copy_trading_enabled: bool | None = None
    feature_social_feed_enabled: bool | None = None
    feature_marketplace_enabled: bool | None = None
    feature_affiliate_enabled: bool | None = None
    feature_whitelabel_enabled: bool | None = None
    feature_ai_strategy_enabled: bool | None = None
    feature_walk_forward_enabled: bool | None = None
    feature_ab_testing_enabled: bool | None = None
    feature_tca_enabled: bool | None = None
    feature_replay_enabled: bool | None = None
    feature_research_enabled: bool | None = None
    feature_geopolitical_enabled: bool | None = None
    feature_prop_firm_enabled: bool | None = None
    feature_teams_enabled: bool | None = None
    feature_leaderboard_enabled: bool | None = None
    feature_crypto_checkout_enabled: bool | None = None
    feature_2fa_enabled: bool | None = None
    feature_kyc_enabled: bool | None = None
    feature_sub_accounts_enabled: bool | None = None
    # LLM / AI provider
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_temperature: float | None = None
    llm_max_tokens: int | None = None
    llm_timeout_s: int | None = None
    llm_max_retries: int | None = None
    llm_fallback_provider: str | None = None
    llm_fallback_model: str | None = None
    llm_embedding_model: str | None = None
    llm_embedding_dimensions: int | None = None
    # Drawdown controls
    drawdown_hard_stop_pct: float | None = None
    drawdown_soft_warn_pct: float | None = None
    drawdown_trailing_enabled: bool | None = None
    drawdown_trailing_lookback_bars: int | None = None
    drawdown_recovery_mode: str | None = None
    drawdown_recovery_size_scale: float | None = None
    drawdown_daily_reset: bool | None = None
    drawdown_notify_on_breach: bool | None = None
    drawdown_auto_reduce_on_warn: bool | None = None
    drawdown_reduce_factor: float | None = None
    # Prop firm mode
    prop_firm_enabled: bool | None = None
    prop_firm_provider: str | None = None
    prop_firm_account_size: float | None = None
    prop_firm_daily_loss_limit_pct: float | None = None
    prop_firm_max_drawdown_pct: float | None = None
    prop_firm_profit_target_pct: float | None = None
    prop_firm_min_trading_days: int | None = None
    prop_firm_max_position_size_pct: float | None = None
    prop_firm_news_trading_allowed: bool | None = None
    prop_firm_weekend_holding_allowed: bool | None = None
    prop_firm_consistency_rule_pct: float | None = None
    prop_firm_scaling_enabled: bool | None = None
    # Position sizing
    position_sizing_method: str | None = None
    position_sizing_fixed_lots: float | None = None
    position_sizing_risk_pct: float | None = None
    position_sizing_kelly_fraction: float | None = None
    position_sizing_max_lots: float | None = None
    position_sizing_min_lots: float | None = None
    position_sizing_atr_multiplier: float | None = None
    position_sizing_atr_period: int | None = None
    position_sizing_volatility_target: float | None = None
    position_sizing_use_correlation_scaling: bool | None = None
    position_sizing_max_correlated_exposure: float | None = None
    # ── Original platform fields ──────────────────────────────────────────────
    ac_eta: float | None = None
    ac_gamma: float | None = None
    ac_max_participation: float | None = None
    ac_min_spread_bps: float | None = None
    ac_queue_factor: float | None = None
    access_token_expire_minutes: float | None = None
    algo_default_iceberg_peak: float | None = None
    algo_default_twap_duration: float | None = None
    algo_default_twap_slices: float | None = None
    algo_iceberg_refill_pct: float | None = None
    algo_iceberg_threshold: float | None = None
    algo_large_order_threshold: float | None = None
    algo_max_participation: float | None = None
    algo_min_child_size: float | None = None
    algo_twap_jitter: float | None = None
    algo_vwap_profile: str | None = None
    blackout_gate_enabled: bool | None = None
    broker_cb_half_open_max: float | None = None
    broker_cb_max_failures: float | None = None
    broker_cb_reset_timeout: float | None = None
    broker_default: str | None = None
    cb_min_accuracy: float | None = None
    cb_min_outcomes: float | None = None
    circuit_breaker_enabled: bool | None = None
    cme_default_contracts: float | None = None
    cme_enabled: bool | None = None
    cme_fix_host: str | None = None
    cme_fix_port: float | None = None
    cme_fix_sender_id: str | None = None
    cme_fix_target_id: str | None = None
    cme_ibkr_fallback: bool | None = None
    cme_latency_warn_ms: float | None = None
    cme_paper_fallback: bool | None = None
    cpp_shim_enabled: bool | None = None
    cpp_shim_latency_warn_us: float | None = None
    cpp_shim_timeout_ms: float | None = None
    cpp_shim_zmq_cmd_addr: str | None = None
    cpp_shim_zmq_resp_addr: str | None = None
    db_echo: bool | None = None
    db_max_overflow: float | None = None
    db_pool_size: float | None = None
    debug: bool | None = None
    decision_engine_cooldown_s: float | None = None
    decision_engine_enabled: bool | None = None
    decision_engine_max_positions: float | None = None
    decision_engine_min_confidence: float | None = None
    decision_engine_use_macro: bool | None = None
    decision_engine_use_regime: bool | None = None
    decision_engine_use_sentiment: bool | None = None
    discord_bot_username: str | None = None
    discord_signal_cooldown_seconds: float | None = None
    drift_monitor_auto_retrain: bool | None = None
    drift_monitor_check_interval_s: float | None = None
    drift_monitor_enabled: bool | None = None
    drift_monitor_threshold: float | None = None
    drift_monitor_window: float | None = None
    engine_initial_equity: float | None = None
    engine_max_position_usd: float | None = None
    engine_max_spread_usd: float | None = None
    engine_min_confidence: float | None = None
    engine_min_data_quality: float | None = None
    engine_signal_cooldown_s: float | None = None
    engine_stale_tick_s: float | None = None
    engine_tick_loop_hz: float | None = None
    env: str | None = None
    ev_min_threshold: float | None = None
    ev_window: float | None = None
    fia_daily_loss_limit: float | None = None
    fia_max_intraday_position: float | None = None
    fia_max_msg_per_sec: float | None = None
    fia_max_order_size: float | None = None
    fia_price_tolerance: float | None = None
    fix_default_units: float | None = None
    fix_host: str | None = None
    fix_latency_warn_ms: float | None = None
    fix_port: float | None = None
    fix_sender_comp_id: str | None = None
    fix_target_comp_id: str | None = None
    gatekeeper_impact_blackout: float | None = None
    gatekeeper_max_daily_trades: float | None = None
    gatekeeper_max_spread_usd: float | None = None
    gatekeeper_min_conf: float | None = None
    gatekeeper_min_data_quality: float | None = None
    gatekeeper_pause_s: float | None = None
    gatekeeper_sent_blackout: float | None = None
    heartbeat_enabled: bool | None = None
    heartbeat_interval_hours: float | None = None
    hopefx_kill_switch: bool | None = None
    ibkr_client_id: float | None = None
    ibkr_connect_timeout_s: float | None = None
    ibkr_host: str | None = None
    ibkr_max_reconnects: float | None = None
    ibkr_order_timeout_s: float | None = None
    ibkr_port_live: float | None = None
    ibkr_port_paper: float | None = None
    ibkr_reconnect_delay_s: float | None = None
    initial_balance: float | None = None
    intra_cvar_confidence: float | None = None
    intra_min_data_quality: float | None = None
    intra_returns_window: float | None = None
    intra_vol_baseline_window: float | None = None
    jwt_algorithm: str | None = None
    k8s_ks_configmap_name: str | None = None
    k8s_ks_namespace: str | None = None
    k8s_ks_poll_interval_s: float | None = None
    log_level: str | None = None
    max_risk_pct_per_trade: float | None = None
    min_confidence_abs: float | None = None
    min_slice_lots: float | None = None
    ml_drift_threshold: float | None = None
    ml_full_retrain_hours: float | None = None
    ml_hourly_enabled: bool | None = None
    ml_hourly_interval_seconds: float | None = None
    ml_model_dir: str | None = None
    ml_monitor_check_interval: float | None = None
    ml_monitor_min_trades: float | None = None
    ml_monitor_rollback_thresh: float | None = None
    ml_monitor_window_trades: float | None = None
    ml_online_learning_rate: float | None = None
    ml_retrain_interval_minutes: float | None = None
    ml_symbols: str | None = None
    mtf_confluence_required: bool | None = None
    news_blackout_minutes: float | None = None
    oanda_environment: str | None = None
    oanda_max_retries: float | None = None
    oanda_retry_backoff_s: float | None = None
    oanda_timeout_s: float | None = None
    ohlcv_store_max_bars: float | None = None
    ohlcv_store_timeframe: str | None = None
    paper_fallback_spread_pct: float | None = None
    paper_fixed_slippage_pct: float | None = None
    paper_impact_factor: float | None = None
    paper_noise_sigma_pct: float | None = None
    paper_slippage_model: str | None = None
    partial_fill_timeout: float | None = None
    rate_admin: str | None = None
    rate_auth: str | None = None
    rate_backtest: str | None = None
    rate_global_default: str | None = None
    rate_market_data: str | None = None
    rate_trading: str | None = None
    rate_websocket: str | None = None
    rate_withdrawal: str | None = None
    redis_health_check_interval: float | None = None
    redis_max_connections: float | None = None
    redis_socket_timeout: float | None = None
    refresh_token_expire_days: float | None = None
    regime_filter_enabled: bool | None = None
    registry_max_oos_pval: float | None = None
    registry_min_oos_acc: float | None = None
    registry_require_sharpe_gate: bool | None = None
    risk_account_equity: float | None = None
    risk_alert_pct_of_limit: float | None = None
    risk_cvar_daily_limit: float | None = None
    risk_dd_size_scale: float | None = None
    risk_drawdown_mode: str | None = None
    risk_factor_var_limit: float | None = None
    risk_impact_size_scale: float | None = None
    risk_kelly_fraction: float | None = None
    risk_max_daily_loss_pct: float | None = None
    risk_max_drawdown_pct: float | None = None
    risk_max_open_positions: float | None = None
    risk_max_position_pct: float | None = None
    risk_min_data_quality: float | None = None
    risk_min_position_pct: float | None = None
    risk_sent_size_scale: float | None = None
    risk_var_confidence: float | None = None
    risk_var_window: float | None = None
    router_max_spread_bps: float | None = None
    router_primary_broker: str | None = None
    router_secondary_broker: str | None = None
    security_rate_limit_requests: float | None = None
    security_rate_limit_window: float | None = None
    signal_abstain_high: float | None = None
    signal_abstain_low: float | None = None
    signal_high_conf: float | None = None
    signal_threshold_long: float | None = None
    signal_threshold_short: float | None = None
    sltp_max_retries: float | None = None
    sltp_poll_interval_ms: float | None = None
    sltp_retry_delay_s: float | None = None
    spread_abs_limit_usd: float | None = None
    spread_baseline_window: float | None = None
    spread_min_ticks: float | None = None
    spread_spike_multiplier: float | None = None
    trading_mode: str | None = None
    twap_default_secs: float | None = None
    twap_default_slices: float | None = None
    vwap_slices: float | None = None


class EngineConfigBody(BaseModel):
    paper_trading_mode: bool | None = None
    live_trading_enabled: bool | None = None
    max_open_positions: int | None = None
    max_risk_per_trade: float | None = None
    max_daily_loss_pct: float | None = None
    max_drawdown_pct: float | None = None
    default_lot_size: float | None = None
    slippage_tolerance: float | None = None
    default_leverage: int | None = None
    auto_trade_enabled: bool | None = None
    signal_confidence_threshold: float | None = None
    broker_type: str | None = None
    execution_mode: str | None = None


class KillSwitchBody(BaseModel):
    enabled: bool


class PauseBody(BaseModel):
    reason: str = "Superadmin manual pause"


class BlockIPBody(BaseModel):
    ip: str
    reason: str = "Manual block"


class SetLogLevelBody(BaseModel):
    logger: str
    level: str


class SetFeatureFlagBody(BaseModel):
    enabled: bool
    user_ids: list[str] | None = None


class SetUserFlagOverrideBody(BaseModel):
    enabled: bool


class RefundBody(BaseModel):
    reason: str = "Superadmin refund"


class MLControlBody(BaseModel):
    action: str  # start | pause | stop | reset


class DeployModelBody(BaseModel):
    model: str
    version: str


# ── Additional Pydantic models (institutional-grade extensions) ───────────────


class KYCDecisionBody(BaseModel):
    reason: str = ""


class AMLAlertUpdateBody(BaseModel):
    status: str
    notes: str = ""


class SanctionsClearBody(BaseModel):
    notes: str = ""


class RegReportTriggerBody(BaseModel):
    report_type: str
    period: str


class CircuitBreakerActionBody(BaseModel):
    reason: str = "Superadmin manual action"


class StressTestRunBody(BaseModel):
    scenario: str


class BrokerActionBody(BaseModel):
    reason: str = ""


class BrokerRoutingBody(BaseModel):
    primary_broker: str | None = None
    fallback_broker: str | None = None
    routing_mode: str | None = None


class TenantCreateBody(BaseModel):
    name: str
    domain: str
    plan: str = "starter"
    company_name: str = ""
    primary_color: str = "#3b82f6"


class TenantUpdateBody(BaseModel):
    status: str | None = None
    plan: str | None = None
    primary_color: str | None = None
    logo_url: str | None = None
    company_name: str | None = None


class GDPRProcessBody(BaseModel):
    action: str  # approve | reject
    notes: str = ""


class GDPREraseBody(BaseModel):
    user_id: str
    user_email: str = ""
    # request_type: access | erasure | portability | rectification | restriction | objection
    request_type: str = "erasure"
    reason: str = ""


class RetentionPolicyBody(BaseModel):
    data_type: str
    retention_days: int


class NuclearHaltBody(BaseModel):
    reason: str


class NuclearHedgeBody(BaseModel):
    hedge_ratio: float = 1.0
    instrument: str = "XAUUSD"
    reason: str = ""


class NuclearRiskOverrideBody(BaseModel):
    max_risk_fraction: float
    reason: str = ""


class RateLimitRuleBody(BaseModel):
    endpoint: str
    limit: int
    window_seconds: int
    scope: str = "per_user"
    enabled: bool = True


class RateLimitRuleUpdateBody(BaseModel):
    limit: int | None = None
    window_seconds: int | None = None
    enabled: bool | None = None


class AlertRuleBody(BaseModel):
    name: str
    condition: str
    severity: str = "warning"
    channels: list[str] = []
    enabled: bool = True


class AlertRuleUpdateBody(BaseModel):
    name: str | None = None
    condition: str | None = None
    severity: str | None = None
    enabled: bool | None = None
    channels: list[str] | None = None


class SilenceAlertBody(BaseModel):
    duration_minutes: int = 60


class ReportGenerateBody(BaseModel):
    type: str
    period: str


class BackupTriggerBody(BaseModel):
    type: str = "incremental"


class ApiKeyRevokeBody(BaseModel):
    reason: str = "Superadmin revocation"
