# HOPEFX-AI-TRADING
# Copyright (c) 2025-2026
# Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
"""SuperAdmin platform config and trading engine sub-router."""

import logging
import sys
import time

from fastapi import APIRouter, Depends, Request

from api.auth import TokenPayload

from ._shared import (
    BroadcastBody,
    EngineConfigBody,
    KillSwitchBody,
    MaintenanceBody,
    PauseBody,
    PlatformConfigBody,
    _get_config_store as _shared_get_config_store,
    _log_superadmin_action,
    _require_superadmin,
    _utcnow,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_config_store():
    """Return config store, honouring any test-level patch on api.superadmin._get_config_store."""
    parent = sys.modules.get("api.superadmin")
    if parent is not None:
        fn = getattr(parent, "_get_config_store", None)
        if fn is not None and fn is not _get_config_store:
            return fn()
    return _shared_get_config_store()


# ── Platform config ───────────────────────────────────────────────────────────

_PLATFORM_CONFIG_KEY = "superadmin_platform_config"

_PLATFORM_CONFIG_DEFAULTS: dict = {
    "platform_name": "HOPEFX AI Trading",
    "support_email": "support@hopefx.ai",
    "max_users": 10000,
    "allow_registrations": True,
    "require_email_verification": True,
    "default_new_user_plan": "free",
    "default_new_user_role": "trader",
    "session_timeout_minutes": 60,
    "max_api_keys_per_user": 5,
    "rate_limit_per_minute": 60,
    "maintenance_mode": False,
    "maintenance_message": "We're performing scheduled maintenance. Back shortly.",
    "announcement_enabled": False,
    "announcement_text": "",
    "announcement_type": "info",
    "force_2fa_for_admins": False,
    "ip_whitelist_enabled": False,
    "ip_whitelist": "",
    # SMTP / Email
    "smtp_host": "",
    "smtp_port": 587,
    "smtp_user": "",
    "smtp_password": "",
    "smtp_from": "noreply@hopefx.ai",
    "smtp_from_name": "HOPEFX Trading",
    "smtp_tls": True,
    "smtp_enabled": False,
    # Monitoring / Observability
    "sentry_dsn": "",
    "sentry_environment": "production",
    "sentry_traces_sample_rate": 0.1,
    "sentry_profiles_sample_rate": 0.1,
    "prometheus_port": 9090,
    "prometheus_scrape_interval_seconds": 15,
    "prometheus_url": "http://prometheus:9090",
    "alertmanager_smtp_host": "localhost:587",
    "alertmanager_smtp_from": "alerts@hopefx.ai",
    "alertmanager_smtp_to": "",
    # Celery / Task Queue
    "celery_broker_url": "redis://redis:6379/1",
    "celery_result_backend": "redis://redis:6379/2",
    "celery_task_serializer": "json",
    "celery_result_expires": 3600,
    "celery_worker_concurrency": 4,
    "celery_max_tasks_per_child": 1000,
    # Compliance thresholds
    "kyc_required_for_live": True,
    "aml_transaction_threshold": 10000,
    "aml_daily_volume_threshold": 50000,
    "sanctions_check_enabled": True,
    "gdpr_data_retention_days": 365,
    "gdpr_erasure_grace_days": 30,
    "regulatory_reporting_enabled": False,
    # ── LSTM model ────────────────────────────────────────────────────────────
    "lstm_enabled": False,
    "lstm_sequence_length": 60,
    "lstm_hidden_size": 128,
    "lstm_num_layers": 2,
    "lstm_dropout": 0.2,
    "lstm_learning_rate": 0.001,
    "lstm_batch_size": 64,
    "lstm_epochs": 50,
    "lstm_retrain_interval_hours": 24,
    "lstm_min_train_samples": 500,
    "lstm_use_attention": True,
    "lstm_bidirectional": False,
    "lstm_clip_grad_norm": 1.0,
    "lstm_weight_decay": 1e-5,
    "lstm_scheduler": "cosine",
    # ── AI Brain / strategy generator ─────────────────────────────────────────
    "brain_enabled": False,
    "brain_model": "gpt-4o",
    "brain_temperature": 0.3,
    "brain_max_tokens": 4096,
    "brain_strategy_timeout_s": 120,
    "brain_max_strategies_per_day": 10,
    "brain_auto_deploy": False,
    "brain_min_backtest_sharpe": 1.0,
    "brain_min_backtest_winrate": 0.52,
    "brain_sandbox_enabled": True,
    # ── Portfolio allocator ───────────────────────────────────────────────────
    "allocator_enabled": False,
    "allocator_method": "equal_weight",
    "allocator_rebalance_interval_hours": 24,
    "allocator_min_weight": 0.05,
    "allocator_max_weight": 0.40,
    "allocator_risk_budget": 0.02,
    "allocator_lookback_days": 252,
    "allocator_transaction_cost_bps": 2.0,
    "allocator_target_volatility": 0.10,
    "allocator_use_black_litterman": False,
    "allocator_use_hrp": False,
    # ── Anomaly detection ─────────────────────────────────────────────────────
    "anomaly_enabled": False,
    "anomaly_model": "isolation_forest",
    "anomaly_contamination": 0.05,
    "anomaly_window": 100,
    "anomaly_threshold": 0.80,
    "anomaly_action": "alert",
    "anomaly_retrain_interval_hours": 24,
    "anomaly_min_samples": 200,
    "anomaly_alert_cooldown_s": 300,
    # ── Macro overlay ─────────────────────────────────────────────────────────
    "macro_enabled": True,
    "macro_fred_api_key": "",
    "macro_refresh_interval_hours": 6,
    "macro_lookback_days": 252,
    "macro_weight_in_signal": 0.15,
    "macro_vix_threshold": 30.0,
    "macro_dxy_threshold": 105.0,
    "macro_yield_spread_threshold": 0.5,
    "macro_wgc_enabled": True,
    "macro_wgc_refresh_hours": 24,
    # ── Online learner ────────────────────────────────────────────────────────
    "online_learner_enabled": False,
    "online_learner_lr": 0.001,
    "online_learner_batch_size": 32,
    "online_learner_update_interval_s": 300,
    "online_learner_max_buffer": 10000,
    "online_learner_algorithm": "sgd",
    "online_learner_forgetting_factor": 0.99,
    "online_learner_min_samples_before_update": 50,
    "online_learner_feature_drift_check": True,
    # ── Sharpe circuit breaker ────────────────────────────────────────────────
    "sharpe_cb_window_trades": 50,
    "sharpe_cb_min_sharpe": 0.0,
    "sharpe_cb_consecutive": 3,
    "sharpe_cb_eval_interval_s": 60,
    "sharpe_cb_min_trades": 20,
    "sharpe_cb_reset_after_s": 3600,
    # ── Regime detection ──────────────────────────────────────────────────────
    "regime_enabled": True,
    "regime_model": "hmm",
    "regime_lookback_bars": 200,
    "regime_n_states": 3,
    "regime_retrain_interval_hours": 24,
    "regime_confidence_threshold": 0.60,
    "regime_use_hmm": True,
    "regime_use_kmeans": False,
    "regime_feature_set": "default",
    "regime_transition_smoothing": 0.3,
    # ── Signal engine ─────────────────────────────────────────────────────────
    "signal_engine_enabled": True,
    "signal_engine_mode": "ensemble",
    "signal_engine_ensemble_method": "weighted_vote",
    "signal_engine_min_model_agreement": 0.60,
    "signal_engine_use_lstm": False,
    "signal_engine_use_xgb": True,
    "signal_engine_use_rf": True,
    "signal_engine_use_lgbm": True,
    "signal_engine_use_regime": True,
    "signal_engine_use_macro": True,
    "signal_engine_use_sentiment": True,
    "signal_engine_cooldown_s": 30,
    "signal_engine_max_signals_per_hour": 12,
    # ── TCA (Transaction Cost Analysis) ──────────────────────────────────────
    "tca_enabled": True,
    "tca_alert_threshold_bps": 5.0,
    "tca_alert_window": 100,
    "tca_persist_redis": True,
    "tca_persist_db": True,
    "tca_max_memory_records": 10000,
    "tca_benchmark": "arrival_price",
    "tca_slippage_model": "linear",
    "tca_impact_model": "square_root",
    "tca_report_interval_hours": 24,
    "tca_min_records_for_report": 10,
    # ── Backtest engine ───────────────────────────────────────────────────────
    "backtest_engine": "vectorbt",
    "backtest_default_initial_capital": 100000,
    "backtest_default_commission_pct": 0.0002,
    "backtest_default_slippage_pct": 0.0001,
    "backtest_default_spread_pct": 0.0002,
    "backtest_max_duration_s": 300,
    "backtest_max_concurrent": 4,
    "backtest_data_source": "ohlcv_store",
    "backtest_use_tick_data": False,
    "backtest_walk_forward_folds": 5,
    "backtest_oos_ratio": 0.20,
    "backtest_min_trades_for_validity": 30,
    "backtest_min_sharpe_for_deploy": 0.80,
    # ── Feature flags ─────────────────────────────────────────────────────────
    "feature_nuclear_enabled": True,
    "feature_copy_trading_enabled": True,
    "feature_social_feed_enabled": True,
    "feature_marketplace_enabled": True,
    "feature_affiliate_enabled": True,
    "feature_whitelabel_enabled": False,
    "feature_ai_strategy_enabled": True,
    "feature_walk_forward_enabled": True,
    "feature_ab_testing_enabled": True,
    "feature_tca_enabled": True,
    "feature_replay_enabled": True,
    "feature_research_enabled": True,
    "feature_geopolitical_enabled": True,
    "feature_prop_firm_enabled": True,
    "feature_teams_enabled": True,
    "feature_leaderboard_enabled": True,
    "feature_crypto_checkout_enabled": True,
    "feature_2fa_enabled": True,
    "feature_kyc_enabled": True,
    "feature_sub_accounts_enabled": True,
    # ── LLM / AI provider ────────────────────────────────────────────────────
    "llm_provider": "openai",
    "llm_model": "gpt-4o",
    "llm_api_key": "",
    "llm_base_url": "",
    "llm_temperature": 0.3,
    "llm_max_tokens": 4096,
    "llm_timeout_s": 60,
    "llm_max_retries": 3,
    "llm_fallback_provider": "anthropic",
    "llm_fallback_model": "claude-3-5-sonnet-20241022",
    "llm_embedding_model": "text-embedding-3-small",
    "llm_embedding_dimensions": 1536,
    # ── Drawdown controls ─────────────────────────────────────────────────────
    "drawdown_hard_stop_pct": 0.10,
    "drawdown_soft_warn_pct": 0.07,
    "drawdown_trailing_enabled": True,
    "drawdown_trailing_lookback_bars": 100,
    "drawdown_recovery_mode": "reduce_size",
    "drawdown_recovery_size_scale": 0.50,
    "drawdown_daily_reset": True,
    "drawdown_notify_on_breach": True,
    "drawdown_auto_reduce_on_warn": True,
    "drawdown_reduce_factor": 0.75,
    # ── Prop firm mode ────────────────────────────────────────────────────────
    "prop_firm_enabled": False,
    "prop_firm_provider": "ftmo",
    "prop_firm_account_size": 100000,
    "prop_firm_daily_loss_limit_pct": 0.05,
    "prop_firm_max_drawdown_pct": 0.10,
    "prop_firm_profit_target_pct": 0.10,
    "prop_firm_min_trading_days": 10,
    "prop_firm_max_position_size_pct": 0.05,
    "prop_firm_news_trading_allowed": False,
    "prop_firm_weekend_holding_allowed": False,
    "prop_firm_consistency_rule_pct": 0.50,
    "prop_firm_scaling_enabled": False,
    # ── Position sizing ───────────────────────────────────────────────────────
    "position_sizing_method": "risk_pct",
    "position_sizing_fixed_lots": 0.01,
    "position_sizing_risk_pct": 0.01,
    "position_sizing_kelly_fraction": 0.25,
    "position_sizing_max_lots": 10.0,
    "position_sizing_min_lots": 0.001,
    "position_sizing_atr_multiplier": 1.5,
    "position_sizing_atr_period": 14,
    "position_sizing_volatility_target": 0.01,
    "position_sizing_use_correlation_scaling": False,
    "position_sizing_max_correlated_exposure": 0.10,
    # ── Original platform fields (risk, execution, broker, ML, etc.) ──────────
    "ac_eta": 0.3,
    "ac_gamma": 0.1,
    "ac_max_participation": 0.10,
    "ac_min_spread_bps": 1.0,
    "ac_queue_factor": 0.5,
    "access_token_expire_minutes": 30,
    "algo_default_iceberg_peak": 5,
    "algo_default_twap_duration": 300,
    "algo_default_twap_slices": 10,
    "algo_iceberg_refill_pct": 0.1,
    "algo_iceberg_threshold": 50,
    "algo_large_order_threshold": 10,
    "algo_max_participation": 0.05,
    "algo_min_child_size": 0.01,
    "algo_twap_jitter": 0.1,
    "algo_vwap_profile": "u_shaped",
    "blackout_gate_enabled": True,
    "broker_cb_half_open_max": 2,
    "broker_cb_max_failures": 5,
    "broker_cb_reset_timeout": 60,
    "broker_default": "paper",
    "cb_min_accuracy": 0.45,
    "cb_min_outcomes": 30,
    "circuit_breaker_enabled": True,
    "cme_default_contracts": 1,
    "cme_enabled": False,
    "cme_fix_host": "127.0.0.1",
    "cme_fix_port": 9876,
    "cme_fix_sender_id": "HOPEFX",
    "cme_fix_target_id": "CME",
    "cme_ibkr_fallback": True,
    "cme_latency_warn_ms": 50,
    "cme_paper_fallback": True,
    "cpp_shim_enabled": True,
    "cpp_shim_latency_warn_us": 1000,
    "cpp_shim_timeout_ms": 5000,
    "cpp_shim_zmq_cmd_addr": "tcp://127.0.0.1:6555",
    "cpp_shim_zmq_resp_addr": "tcp://127.0.0.1:6556",
    "db_echo": False,
    "db_max_overflow": 10,
    "db_pool_size": 20,
    "debug": False,
    "decision_engine_cooldown_s": 30,
    "decision_engine_enabled": True,
    "decision_engine_max_positions": 3,
    "decision_engine_min_confidence": 0.55,
    "decision_engine_use_macro": True,
    "decision_engine_use_regime": True,
    "decision_engine_use_sentiment": True,
    "discord_bot_username": "HOPEFX Signals",
    "discord_signal_cooldown_seconds": 300,
    "drift_monitor_auto_retrain": False,
    "drift_monitor_check_interval_s": 300,
    "drift_monitor_enabled": True,
    "drift_monitor_threshold": 0.05,
    "drift_monitor_window": 200,
    "engine_initial_equity": 100000,
    "engine_max_position_usd": 100000,
    "engine_max_spread_usd": 2.00,
    "engine_min_confidence": 0.55,
    "engine_min_data_quality": 0.40,
    "engine_signal_cooldown_s": 30.0,
    "engine_stale_tick_s": 10.0,
    "engine_tick_loop_hz": 1.0,
    "env": "production",
    "ev_min_threshold": 0.0,
    "ev_window": 50,
    "fia_daily_loss_limit": 0.03,
    "fia_max_intraday_position": 500,
    "fia_max_msg_per_sec": 50,
    "fia_max_order_size": 100,
    "fia_price_tolerance": 0.02,
    "fix_default_units": 1000,
    "fix_host": "127.0.0.1",
    "fix_latency_warn_ms": 50,
    "fix_port": 9876,
    "fix_sender_comp_id": "HOPEFX",
    "fix_target_comp_id": "BROKER",
    "gatekeeper_impact_blackout": 0.75,
    "gatekeeper_max_daily_trades": 20,
    "gatekeeper_max_spread_usd": 2.00,
    "gatekeeper_min_conf": 0.55,
    "gatekeeper_min_data_quality": 0.40,
    "gatekeeper_pause_s": 60,
    "gatekeeper_sent_blackout": 0.85,
    "heartbeat_enabled": True,
    "heartbeat_interval_hours": 1,
    "hopefx_kill_switch": False,
    "ibkr_client_id": 1,
    "ibkr_connect_timeout_s": 30,
    "ibkr_host": "127.0.0.1",
    "ibkr_max_reconnects": 10,
    "ibkr_order_timeout_s": 30,
    "ibkr_port_live": 7496,
    "ibkr_port_paper": 7497,
    "ibkr_reconnect_delay_s": 5,
    "initial_balance": 100000,
    "intra_cvar_confidence": 0.95,
    "intra_min_data_quality": 0.40,
    "intra_returns_window": 200,
    "intra_vol_baseline_window": 100,
    "jwt_algorithm": "HS256",
    "k8s_ks_configmap_name": "hopefx-kill-switch",
    "k8s_ks_namespace": "hopefx",
    "k8s_ks_poll_interval_s": 5,
    "log_level": "INFO",
    "max_risk_pct_per_trade": 0.01,
    "min_confidence_abs": 0.55,
    "min_slice_lots": 0.001,
    "ml_drift_threshold": 0.05,
    "ml_full_retrain_hours": 24,
    "ml_hourly_enabled": False,
    "ml_hourly_interval_seconds": 3600,
    "ml_model_dir": "ml/models",
    "ml_monitor_check_interval": 300,
    "ml_monitor_min_trades": 20,
    "ml_monitor_rollback_thresh": 0.20,
    "ml_monitor_window_trades": 100,
    "ml_online_learning_rate": 0.01,
    "ml_retrain_interval_minutes": 60,
    "ml_symbols": "XAU_USD",
    "mtf_confluence_required": False,
    "news_blackout_minutes": 30,
    "oanda_environment": "practice",
    "oanda_max_retries": 3,
    "oanda_retry_backoff_s": 0.5,
    "oanda_timeout_s": 10,
    "ohlcv_store_max_bars": 500,
    "ohlcv_store_timeframe": "H1",
    "paper_fallback_spread_pct": 0.0002,
    "paper_fixed_slippage_pct": 0.0005,
    "paper_impact_factor": 0.1,
    "paper_noise_sigma_pct": 0.0001,
    "paper_slippage_model": "fixed",
    "partial_fill_timeout": 30,
    "rate_admin": "30 per minute",
    "rate_auth": "10 per minute",
    "rate_backtest": "10 per minute",
    "rate_global_default": "120 per minute",
    "rate_market_data": "300 per minute",
    "rate_trading": "60 per minute",
    "rate_websocket": "20 per minute",
    "rate_withdrawal": "5 per minute",
    "redis_health_check_interval": 30,
    "redis_max_connections": 100,
    "redis_socket_timeout": 5,
    "refresh_token_expire_days": 7,
    "regime_filter_enabled": True,
    "registry_max_oos_pval": 0.05,
    "registry_min_oos_acc": 0.60,
    "registry_require_sharpe_gate": True,
    "risk_account_equity": 1000000,
    "risk_alert_pct_of_limit": 0.80,
    "risk_cvar_daily_limit": 0.02,
    "risk_dd_size_scale": 0.80,
    "risk_drawdown_mode": "equity",
    "risk_factor_var_limit": 0.40,
    "risk_impact_size_scale": 0.50,
    "risk_kelly_fraction": 0.25,
    "risk_max_daily_loss_pct": 0.05,
    "risk_max_drawdown_pct": 0.10,
    "risk_max_open_positions": 3,
    "risk_max_position_pct": 0.05,
    "risk_min_data_quality": 0.40,
    "risk_min_position_pct": 0.001,
    "risk_sent_size_scale": 0.40,
    "risk_var_confidence": 0.95,
    "risk_var_window": 100,
    "router_max_spread_bps": 50.0,
    "router_primary_broker": "oanda",
    "router_secondary_broker": "paper",
    "security_rate_limit_requests": 100,
    "security_rate_limit_window": 60,
    "signal_abstain_high": 0.54,
    "signal_abstain_low": 0.46,
    "signal_high_conf": 0.60,
    "signal_threshold_long": 0.58,
    "signal_threshold_short": 0.42,
    "sltp_max_retries": 3,
    "sltp_poll_interval_ms": 200,
    "sltp_retry_delay_s": 1.0,
    "spread_abs_limit_usd": 5.0,
    "spread_baseline_window": 50,
    "spread_min_ticks": 20,
    "spread_spike_multiplier": 3.0,
    "trading_mode": "paper",
    "twap_default_secs": 60,
    "twap_default_slices": 5,
    "vwap_slices": 6,
}


def _load_platform_config() -> dict:
    cs = _get_config_store()
    if cs:
        stored = cs.get(_PLATFORM_CONFIG_KEY)
        if stored:
            import json

            try:
                return {**_PLATFORM_CONFIG_DEFAULTS, **json.loads(stored)}
            except Exception:
                logger.debug("Suppressed exception (no detail) in %s", __name__)
    return dict(_PLATFORM_CONFIG_DEFAULTS)


def _save_platform_config(cfg: dict) -> None:
    cs = _get_config_store()
    if cs:
        import json

        cs.set(_PLATFORM_CONFIG_KEY, json.dumps(cfg))


@router.get("/platform/config")
async def get_platform_config(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    return _load_platform_config()


@router.patch("/platform/config")
async def update_platform_config(body: PlatformConfigBody, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    cfg = _load_platform_config()
    updates = body.model_dump(exclude_none=True)
    cfg.update(updates)
    _save_platform_config(cfg)
    _log_superadmin_action(user, "update_platform_config", str(list(updates.keys())))
    return {"ok": True}


@router.post("/platform/maintenance")
async def set_maintenance_mode(body: MaintenanceBody, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    cfg = _load_platform_config()
    cfg["maintenance_mode"] = body.enabled
    if body.message:
        cfg["maintenance_message"] = body.message
    _save_platform_config(cfg)
    cs = _get_config_store()
    if cs:
        cs.set("maintenance_mode", "1" if body.enabled else "0")
    _log_superadmin_action(user, "maintenance_mode", str(body.enabled))
    return {"ok": True, "maintenance_mode": body.enabled}


@router.post("/platform/broadcast")
async def broadcast_message(body: BroadcastBody, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    _log_superadmin_action(user, "broadcast", f"[{body.type}] {body.title}")
    try:
        from cache.redis_client import get_redis_client
        import json

        rc = get_redis_client()
        if rc:
            msg = {"title": body.title, "body": body.body, "type": body.type, "ts": _utcnow().isoformat()}
            rc.lpush("platform:broadcasts", json.dumps(msg))
            rc.ltrim("platform:broadcasts", 0, 49)
    except Exception as exc:
        logger.debug("broadcast redis: %s", exc)
    return {"ok": True}


# ── Trading engine ────────────────────────────────────────────────────────────

_ENGINE_CONFIG_KEY = "superadmin_engine_config"

_ENGINE_CONFIG_DEFAULTS: dict = {
    "paper_trading_mode": True,
    "live_trading_enabled": False,
    "max_open_positions": 5,
    "max_risk_per_trade": 2.0,
    "max_daily_loss_pct": 5.0,
    "max_drawdown_pct": 10.0,
    "default_lot_size": 0.01,
    "slippage_tolerance": 2.0,
    "default_leverage": 50,
    "auto_trade_enabled": False,
    "signal_confidence_threshold": 0.65,
    "kill_switch_active": False,
    "engine_status": "running",
    "broker_type": "paper",
    "execution_mode": "market",
}


def _load_engine_config() -> dict:
    cs = _get_config_store()
    if cs:
        stored = cs.get(_ENGINE_CONFIG_KEY)
        if stored:
            import json

            try:
                return {**_ENGINE_CONFIG_DEFAULTS, **json.loads(stored)}
            except Exception:
                logger.debug("Suppressed exception (no detail) in %s", __name__)
    # Also pull from legacy risk settings
    try:
        from api.admin import _get_risk_settings

        rs = _get_risk_settings()
        merged = dict(_ENGINE_CONFIG_DEFAULTS)
        merged["max_open_positions"] = rs.get("max_open_positions", merged["max_open_positions"])
        merged["max_risk_per_trade"] = rs.get("max_risk_per_trade", merged["max_risk_per_trade"])
        merged["max_daily_loss_pct"] = rs.get("max_daily_loss", merged["max_daily_loss_pct"])
        merged["max_drawdown_pct"] = rs.get("max_drawdown", merged["max_drawdown_pct"])
        merged["paper_trading_mode"] = rs.get("paper_trading_mode", merged["paper_trading_mode"])
        return merged
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)
    return dict(_ENGINE_CONFIG_DEFAULTS)


def _save_engine_config(cfg: dict) -> None:
    cs = _get_config_store()
    if cs:
        import json

        cs.set(_ENGINE_CONFIG_KEY, json.dumps(cfg))


@router.get("/engine/status")
async def get_engine_status(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    cfg = _load_engine_config()
    return {"status": cfg.get("engine_status", "unknown"), "kill_switch_active": cfg.get("kill_switch_active", False)}


@router.get("/engine/config")
async def get_engine_config(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    return _load_engine_config()


@router.patch("/engine/config")
async def update_engine_config(body: EngineConfigBody, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    cfg = _load_engine_config()
    updates = body.model_dump(exclude_none=True)
    cfg.update(updates)
    _save_engine_config(cfg)
    try:
        from api.admin import apply_persisted_risk_settings

        apply_persisted_risk_settings()
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)
    _log_superadmin_action(user, "update_engine_config", str(list(updates.keys())))
    return {"ok": True}


@router.post("/engine/kill-switch")
async def toggle_kill_switch(body: KillSwitchBody, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    cfg = _load_engine_config()
    cfg["kill_switch_active"] = body.enabled
    cfg["engine_status"] = "stopped" if body.enabled else "running"
    _save_engine_config(cfg)
    cs = _get_config_store()
    if cs:
        cs.set("kill_switch_active", "1" if body.enabled else "0")
    try:
        from kill_switch import KillSwitch

        ks = KillSwitch()
        if body.enabled:
            ks.activate("Superadmin kill switch")
        else:
            ks.deactivate()
    except Exception as exc:
        logger.debug("kill_switch module: %s", exc)
    _log_superadmin_action(user, "kill_switch", str(body.enabled))
    return {"ok": True, "kill_switch_active": body.enabled}


@router.post("/engine/pause")
async def pause_trading(body: PauseBody, user: TokenPayload = Depends(_require_superadmin)) -> dict:
    cfg = _load_engine_config()
    cfg["engine_status"] = "paused"
    _save_engine_config(cfg)
    _log_superadmin_action(user, "pause_trading", body.reason)
    return {"ok": True, "engine_status": "paused"}


@router.post("/engine/resume")
async def resume_trading(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    cfg = _load_engine_config()
    cfg["engine_status"] = "running"
    _save_engine_config(cfg)
    _log_superadmin_action(user, "resume_trading")
    return {"ok": True, "engine_status": "running"}


@router.put("/platform/config/full")
async def save_full_platform_config(
    request: Request,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Accept and persist the complete platform config (all 200+ fields).

    Uses a free-form dict so new fields added to the frontend don't require
    a backend schema change.  Merges with existing config so partial updates
    are safe.
    """
    body: dict = await request.json()
    cfg = _load_platform_config()
    cfg.update(body)
    _save_platform_config(cfg)
    _log_superadmin_action(user, "full_platform_config_save", f"keys={len(body)}")
    return {"ok": True, "saved_keys": len(body), "saved_at": _utcnow().isoformat()}


@router.post("/platform/test-smtp")
async def test_smtp_config(
    request: Request,
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """Test SMTP connectivity using the current platform config or a provided override."""
    import smtplib

    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        logger.debug("Suppressed non-fatal exception", exc_info=True)  # nosec B110

    cfg = _load_platform_config()
    host = body.get("host") or cfg.get("smtp_host", "")
    port = int(body.get("port") or cfg.get("smtp_port", 587))
    user_val = body.get("user") or cfg.get("smtp_user", "")
    password = body.get("password") or cfg.get("smtp_password", "")
    use_tls = body.get("tls", cfg.get("smtp_tls", True))

    if not host:
        return {"ok": False, "error": "SMTP host not configured"}

    try:
        if use_tls:
            server = smtplib.SMTP(host, port, timeout=10)
            server.starttls()
        else:
            server = smtplib.SMTP(host, port, timeout=10)
        if user_val and password:
            server.login(user_val, password)
        server.quit()
        _log_superadmin_action(user, "smtp_test", f"host={host}:{port} ok")
        return {"ok": True, "host": host, "port": port}
    except (smtplib.SMTPException, OSError) as exc:
        _log_superadmin_action(user, "smtp_test_failed", f"host={host}:{port} err={exc}")
        return {"ok": False, "error": str(exc)}


@router.get("/platform/config/validate")
async def validate_platform_config(
    user: TokenPayload = Depends(_require_superadmin),
) -> dict:
    """
    Validate the current platform config for consistency and completeness.

    Checks required fields, value ranges, and cross-field constraints.
    Returns a list of warnings and errors without modifying any state.
    """
    cfg = _load_platform_config()
    issues: list[dict] = []

    def warn(field: str, msg: str) -> None:
        issues.append({"severity": "warning", "field": field, "message": msg})

    def error(field: str, msg: str) -> None:
        issues.append({"severity": "error", "field": field, "message": msg})

    # Platform identity
    if not cfg.get("support_email"):
        warn("support_email", "Support email not configured")
    if not cfg.get("platform_name"):
        error("platform_name", "Platform name is required")

    # Security
    if cfg.get("debug") and cfg.get("env") == "production":
        error("debug", "Debug mode must not be enabled in production")
    if cfg.get("access_token_expire_minutes", 30) > 1440:
        warn("access_token_expire_minutes", "Access token expiry > 24h is a security risk")

    # ML
    if cfg.get("ml_drift_threshold", 0.05) > 0.2:
        warn("ml_drift_threshold", "Drift threshold > 0.2 may miss significant model degradation")
    if cfg.get("signal_threshold_long", 0.58) < 0.5:
        error("signal_threshold_long", "Long signal threshold below 0.5 means random signals")

    # Risk
    if cfg.get("risk_max_daily_loss_pct", 0.05) > 0.2:
        warn("risk_max_daily_loss_pct", "Daily loss limit > 20% is extremely high risk")
    if cfg.get("risk_max_drawdown_pct", 0.10) > 0.5:
        error("risk_max_drawdown_pct", "Max drawdown > 50% will likely cause account wipeout")
    if cfg.get("risk_kelly_fraction", 0.25) > 0.5:
        warn("risk_kelly_fraction", "Kelly fraction > 0.5 is aggressive; consider 0.25 or less")

    # Execution
    if cfg.get("engine_tick_loop_hz", 1.0) > 100:
        warn("engine_tick_loop_hz", "Tick loop > 100 Hz may overload the system")

    # Kill switch
    if cfg.get("hopefx_kill_switch") and cfg.get("trading_mode") == "live":
        warn("hopefx_kill_switch", "Kill switch is active but trading mode is live — all trades blocked")

    # SMTP
    if cfg.get("smtp_enabled") and not cfg.get("smtp_host"):
        error("smtp_host", "SMTP enabled but host not configured")

    # Compliance
    if cfg.get("trading_mode") == "live" and not cfg.get("kyc_required_for_live"):
        warn("kyc_required_for_live", "Live trading without KYC requirement is a compliance risk")

    errors = [i for i in issues if i["severity"] == "error"]
    warnings = [i for i in issues if i["severity"] == "warning"]

    return {
        "valid": len(errors) == 0,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "issues": issues,
        "checked_at": _utcnow().isoformat(),
    }


@router.get("/engine/metrics")
async def get_engine_metrics(user: TokenPayload = Depends(_require_superadmin)) -> dict:
    """Return trading engine KPIs — all fields populated from real DB/engine data."""
    now = _utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    metrics: dict = {
        "trades_today": 0,
        "open_positions": 0,
        "pnl_today": 0.0,
        "win_rate_today": 0.0,
        "avg_execution_ms": 0,
        "rejected_orders": 0,
        "kill_switch_triggers": 0,
        "uptime_hours": 0.0,
    }

    # ── Uptime from process start time ────────────────────────────────────────
    try:
        from api.admin import _start_time

        metrics["uptime_hours"] = round((time.time() - _start_time) / 3600, 2)
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)

    # ── Live engine counters (open positions, rejected orders) ────────────────
    try:
        from api.admin import app_state

        if app_state and hasattr(app_state, "engine"):
            eng = app_state.engine
            metrics["open_positions"] = len(getattr(eng, "positions", {}))
            metrics["rejected_orders"] = int(getattr(eng, "rejected_orders", 0))
            metrics["kill_switch_triggers"] = int(getattr(eng, "kill_switch_triggers", 0))
    except Exception:
        logger.debug("Suppressed exception (no detail) in %s", __name__)

    # ── DB queries: trades today, PnL, win rate ───────────────────────────────
    try:
        from database.connection import SessionLocal
        from database.models import Trade
        from sqlalchemy import func

        db = SessionLocal()
        try:
            # All trades opened today
            today_trades = (
                db.query(Trade)
                .filter(Trade.entry_time >= today_start)
                .all()
            )
            metrics["trades_today"] = len(today_trades)

            # Open positions from DB (override engine count if DB has more)
            open_count = sum(1 for t in today_trades if t.is_open)
            if open_count > metrics["open_positions"]:
                metrics["open_positions"] = open_count

            # PnL today: sum of total_pnl for closed trades opened today
            closed_today = [t for t in today_trades if not t.is_open]
            if closed_today:
                metrics["pnl_today"] = round(
                    sum(float(t.total_pnl or 0.0) for t in closed_today), 2
                )
                winning = sum(1 for t in closed_today if (t.total_pnl or 0.0) > 0)
                metrics["win_rate_today"] = round(winning / len(closed_today), 4)

        finally:
            db.close()
    except Exception as exc:
        logger.debug("get_engine_metrics: DB query: %s", exc)

    # ── Avg execution latency from Redis (written by order execution layer) ───
    try:
        import json as _json
        from cache.redis_client import get_redis_client

        rc = get_redis_client()
        if rc:
            raw = rc.get("engine:execution_stats")
            if raw:
                stats = _json.loads(raw)
                metrics["avg_execution_ms"] = int(stats.get("avg_execution_ms", 0))
                # Override rejected_orders if the engine writes it to Redis
                if "rejected_orders" in stats:
                    metrics["rejected_orders"] = int(stats["rejected_orders"])
    except Exception as exc:
        logger.debug("get_engine_metrics: redis stats: %s", exc)

    return metrics
