// settings/PlatformConfiguration.tsx
// Super Admin only — every platform setting, parameter, threshold, and flag
// sourced from the Python codebase. Uses only ui.tsx primitives.
import React, { useState, useEffect, useCallback } from 'react';
import { superadminApi } from '../../hooks/useApi';
import {
  Card, SectionHeader, Field, Input, Select, Toggle, Button,
  StatusBadge, Divider, SaveBar,
} from './ui';
import { extractApiError } from '../../lib/utils';
import { ActionBanner } from '../../components/ActionBanner';

// ── Types ─────────────────────────────────────────────────────────────────────

interface PlatformConfig {
  // Platform
  platform_name: string;
  support_email: string;
  max_users: number;
  allow_registrations: boolean;
  require_email_verification: boolean;
  default_new_user_plan: string;
  default_new_user_role: string;
  session_timeout_minutes: number;
  max_api_keys_per_user: number;
  rate_limit_per_minute: number;
  maintenance_mode: boolean;
  maintenance_message: string;
  announcement_enabled: boolean;
  announcement_text: string;
  announcement_type: string;
  force_2fa_for_admins: boolean;
  ip_whitelist_enabled: boolean;
  ip_whitelist: string;
  // Database
  db_pool_size: number;
  db_max_overflow: number;
  db_echo: boolean;
  // Redis
  redis_socket_timeout: number;
  redis_health_check_interval: number;
  redis_max_connections: number;
  // Security
  jwt_algorithm: string;
  access_token_expire_minutes: number;
  refresh_token_expire_days: number;
  security_rate_limit_requests: number;
  security_rate_limit_window: number;
  // ML
  ml_retrain_interval_minutes: number;
  ml_drift_threshold: number;
  ml_online_learning_rate: number;
  ml_hourly_enabled: boolean;
  ml_hourly_interval_seconds: number;
  ml_full_retrain_hours: number;
  ml_symbols: string;
  ml_model_dir: string;
  // Signal filter
  signal_threshold_long: number;
  signal_threshold_short: number;
  signal_abstain_low: number;
  signal_abstain_high: number;
  signal_high_conf: number;
  min_confidence_abs: number;
  ev_min_threshold: number;
  ev_window: number;
  regime_filter_enabled: boolean;
  mtf_confluence_required: boolean;
  blackout_gate_enabled: boolean;
  circuit_breaker_enabled: boolean;
  cb_min_accuracy: number;
  cb_min_outcomes: number;
  // ML model registry
  registry_min_oos_acc: number;
  registry_max_oos_pval: number;
  registry_require_sharpe_gate: boolean;
  // ML performance monitor
  ml_monitor_window_trades: number;
  ml_monitor_check_interval: number;
  ml_monitor_rollback_thresh: number;
  ml_monitor_min_trades: number;
  // Risk
  risk_account_equity: number;
  risk_max_position_pct: number;
  risk_min_position_pct: number;
  risk_kelly_fraction: number;
  risk_max_daily_loss_pct: number;
  risk_max_drawdown_pct: number;
  risk_max_open_positions: number;
  risk_min_data_quality: number;
  risk_sent_size_scale: number;
  risk_impact_size_scale: number;
  risk_dd_size_scale: number;
  risk_var_window: number;
  risk_var_confidence: number;
  risk_cvar_daily_limit: number;
  risk_factor_var_limit: number;
  risk_drawdown_mode: string;
  risk_alert_pct_of_limit: number;
  max_risk_pct_per_trade: number;
  // Gatekeeper
  gatekeeper_min_conf: number;
  gatekeeper_max_daily_trades: number;
  gatekeeper_pause_s: number;
  gatekeeper_min_data_quality: number;
  gatekeeper_max_spread_usd: number;
  gatekeeper_sent_blackout: number;
  gatekeeper_impact_blackout: number;
  news_blackout_minutes: number;
  // Intra-trade monitor
  intra_min_data_quality: number;
  intra_cvar_confidence: number;
  intra_returns_window: number;
  intra_vol_baseline_window: number;
  // FIA compliance
  fia_max_order_size: number;
  fia_max_intraday_position: number;
  fia_price_tolerance: number;
  fia_daily_loss_limit: number;
  fia_max_msg_per_sec: number;
  // Execution engine
  engine_min_confidence: number;
  engine_min_data_quality: number;
  engine_max_spread_usd: number;
  engine_tick_loop_hz: number;
  engine_max_position_usd: number;
  engine_signal_cooldown_s: number;
  engine_stale_tick_s: number;
  engine_initial_equity: number;
  // Broker circuit breaker
  broker_cb_max_failures: number;
  broker_cb_reset_timeout: number;
  broker_cb_half_open_max: number;
  // Order algorithms
  twap_default_slices: number;
  twap_default_secs: number;
  vwap_slices: number;
  partial_fill_timeout: number;
  min_slice_lots: number;
  algo_min_child_size: number;
  algo_max_participation: number;
  algo_twap_jitter: number;
  algo_vwap_profile: string;
  algo_iceberg_refill_pct: number;
  algo_large_order_threshold: number;
  algo_iceberg_threshold: number;
  algo_default_twap_duration: number;
  algo_default_twap_slices: number;
  algo_default_iceberg_peak: number;
  // Market impact
  ac_eta: number;
  ac_gamma: number;
  ac_max_participation: number;
  ac_min_spread_bps: number;
  ac_queue_factor: number;
  // Spread monitor
  spread_spike_multiplier: number;
  spread_baseline_window: number;
  spread_min_ticks: number;
  spread_abs_limit_usd: number;
  // SL/TP monitor
  sltp_poll_interval_ms: number;
  sltp_max_retries: number;
  sltp_retry_delay_s: number;
  // FIX router
  fix_host: string;
  fix_port: number;
  fix_sender_comp_id: string;
  fix_target_comp_id: string;
  fix_latency_warn_ms: number;
  fix_default_units: number;
  // OANDA
  oanda_timeout_s: number;
  oanda_max_retries: number;
  oanda_retry_backoff_s: number;
  oanda_environment: string;
  // IBKR
  ibkr_host: string;
  ibkr_port_paper: number;
  ibkr_port_live: number;
  ibkr_client_id: number;
  ibkr_connect_timeout_s: number;
  ibkr_order_timeout_s: number;
  ibkr_reconnect_delay_s: number;
  ibkr_max_reconnects: number;
  // CME/COMEX
  cme_fix_host: string;
  cme_fix_port: number;
  cme_fix_sender_id: string;
  cme_fix_target_id: string;
  cme_default_contracts: number;
  cme_latency_warn_ms: number;
  cme_ibkr_fallback: boolean;
  cme_paper_fallback: boolean;
  // C++ shim
  cpp_shim_enabled: boolean;
  cpp_shim_zmq_cmd_addr: string;
  cpp_shim_zmq_resp_addr: string;
  cpp_shim_timeout_ms: number;
  cpp_shim_latency_warn_us: number;
  // OHLCV store
  ohlcv_store_timeframe: string;
  ohlcv_store_max_bars: number;
  // Rate limiting
  rate_global_default: string;
  rate_auth: string;
  rate_trading: string;
  rate_market_data: string;
  rate_admin: string;
  rate_websocket: string;
  rate_backtest: string;
  rate_withdrawal: string;
  // Notifications
  heartbeat_enabled: boolean;
  heartbeat_interval_hours: number;
  discord_signal_cooldown_seconds: number;
  discord_bot_username: string;
  // Kill switch
  hopefx_kill_switch: boolean;
  k8s_ks_namespace: string;
  k8s_ks_configmap_name: string;
  k8s_ks_poll_interval_s: number;
  // SMTP / Email
  smtp_host: string;
  smtp_port: number;
  smtp_user: string;
  smtp_password: string;
  smtp_from: string;
  smtp_from_name: string;
  smtp_tls: boolean;
  smtp_enabled: boolean;
  // Monitoring / Observability
  sentry_dsn: string;
  sentry_environment: string;
  sentry_traces_sample_rate: number;
  sentry_profiles_sample_rate: number;
  prometheus_port: number;
  prometheus_scrape_interval_seconds: number;
  prometheus_url: string;
  alertmanager_smtp_host: string;
  alertmanager_smtp_from: string;
  alertmanager_smtp_to: string;
  // Celery / Task Queue
  celery_broker_url: string;
  celery_result_backend: string;
  celery_task_serializer: string;
  celery_result_expires: number;
  celery_worker_concurrency: number;
  celery_max_tasks_per_child: number;
  // Compliance thresholds
  kyc_required_for_live: boolean;
  aml_transaction_threshold: number;
  aml_daily_volume_threshold: number;
  sanctions_check_enabled: boolean;
  gdpr_data_retention_days: number;
  gdpr_erasure_grace_days: number;
  regulatory_reporting_enabled: boolean;
  // Paper trading slippage model
  paper_slippage_model: string;
  paper_fixed_slippage_pct: number;
  paper_impact_factor: number;
  paper_noise_sigma_pct: number;
  paper_fallback_spread_pct: number;
  // Drift monitor
  drift_monitor_enabled: boolean;
  drift_monitor_window: number;
  drift_monitor_threshold: number;
  drift_monitor_check_interval_s: number;
  drift_monitor_auto_retrain: boolean;
  // Decision engine
  decision_engine_enabled: boolean;
  decision_engine_min_confidence: number;
  decision_engine_max_positions: number;
  decision_engine_cooldown_s: number;
  decision_engine_use_regime: boolean;
  decision_engine_use_sentiment: boolean;
  decision_engine_use_macro: boolean;
  // Smart router
  router_max_spread_bps: number;
  router_primary_broker: string;
  router_secondary_broker: string;
  // LSTM model
  lstm_enabled: boolean;
  lstm_sequence_length: number;
  lstm_hidden_size: number;
  lstm_num_layers: number;
  lstm_dropout: number;
  lstm_learning_rate: number;
  lstm_batch_size: number;
  lstm_epochs: number;
  lstm_retrain_interval_hours: number;
  lstm_min_train_samples: number;
  lstm_use_attention: boolean;
  lstm_bidirectional: boolean;
  lstm_clip_grad_norm: number;
  lstm_weight_decay: number;
  lstm_scheduler: string;
  // AI Brain / strategy generator
  brain_enabled: boolean;
  brain_model: string;
  brain_temperature: number;
  brain_max_tokens: number;
  brain_strategy_timeout_s: number;
  brain_max_strategies_per_day: number;
  brain_auto_deploy: boolean;
  brain_min_backtest_sharpe: number;
  brain_min_backtest_winrate: number;
  brain_sandbox_enabled: boolean;
  // Portfolio allocator
  allocator_enabled: boolean;
  allocator_method: string;
  allocator_rebalance_interval_hours: number;
  allocator_min_weight: number;
  allocator_max_weight: number;
  allocator_risk_budget: number;
  allocator_lookback_days: number;
  allocator_transaction_cost_bps: number;
  allocator_target_volatility: number;
  allocator_use_black_litterman: boolean;
  allocator_use_hrp: boolean;
  // Anomaly detection
  anomaly_enabled: boolean;
  anomaly_model: string;
  anomaly_contamination: number;
  anomaly_window: number;
  anomaly_threshold: number;
  anomaly_action: string;
  anomaly_retrain_interval_hours: number;
  anomaly_min_samples: number;
  anomaly_alert_cooldown_s: number;
  // Macro overlay
  macro_enabled: boolean;
  macro_fred_api_key: string;
  macro_refresh_interval_hours: number;
  macro_lookback_days: number;
  macro_weight_in_signal: number;
  macro_vix_threshold: number;
  macro_dxy_threshold: number;
  macro_yield_spread_threshold: number;
  macro_wgc_enabled: boolean;
  macro_wgc_refresh_hours: number;
  // Online learner
  online_learner_enabled: boolean;
  online_learner_lr: number;
  online_learner_batch_size: number;
  online_learner_update_interval_s: number;
  online_learner_max_buffer: number;
  online_learner_algorithm: string;
  online_learner_forgetting_factor: number;
  online_learner_min_samples_before_update: number;
  online_learner_feature_drift_check: boolean;
  // Sharpe circuit breaker
  sharpe_cb_window_trades: number;
  sharpe_cb_min_sharpe: number;
  sharpe_cb_consecutive: number;
  sharpe_cb_eval_interval_s: number;
  sharpe_cb_min_trades: number;
  sharpe_cb_reset_after_s: number;
  // Regime detection
  regime_enabled: boolean;
  regime_model: string;
  regime_lookback_bars: number;
  regime_n_states: number;
  regime_retrain_interval_hours: number;
  regime_confidence_threshold: number;
  regime_use_hmm: boolean;
  regime_use_kmeans: boolean;
  regime_feature_set: string;
  regime_transition_smoothing: number;
  // Signal engine
  signal_engine_enabled: boolean;
  signal_engine_mode: string;
  signal_engine_ensemble_method: string;
  signal_engine_min_model_agreement: number;
  signal_engine_use_lstm: boolean;
  signal_engine_use_xgb: boolean;
  signal_engine_use_rf: boolean;
  signal_engine_use_lgbm: boolean;
  signal_engine_use_regime: boolean;
  signal_engine_use_macro: boolean;
  signal_engine_use_sentiment: boolean;
  signal_engine_cooldown_s: number;
  signal_engine_max_signals_per_hour: number;
  // TCA (Transaction Cost Analysis)
  tca_enabled: boolean;
  tca_alert_threshold_bps: number;
  tca_alert_window: number;
  tca_persist_redis: boolean;
  tca_persist_db: boolean;
  tca_max_memory_records: number;
  tca_benchmark: string;
  tca_slippage_model: string;
  tca_impact_model: string;
  tca_report_interval_hours: number;
  tca_min_records_for_report: number;
  // Backtest engine
  backtest_engine: string;
  backtest_default_initial_capital: number;
  backtest_default_commission_pct: number;
  backtest_default_slippage_pct: number;
  backtest_default_spread_pct: number;
  backtest_max_duration_s: number;
  backtest_max_concurrent: number;
  backtest_data_source: string;
  backtest_use_tick_data: boolean;
  backtest_walk_forward_folds: number;
  backtest_oos_ratio: number;
  backtest_min_trades_for_validity: number;
  backtest_min_sharpe_for_deploy: number;
  // Feature flags
  feature_nuclear_enabled: boolean;
  feature_copy_trading_enabled: boolean;
  feature_social_feed_enabled: boolean;
  feature_marketplace_enabled: boolean;
  feature_affiliate_enabled: boolean;
  feature_whitelabel_enabled: boolean;
  feature_ai_strategy_enabled: boolean;
  feature_walk_forward_enabled: boolean;
  feature_ab_testing_enabled: boolean;
  feature_tca_enabled: boolean;
  feature_replay_enabled: boolean;
  feature_research_enabled: boolean;
  feature_geopolitical_enabled: boolean;
  feature_prop_firm_enabled: boolean;
  feature_teams_enabled: boolean;
  feature_leaderboard_enabled: boolean;
  feature_crypto_checkout_enabled: boolean;
  feature_2fa_enabled: boolean;
  feature_kyc_enabled: boolean;
  feature_sub_accounts_enabled: boolean;
  // LLM / AI provider
  llm_provider: string;
  llm_model: string;
  llm_api_key: string;
  llm_base_url: string;
  llm_temperature: number;
  llm_max_tokens: number;
  llm_timeout_s: number;
  llm_max_retries: number;
  llm_fallback_provider: string;
  llm_fallback_model: string;
  llm_embedding_model: string;
  llm_embedding_dimensions: number;
  // Drawdown controls
  drawdown_hard_stop_pct: number;
  drawdown_soft_warn_pct: number;
  drawdown_trailing_enabled: boolean;
  drawdown_trailing_lookback_bars: number;
  drawdown_recovery_mode: string;
  drawdown_recovery_size_scale: number;
  drawdown_daily_reset: boolean;
  drawdown_notify_on_breach: boolean;
  drawdown_auto_reduce_on_warn: boolean;
  drawdown_reduce_factor: number;
  // Prop firm mode
  prop_firm_enabled: boolean;
  prop_firm_provider: string;
  prop_firm_account_size: number;
  prop_firm_daily_loss_limit_pct: number;
  prop_firm_max_drawdown_pct: number;
  prop_firm_profit_target_pct: number;
  prop_firm_min_trading_days: number;
  prop_firm_max_position_size_pct: number;
  prop_firm_news_trading_allowed: boolean;
  prop_firm_weekend_holding_allowed: boolean;
  prop_firm_consistency_rule_pct: number;
  prop_firm_scaling_enabled: boolean;
  // Position sizing
  position_sizing_method: string;
  position_sizing_fixed_lots: number;
  position_sizing_risk_pct: number;
  position_sizing_kelly_fraction: number;
  position_sizing_max_lots: number;
  position_sizing_min_lots: number;
  position_sizing_atr_multiplier: number;
  position_sizing_atr_period: number;
  position_sizing_volatility_target: number;
  position_sizing_use_correlation_scaling: boolean;
  position_sizing_max_correlated_exposure: number;
  // General
  env: string;
  debug: boolean;
  log_level: string;
  initial_balance: number;
  trading_mode: string;
  broker_default: string;
  cme_enabled: boolean;
}

interface HealerConfig {
  enabled: boolean;
  scan_interval_sec: number;
  patch_interval_sec: number;
  max_patch_bytes: number;
  aggressiveness: string;
  baseline_auto_rebuild: boolean;
  quarantine_enabled: boolean;
  quarantine_retention_days: number;
  auto_rollback_sensitivity: string;
  max_healing_attempts: number;
  healing_cooldown_sec: number;
  log_level: string;
  protected_paths: string;
  tests_enabled: boolean;
  test_categories: Record<string, boolean>;
  test_execution_strategy: string[];
  test_timeout_sec: number;
  global_test_timeout_sec: number;
  parallel_tests: boolean;
  test_schedule_interval_min: number;
  require_approval_categories: string[];
}

interface HealerStatus {
  running: boolean;
  baseline_files: number;
  drift_events: number;
  patches_applied: number;
  patches_failed: number;
  last_scan: string | null;
  last_test_run: string | null;
  last_test_passed: number | null;
  last_test_failed: number | null;
}

interface TestIndex {
  total: number;
  by_category: Record<string, number>;
}


// ── Defaults ──────────────────────────────────────────────────────────────────

const DEFAULT_PLATFORM: PlatformConfig = {
  platform_name: 'HOPEFX', support_email: '', max_users: 0,
  allow_registrations: true, require_email_verification: true,
  default_new_user_plan: 'free', default_new_user_role: 'user',
  session_timeout_minutes: 60, max_api_keys_per_user: 10,
  rate_limit_per_minute: 120, maintenance_mode: false,
  maintenance_message: '', announcement_enabled: false,
  announcement_text: '', announcement_type: 'info',
  force_2fa_for_admins: false, ip_whitelist_enabled: false, ip_whitelist: '',
  db_pool_size: 20, db_max_overflow: 10, db_echo: false,
  redis_socket_timeout: 5, redis_health_check_interval: 30, redis_max_connections: 100,
  jwt_algorithm: 'HS256', access_token_expire_minutes: 30, refresh_token_expire_days: 7,
  security_rate_limit_requests: 100, security_rate_limit_window: 60,
  ml_retrain_interval_minutes: 60, ml_drift_threshold: 0.05, ml_online_learning_rate: 0.01,
  ml_hourly_enabled: false, ml_hourly_interval_seconds: 3600, ml_full_retrain_hours: 24,
  ml_symbols: 'XAU_USD', ml_model_dir: 'ml/models',
  signal_threshold_long: 0.58, signal_threshold_short: 0.42,
  signal_abstain_low: 0.46, signal_abstain_high: 0.54, signal_high_conf: 0.60,
  min_confidence_abs: 0.55, ev_min_threshold: 0.0, ev_window: 50,
  regime_filter_enabled: true, mtf_confluence_required: false,
  blackout_gate_enabled: true, circuit_breaker_enabled: true,
  cb_min_accuracy: 0.45, cb_min_outcomes: 30,
  registry_min_oos_acc: 0.60, registry_max_oos_pval: 0.05, registry_require_sharpe_gate: true,
  ml_monitor_window_trades: 100, ml_monitor_check_interval: 300,
  ml_monitor_rollback_thresh: 0.20, ml_monitor_min_trades: 20,
  risk_account_equity: 1000000, risk_max_position_pct: 0.05, risk_min_position_pct: 0.001,
  risk_kelly_fraction: 0.25, risk_max_daily_loss_pct: 0.05, risk_max_drawdown_pct: 0.10,
  risk_max_open_positions: 3, risk_min_data_quality: 0.40,
  risk_sent_size_scale: 0.40, risk_impact_size_scale: 0.50, risk_dd_size_scale: 0.80,
  risk_var_window: 100, risk_var_confidence: 0.95, risk_cvar_daily_limit: 0.02,
  risk_factor_var_limit: 0.40, risk_drawdown_mode: 'equity', risk_alert_pct_of_limit: 0.80,
  max_risk_pct_per_trade: 0.01,
  gatekeeper_min_conf: 0.55, gatekeeper_max_daily_trades: 20, gatekeeper_pause_s: 60,
  gatekeeper_min_data_quality: 0.40, gatekeeper_max_spread_usd: 2.00,
  gatekeeper_sent_blackout: 0.85, gatekeeper_impact_blackout: 0.75, news_blackout_minutes: 30,
  intra_min_data_quality: 0.40, intra_cvar_confidence: 0.95,
  intra_returns_window: 200, intra_vol_baseline_window: 100,
  fia_max_order_size: 100, fia_max_intraday_position: 500, fia_price_tolerance: 0.02,
  fia_daily_loss_limit: 0.03, fia_max_msg_per_sec: 50,
  engine_min_confidence: 0.55, engine_min_data_quality: 0.40, engine_max_spread_usd: 2.00,
  engine_tick_loop_hz: 1.0, engine_max_position_usd: 100000,
  engine_signal_cooldown_s: 30.0, engine_stale_tick_s: 10.0, engine_initial_equity: 100000,
  broker_cb_max_failures: 5, broker_cb_reset_timeout: 60, broker_cb_half_open_max: 2,
  twap_default_slices: 5, twap_default_secs: 60, vwap_slices: 6,
  partial_fill_timeout: 30, min_slice_lots: 0.001,
  algo_min_child_size: 0.01, algo_max_participation: 0.05, algo_twap_jitter: 0.1,
  algo_vwap_profile: 'u_shaped', algo_iceberg_refill_pct: 0.1,
  algo_large_order_threshold: 10, algo_iceberg_threshold: 50,
  algo_default_twap_duration: 300, algo_default_twap_slices: 10, algo_default_iceberg_peak: 5,
  ac_eta: 0.3, ac_gamma: 0.1, ac_max_participation: 0.10, ac_min_spread_bps: 1.0, ac_queue_factor: 0.5,
  spread_spike_multiplier: 3.0, spread_baseline_window: 50, spread_min_ticks: 20, spread_abs_limit_usd: 5.0,
  sltp_poll_interval_ms: 200, sltp_max_retries: 3, sltp_retry_delay_s: 1.0,
  fix_host: '127.0.0.1', fix_port: 9876, fix_sender_comp_id: 'HOPEFX',
  fix_target_comp_id: 'BROKER', fix_latency_warn_ms: 50, fix_default_units: 1000,
  oanda_timeout_s: 10, oanda_max_retries: 3, oanda_retry_backoff_s: 0.5, oanda_environment: 'practice',
  ibkr_host: '127.0.0.1', ibkr_port_paper: 7497, ibkr_port_live: 7496, ibkr_client_id: 1,
  ibkr_connect_timeout_s: 30, ibkr_order_timeout_s: 30, ibkr_reconnect_delay_s: 5, ibkr_max_reconnects: 10,
  cme_fix_host: '127.0.0.1', cme_fix_port: 9876, cme_fix_sender_id: 'HOPEFX', cme_fix_target_id: 'CME',
  cme_default_contracts: 1, cme_latency_warn_ms: 50, cme_ibkr_fallback: true, cme_paper_fallback: true,
  cpp_shim_enabled: true, cpp_shim_zmq_cmd_addr: 'tcp://127.0.0.1:6555',
  cpp_shim_zmq_resp_addr: 'tcp://127.0.0.1:6556', cpp_shim_timeout_ms: 5000, cpp_shim_latency_warn_us: 1000,
  ohlcv_store_timeframe: 'H1', ohlcv_store_max_bars: 500,
  rate_global_default: '120 per minute', rate_auth: '10 per minute',
  rate_trading: '60 per minute', rate_market_data: '300 per minute',
  rate_admin: '30 per minute', rate_websocket: '20 per minute',
  rate_backtest: '10 per minute', rate_withdrawal: '5 per minute',
  heartbeat_enabled: true, heartbeat_interval_hours: 1,
  discord_signal_cooldown_seconds: 300, discord_bot_username: 'HOPEFX Signals',
  hopefx_kill_switch: false, k8s_ks_namespace: 'hopefx',
  k8s_ks_configmap_name: 'hopefx-kill-switch', k8s_ks_poll_interval_s: 5,
  // SMTP
  smtp_host: '', smtp_port: 587, smtp_user: '', smtp_password: '',
  smtp_from: 'noreply@hopefx.ai', smtp_from_name: 'HOPEFX Trading',
  smtp_tls: true, smtp_enabled: false,
  // Monitoring
  sentry_dsn: '', sentry_environment: 'production',
  sentry_traces_sample_rate: 0.1, sentry_profiles_sample_rate: 0.1,
  prometheus_port: 9090, prometheus_scrape_interval_seconds: 15,
  prometheus_url: 'http://prometheus:9090',
  alertmanager_smtp_host: 'localhost:587', alertmanager_smtp_from: 'alerts@hopefx.ai',
  alertmanager_smtp_to: '',
  // Celery
  celery_broker_url: 'redis://redis:6379/1', celery_result_backend: 'redis://redis:6379/2',
  celery_task_serializer: 'json', celery_result_expires: 3600,
  celery_worker_concurrency: 4, celery_max_tasks_per_child: 1000,
  // Compliance
  kyc_required_for_live: true, aml_transaction_threshold: 10000,
  aml_daily_volume_threshold: 50000, sanctions_check_enabled: true,
  gdpr_data_retention_days: 365, gdpr_erasure_grace_days: 30,
  regulatory_reporting_enabled: false,
  // Paper trading slippage model
  paper_slippage_model: 'fixed', paper_fixed_slippage_pct: 0.0005,
  paper_impact_factor: 0.1, paper_noise_sigma_pct: 0.0001, paper_fallback_spread_pct: 0.0002,
  // Drift monitor
  drift_monitor_enabled: true, drift_monitor_window: 200, drift_monitor_threshold: 0.05,
  drift_monitor_check_interval_s: 300, drift_monitor_auto_retrain: false,
  // Decision engine
  decision_engine_enabled: true, decision_engine_min_confidence: 0.55,
  decision_engine_max_positions: 3, decision_engine_cooldown_s: 30,
  decision_engine_use_regime: true, decision_engine_use_sentiment: true, decision_engine_use_macro: true,
  // Smart router
  router_max_spread_bps: 50.0, router_primary_broker: 'oanda', router_secondary_broker: 'paper',
  // LSTM model
  lstm_enabled: false, lstm_sequence_length: 60, lstm_hidden_size: 128, lstm_num_layers: 2,
  lstm_dropout: 0.2, lstm_learning_rate: 0.001, lstm_batch_size: 64, lstm_epochs: 50,
  lstm_retrain_interval_hours: 24, lstm_min_train_samples: 500, lstm_use_attention: true,
  lstm_bidirectional: false, lstm_clip_grad_norm: 1.0, lstm_weight_decay: 1e-5,
  lstm_scheduler: 'cosine',
  // AI Brain
  brain_enabled: false, brain_model: 'gpt-4o', brain_temperature: 0.3, brain_max_tokens: 4096,
  brain_strategy_timeout_s: 120, brain_max_strategies_per_day: 10, brain_auto_deploy: false,
  brain_min_backtest_sharpe: 1.0, brain_min_backtest_winrate: 0.52, brain_sandbox_enabled: true,
  // Portfolio allocator
  allocator_enabled: false, allocator_method: 'equal_weight',
  allocator_rebalance_interval_hours: 24, allocator_min_weight: 0.05, allocator_max_weight: 0.40,
  allocator_risk_budget: 0.02, allocator_lookback_days: 252, allocator_transaction_cost_bps: 2.0,
  allocator_target_volatility: 0.10, allocator_use_black_litterman: false, allocator_use_hrp: false,
  // Anomaly detection
  anomaly_enabled: false, anomaly_model: 'isolation_forest', anomaly_contamination: 0.05,
  anomaly_window: 100, anomaly_threshold: 0.80, anomaly_action: 'alert',
  anomaly_retrain_interval_hours: 24, anomaly_min_samples: 200, anomaly_alert_cooldown_s: 300,
  // Macro overlay
  macro_enabled: true, macro_fred_api_key: '', macro_refresh_interval_hours: 6,
  macro_lookback_days: 252, macro_weight_in_signal: 0.15, macro_vix_threshold: 30.0,
  macro_dxy_threshold: 105.0, macro_yield_spread_threshold: 0.5, macro_wgc_enabled: true,
  macro_wgc_refresh_hours: 24,
  // Online learner
  online_learner_enabled: false, online_learner_lr: 0.001, online_learner_batch_size: 32,
  online_learner_update_interval_s: 300, online_learner_max_buffer: 10000,
  online_learner_algorithm: 'sgd', online_learner_forgetting_factor: 0.99,
  online_learner_min_samples_before_update: 50, online_learner_feature_drift_check: true,
  // Sharpe circuit breaker
  sharpe_cb_window_trades: 50, sharpe_cb_min_sharpe: 0.0, sharpe_cb_consecutive: 3,
  sharpe_cb_eval_interval_s: 60, sharpe_cb_min_trades: 20, sharpe_cb_reset_after_s: 3600,
  // Regime detection
  regime_enabled: true, regime_model: 'hmm', regime_lookback_bars: 200, regime_n_states: 3,
  regime_retrain_interval_hours: 24, regime_confidence_threshold: 0.60, regime_use_hmm: true,
  regime_use_kmeans: false, regime_feature_set: 'default', regime_transition_smoothing: 0.3,
  // Signal engine
  signal_engine_enabled: true, signal_engine_mode: 'ensemble', signal_engine_ensemble_method: 'weighted_vote',
  signal_engine_min_model_agreement: 0.60, signal_engine_use_lstm: false, signal_engine_use_xgb: true,
  signal_engine_use_rf: true, signal_engine_use_lgbm: true, signal_engine_use_regime: true,
  signal_engine_use_macro: true, signal_engine_use_sentiment: true,
  signal_engine_cooldown_s: 30, signal_engine_max_signals_per_hour: 12,
  // TCA
  tca_enabled: true, tca_alert_threshold_bps: 5.0, tca_alert_window: 100,
  tca_persist_redis: true, tca_persist_db: true, tca_max_memory_records: 10000,
  tca_benchmark: 'arrival_price', tca_slippage_model: 'linear', tca_impact_model: 'square_root',
  tca_report_interval_hours: 24, tca_min_records_for_report: 10,
  // Backtest engine
  backtest_engine: 'vectorbt', backtest_default_initial_capital: 100000,
  backtest_default_commission_pct: 0.0002, backtest_default_slippage_pct: 0.0001,
  backtest_default_spread_pct: 0.0002, backtest_max_duration_s: 300, backtest_max_concurrent: 4,
  backtest_data_source: 'ohlcv_store', backtest_use_tick_data: false,
  backtest_walk_forward_folds: 5, backtest_oos_ratio: 0.20,
  backtest_min_trades_for_validity: 30, backtest_min_sharpe_for_deploy: 0.80,
  // Feature flags
  feature_nuclear_enabled: true, feature_copy_trading_enabled: true,
  feature_social_feed_enabled: true, feature_marketplace_enabled: true,
  feature_affiliate_enabled: true, feature_whitelabel_enabled: false,
  feature_ai_strategy_enabled: true, feature_walk_forward_enabled: true,
  feature_ab_testing_enabled: true, feature_tca_enabled: true,
  feature_replay_enabled: true, feature_research_enabled: true,
  feature_geopolitical_enabled: true, feature_prop_firm_enabled: true,
  feature_teams_enabled: true, feature_leaderboard_enabled: true,
  feature_crypto_checkout_enabled: true, feature_2fa_enabled: true,
  feature_kyc_enabled: true, feature_sub_accounts_enabled: true,
  // LLM / AI provider
  llm_provider: 'openai', llm_model: 'gpt-4o', llm_api_key: '', llm_base_url: '',
  llm_temperature: 0.3, llm_max_tokens: 4096, llm_timeout_s: 60, llm_max_retries: 3,
  llm_fallback_provider: 'anthropic', llm_fallback_model: 'claude-3-5-sonnet-20241022',
  llm_embedding_model: 'text-embedding-3-small', llm_embedding_dimensions: 1536,
  // Drawdown controls
  drawdown_hard_stop_pct: 0.10, drawdown_soft_warn_pct: 0.07, drawdown_trailing_enabled: true,
  drawdown_trailing_lookback_bars: 100, drawdown_recovery_mode: 'reduce_size',
  drawdown_recovery_size_scale: 0.50, drawdown_daily_reset: true, drawdown_notify_on_breach: true,
  drawdown_auto_reduce_on_warn: true, drawdown_reduce_factor: 0.75,
  // Prop firm mode
  prop_firm_enabled: false, prop_firm_provider: 'ftmo', prop_firm_account_size: 100000,
  prop_firm_daily_loss_limit_pct: 0.05, prop_firm_max_drawdown_pct: 0.10,
  prop_firm_profit_target_pct: 0.10, prop_firm_min_trading_days: 10,
  prop_firm_max_position_size_pct: 0.05, prop_firm_news_trading_allowed: false,
  prop_firm_weekend_holding_allowed: false, prop_firm_consistency_rule_pct: 0.50,
  prop_firm_scaling_enabled: false,
  // Position sizing
  position_sizing_method: 'risk_pct', position_sizing_fixed_lots: 0.01,
  position_sizing_risk_pct: 0.01, position_sizing_kelly_fraction: 0.25,
  position_sizing_max_lots: 10.0, position_sizing_min_lots: 0.001,
  position_sizing_atr_multiplier: 1.5, position_sizing_atr_period: 14,
  position_sizing_volatility_target: 0.01, position_sizing_use_correlation_scaling: false,
  position_sizing_max_correlated_exposure: 0.10,
  // General
  env: 'production', debug: false, log_level: 'INFO',
  initial_balance: 100000, trading_mode: 'paper', broker_default: 'paper', cme_enabled: false,
};

const DEFAULT_HEALER: HealerConfig = {
  enabled: true, scan_interval_sec: 120, patch_interval_sec: 60,
  max_patch_bytes: 65536, aggressiveness: 'medium', baseline_auto_rebuild: true,
  quarantine_enabled: true, quarantine_retention_days: 30,
  auto_rollback_sensitivity: 'medium', max_healing_attempts: 3,
  healing_cooldown_sec: 300, log_level: 'standard',
  protected_paths: 'live_trading.py,risk_manager.py,ml/models/,config/secrets/',
  tests_enabled: true,
  test_categories: { unit: true, api: true, broker: true, risk: true, ml: true, security: true, performance: false, e2e: false },
  test_execution_strategy: ['after_patch', 'on_drift'],
  test_timeout_sec: 120, global_test_timeout_sec: 600, parallel_tests: true,
  test_schedule_interval_min: 60, require_approval_categories: ['nuclear', 'e2e'],
};


// ── Shared sub-components ─────────────────────────────────────────────────────

const Num: React.FC<{
  label: string; desc?: string; value: number; step?: number; min?: number; max?: number;
  onChange: (v: number) => void;
}> = ({ label, desc, value, step = 1, min, max, onChange }) => (
  <Field label={label} description={desc}>
    <Input
      type="number" value={value} step={step}
      min={min !== undefined ? min : undefined}
      max={max !== undefined ? max : undefined}
      onChange={(e) => onChange(parseFloat(e.target.value) || 0)}
    />
  </Field>
);

const Txt: React.FC<{
  label: string; desc?: string; value: string; placeholder?: string;
  onChange: (v: string) => void; password?: boolean;
}> = ({ label, desc, value, placeholder, onChange, password }) => (
  <Field label={label} description={desc}>
    <Input
      type={password ? 'password' : 'text'} value={value}
      placeholder={placeholder} onChange={(e) => onChange(e.target.value)}
    />
  </Field>
);

const Sel: React.FC<{
  label: string; desc?: string; value: string;
  options: { value: string; label: string }[];
  onChange: (v: string) => void;
}> = ({ label, desc, value, options, onChange }) => (
  <Field label={label} description={desc}>
    <Select value={value} options={options} onChange={(e) => onChange(e.target.value)} />
  </Field>
);

const Tog: React.FC<{
  id: string; label: string; desc?: string; checked: boolean; onChange: (v: boolean) => void;
}> = ({ id, label, desc, checked, onChange }) => (
  <Toggle id={id} label={label} description={desc} checked={checked} onChange={onChange} />
);

// ── Tab bar ───────────────────────────────────────────────────────────────────

const TABS = [
  { id: 'platform',       label: '🌐 Platform',        },
  { id: 'database',       label: '🗄️ Database & Cache', },
  { id: 'security',       label: '🔒 Security',         },
  { id: 'ml',             label: '🧠 ML / AI',          },
  { id: 'lstm',           label: '🔁 LSTM',             },
  { id: 'brain',          label: '💡 AI Brain',         },
  { id: 'allocator',      label: '📊 Allocator',        },
  { id: 'anomaly',        label: '🚨 Anomaly',          },
  { id: 'macro',          label: '🌍 Macro',            },
  { id: 'online',         label: '📡 Online Learner',   },
  { id: 'sharpe',         label: '📈 Sharpe CB',        },
  { id: 'regime',         label: '🗺️ Regime',           },
  { id: 'signal_engine',  label: '⚡ Signal Engine',    },
  { id: 'tca',            label: '💹 TCA',              },
  { id: 'backtest',       label: '🔄 Backtest',         },
  { id: 'feature_flags',  label: '🚩 Feature Flags',    },
  { id: 'llm',            label: '🤖 LLM / AI',         },
  { id: 'drawdown',       label: '📉 Drawdown',         },
  { id: 'prop_firm',      label: '🏆 Prop Firm',        },
  { id: 'position_sizing',label: '📐 Position Sizing',  },
  { id: 'decision',       label: '🎯 Decision Engine',  },
  { id: 'risk',           label: '⚖️ Risk Engine',      },
  { id: 'execution',      label: '⚡ Execution',        },
  { id: 'brokers',        label: '🏦 Brokers',          },
  { id: 'paper',          label: '📄 Paper Trading',    },
  { id: 'ratelimit',      label: '🚦 Rate Limiting',    },
  { id: 'notify',         label: '🔔 Notifications',    },
  { id: 'smtp',           label: '📧 SMTP / Email',     },
  { id: 'monitoring',     label: '📊 Monitoring',       },
  { id: 'celery',         label: '⚙️ Task Queue',       },
  { id: 'compliance',     label: '⚖️ Compliance',       },
  { id: 'killswitch',     label: '🛑 Kill Switch',      },
  { id: 'healing',        label: '🩺 Auto-Healing',     },
  { id: 'infrastructure', label: '🏗️ Infrastructure',   },
  { id: 'diagnostics',    label: '🔬 Diagnostics',      },
];

const TabBar: React.FC<{ active: string; onChange: (t: string) => void }> = ({ active, onChange }) => (
  <div style={{
    display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 24,
    borderBottom: '1px solid #1e293b', paddingBottom: 12,
  }}>
    {TABS.map((t) => (
      <button
        key={t.id}
        onClick={() => onChange(t.id)}
        style={{
          padding: '7px 14px', borderRadius: 8, border: 'none', cursor: 'pointer',
          fontSize: 12, fontWeight: active === t.id ? 700 : 500,
          background: active === t.id ? '#1e3a5f' : '#1e293b',
          color: active === t.id ? '#60a5fa' : '#94a3b8',
          transition: 'all 0.15s',
        }}
      >{t.label}</button>
    ))}
  </div>
);


// ── Section renderers ─────────────────────────────────────────────────────────

const PlatformTab: React.FC<{ cfg: PlatformConfig; set: (p: Partial<PlatformConfig>) => void }> = ({ cfg, set }) => (
  <>
    <Card>
      <SectionHeader icon="🌐" title="Platform Identity" />
      <Txt label="Platform Name" value={cfg.platform_name} onChange={(v) => set({ platform_name: v })} />
      <Txt label="Support Email" value={cfg.support_email} onChange={(v) => set({ support_email: v })} />
      <Sel label="Environment" value={cfg.env}
        options={[{ value: 'development', label: 'Development' }, { value: 'staging', label: 'Staging' }, { value: 'production', label: 'Production' }]}
        onChange={(v) => set({ env: v })} />
      <Sel label="Log Level" value={cfg.log_level}
        options={['DEBUG','INFO','WARNING','ERROR','CRITICAL'].map((v) => ({ value: v, label: v }))}
        onChange={(v) => set({ log_level: v })} />
      <Tog id="debug" label="Debug Mode" desc="Enables verbose stack traces. Never enable in production." checked={cfg.debug} onChange={(v) => set({ debug: v })} />
    </Card>
    <Card>
      <SectionHeader icon="👥" title="User Registration" />
      <Tog id="allow_reg" label="Allow New Registrations" checked={cfg.allow_registrations} onChange={(v) => set({ allow_registrations: v })} />
      <Tog id="email_verify" label="Require Email Verification" checked={cfg.require_email_verification} onChange={(v) => set({ require_email_verification: v })} />
      <Sel label="Default New User Plan" value={cfg.default_new_user_plan}
        options={['free','starter','professional','enterprise','elite'].map((v) => ({ value: v, label: v.charAt(0).toUpperCase() + v.slice(1) }))}
        onChange={(v) => set({ default_new_user_plan: v })} />
      <Sel label="Default New User Role" value={cfg.default_new_user_role}
        options={['user','trader','admin'].map((v) => ({ value: v, label: v.charAt(0).toUpperCase() + v.slice(1) }))}
        onChange={(v) => set({ default_new_user_role: v })} />
      <Num label="Max Users (0 = unlimited)" value={cfg.max_users} min={0} onChange={(v) => set({ max_users: v })} />
      <Num label="Max API Keys Per User" value={cfg.max_api_keys_per_user} min={1} onChange={(v) => set({ max_api_keys_per_user: v })} />
      <Num label="Session Timeout (minutes)" value={cfg.session_timeout_minutes} min={1} onChange={(v) => set({ session_timeout_minutes: v })} />
      <Tog id="force_2fa" label="Force 2FA for Admins" checked={cfg.force_2fa_for_admins} onChange={(v) => set({ force_2fa_for_admins: v })} />
    </Card>
    <Card>
      <SectionHeader icon="📢" title="Maintenance & Announcements" />
      <Tog id="maint" label="Maintenance Mode" desc="Blocks all non-admin access." checked={cfg.maintenance_mode} onChange={(v) => set({ maintenance_mode: v })} />
      <Txt label="Maintenance Message" value={cfg.maintenance_message} placeholder="We'll be back shortly…" onChange={(v) => set({ maintenance_message: v })} />
      <Divider />
      <Tog id="ann_en" label="Announcement Banner" checked={cfg.announcement_enabled} onChange={(v) => set({ announcement_enabled: v })} />
      <Txt label="Announcement Text" value={cfg.announcement_text} onChange={(v) => set({ announcement_text: v })} />
      <Sel label="Announcement Type" value={cfg.announcement_type}
        options={['info','warning','error','success'].map((v) => ({ value: v, label: v.charAt(0).toUpperCase() + v.slice(1) }))}
        onChange={(v) => set({ announcement_type: v })} />
    </Card>
    <Card>
      <SectionHeader icon="🚦" title="Global Rate Limit" />
      <Num label="Rate Limit Per Minute (global)" value={cfg.rate_limit_per_minute} min={1} onChange={(v) => set({ rate_limit_per_minute: v })} />
    </Card>
    <Card>
      <SectionHeader icon="🛡️" title="IP Whitelist" />
      <Tog id="ip_wl" label="Enable IP Whitelist" checked={cfg.ip_whitelist_enabled} onChange={(v) => set({ ip_whitelist_enabled: v })} />
      <Txt label="Allowed IPs (comma-separated)" value={cfg.ip_whitelist} placeholder="1.2.3.4, 5.6.7.8" onChange={(v) => set({ ip_whitelist: v })} />
    </Card>
    <Card>
      <SectionHeader icon="💱" title="Trading Mode" />
      <Sel label="Default Trading Mode" value={cfg.trading_mode}
        options={[{ value: 'paper', label: 'Paper Trading' }, { value: 'live', label: 'Live Trading' }]}
        onChange={(v) => set({ trading_mode: v })} />
      <Sel label="Default Broker" value={cfg.broker_default}
        options={['paper','oanda','alpaca','ibkr','mt5','binance','cme'].map((v) => ({ value: v, label: v.toUpperCase() }))}
        onChange={(v) => set({ broker_default: v })} />
      <Num label="Initial Balance (USD)" value={cfg.initial_balance} min={0} step={1000} onChange={(v) => set({ initial_balance: v })} />
    </Card>
  </>
);


const DatabaseTab: React.FC<{ cfg: PlatformConfig; set: (p: Partial<PlatformConfig>) => void }> = ({ cfg, set }) => (
  <>
    <Card>
      <SectionHeader icon="🗄️" title="PostgreSQL / SQLAlchemy" desc="config/settings.py — DatabaseSettings" />
      <Num label="Connection Pool Size" desc="DB_POOL_SIZE" value={cfg.db_pool_size} min={1} onChange={(v) => set({ db_pool_size: v })} />
      <Num label="Max Overflow" desc="DB_MAX_OVERFLOW" value={cfg.db_max_overflow} min={0} onChange={(v) => set({ db_max_overflow: v })} />
      <Tog id="db_echo" label="Echo SQL Queries" desc="DB_ECHO — never enable in production" checked={cfg.db_echo} onChange={(v) => set({ db_echo: v })} />
    </Card>
    <Card>
      <SectionHeader icon="⚡" title="Redis" desc="config/settings.py — RedisSettings" />
      <Num label="Socket Timeout (s)" desc="REDIS_SOCKET_TIMEOUT" value={cfg.redis_socket_timeout} step={0.5} min={0.5} onChange={(v) => set({ redis_socket_timeout: v })} />
      <Num label="Health Check Interval (s)" desc="REDIS_HEALTH_CHECK_INTERVAL" value={cfg.redis_health_check_interval} min={5} onChange={(v) => set({ redis_health_check_interval: v })} />
      <Num label="Max Connections" desc="REDIS_MAX_CONNECTIONS" value={cfg.redis_max_connections} min={1} onChange={(v) => set({ redis_max_connections: v })} />
    </Card>
    <Card>
      <SectionHeader icon="📦" title="OHLCV Store" desc="brokers/ohlcv_store.py" />
      <Sel label="Default Timeframe" desc="OHLCV_STORE_TIMEFRAME" value={cfg.ohlcv_store_timeframe}
        options={['M1','M5','M15','M30','H1','H4','D','W'].map((v) => ({ value: v, label: v }))}
        onChange={(v) => set({ ohlcv_store_timeframe: v })} />
      <Num label="Max Bars in Memory" desc="OHLCV_STORE_MAX_BARS" value={cfg.ohlcv_store_max_bars} min={50} onChange={(v) => set({ ohlcv_store_max_bars: v })} />
    </Card>
  </>
);

const SecurityTab: React.FC<{ cfg: PlatformConfig; set: (p: Partial<PlatformConfig>) => void }> = ({ cfg, set }) => (
  <>
    <Card>
      <SectionHeader icon="🔑" title="JWT / Auth" desc="config/settings.py — SecuritySettings" />
      <Sel label="JWT Algorithm" desc="SECURITY_JWT_ALGORITHM" value={cfg.jwt_algorithm}
        options={['HS256','HS384','HS512','RS256'].map((v) => ({ value: v, label: v }))}
        onChange={(v) => set({ jwt_algorithm: v })} />
      <Num label="Access Token Expiry (minutes)" desc="SECURITY_ACCESS_TOKEN_EXPIRE_MINUTES" value={cfg.access_token_expire_minutes} min={5} onChange={(v) => set({ access_token_expire_minutes: v })} />
      <Num label="Refresh Token Expiry (days)" desc="SECURITY_REFRESH_TOKEN_EXPIRE_DAYS" value={cfg.refresh_token_expire_days} min={1} onChange={(v) => set({ refresh_token_expire_days: v })} />
    </Card>
    <Card>
      <SectionHeader icon="🚦" title="Auth Rate Limiting" desc="config/settings.py — SecuritySettings" />
      <Num label="Rate Limit Requests" desc="SECURITY_RATE_LIMIT_REQUESTS" value={cfg.security_rate_limit_requests} min={1} onChange={(v) => set({ security_rate_limit_requests: v })} />
      <Num label="Rate Limit Window (s)" desc="SECURITY_RATE_LIMIT_WINDOW" value={cfg.security_rate_limit_window} min={1} onChange={(v) => set({ security_rate_limit_window: v })} />
    </Card>
  </>
);


const MLTab: React.FC<{ cfg: PlatformConfig; set: (p: Partial<PlatformConfig>) => void }> = ({ cfg, set }) => (
  <>
    <Card>
      <SectionHeader icon="🧠" title="ML Core" desc="config/settings.py — MLSettings" />
      <Num label="Retrain Interval (minutes)" desc="ML_RETRAIN_INTERVAL_MINUTES" value={cfg.ml_retrain_interval_minutes} min={1} onChange={(v) => set({ ml_retrain_interval_minutes: v })} />
      <Num label="Drift Threshold" desc="ML_DRIFT_THRESHOLD" value={cfg.ml_drift_threshold} step={0.01} min={0} max={1} onChange={(v) => set({ ml_drift_threshold: v })} />
      <Num label="Online Learning Rate" desc="ML_ONLINE_LEARNING_RATE" value={cfg.ml_online_learning_rate} step={0.001} min={0} onChange={(v) => set({ ml_online_learning_rate: v })} />
    </Card>
    <Card>
      <SectionHeader icon="⏱️" title="Hourly Trainer" desc="ml/hourly_trainer.py" />
      <Tog id="ml_hourly" label="Enable Hourly Trainer" desc="ML_HOURLY_ENABLED" checked={cfg.ml_hourly_enabled} onChange={(v) => set({ ml_hourly_enabled: v })} />
      <Num label="Interval (seconds)" desc="ML_HOURLY_INTERVAL_SECONDS" value={cfg.ml_hourly_interval_seconds} min={60} onChange={(v) => set({ ml_hourly_interval_seconds: v })} />
      <Num label="Full Retrain Every N Hours" desc="ML_FULL_RETRAIN_HOURS" value={cfg.ml_full_retrain_hours} min={1} onChange={(v) => set({ ml_full_retrain_hours: v })} />
      <Txt label="Symbols (comma-separated)" desc="ML_SYMBOLS" value={cfg.ml_symbols} placeholder="XAU_USD,EUR_USD" onChange={(v) => set({ ml_symbols: v })} />
      <Txt label="Model Directory" desc="ML_MODEL_DIR" value={cfg.ml_model_dir} onChange={(v) => set({ ml_model_dir: v })} />
    </Card>
    <Card>
      <SectionHeader icon="📡" title="Signal Filter" desc="ml/signal_filter.py + ml/advanced_predictor.py" />
      <Num label="Long Threshold" desc="SIGNAL_THRESHOLD_LONG" value={cfg.signal_threshold_long} step={0.01} min={0.5} max={1} onChange={(v) => set({ signal_threshold_long: v })} />
      <Num label="Short Threshold" desc="SIGNAL_THRESHOLD_SHORT" value={cfg.signal_threshold_short} step={0.01} min={0} max={0.5} onChange={(v) => set({ signal_threshold_short: v })} />
      <Num label="Abstain Low" desc="SIGNAL_ABSTAIN_LOW" value={cfg.signal_abstain_low} step={0.01} min={0} max={1} onChange={(v) => set({ signal_abstain_low: v })} />
      <Num label="Abstain High" desc="SIGNAL_ABSTAIN_HIGH" value={cfg.signal_abstain_high} step={0.01} min={0} max={1} onChange={(v) => set({ signal_abstain_high: v })} />
      <Num label="High Confidence Threshold" desc="SIGNAL_HIGH_CONF" value={cfg.signal_high_conf} step={0.01} min={0.5} max={1} onChange={(v) => set({ signal_high_conf: v })} />
      <Num label="Min Confidence (absolute)" desc="MIN_CONFIDENCE_ABS" value={cfg.min_confidence_abs} step={0.01} min={0} max={1} onChange={(v) => set({ min_confidence_abs: v })} />
      <Num label="EV Min Threshold" desc="EV_MIN_THRESHOLD" value={cfg.ev_min_threshold} step={0.01} onChange={(v) => set({ ev_min_threshold: v })} />
      <Num label="EV Window" desc="EV_WINDOW" value={cfg.ev_window} min={10} onChange={(v) => set({ ev_window: v })} />
      <Tog id="regime_filter" label="Regime Filter" desc="REGIME_FILTER_ENABLED" checked={cfg.regime_filter_enabled} onChange={(v) => set({ regime_filter_enabled: v })} />
      <Tog id="mtf_conf" label="MTF Confluence Required" desc="MTF_CONFLUENCE_REQUIRED" checked={cfg.mtf_confluence_required} onChange={(v) => set({ mtf_confluence_required: v })} />
      <Tog id="blackout_gate" label="Blackout Gate" desc="BLACKOUT_GATE_ENABLED" checked={cfg.blackout_gate_enabled} onChange={(v) => set({ blackout_gate_enabled: v })} />
      <Tog id="cb_enabled" label="Circuit Breaker" desc="CIRCUIT_BREAKER_ENABLED" checked={cfg.circuit_breaker_enabled} onChange={(v) => set({ circuit_breaker_enabled: v })} />
      <Num label="CB Min Accuracy" desc="CB_MIN_ACCURACY" value={cfg.cb_min_accuracy} step={0.01} min={0} max={1} onChange={(v) => set({ cb_min_accuracy: v })} />
      <Num label="CB Min Outcomes" desc="CB_MIN_OUTCOMES" value={cfg.cb_min_outcomes} min={1} onChange={(v) => set({ cb_min_outcomes: v })} />
    </Card>
    <Card>
      <SectionHeader icon="📋" title="Model Registry" desc="ml/model_registry.py" />
      <Num label="Min OOS Accuracy" desc="REGISTRY_MIN_OOS_ACC" value={cfg.registry_min_oos_acc} step={0.01} min={0} max={1} onChange={(v) => set({ registry_min_oos_acc: v })} />
      <Num label="Max OOS P-Value" desc="REGISTRY_MAX_OOS_PVAL" value={cfg.registry_max_oos_pval} step={0.001} min={0} max={1} onChange={(v) => set({ registry_max_oos_pval: v })} />
      <Tog id="sharpe_gate" label="Require Sharpe Gate" desc="REGISTRY_REQUIRE_SHARPE_GATE" checked={cfg.registry_require_sharpe_gate} onChange={(v) => set({ registry_require_sharpe_gate: v })} />
    </Card>
    <Card>
      <SectionHeader icon="📊" title="Performance Monitor" desc="ml/performance_monitor.py" />
      <Num label="Window Trades" desc="ML_MONITOR_WINDOW_TRADES" value={cfg.ml_monitor_window_trades} min={10} onChange={(v) => set({ ml_monitor_window_trades: v })} />
      <Num label="Check Interval (s)" desc="ML_MONITOR_CHECK_INTERVAL" value={cfg.ml_monitor_check_interval} min={30} onChange={(v) => set({ ml_monitor_check_interval: v })} />
      <Num label="Rollback Threshold" desc="ML_MONITOR_ROLLBACK_THRESH" value={cfg.ml_monitor_rollback_thresh} step={0.01} min={0} max={1} onChange={(v) => set({ ml_monitor_rollback_thresh: v })} />
      <Num label="Min Trades Before Eval" desc="ML_MONITOR_MIN_TRADES" value={cfg.ml_monitor_min_trades} min={1} onChange={(v) => set({ ml_monitor_min_trades: v })} />
    </Card>
    <Card>
      <SectionHeader icon="📉" title="Sharpe Circuit Breaker" desc="ml/sharpe_circuit_breaker.py" />
      <Num label="Window Trades" desc="SHARPE_CB_WINDOW_TRADES" value={cfg.sharpe_cb_window_trades} min={10} onChange={(v) => set({ sharpe_cb_window_trades: v })} />
      <Num label="Min Sharpe Ratio" desc="SHARPE_CB_MIN_SHARPE" value={cfg.sharpe_cb_min_sharpe} step={0.1} onChange={(v) => set({ sharpe_cb_min_sharpe: v })} />
      <Num label="Consecutive Windows to Trip" desc="SHARPE_CB_CONSECUTIVE" value={cfg.sharpe_cb_consecutive} min={1} onChange={(v) => set({ sharpe_cb_consecutive: v })} />
      <Num label="Eval Interval (s)" desc="SHARPE_CB_EVAL_INTERVAL_S" value={cfg.sharpe_cb_eval_interval_s} min={10} onChange={(v) => set({ sharpe_cb_eval_interval_s: v })} />
      <Num label="Min Trades Before Eval" desc="SHARPE_CB_MIN_TRADES" value={cfg.sharpe_cb_min_trades} min={1} onChange={(v) => set({ sharpe_cb_min_trades: v })} />
      <Num label="Reset After (s)" desc="SHARPE_CB_RESET_AFTER_S" value={cfg.sharpe_cb_reset_after_s} min={60} onChange={(v) => set({ sharpe_cb_reset_after_s: v })} />
    </Card>
  </>
);


const RiskTab: React.FC<{ cfg: PlatformConfig; set: (p: Partial<PlatformConfig>) => void }> = ({ cfg, set }) => (
  <>
    <Card>
      <SectionHeader icon="⚖️" title="Risk Manager" desc="risk/manager.py" />
      <Num label="Account Equity (USD)" desc="RISK_ACCOUNT_EQUITY" value={cfg.risk_account_equity} step={1000} min={0} onChange={(v) => set({ risk_account_equity: v })} />
      <Num label="Max Position Size (%)" desc="RISK_MAX_POSITION_PCT" value={cfg.risk_max_position_pct} step={0.001} min={0} max={1} onChange={(v) => set({ risk_max_position_pct: v })} />
      <Num label="Min Position Size (%)" desc="RISK_MIN_POSITION_PCT" value={cfg.risk_min_position_pct} step={0.0001} min={0} onChange={(v) => set({ risk_min_position_pct: v })} />
      <Num label="Kelly Fraction" desc="RISK_KELLY_FRACTION" value={cfg.risk_kelly_fraction} step={0.01} min={0} max={1} onChange={(v) => set({ risk_kelly_fraction: v })} />
      <Num label="Max Daily Loss (%)" desc="RISK_MAX_DAILY_LOSS_PCT" value={cfg.risk_max_daily_loss_pct} step={0.001} min={0} max={1} onChange={(v) => set({ risk_max_daily_loss_pct: v })} />
      <Num label="Max Drawdown (%)" desc="RISK_MAX_DRAWDOWN_PCT" value={cfg.risk_max_drawdown_pct} step={0.001} min={0} max={1} onChange={(v) => set({ risk_max_drawdown_pct: v })} />
      <Num label="Max Open Positions" desc="RISK_MAX_OPEN_POSITIONS" value={cfg.risk_max_open_positions} min={1} onChange={(v) => set({ risk_max_open_positions: v })} />
      <Num label="Min Data Quality" desc="RISK_MIN_DATA_QUALITY" value={cfg.risk_min_data_quality} step={0.01} min={0} max={1} onChange={(v) => set({ risk_min_data_quality: v })} />
      <Num label="Sentiment Size Scale" desc="RISK_SENT_SIZE_SCALE" value={cfg.risk_sent_size_scale} step={0.01} min={0} max={1} onChange={(v) => set({ risk_sent_size_scale: v })} />
      <Num label="Impact Size Scale" desc="RISK_IMPACT_SIZE_SCALE" value={cfg.risk_impact_size_scale} step={0.01} min={0} max={1} onChange={(v) => set({ risk_impact_size_scale: v })} />
      <Num label="Drawdown Size Scale" desc="RISK_DD_SIZE_SCALE" value={cfg.risk_dd_size_scale} step={0.01} min={0} max={1} onChange={(v) => set({ risk_dd_size_scale: v })} />
      <Num label="VaR Window (bars)" desc="RISK_VAR_WINDOW" value={cfg.risk_var_window} min={10} onChange={(v) => set({ risk_var_window: v })} />
      <Num label="VaR Confidence" desc="RISK_VAR_CONFIDENCE" value={cfg.risk_var_confidence} step={0.01} min={0.5} max={0.999} onChange={(v) => set({ risk_var_confidence: v })} />
      <Num label="CVaR Daily Limit" desc="RISK_CVAR_DAILY_LIMIT" value={cfg.risk_cvar_daily_limit} step={0.001} min={0} max={1} onChange={(v) => set({ risk_cvar_daily_limit: v })} />
      <Num label="Factor VaR Limit" desc="RISK_FACTOR_VAR_LIMIT" value={cfg.risk_factor_var_limit} step={0.01} min={0} max={1} onChange={(v) => set({ risk_factor_var_limit: v })} />
      <Sel label="Drawdown Mode" desc="RISK_DRAWDOWN_MODE" value={cfg.risk_drawdown_mode}
        options={[{ value: 'equity', label: 'Equity' }, { value: 'balance', label: 'Balance' }]}
        onChange={(v) => set({ risk_drawdown_mode: v })} />
      <Num label="Alert at % of Limit" desc="RISK_ALERT_PCT_OF_LIMIT" value={cfg.risk_alert_pct_of_limit} step={0.01} min={0} max={1} onChange={(v) => set({ risk_alert_pct_of_limit: v })} />
      <Num label="Max Risk Per Trade (%)" desc="MAX_RISK_PCT_PER_TRADE" value={cfg.max_risk_pct_per_trade} step={0.001} min={0} max={1} onChange={(v) => set({ max_risk_pct_per_trade: v })} />
    </Card>
    <Card>
      <SectionHeader icon="🚧" title="Gatekeeper" desc="risk/gatekeeper.py" />
      <Num label="Min Signal Confidence" desc="GATEKEEPER_MIN_CONF" value={cfg.gatekeeper_min_conf} step={0.01} min={0} max={1} onChange={(v) => set({ gatekeeper_min_conf: v })} />
      <Num label="Max Daily Trades" desc="GATEKEEPER_MAX_DAILY_TRADES" value={cfg.gatekeeper_max_daily_trades} min={1} onChange={(v) => set({ gatekeeper_max_daily_trades: v })} />
      <Num label="Pause After Breach (s)" desc="GATEKEEPER_PAUSE_S" value={cfg.gatekeeper_pause_s} min={0} onChange={(v) => set({ gatekeeper_pause_s: v })} />
      <Num label="Min Data Quality" desc="GATEKEEPER_MIN_DATA_QUALITY" value={cfg.gatekeeper_min_data_quality} step={0.01} min={0} max={1} onChange={(v) => set({ gatekeeper_min_data_quality: v })} />
      <Num label="Max Spread (USD)" desc="GATEKEEPER_MAX_SPREAD_USD" value={cfg.gatekeeper_max_spread_usd} step={0.1} min={0} onChange={(v) => set({ gatekeeper_max_spread_usd: v })} />
      <Num label="Sentiment Blackout Threshold" desc="GATEKEEPER_SENT_BLACKOUT" value={cfg.gatekeeper_sent_blackout} step={0.01} min={0} max={1} onChange={(v) => set({ gatekeeper_sent_blackout: v })} />
      <Num label="Impact Blackout Threshold" desc="GATEKEEPER_IMPACT_BLACKOUT" value={cfg.gatekeeper_impact_blackout} step={0.01} min={0} max={1} onChange={(v) => set({ gatekeeper_impact_blackout: v })} />
      <Num label="News Blackout Window (minutes)" desc="NEWS_BLACKOUT_MINUTES" value={cfg.news_blackout_minutes} min={0} onChange={(v) => set({ news_blackout_minutes: v })} />
    </Card>
    <Card>
      <SectionHeader icon="🔍" title="Intra-Trade Monitor" desc="risk/intra_trade_monitor.py" />
      <Num label="Min Data Quality" desc="INTRA_MIN_DATA_QUALITY" value={cfg.intra_min_data_quality} step={0.01} min={0} max={1} onChange={(v) => set({ intra_min_data_quality: v })} />
      <Num label="CVaR Confidence" desc="INTRA_CVAR_CONFIDENCE" value={cfg.intra_cvar_confidence} step={0.01} min={0.5} max={0.999} onChange={(v) => set({ intra_cvar_confidence: v })} />
      <Num label="Returns Window" desc="INTRA_RETURNS_WINDOW" value={cfg.intra_returns_window} min={10} onChange={(v) => set({ intra_returns_window: v })} />
      <Num label="Vol Baseline Window" desc="INTRA_VOL_BASELINE_WINDOW" value={cfg.intra_vol_baseline_window} min={10} onChange={(v) => set({ intra_vol_baseline_window: v })} />
    </Card>
    <Card>
      <SectionHeader icon="📜" title="FIA Compliance" desc="risk/gatekeeper.py — FIA limits" />
      <Num label="Max Order Size (lots)" desc="FIA_MAX_ORDER_SIZE" value={cfg.fia_max_order_size} min={0} onChange={(v) => set({ fia_max_order_size: v })} />
      <Num label="Max Intraday Position (lots)" desc="FIA_MAX_INTRADAY_POSITION" value={cfg.fia_max_intraday_position} min={0} onChange={(v) => set({ fia_max_intraday_position: v })} />
      <Num label="Price Tolerance" desc="FIA_PRICE_TOLERANCE" value={cfg.fia_price_tolerance} step={0.001} min={0} onChange={(v) => set({ fia_price_tolerance: v })} />
      <Num label="Daily Loss Limit (%)" desc="FIA_DAILY_LOSS_LIMIT" value={cfg.fia_daily_loss_limit} step={0.001} min={0} max={1} onChange={(v) => set({ fia_daily_loss_limit: v })} />
      <Num label="Max Messages Per Second" desc="FIA_MAX_MSG_PER_SEC" value={cfg.fia_max_msg_per_sec} min={1} onChange={(v) => set({ fia_max_msg_per_sec: v })} />
    </Card>
  </>
);


const ExecutionTab: React.FC<{ cfg: PlatformConfig; set: (p: Partial<PlatformConfig>) => void }> = ({ cfg, set }) => (
  <>
    <Card>
      <SectionHeader icon="⚡" title="HOPEFX Engine" desc="execution/hopefx_engine.py" />
      <Num label="Min Signal Confidence" desc="ENGINE_MIN_CONFIDENCE" value={cfg.engine_min_confidence} step={0.01} min={0} max={1} onChange={(v) => set({ engine_min_confidence: v })} />
      <Num label="Min Data Quality" desc="ENGINE_MIN_DATA_QUALITY" value={cfg.engine_min_data_quality} step={0.01} min={0} max={1} onChange={(v) => set({ engine_min_data_quality: v })} />
      <Num label="Max Spread (USD)" desc="ENGINE_MAX_SPREAD_USD" value={cfg.engine_max_spread_usd} step={0.1} min={0} onChange={(v) => set({ engine_max_spread_usd: v })} />
      <Num label="Tick Loop Hz" desc="ENGINE_TICK_LOOP_HZ" value={cfg.engine_tick_loop_hz} step={0.1} min={0.1} onChange={(v) => set({ engine_tick_loop_hz: v })} />
      <Num label="Max Position (USD)" desc="ENGINE_MAX_POSITION_USD" value={cfg.engine_max_position_usd} step={1000} min={0} onChange={(v) => set({ engine_max_position_usd: v })} />
      <Num label="Signal Cooldown (s)" desc="ENGINE_SIGNAL_COOLDOWN_S" value={cfg.engine_signal_cooldown_s} step={1} min={0} onChange={(v) => set({ engine_signal_cooldown_s: v })} />
      <Num label="Stale Tick Threshold (s)" desc="ENGINE_STALE_TICK_S" value={cfg.engine_stale_tick_s} step={0.5} min={0} onChange={(v) => set({ engine_stale_tick_s: v })} />
      <Num label="Initial Equity (USD)" desc="ENGINE_INITIAL_EQUITY" value={cfg.engine_initial_equity} step={1000} min={0} onChange={(v) => set({ engine_initial_equity: v })} />
    </Card>
    <Card>
      <SectionHeader icon="🔌" title="Broker Circuit Breaker" desc="execution/broker_circuit_breaker.py" />
      <Num label="Max Failures Before Open" desc="BROKER_CB_MAX_FAILURES" value={cfg.broker_cb_max_failures} min={1} onChange={(v) => set({ broker_cb_max_failures: v })} />
      <Num label="Reset Timeout (s)" desc="BROKER_CB_RESET_TIMEOUT" value={cfg.broker_cb_reset_timeout} min={1} onChange={(v) => set({ broker_cb_reset_timeout: v })} />
      <Num label="Half-Open Max Probes" desc="BROKER_CB_HALF_OPEN_MAX" value={cfg.broker_cb_half_open_max} min={1} onChange={(v) => set({ broker_cb_half_open_max: v })} />
    </Card>
    <Card>
      <SectionHeader icon="🔀" title="Order Algorithms (TWAP / VWAP)" desc="execution/order_algorithms.py + execution/algo_orders.py" />
      <Num label="TWAP Default Slices" desc="TWAP_DEFAULT_SLICES" value={cfg.twap_default_slices} min={2} onChange={(v) => set({ twap_default_slices: v })} />
      <Num label="TWAP Default Duration (s)" desc="TWAP_DEFAULT_SECS" value={cfg.twap_default_secs} min={1} onChange={(v) => set({ twap_default_secs: v })} />
      <Num label="VWAP Slices" desc="VWAP_SLICES" value={cfg.vwap_slices} min={2} onChange={(v) => set({ vwap_slices: v })} />
      <Num label="Partial Fill Timeout (s)" desc="PARTIAL_FILL_TIMEOUT" value={cfg.partial_fill_timeout} min={1} onChange={(v) => set({ partial_fill_timeout: v })} />
      <Num label="Min Slice Lots" desc="MIN_SLICE_LOTS" value={cfg.min_slice_lots} step={0.001} min={0.001} onChange={(v) => set({ min_slice_lots: v })} />
      <Num label="Algo Min Child Size" desc="ALGO_MIN_CHILD_SIZE" value={cfg.algo_min_child_size} step={0.001} min={0} onChange={(v) => set({ algo_min_child_size: v })} />
      <Num label="Algo Max Participation" desc="ALGO_MAX_PARTICIPATION" value={cfg.algo_max_participation} step={0.01} min={0} max={1} onChange={(v) => set({ algo_max_participation: v })} />
      <Num label="TWAP Jitter" desc="ALGO_TWAP_JITTER" value={cfg.algo_twap_jitter} step={0.01} min={0} max={1} onChange={(v) => set({ algo_twap_jitter: v })} />
      <Sel label="VWAP Volume Profile" desc="ALGO_VWAP_PROFILE" value={cfg.algo_vwap_profile}
        options={['u_shaped','flat','front_loaded','back_loaded'].map((v) => ({ value: v, label: v }))}
        onChange={(v) => set({ algo_vwap_profile: v })} />
      <Num label="Iceberg Refill %" desc="ALGO_ICEBERG_REFILL_PCT" value={cfg.algo_iceberg_refill_pct} step={0.01} min={0} max={1} onChange={(v) => set({ algo_iceberg_refill_pct: v })} />
      <Num label="Large Order Threshold (lots)" desc="ALGO_LARGE_ORDER_THRESHOLD" value={cfg.algo_large_order_threshold} step={0.1} min={0} onChange={(v) => set({ algo_large_order_threshold: v })} />
      <Num label="Iceberg Threshold (lots)" desc="ALGO_ICEBERG_THRESHOLD" value={cfg.algo_iceberg_threshold} step={1} min={0} onChange={(v) => set({ algo_iceberg_threshold: v })} />
      <Num label="Default TWAP Duration (s)" desc="ALGO_DEFAULT_TWAP_DURATION" value={cfg.algo_default_twap_duration} min={1} onChange={(v) => set({ algo_default_twap_duration: v })} />
      <Num label="Default TWAP Slices" desc="ALGO_DEFAULT_TWAP_SLICES" value={cfg.algo_default_twap_slices} min={2} onChange={(v) => set({ algo_default_twap_slices: v })} />
      <Num label="Default Iceberg Peak (lots)" desc="ALGO_DEFAULT_ICEBERG_PEAK" value={cfg.algo_default_iceberg_peak} step={0.1} min={0} onChange={(v) => set({ algo_default_iceberg_peak: v })} />
    </Card>
    <Card>
      <SectionHeader icon="📊" title="Market Impact (Almgren-Chriss)" desc="execution/market_impact.py" />
      <Num label="Eta (temporary impact)" desc="AC_ETA" value={cfg.ac_eta} step={0.01} min={0} onChange={(v) => set({ ac_eta: v })} />
      <Num label="Gamma (permanent impact)" desc="AC_GAMMA" value={cfg.ac_gamma} step={0.01} min={0} onChange={(v) => set({ ac_gamma: v })} />
      <Num label="Max Participation Rate" desc="AC_MAX_PARTICIPATION" value={cfg.ac_max_participation} step={0.01} min={0} max={1} onChange={(v) => set({ ac_max_participation: v })} />
      <Num label="Min Spread (bps)" desc="AC_MIN_SPREAD_BPS" value={cfg.ac_min_spread_bps} step={0.1} min={0} onChange={(v) => set({ ac_min_spread_bps: v })} />
      <Num label="Queue Factor" desc="AC_QUEUE_FACTOR" value={cfg.ac_queue_factor} step={0.01} min={0} max={1} onChange={(v) => set({ ac_queue_factor: v })} />
    </Card>
    <Card>
      <SectionHeader icon="📏" title="Spread Monitor" desc="execution/spread_monitor.py" />
      <Num label="Spike Multiplier" desc="SPREAD_SPIKE_MULTIPLIER" value={cfg.spread_spike_multiplier} step={0.1} min={1} onChange={(v) => set({ spread_spike_multiplier: v })} />
      <Num label="Baseline Window (ticks)" desc="SPREAD_BASELINE_WINDOW" value={cfg.spread_baseline_window} min={5} onChange={(v) => set({ spread_baseline_window: v })} />
      <Num label="Min Ticks Before Alert" desc="SPREAD_MIN_TICKS" value={cfg.spread_min_ticks} min={1} onChange={(v) => set({ spread_min_ticks: v })} />
      <Num label="Absolute Limit (USD)" desc="SPREAD_ABS_LIMIT_USD" value={cfg.spread_abs_limit_usd} step={0.1} min={0} onChange={(v) => set({ spread_abs_limit_usd: v })} />
    </Card>
    <Card>
      <SectionHeader icon="🎯" title="SL/TP Monitor" desc="execution/sl_tp_monitor.py" />
      <Num label="Poll Interval (ms)" desc="SLTP_POLL_INTERVAL_MS" value={cfg.sltp_poll_interval_ms} min={50} onChange={(v) => set({ sltp_poll_interval_ms: v })} />
      <Num label="Max Retries" desc="SLTP_MAX_RETRIES" value={cfg.sltp_max_retries} min={1} onChange={(v) => set({ sltp_max_retries: v })} />
      <Num label="Retry Delay (s)" desc="SLTP_RETRY_DELAY_S" value={cfg.sltp_retry_delay_s} step={0.1} min={0} onChange={(v) => set({ sltp_retry_delay_s: v })} />
    </Card>
    <Card>
      <SectionHeader icon="📈" title="TCA Recorder" desc="execution/tca_recorder.py" />
      <Num label="Alert Threshold (bps)" desc="TCA_ALERT_THRESHOLD_BPS" value={cfg.tca_alert_threshold_bps} step={0.1} min={0} onChange={(v) => set({ tca_alert_threshold_bps: v })} />
      <Num label="Alert Window (trades)" desc="TCA_ALERT_WINDOW" value={cfg.tca_alert_window} min={1} onChange={(v) => set({ tca_alert_window: v })} />
      <Tog id="tca_redis" label="Persist to Redis" desc="TCA_PERSIST_REDIS" checked={cfg.tca_persist_redis} onChange={(v) => set({ tca_persist_redis: v })} />
      <Tog id="tca_db" label="Persist to Database" desc="TCA_PERSIST_DB" checked={cfg.tca_persist_db} onChange={(v) => set({ tca_persist_db: v })} />
      <Num label="Max In-Memory Records" desc="TCA_MAX_MEMORY_RECORDS" value={cfg.tca_max_memory_records} min={100} onChange={(v) => set({ tca_max_memory_records: v })} />
    </Card>
  </>
);


const BrokersTab: React.FC<{ cfg: PlatformConfig; set: (p: Partial<PlatformConfig>) => void }> = ({ cfg, set }) => (
  <>
    <Card>
      <SectionHeader icon="📡" title="FIX Router" desc="execution/fix_router.py" />
      <Txt label="FIX Host" desc="FIX_HOST" value={cfg.fix_host} onChange={(v) => set({ fix_host: v })} />
      <Num label="FIX Port" desc="FIX_PORT" value={cfg.fix_port} min={1} max={65535} onChange={(v) => set({ fix_port: v })} />
      <Txt label="Sender Comp ID" desc="FIX_SENDER_COMP_ID" value={cfg.fix_sender_comp_id} onChange={(v) => set({ fix_sender_comp_id: v })} />
      <Txt label="Target Comp ID" desc="FIX_TARGET_COMP_ID" value={cfg.fix_target_comp_id} onChange={(v) => set({ fix_target_comp_id: v })} />
      <Num label="Latency Warn (ms)" desc="FIX_LATENCY_WARN_MS" value={cfg.fix_latency_warn_ms} step={1} min={0} onChange={(v) => set({ fix_latency_warn_ms: v })} />
      <Num label="Default Units (lots)" desc="FIX_DEFAULT_UNITS" value={cfg.fix_default_units} step={100} min={0} onChange={(v) => set({ fix_default_units: v })} />
    </Card>
    <Card>
      <SectionHeader icon="🏦" title="OANDA" desc="brokers/oanda.py" />
      <Sel label="Environment" desc="OANDA_ENVIRONMENT" value={cfg.oanda_environment}
        options={[{ value: 'practice', label: 'Practice (fxpractice)' }, { value: 'live', label: 'Live (fxtrade)' }]}
        onChange={(v) => set({ oanda_environment: v })} />
      <Num label="Request Timeout (s)" desc="OANDA_TIMEOUT_S" value={cfg.oanda_timeout_s} step={0.5} min={1} onChange={(v) => set({ oanda_timeout_s: v })} />
      <Num label="Max Retries" desc="OANDA_MAX_RETRIES" value={cfg.oanda_max_retries} min={0} onChange={(v) => set({ oanda_max_retries: v })} />
      <Num label="Retry Backoff (s)" desc="OANDA_RETRY_BACKOFF_S" value={cfg.oanda_retry_backoff_s} step={0.1} min={0} onChange={(v) => set({ oanda_retry_backoff_s: v })} />
    </Card>
    <Card>
      <SectionHeader icon="🏛️" title="Interactive Brokers (IBKR)" desc="brokers/ibkr.py" />
      <Txt label="TWS Host" desc="IBKR_HOST" value={cfg.ibkr_host} onChange={(v) => set({ ibkr_host: v })} />
      <Num label="Paper Port" desc="IBKR_PORT_PAPER" value={cfg.ibkr_port_paper} min={1} max={65535} onChange={(v) => set({ ibkr_port_paper: v })} />
      <Num label="Live Port" desc="IBKR_PORT_LIVE" value={cfg.ibkr_port_live} min={1} max={65535} onChange={(v) => set({ ibkr_port_live: v })} />
      <Num label="Client ID" desc="IBKR_CLIENT_ID" value={cfg.ibkr_client_id} min={0} onChange={(v) => set({ ibkr_client_id: v })} />
      <Num label="Connect Timeout (s)" desc="IBKR_CONNECT_TIMEOUT_S" value={cfg.ibkr_connect_timeout_s} step={1} min={1} onChange={(v) => set({ ibkr_connect_timeout_s: v })} />
      <Num label="Order Timeout (s)" desc="IBKR_ORDER_TIMEOUT_S" value={cfg.ibkr_order_timeout_s} step={1} min={1} onChange={(v) => set({ ibkr_order_timeout_s: v })} />
      <Num label="Reconnect Delay (s)" desc="IBKR_RECONNECT_DELAY_S" value={cfg.ibkr_reconnect_delay_s} step={0.5} min={0} onChange={(v) => set({ ibkr_reconnect_delay_s: v })} />
      <Num label="Max Reconnects" desc="IBKR_MAX_RECONNECTS" value={cfg.ibkr_max_reconnects} min={0} onChange={(v) => set({ ibkr_max_reconnects: v })} />
    </Card>
    <Card>
      <SectionHeader icon="🏗️" title="CME / COMEX" desc="brokers/cme_comex.py" />
      <Tog id="cme_en" label="Enable CME Connector" desc="CME_ENABLED" checked={cfg.cme_enabled} onChange={(v) => set({ cme_enabled: v })} />
      <Txt label="FIX Host" desc="CME_FIX_HOST" value={cfg.cme_fix_host} onChange={(v) => set({ cme_fix_host: v })} />
      <Num label="FIX Port" desc="CME_FIX_PORT" value={cfg.cme_fix_port} min={1} max={65535} onChange={(v) => set({ cme_fix_port: v })} />
      <Txt label="Sender ID" desc="CME_FIX_SENDER_ID" value={cfg.cme_fix_sender_id} onChange={(v) => set({ cme_fix_sender_id: v })} />
      <Txt label="Target ID" desc="CME_FIX_TARGET_ID" value={cfg.cme_fix_target_id} onChange={(v) => set({ cme_fix_target_id: v })} />
      <Num label="Default Contracts" desc="CME_DEFAULT_CONTRACTS" value={cfg.cme_default_contracts} min={1} onChange={(v) => set({ cme_default_contracts: v })} />
      <Num label="Latency Warn (ms)" desc="CME_LATENCY_WARN_MS" value={cfg.cme_latency_warn_ms} step={1} min={0} onChange={(v) => set({ cme_latency_warn_ms: v })} />
      <Tog id="cme_ibkr_fb" label="IBKR Fallback" desc="CME_IBKR_FALLBACK" checked={cfg.cme_ibkr_fallback} onChange={(v) => set({ cme_ibkr_fallback: v })} />
      <Tog id="cme_paper_fb" label="Paper Fallback" desc="CME_PAPER_FALLBACK" checked={cfg.cme_paper_fallback} onChange={(v) => set({ cme_paper_fallback: v })} />
    </Card>
    <Card>
      <SectionHeader icon="⚙️" title="C++ Low-Latency Shim" desc="brokers/cpp_shim_connector.py" />
      <Tog id="cpp_en" label="Enable C++ Shim" desc="CPP_SHIM_ENABLED" checked={cfg.cpp_shim_enabled} onChange={(v) => set({ cpp_shim_enabled: v })} />
      <Txt label="ZMQ Command Address" desc="CPP_SHIM_ZMQ_CMD_ADDR" value={cfg.cpp_shim_zmq_cmd_addr} onChange={(v) => set({ cpp_shim_zmq_cmd_addr: v })} />
      <Txt label="ZMQ Response Address" desc="CPP_SHIM_ZMQ_RESP_ADDR" value={cfg.cpp_shim_zmq_resp_addr} onChange={(v) => set({ cpp_shim_zmq_resp_addr: v })} />
      <Num label="Timeout (ms)" desc="CPP_SHIM_TIMEOUT_MS" value={cfg.cpp_shim_timeout_ms} min={100} onChange={(v) => set({ cpp_shim_timeout_ms: v })} />
      <Num label="Latency Warn (µs)" desc="CPP_SHIM_LATENCY_WARN_US" value={cfg.cpp_shim_latency_warn_us} min={100} onChange={(v) => set({ cpp_shim_latency_warn_us: v })} />
    </Card>
  </>
);

const RateLimitTab: React.FC<{ cfg: PlatformConfig; set: (p: Partial<PlatformConfig>) => void }> = ({ cfg, set }) => (
  <Card>
    <SectionHeader icon="🚦" title="Per-Endpoint Rate Limits" desc="rate_limiting_configuration.py — format: N per minute/hour" />
    <Txt label="Global Default" desc="RATE_GLOBAL_DEFAULT" value={cfg.rate_global_default} placeholder="120 per minute" onChange={(v) => set({ rate_global_default: v })} />
    <Txt label="Auth (login/token)" desc="RATE_AUTH" value={cfg.rate_auth} placeholder="10 per minute" onChange={(v) => set({ rate_auth: v })} />
    <Txt label="Trading (orders)" desc="RATE_TRADING" value={cfg.rate_trading} placeholder="60 per minute" onChange={(v) => set({ rate_trading: v })} />
    <Txt label="Market Data" desc="RATE_MARKET_DATA" value={cfg.rate_market_data} placeholder="300 per minute" onChange={(v) => set({ rate_market_data: v })} />
    <Txt label="Admin Panel" desc="RATE_ADMIN" value={cfg.rate_admin} placeholder="30 per minute" onChange={(v) => set({ rate_admin: v })} />
    <Txt label="WebSocket Upgrades" desc="RATE_WEBSOCKET" value={cfg.rate_websocket} placeholder="20 per minute" onChange={(v) => set({ rate_websocket: v })} />
    <Txt label="Backtest Submission" desc="RATE_BACKTEST" value={cfg.rate_backtest} placeholder="10 per minute" onChange={(v) => set({ rate_backtest: v })} />
    <Txt label="Withdrawals" desc="RATE_WITHDRAWAL" value={cfg.rate_withdrawal} placeholder="5 per minute" onChange={(v) => set({ rate_withdrawal: v })} />
  </Card>
);

const NotifyTab: React.FC<{ cfg: PlatformConfig; set: (p: Partial<PlatformConfig>) => void }> = ({ cfg, set }) => (
  <>
    <Card>
      <SectionHeader icon="💓" title="Heartbeat Monitor" desc="notifications/heartbeat.py" />
      <Tog id="hb_en" label="Enable Heartbeat" desc="HEARTBEAT_ENABLED" checked={cfg.heartbeat_enabled} onChange={(v) => set({ heartbeat_enabled: v })} />
      <Num label="Interval (hours)" desc="HEARTBEAT_INTERVAL_HOURS" value={cfg.heartbeat_interval_hours} step={0.5} min={0.1} onChange={(v) => set({ heartbeat_interval_hours: v })} />
    </Card>
    <Card>
      <SectionHeader icon="🎮" title="Discord" desc="notifications/discord_bot.py" />
      <Num label="Signal Cooldown (s)" desc="DISCORD_SIGNAL_COOLDOWN_SECONDS" value={cfg.discord_signal_cooldown_seconds} min={0} onChange={(v) => set({ discord_signal_cooldown_seconds: v })} />
      <Txt label="Bot Username" desc="DISCORD_BOT_USERNAME" value={cfg.discord_bot_username} onChange={(v) => set({ discord_bot_username: v })} />
    </Card>
  </>
);

// ── Decision Engine Tab ───────────────────────────────────────────────────────

const DecisionTab: React.FC<{ cfg: PlatformConfig; set: (p: Partial<PlatformConfig>) => void }> = ({ cfg, set }) => (
  <>
    <Card>
      <SectionHeader icon="🎯" title="Decision Engine" desc="core/decision/HOPEFXDecisionEngine.py — master signal routing brain" />
      <Tog id="de_en" label="Enable Decision Engine" desc="DECISION_ENGINE_ENABLED" checked={cfg.decision_engine_enabled} onChange={(v) => set({ decision_engine_enabled: v })} />
      <Num label="Min Signal Confidence" desc="DECISION_ENGINE_MIN_CONFIDENCE" value={cfg.decision_engine_min_confidence} step={0.01} min={0} max={1} onChange={(v) => set({ decision_engine_min_confidence: v })} />
      <Num label="Max Concurrent Positions" desc="DECISION_ENGINE_MAX_POSITIONS" value={cfg.decision_engine_max_positions} min={1} max={50} onChange={(v) => set({ decision_engine_max_positions: v })} />
      <Num label="Signal Cooldown (s)" desc="DECISION_ENGINE_COOLDOWN_S" value={cfg.decision_engine_cooldown_s} step={1} min={0} onChange={(v) => set({ decision_engine_cooldown_s: v })} />
      <Divider />
      <SectionHeader icon="🔀" title="Feature Gating" desc="Which data sources feed the decision" />
      <Tog id="de_regime" label="Use Regime Filter" desc="Blocks signals in unfavourable market regimes" checked={cfg.decision_engine_use_regime} onChange={(v) => set({ decision_engine_use_regime: v })} />
      <Tog id="de_sent" label="Use Sentiment Scaling" desc="Scales position size by news sentiment score" checked={cfg.decision_engine_use_sentiment} onChange={(v) => set({ decision_engine_use_sentiment: v })} />
      <Tog id="de_macro" label="Use Macro Impact" desc="Blocks/scales on macro event impact score" checked={cfg.decision_engine_use_macro} onChange={(v) => set({ decision_engine_use_macro: v })} />
    </Card>
    <Card>
      <SectionHeader icon="🔀" title="Smart Router" desc="execution/smart_router.py — broker routing and spread gate" />
      <Num label="Max Spread (bps)" desc="ROUTER_MAX_SPREAD_BPS" value={cfg.router_max_spread_bps} step={0.5} min={0} onChange={(v) => set({ router_max_spread_bps: v })} />
      <Sel label="Primary Broker" desc="BROKER_PRIMARY" value={cfg.router_primary_broker}
        options={['oanda','ibkr','cme','cpp_shim','paper'].map((v) => ({ value: v, label: v.toUpperCase() }))}
        onChange={(v) => set({ router_primary_broker: v })} />
      <Sel label="Secondary / Fallback Broker" desc="BROKER_SECONDARY" value={cfg.router_secondary_broker}
        options={['paper','oanda','ibkr','cme'].map((v) => ({ value: v, label: v.toUpperCase() }))}
        onChange={(v) => set({ router_secondary_broker: v })} />
    </Card>
    <Card>
      <SectionHeader icon="📡" title="Online Learner" desc="ml/online_learner.py — continuous model adaptation" />
      <Tog id="ol_en" label="Enable Online Learning" desc="ONLINE_LEARNER_ENABLED — adapts model weights on live fills" checked={cfg.online_learner_enabled} onChange={(v) => set({ online_learner_enabled: v })} />
      <Num label="Learning Rate" desc="ONLINE_LEARNER_LR" value={cfg.online_learner_lr} step={0.0001} min={0.00001} max={0.1} onChange={(v) => set({ online_learner_lr: v })} />
      <Num label="Batch Size" desc="ONLINE_LEARNER_BATCH_SIZE" value={cfg.online_learner_batch_size} min={1} max={512} onChange={(v) => set({ online_learner_batch_size: v })} />
      <Num label="Update Interval (s)" desc="ONLINE_LEARNER_UPDATE_INTERVAL_S" value={cfg.online_learner_update_interval_s} min={10} onChange={(v) => set({ online_learner_update_interval_s: v })} />
      <Num label="Max Buffer Size" desc="ONLINE_LEARNER_MAX_BUFFER" value={cfg.online_learner_max_buffer} min={100} onChange={(v) => set({ online_learner_max_buffer: v })} />
    </Card>
    <Card>
      <SectionHeader icon="📉" title="Drift Monitor" desc="ml/drift_monitor.py — detects model distribution shift" />
      <Tog id="dm_en" label="Enable Drift Monitor" desc="DRIFT_MONITOR_ENABLED" checked={cfg.drift_monitor_enabled} onChange={(v) => set({ drift_monitor_enabled: v })} />
      <Num label="Detection Window (samples)" desc="DRIFT_MONITOR_WINDOW" value={cfg.drift_monitor_window} min={10} onChange={(v) => set({ drift_monitor_window: v })} />
      <Num label="Drift Threshold" desc="DRIFT_MONITOR_THRESHOLD — PSI/KL divergence threshold" value={cfg.drift_monitor_threshold} step={0.005} min={0.001} max={1} onChange={(v) => set({ drift_monitor_threshold: v })} />
      <Num label="Check Interval (s)" desc="DRIFT_MONITOR_CHECK_INTERVAL_S" value={cfg.drift_monitor_check_interval_s} min={30} onChange={(v) => set({ drift_monitor_check_interval_s: v })} />
      <Tog id="dm_retrain" label="Auto-Retrain on Drift" desc="Triggers full retrain when drift exceeds threshold" checked={cfg.drift_monitor_auto_retrain} onChange={(v) => set({ drift_monitor_auto_retrain: v })} />
    </Card>
  </>
);

// ── Paper Trading Tab ─────────────────────────────────────────────────────────

const PaperTradingTab: React.FC<{ cfg: PlatformConfig; set: (p: Partial<PlatformConfig>) => void }> = ({ cfg, set }) => (
  <>
    <Card>
      <SectionHeader icon="📄" title="Paper Trading Slippage Model" desc="brokers/paper_trading.py — realistic fill simulation" />
      <Sel label="Slippage Model" desc="PAPER_SLIPPAGE_MODEL" value={cfg.paper_slippage_model}
        options={[
          { value: 'fixed', label: 'Fixed (constant slippage %)' },
          { value: 'market_impact', label: 'Market Impact (size-dependent)' },
          { value: 'random', label: 'Random (Gaussian noise)' },
          { value: 'zero', label: 'Zero (no slippage)' },
        ]}
        onChange={(v) => set({ paper_slippage_model: v })} />
      <Num label="Fixed Slippage (%)" desc="PAPER_FIXED_SLIPPAGE_PCT — used when model=fixed" value={cfg.paper_fixed_slippage_pct} step={0.00001} min={0} max={0.01} onChange={(v) => set({ paper_fixed_slippage_pct: v })} />
      <Num label="Market Impact Factor" desc="PAPER_IMPACT_FACTOR — scales impact with order size" value={cfg.paper_impact_factor} step={0.01} min={0} max={1} onChange={(v) => set({ paper_impact_factor: v })} />
      <Num label="Noise Sigma (%)" desc="PAPER_NOISE_SIGMA_PCT — Gaussian noise std dev" value={cfg.paper_noise_sigma_pct} step={0.00001} min={0} max={0.01} onChange={(v) => set({ paper_noise_sigma_pct: v })} />
      <Num label="Fallback Spread (%)" desc="PAPER_FALLBACK_SPREAD_PCT — used when no live spread available" value={cfg.paper_fallback_spread_pct} step={0.00001} min={0} max={0.01} onChange={(v) => set({ paper_fallback_spread_pct: v })} />
    </Card>
  </>
);

const KillSwitchTab: React.FC<{ cfg: PlatformConfig; set: (p: Partial<PlatformConfig>) => void }> = ({ cfg, set }) => (
  <Card danger>
    <SectionHeader icon="🛑" title="Global Kill Switch" desc="kill_switch.py — immediately halts all trading across all pods" />
    <div style={{ marginBottom: 12, background: '#450a0a', border: '1px solid #7f1d1d', borderRadius: 8, padding: '12px 16px' }}>
      <div style={{ fontSize: 13, color: '#fca5a5', fontWeight: 600 }}>
        ⚠️ Activating the kill switch immediately stops all live trading, cancels pending orders, and blocks new order submission across all running pods.
      </div>
    </div>
    <Tog id="ks" label="ACTIVATE GLOBAL KILL SWITCH" desc="HOPEFX_KILL_SWITCH — sets env var and propagates via Redis + K8s ConfigMap" checked={cfg.hopefx_kill_switch} onChange={(v) => set({ hopefx_kill_switch: v })} />
    <Divider />
    <SectionHeader icon="☸️" title="Kubernetes ConfigMap Propagation" />
    <Txt label="K8s Namespace" desc="K8S_KS_NAMESPACE" value={cfg.k8s_ks_namespace} onChange={(v) => set({ k8s_ks_namespace: v })} />
    <Txt label="ConfigMap Name" desc="K8S_KS_CONFIGMAP_NAME" value={cfg.k8s_ks_configmap_name} onChange={(v) => set({ k8s_ks_configmap_name: v })} />
    <Num label="Poll Interval (s)" desc="K8S_KS_POLL_INTERVAL_S" value={cfg.k8s_ks_poll_interval_s} step={0.5} min={1} onChange={(v) => set({ k8s_ks_poll_interval_s: v })} />
  </Card>
);


// ── Auto-Healing & Self-Repair section ────────────────────────────────────────

const TEST_CATEGORY_META: { key: string; label: string; desc: string; accent: string }[] = [
  { key: 'unit',        label: 'Unit Tests',        desc: 'Fast isolated tests for individual functions and classes', accent: '#3b82f6' },
  { key: 'api',         label: 'API Tests',         desc: 'FastAPI endpoint integration tests', accent: '#8b5cf6' },
  { key: 'broker',      label: 'Broker Tests',      desc: 'Broker connector and order routing tests', accent: '#f59e0b' },
  { key: 'risk',        label: 'Risk Tests',        desc: 'Risk manager, gatekeeper, and drawdown tests', accent: '#ef4444' },
  { key: 'ml',          label: 'ML / AI Tests',     desc: 'Model inference, training pipeline, and signal filter tests', accent: '#10b981' },
  { key: 'security',    label: 'Security Tests',    desc: 'Auth, JWT, self-healer, and integrity tests', accent: '#dc2626' },
  { key: 'performance', label: 'Performance Tests', desc: 'Latency and throughput benchmarks (slow)', accent: '#64748b' },
  { key: 'e2e',         label: 'End-to-End Tests',  desc: 'Full pipeline tests — require live broker connection', accent: '#64748b' },
];

const HealingTab: React.FC<{
  healer: HealerConfig;
  setHealer: (p: Partial<HealerConfig>) => void;
  healerStatus: HealerStatus | null;
  testIndex: TestIndex | null;
  onSaveHealer: () => void;
  savingHealer: boolean;
  savedHealer: boolean;
  healerSaveError: string;
  onRebuildBaseline: () => void;
  onRunTests: () => void;
  onReindexTests: () => void;
  actionMsg: string;
}> = ({
  healer, setHealer, healerStatus, testIndex,
  onSaveHealer, savingHealer, savedHealer, healerSaveError,
  onRebuildBaseline, onRunTests, onReindexTests, actionMsg,
}) => {
  const toggleCategory = (key: string, val: boolean) => {
    setHealer({ test_categories: { ...healer.test_categories, [key]: val } });
  };
  const toggleStrategy = (s: string) => {
    const cur = healer.test_execution_strategy;
    setHealer({
      test_execution_strategy: cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s],
    });
  };
  const toggleApproval = (s: string) => {
    const cur = healer.require_approval_categories;
    setHealer({
      require_approval_categories: cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s],
    });
  };

  return (
    <>
      {/* Live status */}
      {healerStatus && (
        <Card>
          <SectionHeader icon="📊" title="Live Healer Status" />
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12, marginBottom: 8 }}>
            {[
              { label: 'Running',          value: healerStatus.running ? '✅ Yes' : '❌ No' },
              { label: 'Baseline Files',   value: healerStatus.baseline_files },
              { label: 'Drift Events',     value: healerStatus.drift_events },
              { label: 'Patches Applied',  value: healerStatus.patches_applied },
              { label: 'Patches Failed',   value: healerStatus.patches_failed },
              { label: 'Last Test Passed', value: healerStatus.last_test_passed ?? '—' },
              { label: 'Last Test Failed', value: healerStatus.last_test_failed ?? '—' },
            ].map((kpi) => (
              <div key={kpi.label} style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: '10px 14px' }}>
                <div style={{ fontSize: 10, color: '#64748b', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em' }}>{kpi.label}</div>
                <div style={{ fontSize: 20, fontWeight: 800, color: '#f8fafc', marginTop: 4 }}>{kpi.value}</div>
              </div>
            ))}
          </div>
          {healerStatus.last_scan && (
            <div style={{ fontSize: 12, color: '#475569', marginTop: 4 }}>Last scan: {healerStatus.last_scan}</div>
          )}
          {healerStatus.last_test_run && (
            <div style={{ fontSize: 12, color: '#475569' }}>Last test run: {healerStatus.last_test_run}</div>
          )}
        </Card>
      )}

      {/* Core config */}
      <Card>
        <SectionHeader icon="🩺" title="Core Healer Config" desc="security/self_healer.py — SelfHealer.apply_config()" />
        <Tog id="heal_en" label="Enable Self-Healer" desc="enabled" checked={healer.enabled} onChange={(v) => setHealer({ enabled: v })} />
        <Sel label="Aggressiveness" desc="low = scan only | medium = patch approved | aggressive = auto-patch | nuclear = patch + force-restart"
          value={healer.aggressiveness}
          options={['low','medium','aggressive','nuclear'].map((v) => ({ value: v, label: v.charAt(0).toUpperCase() + v.slice(1) }))}
          onChange={(v) => setHealer({ aggressiveness: v })} />
        <Num label="Scan Interval (s)" desc="scan_interval_sec — HEAL_SCAN_INTERVAL" value={healer.scan_interval_sec} min={10} onChange={(v) => setHealer({ scan_interval_sec: v })} />
        <Num label="Patch Drain Interval (s)" desc="patch_interval_sec — HEAL_PATCH_INTERVAL" value={healer.patch_interval_sec} min={10} onChange={(v) => setHealer({ patch_interval_sec: v })} />
        <Num label="Max Patch Size (bytes)" desc="max_patch_bytes — HEAL_MAX_PATCH_BYTES" value={healer.max_patch_bytes} step={1024} min={1024} onChange={(v) => setHealer({ max_patch_bytes: v })} />
        <Sel label="Auto-Rollback Sensitivity" desc="low = rollback only on crash | medium = rollback on compile fail | high = rollback on any test fail"
          value={healer.auto_rollback_sensitivity}
          options={['low','medium','high'].map((v) => ({ value: v, label: v.charAt(0).toUpperCase() + v.slice(1) }))}
          onChange={(v) => setHealer({ auto_rollback_sensitivity: v })} />
        <Num label="Max Healing Attempts Per File" desc="max_healing_attempts" value={healer.max_healing_attempts} min={1} onChange={(v) => setHealer({ max_healing_attempts: v })} />
        <Num label="Healing Cooldown (s)" desc="healing_cooldown_sec — time between heal attempts on same file" value={healer.healing_cooldown_sec} min={0} onChange={(v) => setHealer({ healing_cooldown_sec: v })} />
        <Sel label="Log Level" desc="minimal | standard | verbose | debug"
          value={healer.log_level}
          options={['minimal','standard','verbose','debug'].map((v) => ({ value: v, label: v.charAt(0).toUpperCase() + v.slice(1) }))}
          onChange={(v) => setHealer({ log_level: v })} />
        <Tog id="heal_baseline_auto" label="Auto-Rebuild Baseline" desc="baseline_auto_rebuild — rebuild baseline after successful patch" checked={healer.baseline_auto_rebuild} onChange={(v) => setHealer({ baseline_auto_rebuild: v })} />
      </Card>

      {/* Quarantine */}
      <Card>
        <SectionHeader icon="🔒" title="Quarantine" desc="Files are copied to data/quarantine/ before any modification" />
        <Tog id="quar_en" label="Enable Quarantine" desc="quarantine_enabled" checked={healer.quarantine_enabled} onChange={(v) => setHealer({ quarantine_enabled: v })} />
        <Num label="Retention (days)" desc="quarantine_retention_days" value={healer.quarantine_retention_days} min={1} onChange={(v) => setHealer({ quarantine_retention_days: v })} />
      </Card>

      {/* Protected paths */}
      <Card>
        <SectionHeader icon="🛡️" title="Protected Paths" desc="Files matching these paths are never auto-patched — comma-separated prefixes" />
        <Field label="Protected Paths" description="e.g. live_trading.py,risk_manager.py,ml/models/,config/secrets/">
          <textarea
            value={healer.protected_paths}
            onChange={(e) => setHealer({ protected_paths: e.target.value })}
            rows={4}
            style={{
              width: '100%', padding: '10px 12px', background: '#0f172a',
              border: '1px solid #334155', borderRadius: 8, color: '#f1f5f9',
              fontSize: 13, boxSizing: 'border-box', resize: 'vertical', fontFamily: 'monospace',
            }}
          />
        </Field>
      </Card>

      {/* Test integration */}
      <Card>
        <SectionHeader icon="🧪" title="Test Integration" desc="Controls when and which tests run after healing events" />
        <Tog id="tests_en" label="Enable Test Runner" desc="tests_enabled" checked={healer.tests_enabled} onChange={(v) => setHealer({ tests_enabled: v })} />
        <Num label="Per-Test Timeout (s)" desc="test_timeout_sec" value={healer.test_timeout_sec} min={10} onChange={(v) => setHealer({ test_timeout_sec: v })} />
        <Num label="Global Test Suite Timeout (s)" desc="global_test_timeout_sec" value={healer.global_test_timeout_sec} min={60} onChange={(v) => setHealer({ global_test_timeout_sec: v })} />
        <Tog id="par_tests" label="Run Tests in Parallel" desc="parallel_tests — uses pytest-xdist" checked={healer.parallel_tests} onChange={(v) => setHealer({ parallel_tests: v })} />
        <Num label="Scheduled Test Interval (min)" desc="test_schedule_interval_min — 0 = disabled" value={healer.test_schedule_interval_min} min={0} onChange={(v) => setHealer({ test_schedule_interval_min: v })} />
        <Divider />
        <div style={{ fontSize: 12, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }}>
          Test Execution Triggers
        </div>
        {['after_patch', 'on_drift', 'on_schedule', 'on_startup'].map((s) => (
          <Toggle
            key={s} id={`strat_${s}`}
            label={s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
            checked={healer.test_execution_strategy.includes(s)}
            onChange={() => toggleStrategy(s)}
          />
        ))}
        <Divider />
        <div style={{ fontSize: 12, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }}>
          Test Categories
        </div>
        {testIndex && (
          <div style={{ fontSize: 12, color: '#475569', marginBottom: 10 }}>
            {testIndex.total} tests discovered across {Object.keys(testIndex.by_category).length} categories
          </div>
        )}
        {TEST_CATEGORY_META.map((cat) => (
          <div key={cat.key} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid #1e293b' }}>
            <div>
              <div style={{ fontSize: 13, color: '#e2e8f0', fontWeight: 500, display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ width: 8, height: 8, borderRadius: '50%', background: cat.accent, display: 'inline-block' }} />
                {cat.label}
                {testIndex?.by_category[cat.key] !== undefined && (
                  <span style={{ fontSize: 11, color: '#475569' }}>({testIndex.by_category[cat.key]} tests)</span>
                )}
              </div>
              <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>{cat.desc}</div>
            </div>
            <Toggle
              id={`cat_${cat.key}`} label="" checked={!!healer.test_categories[cat.key]}
              onChange={(v) => toggleCategory(cat.key, v)}
            />
          </div>
        ))}
        <Divider />
        <div style={{ fontSize: 12, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }}>
          Require Manual Approval Before Patching
        </div>
        {['nuclear', 'e2e', 'security', 'risk'].map((s) => (
          <Toggle
            key={s} id={`appr_${s}`}
            label={s.charAt(0).toUpperCase() + s.slice(1) + ' patches require approval'}
            checked={healer.require_approval_categories.includes(s)}
            onChange={() => toggleApproval(s)}
          />
        ))}
      </Card>

      {/* Actions */}
      <Card>
        <SectionHeader icon="🔧" title="Healer Actions" />
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginBottom: 12 }}>
          <Button variant="secondary" onClick={onRebuildBaseline}>Rebuild Integrity Baseline</Button>
          <Button variant="secondary" onClick={onRunTests}>Run Tests Now</Button>
          <Button variant="secondary" onClick={onReindexTests}>Re-index Test Files</Button>
        </div>
        {actionMsg && (
          <div style={{ fontSize: 13, color: '#60a5fa', padding: '8px 12px', background: '#0c1a2e', borderRadius: 6, border: '1px solid #1e3a5f' }}>
            {actionMsg}
          </div>
        )}
      </Card>

      <SaveBar onSave={onSaveHealer} saving={savingHealer} saved={savedHealer} error={healerSaveError} />
    </>
  );
};




// ── LSTM tab ──────────────────────────────────────────────────────────────────

const LstmTab: React.FC<{ cfg: PlatformConfig; set: (p: Partial<PlatformConfig>) => void }> = ({ cfg, set }) => (
  <>
    <Card>
      <SectionHeader icon="🔁" title="LSTM Model" desc="Long Short-Term Memory sequence model. LSTM_*" />
      <Tog id="lstm_en" label="Enable LSTM" desc="LSTM_ENABLED" checked={cfg.lstm_enabled} onChange={(v) => set({ lstm_enabled: v })} />
      <Divider />
      <Num label="Sequence Length" desc="LSTM_SEQUENCE_LENGTH" value={cfg.lstm_sequence_length} min={10} max={500} onChange={(v) => set({ lstm_sequence_length: v })} />
      <Num label="Hidden Size" desc="LSTM_HIDDEN_SIZE" value={cfg.lstm_hidden_size} min={16} max={1024} onChange={(v) => set({ lstm_hidden_size: v })} />
      <Num label="Num Layers" desc="LSTM_NUM_LAYERS" value={cfg.lstm_num_layers} min={1} max={8} onChange={(v) => set({ lstm_num_layers: v })} />
      <Num label="Dropout" desc="LSTM_DROPOUT" value={cfg.lstm_dropout} step={0.01} min={0} max={0.9} onChange={(v) => set({ lstm_dropout: v })} />
      <Num label="Learning Rate" desc="LSTM_LEARNING_RATE" value={cfg.lstm_learning_rate} step={0.0001} min={0.00001} onChange={(v) => set({ lstm_learning_rate: v })} />
      <Num label="Batch Size" desc="LSTM_BATCH_SIZE" value={cfg.lstm_batch_size} min={8} max={512} onChange={(v) => set({ lstm_batch_size: v })} />
      <Num label="Epochs" desc="LSTM_EPOCHS" value={cfg.lstm_epochs} min={1} max={500} onChange={(v) => set({ lstm_epochs: v })} />
      <Num label="Retrain Interval (hours)" desc="LSTM_RETRAIN_INTERVAL_HOURS" value={cfg.lstm_retrain_interval_hours} min={1} onChange={(v) => set({ lstm_retrain_interval_hours: v })} />
      <Num label="Min Train Samples" desc="LSTM_MIN_TRAIN_SAMPLES" value={cfg.lstm_min_train_samples} min={100} onChange={(v) => set({ lstm_min_train_samples: v })} />
      <Num label="Clip Grad Norm" desc="LSTM_CLIP_GRAD_NORM" value={cfg.lstm_clip_grad_norm} step={0.1} min={0} onChange={(v) => set({ lstm_clip_grad_norm: v })} />
      <Num label="Weight Decay" desc="LSTM_WEIGHT_DECAY" value={cfg.lstm_weight_decay} step={0.00001} min={0} onChange={(v) => set({ lstm_weight_decay: v })} />
      <Sel label="LR Scheduler" desc="LSTM_SCHEDULER" value={cfg.lstm_scheduler}
        options={['cosine','step','plateau','none'].map((v) => ({ value: v, label: v }))}
        onChange={(v) => set({ lstm_scheduler: v })} />
      <Tog id="lstm_attn" label="Use Attention" desc="LSTM_USE_ATTENTION" checked={cfg.lstm_use_attention} onChange={(v) => set({ lstm_use_attention: v })} />
      <Tog id="lstm_bi" label="Bidirectional" desc="LSTM_BIDIRECTIONAL" checked={cfg.lstm_bidirectional} onChange={(v) => set({ lstm_bidirectional: v })} />
    </Card>
  </>
);

// ── Brain tab ─────────────────────────────────────────────────────────────────

const BrainTab: React.FC<{ cfg: PlatformConfig; set: (p: Partial<PlatformConfig>) => void }> = ({ cfg, set }) => (
  <>
    <Card>
      <SectionHeader icon="💡" title="AI Brain / Strategy Generator" desc="LLM-powered strategy generation engine. BRAIN_*" />
      <Tog id="brain_en" label="Enable AI Brain" desc="BRAIN_ENABLED" checked={cfg.brain_enabled} onChange={(v) => set({ brain_enabled: v })} />
      <Divider />
      <Txt label="LLM Model" desc="BRAIN_MODEL" value={cfg.brain_model} placeholder="gpt-4o" onChange={(v) => set({ brain_model: v })} />
      <Num label="Temperature" desc="BRAIN_TEMPERATURE" value={cfg.brain_temperature} step={0.05} min={0} max={2} onChange={(v) => set({ brain_temperature: v })} />
      <Num label="Max Tokens" desc="BRAIN_MAX_TOKENS" value={cfg.brain_max_tokens} min={256} max={32768} onChange={(v) => set({ brain_max_tokens: v })} />
      <Num label="Strategy Timeout (s)" desc="BRAIN_STRATEGY_TIMEOUT_S" value={cfg.brain_strategy_timeout_s} min={10} onChange={(v) => set({ brain_strategy_timeout_s: v })} />
      <Num label="Max Strategies/Day" desc="BRAIN_MAX_STRATEGIES_PER_DAY" value={cfg.brain_max_strategies_per_day} min={1} onChange={(v) => set({ brain_max_strategies_per_day: v })} />
      <Num label="Min Backtest Sharpe" desc="BRAIN_MIN_BACKTEST_SHARPE" value={cfg.brain_min_backtest_sharpe} step={0.1} min={0} onChange={(v) => set({ brain_min_backtest_sharpe: v })} />
      <Num label="Min Backtest Win Rate" desc="BRAIN_MIN_BACKTEST_WINRATE" value={cfg.brain_min_backtest_winrate} step={0.01} min={0} max={1} onChange={(v) => set({ brain_min_backtest_winrate: v })} />
      <Tog id="brain_auto" label="Auto-Deploy Strategies" desc="BRAIN_AUTO_DEPLOY" checked={cfg.brain_auto_deploy} onChange={(v) => set({ brain_auto_deploy: v })} />
      <Tog id="brain_sandbox" label="Sandbox Mode" desc="BRAIN_SANDBOX_ENABLED — paper-test before live" checked={cfg.brain_sandbox_enabled} onChange={(v) => set({ brain_sandbox_enabled: v })} />
    </Card>
  </>
);

// ── Allocator tab ─────────────────────────────────────────────────────────────

const AllocatorTab: React.FC<{ cfg: PlatformConfig; set: (p: Partial<PlatformConfig>) => void }> = ({ cfg, set }) => (
  <>
    <Card>
      <SectionHeader icon="📊" title="Portfolio Allocator" desc="Multi-asset portfolio allocation engine. ALLOCATOR_*" />
      <Tog id="alloc_en" label="Enable Allocator" desc="ALLOCATOR_ENABLED" checked={cfg.allocator_enabled} onChange={(v) => set({ allocator_enabled: v })} />
      <Divider />
      <Sel label="Method" desc="ALLOCATOR_METHOD" value={cfg.allocator_method}
        options={['equal_weight','risk_parity','mean_variance','hrp','black_litterman'].map((v) => ({ value: v, label: v }))}
        onChange={(v) => set({ allocator_method: v })} />
      <Num label="Rebalance Interval (hours)" desc="ALLOCATOR_REBALANCE_INTERVAL_HOURS" value={cfg.allocator_rebalance_interval_hours} min={1} onChange={(v) => set({ allocator_rebalance_interval_hours: v })} />
      <Num label="Min Weight" desc="ALLOCATOR_MIN_WEIGHT" value={cfg.allocator_min_weight} step={0.01} min={0} max={1} onChange={(v) => set({ allocator_min_weight: v })} />
      <Num label="Max Weight" desc="ALLOCATOR_MAX_WEIGHT" value={cfg.allocator_max_weight} step={0.01} min={0} max={1} onChange={(v) => set({ allocator_max_weight: v })} />
      <Num label="Risk Budget" desc="ALLOCATOR_RISK_BUDGET" value={cfg.allocator_risk_budget} step={0.001} min={0} onChange={(v) => set({ allocator_risk_budget: v })} />
      <Num label="Lookback Days" desc="ALLOCATOR_LOOKBACK_DAYS" value={cfg.allocator_lookback_days} min={30} onChange={(v) => set({ allocator_lookback_days: v })} />
      <Num label="Transaction Cost (bps)" desc="ALLOCATOR_TRANSACTION_COST_BPS" value={cfg.allocator_transaction_cost_bps} step={0.1} min={0} onChange={(v) => set({ allocator_transaction_cost_bps: v })} />
      <Num label="Target Volatility" desc="ALLOCATOR_TARGET_VOLATILITY" value={cfg.allocator_target_volatility} step={0.01} min={0} onChange={(v) => set({ allocator_target_volatility: v })} />
      <Tog id="alloc_bl" label="Use Black-Litterman" desc="ALLOCATOR_USE_BLACK_LITTERMAN" checked={cfg.allocator_use_black_litterman} onChange={(v) => set({ allocator_use_black_litterman: v })} />
      <Tog id="alloc_hrp" label="Use HRP" desc="ALLOCATOR_USE_HRP — Hierarchical Risk Parity" checked={cfg.allocator_use_hrp} onChange={(v) => set({ allocator_use_hrp: v })} />
    </Card>
  </>
);

// ── Anomaly tab ───────────────────────────────────────────────────────────────

const AnomalyTab: React.FC<{ cfg: PlatformConfig; set: (p: Partial<PlatformConfig>) => void }> = ({ cfg, set }) => (
  <>
    <Card>
      <SectionHeader icon="🚨" title="Anomaly Detection" desc="Detects abnormal market conditions and trading patterns. ANOMALY_*" />
      <Tog id="anom_en" label="Enable Anomaly Detection" desc="ANOMALY_ENABLED" checked={cfg.anomaly_enabled} onChange={(v) => set({ anomaly_enabled: v })} />
      <Divider />
      <Sel label="Model" desc="ANOMALY_MODEL" value={cfg.anomaly_model}
        options={['isolation_forest','lof','autoencoder','one_class_svm'].map((v) => ({ value: v, label: v }))}
        onChange={(v) => set({ anomaly_model: v })} />
      <Num label="Contamination" desc="ANOMALY_CONTAMINATION — expected outlier fraction" value={cfg.anomaly_contamination} step={0.01} min={0.001} max={0.5} onChange={(v) => set({ anomaly_contamination: v })} />
      <Num label="Window" desc="ANOMALY_WINDOW — rolling bars" value={cfg.anomaly_window} min={10} onChange={(v) => set({ anomaly_window: v })} />
      <Num label="Threshold" desc="ANOMALY_THRESHOLD — score above this triggers action" value={cfg.anomaly_threshold} step={0.01} min={0} max={1} onChange={(v) => set({ anomaly_threshold: v })} />
      <Sel label="Action on Anomaly" desc="ANOMALY_ACTION" value={cfg.anomaly_action}
        options={['alert','pause','reduce_size','close_all'].map((v) => ({ value: v, label: v }))}
        onChange={(v) => set({ anomaly_action: v })} />
      <Num label="Retrain Interval (hours)" desc="ANOMALY_RETRAIN_INTERVAL_HOURS" value={cfg.anomaly_retrain_interval_hours} min={1} onChange={(v) => set({ anomaly_retrain_interval_hours: v })} />
      <Num label="Min Samples" desc="ANOMALY_MIN_SAMPLES" value={cfg.anomaly_min_samples} min={50} onChange={(v) => set({ anomaly_min_samples: v })} />
      <Num label="Alert Cooldown (s)" desc="ANOMALY_ALERT_COOLDOWN_S" value={cfg.anomaly_alert_cooldown_s} min={0} onChange={(v) => set({ anomaly_alert_cooldown_s: v })} />
    </Card>
  </>
);

// ── Macro tab ─────────────────────────────────────────────────────────────────

const MacroTab: React.FC<{ cfg: PlatformConfig; set: (p: Partial<PlatformConfig>) => void }> = ({ cfg, set }) => (
  <>
    <Card>
      <SectionHeader icon="🌍" title="Macro Overlay" desc="FRED / WGC macro data integration for signal weighting. MACRO_*" />
      <Tog id="macro_en" label="Enable Macro Overlay" desc="MACRO_ENABLED" checked={cfg.macro_enabled} onChange={(v) => set({ macro_enabled: v })} />
      <Divider />
      <Txt label="FRED API Key" desc="MACRO_FRED_API_KEY" value={cfg.macro_fred_api_key} password placeholder="your-fred-api-key" onChange={(v) => set({ macro_fred_api_key: v })} />
      <Num label="Refresh Interval (hours)" desc="MACRO_REFRESH_INTERVAL_HOURS" value={cfg.macro_refresh_interval_hours} min={1} onChange={(v) => set({ macro_refresh_interval_hours: v })} />
      <Num label="Lookback Days" desc="MACRO_LOOKBACK_DAYS" value={cfg.macro_lookback_days} min={30} onChange={(v) => set({ macro_lookback_days: v })} />
      <Num label="Weight in Signal" desc="MACRO_WEIGHT_IN_SIGNAL (0–1)" value={cfg.macro_weight_in_signal} step={0.01} min={0} max={1} onChange={(v) => set({ macro_weight_in_signal: v })} />
      <Num label="VIX Threshold" desc="MACRO_VIX_THRESHOLD — above this reduces position size" value={cfg.macro_vix_threshold} step={0.5} min={0} onChange={(v) => set({ macro_vix_threshold: v })} />
      <Num label="DXY Threshold" desc="MACRO_DXY_THRESHOLD" value={cfg.macro_dxy_threshold} step={0.5} min={0} onChange={(v) => set({ macro_dxy_threshold: v })} />
      <Num label="Yield Spread Threshold" desc="MACRO_YIELD_SPREAD_THRESHOLD" value={cfg.macro_yield_spread_threshold} step={0.1} min={0} onChange={(v) => set({ macro_yield_spread_threshold: v })} />
      <Tog id="macro_wgc" label="Enable WGC Gold Data" desc="MACRO_WGC_ENABLED" checked={cfg.macro_wgc_enabled} onChange={(v) => set({ macro_wgc_enabled: v })} />
      <Num label="WGC Refresh (hours)" desc="MACRO_WGC_REFRESH_HOURS" value={cfg.macro_wgc_refresh_hours} min={1} onChange={(v) => set({ macro_wgc_refresh_hours: v })} />
    </Card>
  </>
);

// ── Online Learner tab ────────────────────────────────────────────────────────

const OnlineTab: React.FC<{ cfg: PlatformConfig; set: (p: Partial<PlatformConfig>) => void }> = ({ cfg, set }) => (
  <>
    <Card>
      <SectionHeader icon="📡" title="Online Learner" desc="Continuous incremental model updates from live trade outcomes. ONLINE_LEARNER_*" />
      <Tog id="ol_en" label="Enable Online Learner" desc="ONLINE_LEARNER_ENABLED" checked={cfg.online_learner_enabled} onChange={(v) => set({ online_learner_enabled: v })} />
      <Divider />
      <Sel label="Algorithm" desc="ONLINE_LEARNER_ALGORITHM" value={cfg.online_learner_algorithm}
        options={['sgd','adam','rmsprop','passive_aggressive','perceptron'].map((v) => ({ value: v, label: v }))}
        onChange={(v) => set({ online_learner_algorithm: v })} />
      <Num label="Learning Rate" desc="ONLINE_LEARNER_LR" value={cfg.online_learner_lr} step={0.0001} min={0.00001} onChange={(v) => set({ online_learner_lr: v })} />
      <Num label="Batch Size" desc="ONLINE_LEARNER_BATCH_SIZE" value={cfg.online_learner_batch_size} min={1} max={512} onChange={(v) => set({ online_learner_batch_size: v })} />
      <Num label="Update Interval (s)" desc="ONLINE_LEARNER_UPDATE_INTERVAL_S" value={cfg.online_learner_update_interval_s} min={10} onChange={(v) => set({ online_learner_update_interval_s: v })} />
      <Num label="Max Buffer Size" desc="ONLINE_LEARNER_MAX_BUFFER" value={cfg.online_learner_max_buffer} min={100} onChange={(v) => set({ online_learner_max_buffer: v })} />
      <Num label="Forgetting Factor" desc="ONLINE_LEARNER_FORGETTING_FACTOR (0–1)" value={cfg.online_learner_forgetting_factor} step={0.01} min={0} max={1} onChange={(v) => set({ online_learner_forgetting_factor: v })} />
      <Num label="Min Samples Before Update" desc="ONLINE_LEARNER_MIN_SAMPLES_BEFORE_UPDATE" value={cfg.online_learner_min_samples_before_update} min={1} onChange={(v) => set({ online_learner_min_samples_before_update: v })} />
      <Tog id="ol_drift" label="Feature Drift Check" desc="ONLINE_LEARNER_FEATURE_DRIFT_CHECK" checked={cfg.online_learner_feature_drift_check} onChange={(v) => set({ online_learner_feature_drift_check: v })} />
    </Card>
  </>
);

// ── Sharpe CB tab ─────────────────────────────────────────────────────────────

const SharpeTab: React.FC<{ cfg: PlatformConfig; set: (p: Partial<PlatformConfig>) => void }> = ({ cfg, set }) => (
  <>
    <Card>
      <SectionHeader icon="📈" title="Sharpe Circuit Breaker" desc="Halts trading when rolling Sharpe ratio falls below threshold. SHARPE_CB_*" />
      <Num label="Window Trades" desc="SHARPE_CB_WINDOW_TRADES" value={cfg.sharpe_cb_window_trades} min={5} onChange={(v) => set({ sharpe_cb_window_trades: v })} />
      <Num label="Min Sharpe" desc="SHARPE_CB_MIN_SHARPE — halt below this" value={cfg.sharpe_cb_min_sharpe} step={0.1} onChange={(v) => set({ sharpe_cb_min_sharpe: v })} />
      <Num label="Consecutive Breaches" desc="SHARPE_CB_CONSECUTIVE — N consecutive before halt" value={cfg.sharpe_cb_consecutive} min={1} onChange={(v) => set({ sharpe_cb_consecutive: v })} />
      <Num label="Eval Interval (s)" desc="SHARPE_CB_EVAL_INTERVAL_S" value={cfg.sharpe_cb_eval_interval_s} min={10} onChange={(v) => set({ sharpe_cb_eval_interval_s: v })} />
      <Num label="Min Trades" desc="SHARPE_CB_MIN_TRADES — minimum before evaluating" value={cfg.sharpe_cb_min_trades} min={1} onChange={(v) => set({ sharpe_cb_min_trades: v })} />
      <Num label="Reset After (s)" desc="SHARPE_CB_RESET_AFTER_S — auto-reset cooldown" value={cfg.sharpe_cb_reset_after_s} min={60} onChange={(v) => set({ sharpe_cb_reset_after_s: v })} />
    </Card>
  </>
);

// ── Regime tab ────────────────────────────────────────────────────────────────

const RegimeTab: React.FC<{ cfg: PlatformConfig; set: (p: Partial<PlatformConfig>) => void }> = ({ cfg, set }) => (
  <>
    <Card>
      <SectionHeader icon="🗺️" title="Regime Detection" desc="Market regime classification (trending/ranging/volatile). REGIME_*" />
      <Tog id="regime_en" label="Enable Regime Detection" desc="REGIME_ENABLED" checked={cfg.regime_enabled} onChange={(v) => set({ regime_enabled: v })} />
      <Divider />
      <Sel label="Model" desc="REGIME_MODEL" value={cfg.regime_model}
        options={['hmm','kmeans','gmm','threshold'].map((v) => ({ value: v, label: v }))}
        onChange={(v) => set({ regime_model: v })} />
      <Num label="Lookback Bars" desc="REGIME_LOOKBACK_BARS" value={cfg.regime_lookback_bars} min={20} onChange={(v) => set({ regime_lookback_bars: v })} />
      <Num label="N States" desc="REGIME_N_STATES — number of regime classes" value={cfg.regime_n_states} min={2} max={10} onChange={(v) => set({ regime_n_states: v })} />
      <Num label="Retrain Interval (hours)" desc="REGIME_RETRAIN_INTERVAL_HOURS" value={cfg.regime_retrain_interval_hours} min={1} onChange={(v) => set({ regime_retrain_interval_hours: v })} />
      <Num label="Confidence Threshold" desc="REGIME_CONFIDENCE_THRESHOLD" value={cfg.regime_confidence_threshold} step={0.01} min={0} max={1} onChange={(v) => set({ regime_confidence_threshold: v })} />
      <Num label="Transition Smoothing" desc="REGIME_TRANSITION_SMOOTHING — EMA factor" value={cfg.regime_transition_smoothing} step={0.05} min={0} max={1} onChange={(v) => set({ regime_transition_smoothing: v })} />
      <Sel label="Feature Set" desc="REGIME_FEATURE_SET" value={cfg.regime_feature_set}
        options={['default','extended','minimal'].map((v) => ({ value: v, label: v }))}
        onChange={(v) => set({ regime_feature_set: v })} />
      <Tog id="regime_hmm" label="Use HMM" desc="REGIME_USE_HMM" checked={cfg.regime_use_hmm} onChange={(v) => set({ regime_use_hmm: v })} />
      <Tog id="regime_km" label="Use K-Means" desc="REGIME_USE_KMEANS" checked={cfg.regime_use_kmeans} onChange={(v) => set({ regime_use_kmeans: v })} />
    </Card>
  </>
);

// ── Signal Engine tab ─────────────────────────────────────────────────────────

const SignalEngineTab: React.FC<{ cfg: PlatformConfig; set: (p: Partial<PlatformConfig>) => void }> = ({ cfg, set }) => (
  <>
    <Card>
      <SectionHeader icon="⚡" title="Signal Engine" desc="Ensemble signal generation pipeline. SIGNAL_ENGINE_*" />
      <Tog id="se_en" label="Enable Signal Engine" desc="SIGNAL_ENGINE_ENABLED" checked={cfg.signal_engine_enabled} onChange={(v) => set({ signal_engine_enabled: v })} />
      <Divider />
      <Sel label="Mode" desc="SIGNAL_ENGINE_MODE" value={cfg.signal_engine_mode}
        options={['ensemble','single','voting'].map((v) => ({ value: v, label: v }))}
        onChange={(v) => set({ signal_engine_mode: v })} />
      <Sel label="Ensemble Method" desc="SIGNAL_ENGINE_ENSEMBLE_METHOD" value={cfg.signal_engine_ensemble_method}
        options={['weighted_vote','majority_vote','stacking','average'].map((v) => ({ value: v, label: v }))}
        onChange={(v) => set({ signal_engine_ensemble_method: v })} />
      <Num label="Min Model Agreement" desc="SIGNAL_ENGINE_MIN_MODEL_AGREEMENT" value={cfg.signal_engine_min_model_agreement} step={0.05} min={0} max={1} onChange={(v) => set({ signal_engine_min_model_agreement: v })} />
      <Num label="Cooldown (s)" desc="SIGNAL_ENGINE_COOLDOWN_S" value={cfg.signal_engine_cooldown_s} min={0} onChange={(v) => set({ signal_engine_cooldown_s: v })} />
      <Num label="Max Signals/Hour" desc="SIGNAL_ENGINE_MAX_SIGNALS_PER_HOUR" value={cfg.signal_engine_max_signals_per_hour} min={1} onChange={(v) => set({ signal_engine_max_signals_per_hour: v })} />
    </Card>
    <Card>
      <SectionHeader icon="🧩" title="Model Components" desc="Which models contribute to the ensemble." />
      <Tog id="se_lstm" label="Use LSTM" desc="SIGNAL_ENGINE_USE_LSTM" checked={cfg.signal_engine_use_lstm} onChange={(v) => set({ signal_engine_use_lstm: v })} />
      <Tog id="se_xgb" label="Use XGBoost" desc="SIGNAL_ENGINE_USE_XGB" checked={cfg.signal_engine_use_xgb} onChange={(v) => set({ signal_engine_use_xgb: v })} />
      <Tog id="se_rf" label="Use Random Forest" desc="SIGNAL_ENGINE_USE_RF" checked={cfg.signal_engine_use_rf} onChange={(v) => set({ signal_engine_use_rf: v })} />
      <Tog id="se_lgbm" label="Use LightGBM" desc="SIGNAL_ENGINE_USE_LGBM" checked={cfg.signal_engine_use_lgbm} onChange={(v) => set({ signal_engine_use_lgbm: v })} />
      <Tog id="se_regime" label="Use Regime Filter" desc="SIGNAL_ENGINE_USE_REGIME" checked={cfg.signal_engine_use_regime} onChange={(v) => set({ signal_engine_use_regime: v })} />
      <Tog id="se_macro" label="Use Macro Overlay" desc="SIGNAL_ENGINE_USE_MACRO" checked={cfg.signal_engine_use_macro} onChange={(v) => set({ signal_engine_use_macro: v })} />
      <Tog id="se_sent" label="Use Sentiment" desc="SIGNAL_ENGINE_USE_SENTIMENT" checked={cfg.signal_engine_use_sentiment} onChange={(v) => set({ signal_engine_use_sentiment: v })} />
    </Card>
  </>
);

// ── TCA Config tab ────────────────────────────────────────────────────────────

const TcaConfigTab: React.FC<{ cfg: PlatformConfig; set: (p: Partial<PlatformConfig>) => void }> = ({ cfg, set }) => (
  <>
    <Card>
      <SectionHeader icon="💹" title="Transaction Cost Analysis" desc="TCA engine configuration and reporting. TCA_*" />
      <Tog id="tca_en" label="Enable TCA" desc="TCA_ENABLED" checked={cfg.tca_enabled} onChange={(v) => set({ tca_enabled: v })} />
      <Divider />
      <Num label="Alert Threshold (bps)" desc="TCA_ALERT_THRESHOLD_BPS" value={cfg.tca_alert_threshold_bps} step={0.5} min={0} onChange={(v) => set({ tca_alert_threshold_bps: v })} />
      <Num label="Alert Window (trades)" desc="TCA_ALERT_WINDOW" value={cfg.tca_alert_window} min={1} onChange={(v) => set({ tca_alert_window: v })} />
      <Num label="Max Memory Records" desc="TCA_MAX_MEMORY_RECORDS" value={cfg.tca_max_memory_records} min={100} onChange={(v) => set({ tca_max_memory_records: v })} />
      <Num label="Report Interval (hours)" desc="TCA_REPORT_INTERVAL_HOURS" value={cfg.tca_report_interval_hours} min={1} onChange={(v) => set({ tca_report_interval_hours: v })} />
      <Num label="Min Records for Report" desc="TCA_MIN_RECORDS_FOR_REPORT" value={cfg.tca_min_records_for_report} min={1} onChange={(v) => set({ tca_min_records_for_report: v })} />
      <Sel label="Benchmark" desc="TCA_BENCHMARK" value={cfg.tca_benchmark}
        options={['arrival_price','vwap','twap','close'].map((v) => ({ value: v, label: v }))}
        onChange={(v) => set({ tca_benchmark: v })} />
      <Sel label="Slippage Model" desc="TCA_SLIPPAGE_MODEL" value={cfg.tca_slippage_model}
        options={['linear','square_root','fixed'].map((v) => ({ value: v, label: v }))}
        onChange={(v) => set({ tca_slippage_model: v })} />
      <Sel label="Impact Model" desc="TCA_IMPACT_MODEL" value={cfg.tca_impact_model}
        options={['square_root','linear','almgren_chriss'].map((v) => ({ value: v, label: v }))}
        onChange={(v) => set({ tca_impact_model: v })} />
      <Tog id="tca_redis" label="Persist to Redis" desc="TCA_PERSIST_REDIS" checked={cfg.tca_persist_redis} onChange={(v) => set({ tca_persist_redis: v })} />
      <Tog id="tca_db" label="Persist to DB" desc="TCA_PERSIST_DB" checked={cfg.tca_persist_db} onChange={(v) => set({ tca_persist_db: v })} />
    </Card>
  </>
);

// ── Backtest Config tab ───────────────────────────────────────────────────────

const BacktestConfigTab: React.FC<{ cfg: PlatformConfig; set: (p: Partial<PlatformConfig>) => void }> = ({ cfg, set }) => (
  <>
    <Card>
      <SectionHeader icon="🔄" title="Backtest Engine" desc="Backtesting engine parameters and defaults. BACKTEST_*" />
      <Sel label="Engine" desc="BACKTEST_ENGINE" value={cfg.backtest_engine}
        options={['vectorbt','backtesting_py','custom'].map((v) => ({ value: v, label: v }))}
        onChange={(v) => set({ backtest_engine: v })} />
      <Sel label="Data Source" desc="BACKTEST_DATA_SOURCE" value={cfg.backtest_data_source}
        options={['ohlcv_store','csv','broker_api'].map((v) => ({ value: v, label: v }))}
        onChange={(v) => set({ backtest_data_source: v })} />
      <Num label="Default Initial Capital" desc="BACKTEST_DEFAULT_INITIAL_CAPITAL" value={cfg.backtest_default_initial_capital} min={1000} step={1000} onChange={(v) => set({ backtest_default_initial_capital: v })} />
      <Num label="Default Commission (%)" desc="BACKTEST_DEFAULT_COMMISSION_PCT" value={cfg.backtest_default_commission_pct} step={0.0001} min={0} onChange={(v) => set({ backtest_default_commission_pct: v })} />
      <Num label="Default Slippage (%)" desc="BACKTEST_DEFAULT_SLIPPAGE_PCT" value={cfg.backtest_default_slippage_pct} step={0.0001} min={0} onChange={(v) => set({ backtest_default_slippage_pct: v })} />
      <Num label="Default Spread (%)" desc="BACKTEST_DEFAULT_SPREAD_PCT" value={cfg.backtest_default_spread_pct} step={0.0001} min={0} onChange={(v) => set({ backtest_default_spread_pct: v })} />
      <Num label="Max Duration (s)" desc="BACKTEST_MAX_DURATION_S — timeout per run" value={cfg.backtest_max_duration_s} min={10} onChange={(v) => set({ backtest_max_duration_s: v })} />
      <Num label="Max Concurrent Runs" desc="BACKTEST_MAX_CONCURRENT" value={cfg.backtest_max_concurrent} min={1} max={32} onChange={(v) => set({ backtest_max_concurrent: v })} />
      <Num label="Walk-Forward Folds" desc="BACKTEST_WALK_FORWARD_FOLDS" value={cfg.backtest_walk_forward_folds} min={2} max={20} onChange={(v) => set({ backtest_walk_forward_folds: v })} />
      <Num label="OOS Ratio" desc="BACKTEST_OOS_RATIO — out-of-sample fraction" value={cfg.backtest_oos_ratio} step={0.05} min={0.1} max={0.5} onChange={(v) => set({ backtest_oos_ratio: v })} />
      <Num label="Min Trades for Validity" desc="BACKTEST_MIN_TRADES_FOR_VALIDITY" value={cfg.backtest_min_trades_for_validity} min={5} onChange={(v) => set({ backtest_min_trades_for_validity: v })} />
      <Num label="Min Sharpe for Deploy" desc="BACKTEST_MIN_SHARPE_FOR_DEPLOY" value={cfg.backtest_min_sharpe_for_deploy} step={0.1} min={0} onChange={(v) => set({ backtest_min_sharpe_for_deploy: v })} />
      <Tog id="bt_tick" label="Use Tick Data" desc="BACKTEST_USE_TICK_DATA — higher fidelity, slower" checked={cfg.backtest_use_tick_data} onChange={(v) => set({ backtest_use_tick_data: v })} />
    </Card>
  </>
);

// ── Feature Flags Config tab ──────────────────────────────────────────────────

const FeatureFlagsConfigTab: React.FC<{ cfg: PlatformConfig; set: (p: Partial<PlatformConfig>) => void }> = ({ cfg, set }) => (
  <>
    <Card>
      <SectionHeader icon="🚩" title="Feature Flags" desc="Enable or disable platform features globally. FEATURE_*" />
      <Tog id="ff_nuclear" label="Nuclear Dashboard" desc="FEATURE_NUCLEAR_ENABLED" checked={cfg.feature_nuclear_enabled} onChange={(v) => set({ feature_nuclear_enabled: v })} />
      <Tog id="ff_copy" label="Copy Trading" desc="FEATURE_COPY_TRADING_ENABLED" checked={cfg.feature_copy_trading_enabled} onChange={(v) => set({ feature_copy_trading_enabled: v })} />
      <Tog id="ff_social" label="Social Feed" desc="FEATURE_SOCIAL_FEED_ENABLED" checked={cfg.feature_social_feed_enabled} onChange={(v) => set({ feature_social_feed_enabled: v })} />
      <Tog id="ff_market" label="Marketplace" desc="FEATURE_MARKETPLACE_ENABLED" checked={cfg.feature_marketplace_enabled} onChange={(v) => set({ feature_marketplace_enabled: v })} />
      <Tog id="ff_aff" label="Affiliate Program" desc="FEATURE_AFFILIATE_ENABLED" checked={cfg.feature_affiliate_enabled} onChange={(v) => set({ feature_affiliate_enabled: v })} />
      <Tog id="ff_wl" label="White-Label" desc="FEATURE_WHITELABEL_ENABLED" checked={cfg.feature_whitelabel_enabled} onChange={(v) => set({ feature_whitelabel_enabled: v })} />
      <Tog id="ff_ai" label="AI Strategy Generator" desc="FEATURE_AI_STRATEGY_ENABLED" checked={cfg.feature_ai_strategy_enabled} onChange={(v) => set({ feature_ai_strategy_enabled: v })} />
      <Tog id="ff_wf" label="Walk-Forward Testing" desc="FEATURE_WALK_FORWARD_ENABLED" checked={cfg.feature_walk_forward_enabled} onChange={(v) => set({ feature_walk_forward_enabled: v })} />
      <Tog id="ff_ab" label="A/B Testing" desc="FEATURE_AB_TESTING_ENABLED" checked={cfg.feature_ab_testing_enabled} onChange={(v) => set({ feature_ab_testing_enabled: v })} />
      <Tog id="ff_tca" label="TCA Dashboard" desc="FEATURE_TCA_ENABLED" checked={cfg.feature_tca_enabled} onChange={(v) => set({ feature_tca_enabled: v })} />
      <Tog id="ff_replay" label="Trade Replay" desc="FEATURE_REPLAY_ENABLED" checked={cfg.feature_replay_enabled} onChange={(v) => set({ feature_replay_enabled: v })} />
      <Tog id="ff_research" label="Research Page" desc="FEATURE_RESEARCH_ENABLED" checked={cfg.feature_research_enabled} onChange={(v) => set({ feature_research_enabled: v })} />
      <Tog id="ff_geo" label="Geopolitical Risk" desc="FEATURE_GEOPOLITICAL_ENABLED" checked={cfg.feature_geopolitical_enabled} onChange={(v) => set({ feature_geopolitical_enabled: v })} />
      <Tog id="ff_prop" label="Prop Firm Tracker" desc="FEATURE_PROP_FIRM_ENABLED" checked={cfg.feature_prop_firm_enabled} onChange={(v) => set({ feature_prop_firm_enabled: v })} />
      <Tog id="ff_teams" label="Teams" desc="FEATURE_TEAMS_ENABLED" checked={cfg.feature_teams_enabled} onChange={(v) => set({ feature_teams_enabled: v })} />
      <Tog id="ff_lb" label="Leaderboard" desc="FEATURE_LEADERBOARD_ENABLED" checked={cfg.feature_leaderboard_enabled} onChange={(v) => set({ feature_leaderboard_enabled: v })} />
      <Tog id="ff_crypto" label="Crypto Checkout" desc="FEATURE_CRYPTO_CHECKOUT_ENABLED" checked={cfg.feature_crypto_checkout_enabled} onChange={(v) => set({ feature_crypto_checkout_enabled: v })} />
      <Tog id="ff_2fa" label="Two-Factor Auth" desc="FEATURE_2FA_ENABLED" checked={cfg.feature_2fa_enabled} onChange={(v) => set({ feature_2fa_enabled: v })} />
      <Tog id="ff_kyc" label="KYC Verification" desc="FEATURE_KYC_ENABLED" checked={cfg.feature_kyc_enabled} onChange={(v) => set({ feature_kyc_enabled: v })} />
      <Tog id="ff_sub" label="Sub-Accounts" desc="FEATURE_SUB_ACCOUNTS_ENABLED" checked={cfg.feature_sub_accounts_enabled} onChange={(v) => set({ feature_sub_accounts_enabled: v })} />
    </Card>
  </>
);

// ── LLM tab ───────────────────────────────────────────────────────────────────

const LlmTab: React.FC<{ cfg: PlatformConfig; set: (p: Partial<PlatformConfig>) => void }> = ({ cfg, set }) => (
  <>
    <Card>
      <SectionHeader icon="🤖" title="LLM / AI Provider" desc="Primary LLM provider for AI features. LLM_*" />
      <Sel label="Provider" desc="LLM_PROVIDER" value={cfg.llm_provider}
        options={['openai','anthropic','google','mistral','local'].map((v) => ({ value: v, label: v }))}
        onChange={(v) => set({ llm_provider: v })} />
      <Txt label="Model" desc="LLM_MODEL" value={cfg.llm_model} placeholder="gpt-4o" onChange={(v) => set({ llm_model: v })} />
      <Txt label="API Key" desc="LLM_API_KEY" value={cfg.llm_api_key} password placeholder="sk-..." onChange={(v) => set({ llm_api_key: v })} />
      <Txt label="Base URL" desc="LLM_BASE_URL — override for local/proxy" value={cfg.llm_base_url} placeholder="https://api.openai.com/v1" onChange={(v) => set({ llm_base_url: v })} />
      <Num label="Temperature" desc="LLM_TEMPERATURE" value={cfg.llm_temperature} step={0.05} min={0} max={2} onChange={(v) => set({ llm_temperature: v })} />
      <Num label="Max Tokens" desc="LLM_MAX_TOKENS" value={cfg.llm_max_tokens} min={256} max={128000} onChange={(v) => set({ llm_max_tokens: v })} />
      <Num label="Timeout (s)" desc="LLM_TIMEOUT_S" value={cfg.llm_timeout_s} min={5} onChange={(v) => set({ llm_timeout_s: v })} />
      <Num label="Max Retries" desc="LLM_MAX_RETRIES" value={cfg.llm_max_retries} min={0} max={10} onChange={(v) => set({ llm_max_retries: v })} />
    </Card>
    <Card>
      <SectionHeader icon="🔄" title="Fallback Provider" desc="Used when primary LLM is unavailable." />
      <Sel label="Fallback Provider" desc="LLM_FALLBACK_PROVIDER" value={cfg.llm_fallback_provider}
        options={['openai','anthropic','google','mistral','none'].map((v) => ({ value: v, label: v }))}
        onChange={(v) => set({ llm_fallback_provider: v })} />
      <Txt label="Fallback Model" desc="LLM_FALLBACK_MODEL" value={cfg.llm_fallback_model} placeholder="claude-3-5-sonnet-20241022" onChange={(v) => set({ llm_fallback_model: v })} />
    </Card>
    <Card>
      <SectionHeader icon="🔢" title="Embeddings" desc="Vector embedding model for semantic search and RAG." />
      <Txt label="Embedding Model" desc="LLM_EMBEDDING_MODEL" value={cfg.llm_embedding_model} placeholder="text-embedding-3-small" onChange={(v) => set({ llm_embedding_model: v })} />
      <Num label="Embedding Dimensions" desc="LLM_EMBEDDING_DIMENSIONS" value={cfg.llm_embedding_dimensions} min={64} max={4096} onChange={(v) => set({ llm_embedding_dimensions: v })} />
    </Card>
  </>
);

// ── Drawdown tab ──────────────────────────────────────────────────────────────

const DrawdownTab: React.FC<{ cfg: PlatformConfig; set: (p: Partial<PlatformConfig>) => void }> = ({ cfg, set }) => (
  <>
    <Card>
      <SectionHeader icon="📉" title="Drawdown Controls" desc="Hard/soft drawdown limits and recovery behaviour. DRAWDOWN_*" />
      <Num label="Hard Stop (%)" desc="DRAWDOWN_HARD_STOP_PCT — halt all trading" value={cfg.drawdown_hard_stop_pct} step={0.01} min={0.01} max={1} onChange={(v) => set({ drawdown_hard_stop_pct: v })} />
      <Num label="Soft Warn (%)" desc="DRAWDOWN_SOFT_WARN_PCT — trigger warning + size reduction" value={cfg.drawdown_soft_warn_pct} step={0.01} min={0.01} max={1} onChange={(v) => set({ drawdown_soft_warn_pct: v })} />
      <Num label="Trailing Lookback Bars" desc="DRAWDOWN_TRAILING_LOOKBACK_BARS" value={cfg.drawdown_trailing_lookback_bars} min={10} onChange={(v) => set({ drawdown_trailing_lookback_bars: v })} />
      <Num label="Recovery Size Scale" desc="DRAWDOWN_RECOVERY_SIZE_SCALE — position size multiplier during recovery" value={cfg.drawdown_recovery_size_scale} step={0.05} min={0.1} max={1} onChange={(v) => set({ drawdown_recovery_size_scale: v })} />
      <Num label="Reduce Factor" desc="DRAWDOWN_REDUCE_FACTOR — size multiplier on soft warn" value={cfg.drawdown_reduce_factor} step={0.05} min={0.1} max={1} onChange={(v) => set({ drawdown_reduce_factor: v })} />
      <Sel label="Recovery Mode" desc="DRAWDOWN_RECOVERY_MODE" value={cfg.drawdown_recovery_mode}
        options={['reduce_size','pause','close_all','none'].map((v) => ({ value: v, label: v }))}
        onChange={(v) => set({ drawdown_recovery_mode: v })} />
      <Tog id="dd_trail" label="Trailing Drawdown" desc="DRAWDOWN_TRAILING_ENABLED — track from equity peak" checked={cfg.drawdown_trailing_enabled} onChange={(v) => set({ drawdown_trailing_enabled: v })} />
      <Tog id="dd_reset" label="Daily Reset" desc="DRAWDOWN_DAILY_RESET — reset drawdown counter each day" checked={cfg.drawdown_daily_reset} onChange={(v) => set({ drawdown_daily_reset: v })} />
      <Tog id="dd_notify" label="Notify on Breach" desc="DRAWDOWN_NOTIFY_ON_BREACH" checked={cfg.drawdown_notify_on_breach} onChange={(v) => set({ drawdown_notify_on_breach: v })} />
      <Tog id="dd_reduce" label="Auto-Reduce on Warn" desc="DRAWDOWN_AUTO_REDUCE_ON_WARN" checked={cfg.drawdown_auto_reduce_on_warn} onChange={(v) => set({ drawdown_auto_reduce_on_warn: v })} />
    </Card>
  </>
);

// ── Prop Firm Config tab ──────────────────────────────────────────────────────

const PropFirmConfigTab: React.FC<{ cfg: PlatformConfig; set: (p: Partial<PlatformConfig>) => void }> = ({ cfg, set }) => (
  <>
    <Card>
      <SectionHeader icon="🏆" title="Prop Firm Mode" desc="Enforce prop firm challenge rules automatically. PROP_FIRM_*" />
      <Tog id="pf_en" label="Enable Prop Firm Mode" desc="PROP_FIRM_ENABLED" checked={cfg.prop_firm_enabled} onChange={(v) => set({ prop_firm_enabled: v })} />
      <Divider />
      <Sel label="Provider" desc="PROP_FIRM_PROVIDER" value={cfg.prop_firm_provider}
        options={['ftmo','mff','e8','the5ers','topstep','custom'].map((v) => ({ value: v, label: v }))}
        onChange={(v) => set({ prop_firm_provider: v })} />
      <Num label="Account Size (USD)" desc="PROP_FIRM_ACCOUNT_SIZE" value={cfg.prop_firm_account_size} min={1000} step={1000} onChange={(v) => set({ prop_firm_account_size: v })} />
      <Num label="Daily Loss Limit (%)" desc="PROP_FIRM_DAILY_LOSS_LIMIT_PCT" value={cfg.prop_firm_daily_loss_limit_pct} step={0.005} min={0.001} max={0.2} onChange={(v) => set({ prop_firm_daily_loss_limit_pct: v })} />
      <Num label="Max Drawdown (%)" desc="PROP_FIRM_MAX_DRAWDOWN_PCT" value={cfg.prop_firm_max_drawdown_pct} step={0.005} min={0.001} max={0.5} onChange={(v) => set({ prop_firm_max_drawdown_pct: v })} />
      <Num label="Profit Target (%)" desc="PROP_FIRM_PROFIT_TARGET_PCT" value={cfg.prop_firm_profit_target_pct} step={0.005} min={0.001} max={1} onChange={(v) => set({ prop_firm_profit_target_pct: v })} />
      <Num label="Min Trading Days" desc="PROP_FIRM_MIN_TRADING_DAYS" value={cfg.prop_firm_min_trading_days} min={1} max={60} onChange={(v) => set({ prop_firm_min_trading_days: v })} />
      <Num label="Max Position Size (%)" desc="PROP_FIRM_MAX_POSITION_SIZE_PCT" value={cfg.prop_firm_max_position_size_pct} step={0.005} min={0.001} max={1} onChange={(v) => set({ prop_firm_max_position_size_pct: v })} />
      <Num label="Consistency Rule (%)" desc="PROP_FIRM_CONSISTENCY_RULE_PCT — max % of profit from single day" value={cfg.prop_firm_consistency_rule_pct} step={0.05} min={0} max={1} onChange={(v) => set({ prop_firm_consistency_rule_pct: v })} />
      <Tog id="pf_news" label="News Trading Allowed" desc="PROP_FIRM_NEWS_TRADING_ALLOWED" checked={cfg.prop_firm_news_trading_allowed} onChange={(v) => set({ prop_firm_news_trading_allowed: v })} />
      <Tog id="pf_wknd" label="Weekend Holding Allowed" desc="PROP_FIRM_WEEKEND_HOLDING_ALLOWED" checked={cfg.prop_firm_weekend_holding_allowed} onChange={(v) => set({ prop_firm_weekend_holding_allowed: v })} />
      <Tog id="pf_scale" label="Scaling Plan Enabled" desc="PROP_FIRM_SCALING_ENABLED" checked={cfg.prop_firm_scaling_enabled} onChange={(v) => set({ prop_firm_scaling_enabled: v })} />
    </Card>
  </>
);

// ── Position Sizing tab ───────────────────────────────────────────────────────

const PositionSizingTab: React.FC<{ cfg: PlatformConfig; set: (p: Partial<PlatformConfig>) => void }> = ({ cfg, set }) => (
  <>
    <Card>
      <SectionHeader icon="📐" title="Position Sizing" desc="How trade size is calculated for each signal. POSITION_SIZING_*" />
      <Sel label="Method" desc="POSITION_SIZING_METHOD" value={cfg.position_sizing_method}
        options={['risk_pct','fixed_lots','kelly','volatility_target','atr_based'].map((v) => ({ value: v, label: v }))}
        onChange={(v) => set({ position_sizing_method: v })} />
      <Num label="Fixed Lots" desc="POSITION_SIZING_FIXED_LOTS — used when method=fixed_lots" value={cfg.position_sizing_fixed_lots} step={0.001} min={0.001} onChange={(v) => set({ position_sizing_fixed_lots: v })} />
      <Num label="Risk % per Trade" desc="POSITION_SIZING_RISK_PCT — used when method=risk_pct" value={cfg.position_sizing_risk_pct} step={0.001} min={0.001} max={0.5} onChange={(v) => set({ position_sizing_risk_pct: v })} />
      <Num label="Kelly Fraction" desc="POSITION_SIZING_KELLY_FRACTION — fractional Kelly multiplier" value={cfg.position_sizing_kelly_fraction} step={0.05} min={0.05} max={1} onChange={(v) => set({ position_sizing_kelly_fraction: v })} />
      <Num label="Max Lots" desc="POSITION_SIZING_MAX_LOTS — hard cap" value={cfg.position_sizing_max_lots} step={0.1} min={0.001} onChange={(v) => set({ position_sizing_max_lots: v })} />
      <Num label="Min Lots" desc="POSITION_SIZING_MIN_LOTS — minimum viable size" value={cfg.position_sizing_min_lots} step={0.001} min={0.001} onChange={(v) => set({ position_sizing_min_lots: v })} />
      <Num label="ATR Multiplier" desc="POSITION_SIZING_ATR_MULTIPLIER — stop distance in ATRs" value={cfg.position_sizing_atr_multiplier} step={0.1} min={0.1} onChange={(v) => set({ position_sizing_atr_multiplier: v })} />
      <Num label="ATR Period" desc="POSITION_SIZING_ATR_PERIOD" value={cfg.position_sizing_atr_period} min={5} max={100} onChange={(v) => set({ position_sizing_atr_period: v })} />
      <Num label="Volatility Target" desc="POSITION_SIZING_VOLATILITY_TARGET — daily vol target" value={cfg.position_sizing_volatility_target} step={0.001} min={0.001} max={0.5} onChange={(v) => set({ position_sizing_volatility_target: v })} />
      <Num label="Max Correlated Exposure" desc="POSITION_SIZING_MAX_CORRELATED_EXPOSURE — total exposure to correlated assets" value={cfg.position_sizing_max_correlated_exposure} step={0.01} min={0} max={1} onChange={(v) => set({ position_sizing_max_correlated_exposure: v })} />
      <Tog id="ps_corr" label="Correlation Scaling" desc="POSITION_SIZING_USE_CORRELATION_SCALING — reduce size when correlated positions exist" checked={cfg.position_sizing_use_correlation_scaling} onChange={(v) => set({ position_sizing_use_correlation_scaling: v })} />
    </Card>
  </>
);


// ── SMTP / Email tab ──────────────────────────────────────────────────────────

const SmtpTab: React.FC<{ cfg: PlatformConfig; set: (p: Partial<PlatformConfig>) => void }> = ({ cfg, set }) => {
  const [testing, setTesting] = React.useState(false);
  const [testResult, setTestResult] = React.useState<'ok' | 'fail' | null>(null);
  const [testMsg, setTestMsg] = React.useState('');

  const testSmtp = async () => {
    setTesting(true); setTestResult(null); setTestMsg('');
    try {
      await superadminApi.testSmtpConfig({
        host: cfg.smtp_host, port: cfg.smtp_port,
        user: cfg.smtp_user, password: cfg.smtp_password,
        from: cfg.smtp_from, tls: cfg.smtp_tls,
      });
      setTestResult('ok'); setTestMsg('SMTP connection successful');
    } catch (e: unknown) {
      setTestResult('fail');
      setTestMsg(extractApiError(e, 'SMTP test failed'));
    } finally { setTesting(false); }
  };

  return (
    <>
      <Card>
        <SectionHeader icon="📧" title="SMTP Configuration" desc="Outbound email for notifications, password resets, and alerts." />
        <Tog id="smtp_en" label="Enable SMTP" desc="Send transactional emails via SMTP" checked={cfg.smtp_enabled} onChange={(v) => set({ smtp_enabled: v })} />
        <Divider />
        <Txt label="SMTP Host" desc="SMTP_HOST" value={cfg.smtp_host} placeholder="smtp.gmail.com" onChange={(v) => set({ smtp_host: v })} />
        <Num label="SMTP Port" desc="SMTP_PORT" value={cfg.smtp_port} min={1} max={65535} onChange={(v) => set({ smtp_port: v })} />
        <Txt label="SMTP Username" desc="SMTP_USER" value={cfg.smtp_user} placeholder="user@domain.com" onChange={(v) => set({ smtp_user: v })} />
        <Txt label="SMTP Password" desc="SMTP_PASSWORD" value={cfg.smtp_password} password onChange={(v) => set({ smtp_password: v })} />
        <Txt label="From Address" desc="EMAIL_FROM" value={cfg.smtp_from} placeholder="noreply@hopefx.ai" onChange={(v) => set({ smtp_from: v })} />
        <Txt label="From Name" desc="EMAIL_FROM_NAME" value={cfg.smtp_from_name} placeholder="HOPEFX Trading" onChange={(v) => set({ smtp_from_name: v })} />
        <Tog id="smtp_tls" label="Use TLS (STARTTLS)" desc="SMTP_TLS" checked={cfg.smtp_tls} onChange={(v) => set({ smtp_tls: v })} />
        <div style={{ marginTop: 16, display: 'flex', alignItems: 'center', gap: 12 }}>
          <Button onClick={testSmtp} disabled={testing} variant="secondary">
            {testing ? 'Testing…' : '🔌 Test SMTP Connection'}
          </Button>
          {testResult && (
            <span style={{ fontSize: 13, fontWeight: 600, color: testResult === 'ok' ? '#22c55e' : '#ef4444' }}>
              {testResult === 'ok' ? '✓' : '✗'} {testMsg}
            </span>
          )}
        </div>
      </Card>
      <Card>
        <SectionHeader icon="🚨" title="Alertmanager SMTP" desc="SMTP relay used by Prometheus Alertmanager for alert emails." />
        <Txt label="Alertmanager SMTP Host" desc="ALERTMANAGER_SMTP_HOST" value={cfg.alertmanager_smtp_host} placeholder="localhost:587" onChange={(v) => set({ alertmanager_smtp_host: v })} />
        <Txt label="Alert From Address" desc="ALERTMANAGER_SMTP_FROM" value={cfg.alertmanager_smtp_from} placeholder="alerts@hopefx.ai" onChange={(v) => set({ alertmanager_smtp_from: v })} />
        <Txt label="Alert To Address" desc="ALERTMANAGER_SMTP_TO" value={cfg.alertmanager_smtp_to} placeholder="ops@hopefx.ai" onChange={(v) => set({ alertmanager_smtp_to: v })} />
      </Card>
    </>
  );
};

// ── Monitoring / Observability tab ────────────────────────────────────────────

const MonitoringTab: React.FC<{ cfg: PlatformConfig; set: (p: Partial<PlatformConfig>) => void }> = ({ cfg, set }) => (
  <>
    <Card>
      <SectionHeader icon="🐛" title="Sentry Error Tracking" desc="Distributed error tracking and performance monitoring." />
      <Txt label="Sentry DSN" desc="SENTRY_DSN — leave blank to disable" value={cfg.sentry_dsn} placeholder="https://xxx@sentry.io/yyy" onChange={(v) => set({ sentry_dsn: v })} />
      <Sel label="Sentry Environment" desc="SENTRY_ENVIRONMENT" value={cfg.sentry_environment}
        options={[
          { value: 'production', label: 'Production' },
          { value: 'staging', label: 'Staging' },
          { value: 'development', label: 'Development' },
        ]}
        onChange={(v) => set({ sentry_environment: v })} />
      <Num label="Traces Sample Rate" desc="SENTRY_TRACES_SAMPLE_RATE (0.0–1.0)" value={cfg.sentry_traces_sample_rate} step={0.01} min={0} max={1} onChange={(v) => set({ sentry_traces_sample_rate: v })} />
      <Num label="Profiles Sample Rate" desc="SENTRY_PROFILES_SAMPLE_RATE (0.0–1.0)" value={cfg.sentry_profiles_sample_rate} step={0.01} min={0} max={1} onChange={(v) => set({ sentry_profiles_sample_rate: v })} />
    </Card>
    <Card>
      <SectionHeader icon="📈" title="Prometheus Metrics" desc="Metrics scraping and alerting configuration." />
      <Txt label="Prometheus URL" desc="PROMETHEUS_URL" value={cfg.prometheus_url} placeholder="http://prometheus:9090" onChange={(v) => set({ prometheus_url: v })} />
      <Num label="Prometheus Port" desc="PROMETHEUS_PORT" value={cfg.prometheus_port} min={1} max={65535} onChange={(v) => set({ prometheus_port: v })} />
      <Num label="Scrape Interval (seconds)" desc="PROMETHEUS_SCRAPE_INTERVAL_SECONDS" value={cfg.prometheus_scrape_interval_seconds} min={5} max={300} onChange={(v) => set({ prometheus_scrape_interval_seconds: v })} />
    </Card>
  </>
);

// ── Celery / Task Queue tab ───────────────────────────────────────────────────

const CeleryTab: React.FC<{ cfg: PlatformConfig; set: (p: Partial<PlatformConfig>) => void }> = ({ cfg, set }) => (
  <>
    <Card>
      <SectionHeader icon="⚙️" title="Celery Task Queue" desc="Async task processing for ML retraining, reports, and background jobs." />
      <Txt label="Broker URL" desc="CELERY_BROKER_URL — Redis or RabbitMQ" value={cfg.celery_broker_url} placeholder="redis://redis:6379/1" onChange={(v) => set({ celery_broker_url: v })} />
      <Txt label="Result Backend" desc="CELERY_RESULT_BACKEND" value={cfg.celery_result_backend} placeholder="redis://redis:6379/2" onChange={(v) => set({ celery_result_backend: v })} />
      <Sel label="Task Serializer" desc="CELERY_TASK_SERIALIZER" value={cfg.celery_task_serializer}
        options={[
          { value: 'json', label: 'JSON' },
          { value: 'msgpack', label: 'MessagePack' },
          { value: 'pickle', label: 'Pickle (not recommended)' },
        ]}
        onChange={(v) => set({ celery_task_serializer: v })} />
      <Num label="Result Expiry (seconds)" desc="CELERY_RESULT_EXPIRES" value={cfg.celery_result_expires} min={60} onChange={(v) => set({ celery_result_expires: v })} />
      <Num label="Worker Concurrency" desc="CELERY_WORKER_CONCURRENCY — parallel task slots" value={cfg.celery_worker_concurrency} min={1} max={64} onChange={(v) => set({ celery_worker_concurrency: v })} />
      <Num label="Max Tasks Per Child" desc="CELERY_MAX_TASKS_PER_CHILD — restart worker after N tasks" value={cfg.celery_max_tasks_per_child} min={100} onChange={(v) => set({ celery_max_tasks_per_child: v })} />
    </Card>
  </>
);

// ── Compliance thresholds tab ─────────────────────────────────────────────────

const ComplianceTab: React.FC<{ cfg: PlatformConfig; set: (p: Partial<PlatformConfig>) => void }> = ({ cfg, set }) => (
  <>
    <Card>
      <SectionHeader icon="🪪" title="KYC Requirements" desc="Know Your Customer verification gates." />
      <Tog id="kyc_live" label="Require KYC for Live Trading" desc="Block live trading until KYC is approved" checked={cfg.kyc_required_for_live} onChange={(v) => set({ kyc_required_for_live: v })} />
    </Card>
    <Card>
      <SectionHeader icon="🔍" title="AML Thresholds" desc="Anti-Money Laundering transaction monitoring limits." />
      <Num label="Single Transaction Threshold (USD)" desc="Transactions above this trigger AML review" value={cfg.aml_transaction_threshold} min={1000} step={1000} onChange={(v) => set({ aml_transaction_threshold: v })} />
      <Num label="Daily Volume Threshold (USD)" desc="Daily volume above this triggers AML review" value={cfg.aml_daily_volume_threshold} min={5000} step={5000} onChange={(v) => set({ aml_daily_volume_threshold: v })} />
      <Tog id="sanctions" label="Enable Sanctions Screening" desc="Screen all users against OFAC/UN sanctions lists" checked={cfg.sanctions_check_enabled} onChange={(v) => set({ sanctions_check_enabled: v })} />
    </Card>
    <Card>
      <SectionHeader icon="🔒" title="GDPR / Data Privacy" desc="Data retention and erasure policy configuration." />
      <Num label="Data Retention (days)" desc="How long to retain user data after account closure" value={cfg.gdpr_data_retention_days} min={30} max={3650} onChange={(v) => set({ gdpr_data_retention_days: v })} />
      <Num label="Erasure Grace Period (days)" desc="Days before erasure request is executed" value={cfg.gdpr_erasure_grace_days} min={0} max={90} onChange={(v) => set({ gdpr_erasure_grace_days: v })} />
    </Card>
    <Card>
      <SectionHeader icon="📋" title="Regulatory Reporting" desc="Automated regulatory report generation." />
      <Tog id="reg_report" label="Enable Regulatory Reporting" desc="Auto-generate CFTC/FCA/MiFID II reports" checked={cfg.regulatory_reporting_enabled} onChange={(v) => set({ regulatory_reporting_enabled: v })} />
    </Card>
  </>
);

// ── Diagnostics tab ───────────────────────────────────────────────────────────

// ── Infrastructure Tab ────────────────────────────────────────────────────────

const InfrastructureTab: React.FC = () => {
  const [infraHealth, setInfraHealth] = React.useState<Record<string, unknown> | null>(null);
  const [cacheStats, setCacheStats]   = React.useState<Record<string, unknown> | null>(null);
  const [dbStats, setDbStats]         = React.useState<Record<string, unknown> | null>(null);
  const [queueStats, setQueueStats]   = React.useState<Record<string, unknown> | null>(null);
  const [loading, setLoading]         = React.useState(false);
  const [flushPattern, setFlushPattern] = React.useState('');
  const [flushing, setFlushing]       = React.useState(false);
  const [msg, setMsg]                 = React.useState('');
  const [msgOk, setMsgOk]             = React.useState(false);
  const [loadErr, setLoadErr]         = React.useState('');
  const [confirmFlushAll, setConfirmFlushAll] = React.useState(false);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const [h, c, d, q] = await Promise.allSettled([
        superadminApi.infraHealth(),
        superadminApi.cacheStats(),
        superadminApi.dbStats(),
        superadminApi.queueStats(),
      ]);
      const failed: string[] = [];
      if (h.status === 'fulfilled') setInfraHealth(h.value.data); else failed.push('infrastructure health');
      if (c.status === 'fulfilled') setCacheStats(c.value.data); else failed.push('cache stats');
      if (d.status === 'fulfilled') setDbStats(d.value.data); else failed.push('database stats');
      if (q.status === 'fulfilled') setQueueStats(q.value.data); else failed.push('queue stats');
      // An absent panel means "could not read", not "nothing to report".
      setLoadErr(failed.length ? `Could not load: ${failed.join(', ')}.` : '');
    } finally { setLoading(false); }
  }, []);

  React.useEffect(() => { load(); }, [load]);

  const flushCache = async () => {
    setFlushing(true); setMsg(''); setConfirmFlushAll(false);
    try {
      await superadminApi.flushCache(flushPattern || undefined);
      setMsg(`Cache flushed${flushPattern ? ` (pattern: ${flushPattern})` : ' (all keys)'}`);
      setMsgOk(true);
      setTimeout(load, 500);
    } catch (e) {
      setMsg(extractApiError(e, 'Cache flush failed'));
      setMsgOk(false);
    }
    finally { setFlushing(false); }
  };

  /** Flushing every key is unscoped and unrecoverable — make it a two-step action. */
  const requestFlush = () => {
    if (flushPattern.trim()) { void flushCache(); return; }
    setConfirmFlushAll(true);
  };

  const statusColor = (s: string) =>
    s === 'healthy' || s === 'ok' ? '#22c55e' : s === 'degraded' || s === 'warning' ? '#f59e0b' : '#ef4444';

  return (
    <>
      <Card>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <SectionHeader icon="🏗️" title="Infrastructure Health" />
          <Button onClick={load} disabled={loading} variant="secondary" size="sm">
            {loading ? '…' : '↻ Refresh'}
          </Button>
        </div>
        {loadErr && <ActionBanner message={loadErr} ok={false} onDismiss={() => setLoadErr('')} />}
        {infraHealth && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 10 }}>
            {Object.entries(infraHealth as Record<string, { status?: string; latency_ms?: number; detail?: string }>).map(([key, val]) => {
              if (typeof val !== 'object' || !val) return null;
              const s = val.status ?? 'unknown';
              return (
                <div key={key} style={{
                  background: '#0f172a', border: `1px solid ${statusColor(s)}33`,
                  borderRadius: 8, padding: '12px 14px',
                }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', marginBottom: 4 }}>
                    {key.replace(/_/g, ' ')}
                  </div>
                  <div style={{ fontSize: 13, fontWeight: 700, color: statusColor(s) }}>{s.toUpperCase()}</div>
                  {val.latency_ms !== undefined && (
                    <div style={{ fontSize: 11, color: '#475569', marginTop: 2 }}>{val.latency_ms}ms</div>
                  )}
                  {val.detail && (
                    <div style={{ fontSize: 11, color: '#475569', marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {val.detail}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </Card>

      <Card>
        <SectionHeader icon="⚡" title="Redis Cache Stats" />
        {cacheStats && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 10, marginBottom: 16 }}>
            {[
              { label: 'Connected Clients', value: String(cacheStats.connected_clients ?? '—') },
              { label: 'Used Memory', value: `${cacheStats.used_memory_mb ?? '—'} MB` },
              { label: 'Total Keys', value: String(cacheStats.total_keys ?? '—') },
              { label: 'Keyspace Hits', value: String(cacheStats.keyspace_hits ?? '—') },
              { label: 'Keyspace Misses', value: String(cacheStats.keyspace_misses ?? '—') },
              { label: 'Commands/sec', value: String(cacheStats.instantaneous_ops_per_sec ?? '—') },
            ].map((m) => (
              <div key={m.label} style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: '10px 14px' }}>
                <div style={{ fontSize: 11, color: '#64748b', marginBottom: 4 }}>{m.label}</div>
                <div style={{ fontSize: 16, fontWeight: 700, color: '#f1f5f9' }}>{m.value}</div>
              </div>
            ))}
          </div>
        )}
        <Divider />
        <div style={{ display: 'flex', gap: 10, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <Field label="Flush Pattern (optional)" description="e.g. 'hopefx:orders:*' — leave blank to flush all">
            <Input
              type="text" value={flushPattern} placeholder="key:pattern:*"
              onChange={(e) => setFlushPattern(e.target.value)}
            />
          </Field>
          <Button onClick={requestFlush} disabled={flushing} variant="danger" style={{ marginBottom: 20 }}>
            {flushing ? 'Flushing…' : '🗑️ Flush Cache'}
          </Button>
        </div>
        {confirmFlushAll && (
          <div
            role="alertdialog"
            aria-label="Confirm full cache flush"
            style={{
              background: '#450a0a', border: '1px solid #dc2626', borderRadius: 8,
              padding: '12px 14px', marginBottom: 12,
            }}
          >
            <div style={{ fontSize: 13, color: '#fecaca', marginBottom: 10 }}>
              No pattern set — this will evict <strong>every key</strong> in Redis, including live
              sessions and cached market data. Continue?
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <Button onClick={flushCache} disabled={flushing} variant="danger" size="sm">
                {flushing ? 'Flushing…' : 'Yes, flush all keys'}
              </Button>
              <Button onClick={() => setConfirmFlushAll(false)} variant="secondary" size="sm">
                Cancel
              </Button>
            </div>
          </div>
        )}
        <ActionBanner message={msg} ok={msgOk} onDismiss={() => setMsg('')} />
      </Card>

      <Card>
        <SectionHeader icon="🗄️" title="Database Stats" />
        {dbStats && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 10 }}>
            {Object.entries(dbStats as Record<string, unknown>).filter(([, v]) => typeof v !== 'object').map(([key, val]) => (
              <div key={key} style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: '10px 14px' }}>
                <div style={{ fontSize: 11, color: '#64748b', marginBottom: 4 }}>{key.replace(/_/g, ' ')}</div>
                <div style={{ fontSize: 14, fontWeight: 700, color: '#f1f5f9' }}>{String(val)}</div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card>
        <SectionHeader icon="📬" title="Task Queue Stats" />
        {queueStats && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 10 }}>
            {Object.entries(queueStats as Record<string, unknown>).filter(([, v]) => typeof v !== 'object').map(([key, val]) => (
              <div key={key} style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: '10px 14px' }}>
                <div style={{ fontSize: 11, color: '#64748b', marginBottom: 4 }}>{key.replace(/_/g, ' ')}</div>
                <div style={{ fontSize: 14, fontWeight: 700, color: '#f1f5f9' }}>{String(val)}</div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </>
  );
};

// ── Diagnostics Tab ───────────────────────────────────────────────────────────

const DiagnosticsTab: React.FC = () => {
  const [summary, setSummary] = React.useState<Record<string, unknown> | null>(null);
  const [report, setReport] = React.useState<Record<string, unknown> | null>(null);
  const [running, setRunning] = React.useState(false);
  const [remediating, setRemediating] = React.useState(false);
  const [msg, setMsg] = React.useState('');
  const [msgOk, setMsgOk] = React.useState(false);
  const [summaryErr, setSummaryErr] = React.useState('');
  const [confirmRemediate, setConfirmRemediate] = React.useState(false);

  const loadSummary = React.useCallback(async () => {
    try {
      const res = await superadminApi.diagnosticsSummary();
      setSummary(res.data);
      setSummaryErr('');
    } catch (e) {
      setSummaryErr(extractApiError(e, 'Failed to load the diagnostics summary'));
    }
  }, []);

  React.useEffect(() => { loadSummary(); }, [loadSummary]);

  const runDiag = async () => {
    setRunning(true); setMsg('');
    try {
      await superadminApi.diagnosticsRun();
      setMsg('Diagnostic run started — polling for results…');
      setMsgOk(true);
      setTimeout(() => {
        // The fetch of the finished report can fail on its own; without this the
        // banner sits on "polling for results…" forever and the rejection is
        // unhandled.
        void (async () => {
          try {
            const res = await superadminApi.diagnosticsReport();
            setReport(res.data);
            await loadSummary();
            setMsg('');
          } catch (e) {
            setMsg(extractApiError(e, 'Diagnostics ran, but the report could not be fetched'));
            setMsgOk(false);
          }
        })();
      }, 4000);
    } catch (e) {
      setMsg(extractApiError(e, 'Failed to start diagnostic run'));
      setMsgOk(false);
    }
    finally { setRunning(false); }
  };

  const remediate = async () => {
    setRemediating(true); setMsg(''); setConfirmRemediate(false);
    try {
      const res = await superadminApi.diagnosticsRemediate();
      setMsg(`Remediation complete — ${res.data.actions_taken} action(s) taken`);
      setMsgOk(true);
      loadSummary();
    } catch (e) {
      setMsg(extractApiError(e, 'Remediation failed'));
      setMsgOk(false);
    }
    finally { setRemediating(false); }
  };

  const score = summary ? Number(summary.health_score ?? 0) : null;
  const scoreColor = score === null ? '#94a3b8' : score >= 90 ? '#22c55e' : score >= 70 ? '#f59e0b' : '#ef4444';

  return (
    <>
      <Card>
        <SectionHeader icon="🔬" title="Platform Diagnostics" />
        <p style={{ fontSize: 13, color: '#64748b', marginBottom: 16 }}>
          Run the full diagnostic suite across all 12 check categories. Auto-remediates critical findings.
        </p>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 16 }}>
          <Button onClick={runDiag} disabled={running}>{running ? 'Running…' : '▶ Run Full Diagnostics'}</Button>
          <Button onClick={() => setConfirmRemediate(true)} disabled={remediating} variant="secondary">{remediating ? 'Remediating…' : '🔧 Auto-Remediate'}</Button>
          <Button onClick={loadSummary} variant="secondary">↻ Refresh</Button>
        </div>
        {confirmRemediate && (
          <div
            role="alertdialog"
            aria-label="Confirm auto-remediation"
            style={{
              background: '#451a03', border: '1px solid #d97706', borderRadius: 8,
              padding: '12px 14px', marginBottom: 12,
            }}
          >
            <div style={{ fontSize: 13, color: '#fed7aa', marginBottom: 10 }}>
              Auto-remediation applies corrective actions to live platform state without a preview.
              Run it now?
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <Button onClick={remediate} disabled={remediating} size="sm">
                {remediating ? 'Remediating…' : 'Yes, remediate'}
              </Button>
              <Button onClick={() => setConfirmRemediate(false)} variant="secondary" size="sm">
                Cancel
              </Button>
            </div>
          </div>
        )}
        {summaryErr && <ActionBanner message={summaryErr} ok={false} onDismiss={() => setSummaryErr('')} />}
        <ActionBanner message={msg} ok={msgOk} onDismiss={() => setMsg('')} />
        {summary && (
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            {[
              { label: 'Health Score', value: score !== null ? `${score}%` : '—', color: scoreColor },
              { label: 'Total Checks', value: String(summary.total_checks ?? 0), color: '#94a3b8' },
              { label: 'OK', value: String((summary.counts as Record<string,number>)?.ok ?? 0), color: '#22c55e' },
              { label: 'Warnings', value: String((summary.counts as Record<string,number>)?.warning ?? 0), color: '#f59e0b' },
              { label: 'Errors', value: String((summary.counts as Record<string,number>)?.error ?? 0), color: '#ef4444' },
              { label: 'Critical', value: String((summary.counts as Record<string,number>)?.critical ?? 0), color: '#dc2626' },
            ].map((m) => (
              <div key={m.label} style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: '10px 16px', textAlign: 'center', minWidth: 80 }}>
                <div style={{ fontSize: 20, fontWeight: 800, color: m.color }}>{m.value}</div>
                <div style={{ fontSize: 11, color: '#475569', marginTop: 2 }}>{m.label}</div>
              </div>
            ))}
          </div>
        )}
      </Card>
      {summary?.top_issues && (Array.isArray(summary.top_issues) && summary.top_issues.length > 0) && (
        <Card>
          <SectionHeader icon="⚠️" title="Top Issues" />
          {(summary.top_issues as Array<Record<string,string>>).map((issue, i) => (
            <div key={i} style={{ padding: '10px 14px', borderRadius: 8, background: '#450a0a', border: '1px solid #dc262633', marginBottom: 8 }}>
              <div style={{ fontWeight: 600, fontSize: 13, color: '#fca5a5' }}>{issue.check_name}</div>
              <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 4 }}>{issue.message}</div>
              {issue.remediation && <div style={{ fontSize: 11, color: '#64748b', marginTop: 4 }}>Fix: {issue.remediation}</div>}
            </div>
          ))}
        </Card>
      )}
      {report && (
        <Card>
          <SectionHeader icon="📋" title="Last Diagnostic Report" />
          <div style={{ fontSize: 12, color: '#64748b', marginBottom: 12 }}>
            Completed: {String(report.completed_at ?? 'N/A')}
          </div>
          {(report.results as Array<Record<string,string>> ?? []).map((r, i) => (
            <div key={i} style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              padding: '8px 12px', borderRadius: 6, marginBottom: 4,
              background: r.status === 'ok' ? '#052e16' : r.status === 'warning' ? '#451a03' : '#450a0a',
              border: `1px solid ${r.status === 'ok' ? '#16a34a33' : r.status === 'warning' ? '#d9770633' : '#dc262633'}`,
            }}>
              <div>
                <span style={{ fontSize: 13, fontWeight: 600, color: '#f1f5f9' }}>{r.check_name}</span>
                <div style={{ fontSize: 12, color: '#94a3b8' }}>{r.message}</div>
              </div>
              <span style={{ fontSize: 11, fontWeight: 700, color: r.status === 'ok' ? '#22c55e' : r.status === 'warning' ? '#f59e0b' : '#ef4444', textTransform: 'uppercase', flexShrink: 0, marginLeft: 12 }}>
                {r.status}
              </span>
            </div>
          ))}
        </Card>
      )}
    </>
  );
};


// ── Root component ────────────────────────────────────────────────────────────

const PlatformConfiguration: React.FC = () => {
  const [activeTab, setActiveTab] = useState('platform');

  // Platform config state
  const [cfg, setCfg]         = useState<PlatformConfig>(DEFAULT_PLATFORM);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving]   = useState(false);
  const [saved, setSaved]     = useState(false);
  const [saveError, setSaveError] = useState('');

  // Config validation state
  const [validating, setValidating] = useState(false);
  const [validationResult, setValidationResult] = useState<{
    valid: boolean; error_count: number; warning_count: number;
    issues: Array<{ severity: string; field: string; message: string }>;
  } | null>(null);

  // Healer state
  const [healer, setHealerState]   = useState<HealerConfig>(DEFAULT_HEALER);
  const [healerStatus, setHealerStatus] = useState<HealerStatus | null>(null);
  const [testIndex, setTestIndex]  = useState<TestIndex | null>(null);
  const [savingHealer, setSavingHealer] = useState(false);
  const [savedHealer, setSavedHealer]   = useState(false);
  const [healerSaveError, setHealerSaveError] = useState('');
  const [actionMsg, setActionMsg]  = useState('');
  // handleSave PUTs the FULL config — all 200+ fields. If the GET failed, `cfg`
  // is still DEFAULT_PLATFORM, so one save would overwrite every platform
  // setting with a default. Same for the healer config. Refuse to render an
  // editable form we could not populate (audit S7/S8).
  const [cfgLoadFailed, setCfgLoadFailed] = useState(false);
  const [healerLoadFailed, setHealerLoadFailed] = useState(false);
  const [validateErrMsg, setValidateErrMsg] = useState('');

  const setHealer = useCallback((patch: Partial<HealerConfig>) =>
    setHealerState((prev) => ({ ...prev, ...patch })), []);

  const set = useCallback((patch: Partial<PlatformConfig>) =>
    setCfg((prev) => ({ ...prev, ...patch })), []);

  // Load platform config
  const loadConfig = useCallback(async () => {
    setLoading(true);
    setCfgLoadFailed(false);
    try {
      const res = await superadminApi.platformConfig();
      setCfg((prev) => ({ ...prev, ...res.data }));
    } catch (e) {
      console.warn('[PlatformConfig] load failed:', e);
      setCfgLoadFailed(true);
    } finally {
      setLoading(false);
    }
  }, []);

  // Load healer config + status + test index
  const loadHealer = useCallback(async () => {
    try {
      const [cfgRes, statusRes, idxRes] = await Promise.allSettled([
        superadminApi.autoHealConfig(),
        superadminApi.autoHealStatus(),
        superadminApi.autoHealTestIndex(),
      ]);
      if (cfgRes.status === 'fulfilled') {
        setHealerState((prev) => ({ ...prev, ...cfgRes.value.data }));
        setHealerLoadFailed(false);
      } else {
        // DEFAULT_HEALER has self-healing enabled. Saving it after a failed read
        // would arm automated patching of the live platform.
        setHealerLoadFailed(true);
      }
      if (statusRes.status === 'fulfilled') setHealerStatus(statusRes.value.data);
      if (idxRes.status === 'fulfilled') setTestIndex(idxRes.value.data);
    } catch (e) {
      console.warn('[PlatformConfig] healer load failed:', e);
      setHealerLoadFailed(true);
    }
  }, []);

  useEffect(() => {
    loadConfig();
    loadHealer();
  }, [loadConfig, loadHealer]);

  // Save platform config — uses full-config PUT so all 200+ fields persist
  const handleSave = async () => {
    setSaving(true); setSaveError('');
    try {
      await superadminApi.savePlatformConfigFull(cfg);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (e: unknown) {
      setSaveError(extractApiError(e, 'Save failed'));
    } finally {
      setSaving(false);
    }
  };

  // Save healer config
  const handleSaveHealer = async () => {
    setSavingHealer(true); setHealerSaveError('');
    try {
      await superadminApi.autoHealSaveConfig(healer);
      setSavedHealer(true);
      setTimeout(() => setSavedHealer(false), 3000);
    } catch (e: unknown) {
      setHealerSaveError(extractApiError(e, 'Save failed'));
    } finally {
      setSavingHealer(false);
    }
  };

  const flash = (msg: string) => { setActionMsg(msg); setTimeout(() => setActionMsg(''), 5000); };

  const handleValidate = async () => {
    setValidating(true); setValidationResult(null);
    try {
      const res = await superadminApi.validatePlatformConfig();
      setValidationResult(res.data);
      setValidateErrMsg('');
    } catch (e) {
      // A missing result used to be indistinguishable from "nothing to report".
      setValidateErrMsg(extractApiError(e, 'Validation could not be run'));
    } finally { setValidating(false); }
  };

  const handleRebuildBaseline = async () => {
    try {
      await superadminApi.autoHealRebuildBaseline();
      flash('Baseline rebuilt successfully');
      loadHealer();
    } catch { flash('Baseline rebuild failed'); }
  };

  const handleRunTests = async () => {
    flash('Test run triggered…');
    try {
      await superadminApi.autoHealRunTests();
      flash('Test run complete — check status above');
      loadHealer();
    } catch { flash('Test run failed'); }
  };

  const handleReindexTests = async () => {
    flash('Re-indexing tests…');
    try {
      await superadminApi.autoHealReindexTests();
      flash('Test index rebuilt');
      loadHealer();
    } catch { flash('Re-index failed'); }
  };

  if (loading) return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: '#64748b', padding: 32 }}>
      <div style={{ width: 20, height: 20, border: '2px solid #334155', borderTopColor: '#3b82f6', borderRadius: '50%', animation: 'spin 0.7s linear infinite' }} />
      Loading platform configuration…
    </div>
  );

  if (cfgLoadFailed) return (
    <div>
      <SectionHeader icon="⚙️" title="Platform Configuration" desc="Every platform setting, parameter, threshold and flag." />
      <ActionBanner
        message={
          'Couldn\'t load the platform configuration. Nothing has been changed — but saving from ' +
          'here would PUT all 200+ fields at their default values over the live configuration.'
        }
        ok={false}
      />
      <div style={{ marginTop: 14 }}>
        <Button onClick={loadConfig} variant="secondary">Retry</Button>
      </div>
    </div>
  );

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
        <SectionHeader
          icon="🛠️"
          title="Platform Configuration"
          description="Every setting, parameter, threshold, and flag across the entire HOPEFX platform. Super Admin only."
        />
        <Button onClick={handleValidate} disabled={validating} variant="secondary" style={{ marginTop: 4, flexShrink: 0 }}>
          {validating ? '⏳ Validating…' : '✅ Validate Config'}
        </Button>
      </div>

      {/* Validation result banner */}
      {validateErrMsg && <ActionBanner message={validateErrMsg} ok={false} onDismiss={() => setValidateErrMsg('')} />}
      {validationResult && (
        <div style={{
          marginBottom: 16, padding: '12px 16px', borderRadius: 10,
          background: validationResult.valid ? '#052e16' : '#450a0a',
          border: `1px solid ${validationResult.valid ? '#16a34a' : '#dc2626'}`,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: validationResult.issues.length > 0 ? 10 : 0 }}>
            <span style={{ fontWeight: 700, fontSize: 13, color: validationResult.valid ? '#4ade80' : '#f87171' }}>
              {validationResult.valid ? '✓ Config valid' : `✗ ${validationResult.error_count} error(s), ${validationResult.warning_count} warning(s)`}
            </span>
            <button onClick={() => setValidationResult(null)} style={{ background: 'none', border: 'none', color: '#64748b', cursor: 'pointer', fontSize: 16 }}>×</button>
          </div>
          {validationResult.issues.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {validationResult.issues.map((issue, i) => (
                <div key={i} style={{ fontSize: 12, color: issue.severity === 'error' ? '#fca5a5' : '#fde68a' }}>
                  <span style={{ fontWeight: 700, textTransform: 'uppercase', marginRight: 6 }}>[{issue.severity}]</span>
                  <span style={{ color: '#94a3b8', marginRight: 4 }}>{issue.field}:</span>
                  {issue.message}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <TabBar active={activeTab} onChange={setActiveTab} />

      {activeTab === 'platform'   && <><PlatformTab cfg={cfg} set={set} /><SaveBar onSave={handleSave} saving={saving} saved={saved} error={saveError} /></>}
      {activeTab === 'database'   && <><DatabaseTab cfg={cfg} set={set} /><SaveBar onSave={handleSave} saving={saving} saved={saved} error={saveError} /></>}
      {activeTab === 'security'   && <><SecurityTab cfg={cfg} set={set} /><SaveBar onSave={handleSave} saving={saving} saved={saved} error={saveError} /></>}
      {activeTab === 'ml'         && <><MLTab cfg={cfg} set={set} /><SaveBar onSave={handleSave} saving={saving} saved={saved} error={saveError} /></>}
      {activeTab === 'decision'   && <><DecisionTab cfg={cfg} set={set} /><SaveBar onSave={handleSave} saving={saving} saved={saved} error={saveError} /></>}
      {activeTab === 'risk'       && <><RiskTab cfg={cfg} set={set} /><SaveBar onSave={handleSave} saving={saving} saved={saved} error={saveError} /></>}
      {activeTab === 'execution'  && <><ExecutionTab cfg={cfg} set={set} /><SaveBar onSave={handleSave} saving={saving} saved={saved} error={saveError} /></>}
      {activeTab === 'brokers'    && <><BrokersTab cfg={cfg} set={set} /><SaveBar onSave={handleSave} saving={saving} saved={saved} error={saveError} /></>}
      {activeTab === 'paper'      && <><PaperTradingTab cfg={cfg} set={set} /><SaveBar onSave={handleSave} saving={saving} saved={saved} error={saveError} /></>}
      {activeTab === 'ratelimit'  && <><RateLimitTab cfg={cfg} set={set} /><SaveBar onSave={handleSave} saving={saving} saved={saved} error={saveError} /></>}
      {activeTab === 'notify'      && <><NotifyTab cfg={cfg} set={set} /><SaveBar onSave={handleSave} saving={saving} saved={saved} error={saveError} /></>}
      {activeTab === 'smtp'        && <><SmtpTab cfg={cfg} set={set} /><SaveBar onSave={handleSave} saving={saving} saved={saved} error={saveError} /></>}
      {activeTab === 'monitoring'  && <><MonitoringTab cfg={cfg} set={set} /><SaveBar onSave={handleSave} saving={saving} saved={saved} error={saveError} /></>}
      {activeTab === 'celery'      && <><CeleryTab cfg={cfg} set={set} /><SaveBar onSave={handleSave} saving={saving} saved={saved} error={saveError} /></>}
      {activeTab === 'compliance'  && <><ComplianceTab cfg={cfg} set={set} /><SaveBar onSave={handleSave} saving={saving} saved={saved} error={saveError} /></>}
      {activeTab === 'lstm'          && <><LstmTab cfg={cfg} set={set} /><SaveBar onSave={handleSave} saving={saving} saved={saved} error={saveError} /></>}
      {activeTab === 'brain'         && <><BrainTab cfg={cfg} set={set} /><SaveBar onSave={handleSave} saving={saving} saved={saved} error={saveError} /></>}
      {activeTab === 'allocator'     && <><AllocatorTab cfg={cfg} set={set} /><SaveBar onSave={handleSave} saving={saving} saved={saved} error={saveError} /></>}
      {activeTab === 'anomaly'       && <><AnomalyTab cfg={cfg} set={set} /><SaveBar onSave={handleSave} saving={saving} saved={saved} error={saveError} /></>}
      {activeTab === 'macro'         && <><MacroTab cfg={cfg} set={set} /><SaveBar onSave={handleSave} saving={saving} saved={saved} error={saveError} /></>}
      {activeTab === 'online'        && <><OnlineTab cfg={cfg} set={set} /><SaveBar onSave={handleSave} saving={saving} saved={saved} error={saveError} /></>}
      {activeTab === 'sharpe'        && <><SharpeTab cfg={cfg} set={set} /><SaveBar onSave={handleSave} saving={saving} saved={saved} error={saveError} /></>}
      {activeTab === 'regime'        && <><RegimeTab cfg={cfg} set={set} /><SaveBar onSave={handleSave} saving={saving} saved={saved} error={saveError} /></>}
      {activeTab === 'signal_engine' && <><SignalEngineTab cfg={cfg} set={set} /><SaveBar onSave={handleSave} saving={saving} saved={saved} error={saveError} /></>}
      {activeTab === 'tca'           && <><TcaConfigTab cfg={cfg} set={set} /><SaveBar onSave={handleSave} saving={saving} saved={saved} error={saveError} /></>}
      {activeTab === 'backtest'      && <><BacktestConfigTab cfg={cfg} set={set} /><SaveBar onSave={handleSave} saving={saving} saved={saved} error={saveError} /></>}
      {activeTab === 'feature_flags' && <><FeatureFlagsConfigTab cfg={cfg} set={set} /><SaveBar onSave={handleSave} saving={saving} saved={saved} error={saveError} /></>}
      {activeTab === 'llm'           && <><LlmTab cfg={cfg} set={set} /><SaveBar onSave={handleSave} saving={saving} saved={saved} error={saveError} /></>}
      {activeTab === 'drawdown'      && <><DrawdownTab cfg={cfg} set={set} /><SaveBar onSave={handleSave} saving={saving} saved={saved} error={saveError} /></>}
      {activeTab === 'prop_firm'     && <><PropFirmConfigTab cfg={cfg} set={set} /><SaveBar onSave={handleSave} saving={saving} saved={saved} error={saveError} /></>}
      {activeTab === 'position_sizing' && <><PositionSizingTab cfg={cfg} set={set} /><SaveBar onSave={handleSave} saving={saving} saved={saved} error={saveError} /></>}
      {activeTab === 'killswitch'  && <><KillSwitchTab cfg={cfg} set={set} /><SaveBar onSave={handleSave} saving={saving} saved={saved} error={saveError} /></>}
      {activeTab === 'healing' && healerLoadFailed && (
        <div>
          <ActionBanner
            message={
              'Couldn\'t load the self-healer configuration. Nothing has been changed — saving from ' +
              'here would post DEFAULT_HEALER, which has self-healing enabled, over the real config.'
            }
            ok={false}
          />
          <div style={{ marginTop: 14 }}>
            <Button onClick={loadHealer} variant="secondary">Retry</Button>
          </div>
        </div>
      )}
      {activeTab === 'healing' && !healerLoadFailed && (
        <HealingTab
          healer={healer} setHealer={setHealer}
          healerStatus={healerStatus} testIndex={testIndex}
          onSaveHealer={handleSaveHealer} savingHealer={savingHealer}
          savedHealer={savedHealer} healerSaveError={healerSaveError}
          onRebuildBaseline={handleRebuildBaseline}
          onRunTests={handleRunTests}
          onReindexTests={handleReindexTests}
          actionMsg={actionMsg}
        />
      )}
      {activeTab === 'infrastructure' && <InfrastructureTab />}
      {activeTab === 'diagnostics' && <DiagnosticsTab />}
    </div>
  );
};

export default PlatformConfiguration;
