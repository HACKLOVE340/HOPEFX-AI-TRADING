// superadmin/types.ts — shared types for all superadmin sections

import { createContext, useContext } from 'react';

/**
 * Context that lets any section inside SuperAdminDashboard navigate to another tab
 * without requiring prop-drilling through every lazy-loaded section.
 */
export interface SuperAdminNavContextValue {
  navigateTo: (tab: SuperAdminTab) => void;
}
export const SuperAdminNavContext = createContext<SuperAdminNavContextValue>({
  navigateTo: () => { /* noop until provider mounts */ },
});
export const useSuperAdminNav = () => useContext(SuperAdminNavContext);

export type SuperAdminTab =
  | 'overview'
  | 'users'
  | 'platform'
  | 'ml-ai'
  | 'trading-engine'
  | 'financial'
  | 'security'
  | 'logs'
  | 'feature-flags'
  // Institutional-grade additions
  | 'compliance'
  | 'risk-management'
  | 'broker-management'
  | 'whitelabel'
  | 'system-health'
  | 'alerting'
  | 'gdpr'
  | 'reporting'
  | 'nuclear-controls'
  | 'rate-limiting'
  | 'audit-trail'
  | 'security-infra'
  | 'auto-healing'
  | 'reliability';

export interface PlatformOverview {
  total_users: number;
  active_users_24h: number;
  new_users_7d: number;
  total_trades_today: number;
  open_positions: number;
  revenue_mtd: number;
  revenue_currency: string;
  system_health: 'healthy' | 'degraded' | 'critical';
  uptime_pct: number;
  active_sessions: number;
  ml_model_accuracy: number;
  signals_generated_today: number;
  engine_status: 'running' | 'paused' | 'stopped';
  kill_switch_active: boolean;
  maintenance_mode: boolean;
  db_connections: number;
  redis_memory_mb: number;
  cpu_pct: number;
  memory_pct: number;
  error_rate_pct: number;
  avg_response_ms: number;
}

export interface SuperAdminUser {
  user_id: string;
  username: string;
  email: string;
  role: string;
  plan: string;
  status: 'active' | 'banned' | 'pending' | 'inactive';
  total_trades: number;
  created_at: string;
  last_login: string | null;
  two_fa_enabled: boolean;
  country: string | null;
  revenue_generated: number;
}

export interface MLModel {
  name: string;
  version: string;
  status: 'active' | 'training' | 'staged' | 'retired';
  accuracy: number;
  last_trained: string;
  predictions_today: number;
  /** null when drift was not measured. 0.0 is the BEST value on this scale, so
   *  a number alone cannot carry "the monitor is down" — read drift_state. */
  drift_score: number | null;
  /** "measured" — a real reading. "unmeasured" — the drift monitor could not be
   *  read. "not_serving" — a staged/retired version, which nothing measures. */
  drift_state?: 'measured' | 'unmeasured' | 'not_serving';
  deployed_at: string | null;
  /** Other registry entries pointing at the identical artifact. The VERSION
   *  column is sha256[:8], so these rows are indistinguishable without it. */
  shares_artifact_with?: string[];
  /** True when entries over these identical bytes disagree about their
   *  measured metrics — which cannot both be true. */
  metrics_conflict?: boolean;
}

export interface EngineMetric {
  label: string;
  value: string | number;
  unit?: string;
  status?: 'ok' | 'warn' | 'error';
}

export interface SecurityEvent {
  event_id: string;
  event_type: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  user_id: string | null;
  ip_address: string;
  detail: string;
  created_at: string;
}

export interface FeatureFlag {
  name: string;
  enabled: boolean;
  description: string;
  env_var: string;
  rollout_pct: number;
  user_overrides: number;
}

export interface LogEntry {
  ts: string;
  level: 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR' | 'CRITICAL';
  logger: string;
  message: string;
  trace_id?: string;
}

export interface RevenueStats {
  mrr: number;
  arr: number;
  revenue_today: number;
  revenue_mtd: number;
  revenue_ytd: number;
  currency: string;
  plan_breakdown: Record<string, number>;
  churn_rate_pct: number;
  ltv_avg: number;
  new_subs_mtd: number;
  cancelled_mtd: number;
}

export interface SubscriptionStats {
  total_active: number;
  by_plan: Record<string, number>;
  trial_count: number;
  expiring_soon: number;
  cancelled_count: number;
}

// ── Compliance ────────────────────────────────────────────────────────────────

export interface KYCRecord {
  user_id: string;
  username: string;
  email: string;
  kyc_status: 'unverified' | 'pending' | 'submitted' | 'under_review' | 'approved' | 'rejected';
  submitted_at: string | null;
  reviewed_at: string | null;
  reviewer_id: string | null;
  rejection_reason: string | null;
  country: string | null;
  document_type: string | null;
}

export interface AMLAlert {
  alert_id: string;
  user_id: string;
  username: string;
  alert_type: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  amount: number;
  currency: string;
  description: string;
  status: 'open' | 'investigating' | 'cleared' | 'reported';
  created_at: string;
}

export interface SanctionsHit {
  hit_id: string;
  user_id: string;
  username: string;
  list_name: string;
  match_score: number;
  status: 'pending' | 'cleared' | 'confirmed';
  created_at: string;
}

// ── Risk Management ───────────────────────────────────────────────────────────

export interface CircuitBreakerState {
  name: string;
  state: 'closed' | 'open' | 'half_open';
  failure_count: number;
  last_failure: string | null;
  last_success: string | null;
  threshold: number;
}

export interface VaRMetrics {
  var_95: number;
  var_99: number;
  expected_shortfall: number;
  max_drawdown: number;
  current_drawdown: number;
  sharpe_ratio: number;
  sortino_ratio: number;
  calmar_ratio: number;
  portfolio_value: number;
  currency: string;
}

export interface StressTestResult {
  scenario:    string;
  name?:       string;        // backend uses 'name' not 'scenario' in results array
  pnl_impact?: number;        // alias for pnl_usd
  pnl_usd?:    number;
  pnl_pct:     number;        // already a percentage (e.g. -12.5)
  max_loss?:   number;
  probability?: number;       // optional — not always returned by backend
  breaches_gate?: boolean;
  run_at?:     string;
}

// ── Broker Management ─────────────────────────────────────────────────────────

export interface BrokerHealth {
  broker_id: string;
  name: string;
  type: string;
  status: 'connected' | 'degraded' | 'disconnected';
  latency_ms: number;
  fill_rate_pct: number;
  slippage_avg_pips: number;
  orders_today: number;
  uptime_pct: number;
  last_heartbeat: string;
}

export interface TCAMetric {
  broker_id: string;
  broker_name: string;
  avg_slippage_pips: number;
  fill_rate_pct: number;
  rejection_rate_pct: number;
  avg_execution_ms: number;
  total_orders: number;
  period: string;
}

// ── White-Label ───────────────────────────────────────────────────────────────

export interface Tenant {
  tenant_id: string;
  name: string;
  domain: string;
  status: 'active' | 'suspended' | 'trial';
  plan: string;
  user_count: number;
  created_at: string;
  monthly_revenue: number;
  branding: {
    primary_color: string;
    logo_url: string;
    company_name: string;
  };
}

// ── System Health ─────────────────────────────────────────────────────────────

export interface ServiceStatus {
  name: string;
  status: 'healthy' | 'degraded' | 'down';
  latency_ms: number;
  last_check: string;
  error?: string;
}

export interface BackupRecord {
  backup_id: string;
  type: 'full' | 'incremental' | 'snapshot';
  status: 'completed' | 'running' | 'failed';
  size_mb: number;
  created_at: string;
  location: string;
}

export interface ScheduledJob {
  job_id: string;
  name: string;
  schedule: string;
  last_run: string | null;
  next_run: string | null;
  status: 'active' | 'paused' | 'failed';
  last_duration_ms: number;
}

// ── Alerting ──────────────────────────────────────────────────────────────────

export interface AlertRule {
  rule_id: string;
  name: string;
  condition: string;
  severity: 'info' | 'warning' | 'critical';
  enabled: boolean;
  channels: string[];
  last_fired: string | null;
  fire_count: number;
}

// ── GDPR ──────────────────────────────────────────────────────────────────────

export interface DataSubjectRequest {
  request_id: string;
  user_id: string;
  username: string;
  email: string;
  request_type: 'export' | 'erasure' | 'rectification' | 'portability';
  status: 'pending' | 'processing' | 'completed' | 'rejected';
  submitted_at: string;
  completed_at: string | null;
  notes: string;
}

// ── Reporting ─────────────────────────────────────────────────────────────────

export interface ReportRecord {
  report_id: string;
  type: string;
  period: string;
  status: 'completed' | 'generating' | 'failed';
  generated_at: string | null;
  size_kb: number;
  download_url: string | null;
}

// ── Rate Limiting ─────────────────────────────────────────────────────────────

export interface RateLimitRule {
  rule_id: string;
  endpoint: string;
  limit: number;
  window_seconds: number;
  scope: 'global' | 'per_user' | 'per_ip';
  enabled: boolean;
  current_hits: number;
}

// ── Prop Firm Breach Tracking ─────────────────────────────────────────────────

export interface PropBreach {
  breach_id: string;
  user_id: string;
  username: string;
  account_id: string;
  breach_type: 'daily_loss' | 'max_drawdown' | 'position_size' | 'news_trading' | 'weekend_hold';
  threshold: number;
  actual_value: number;
  severity: 'warning' | 'breach' | 'disqualified';
  status: 'open' | 'reviewed' | 'resolved' | 'disqualified';
  detected_at: string;
  resolved_at: string | null;
  notes: string | null;
}

export interface DrawdownStats {
  current_drawdown_pct: number;
  max_drawdown_pct: number;
  peak_equity: number;
  trough_equity: number;
  accounts_in_drawdown: number;
  accounts_near_limit: number;
  drawdown_distribution: { bucket: string; count: number }[];
}

// ── Financial — Chargebacks, Tax, Reconciliation, Affiliates ─────────────────

export interface Chargeback {
  chargeback_id: string;
  payment_id: string;
  user_id: string;
  username: string;
  amount: number;
  currency: string;
  reason: string;
  status: 'open' | 'won' | 'lost' | 'pending_evidence';
  provider: string;
  opened_at: string;
  resolved_at: string | null;
}

export interface TaxReport {
  report_id: string;
  period: string;
  jurisdiction: string;
  total_revenue: number;
  taxable_amount: number;
  tax_rate_pct: number;
  tax_owed: number;
  currency: string;
  status: 'draft' | 'filed' | 'paid' | 'overdue';
  due_date: string;
  filed_at: string | null;
}

export interface ReconciliationRecord {
  recon_id: string;
  period: string;
  provider: string;
  expected_amount: number;
  actual_amount: number;
  discrepancy: number;
  currency: string;
  status: 'matched' | 'discrepancy' | 'pending' | 'resolved';
  created_at: string;
  resolved_at: string | null;
}

export interface AffiliateStats {
  total_affiliates: number;
  active_affiliates: number;
  total_commissions_paid: number;
  commissions_pending: number;
  total_referrals: number;
  conversions_mtd: number;
  currency: string;
  top_affiliates: {
    affiliate_id: string;
    username: string;
    referrals: number;
    conversions: number;
    commission_earned: number;
    commission_pending: number;
  }[];
}

// ── Bulk User Operations ──────────────────────────────────────────────────────

export interface BulkUserResult {
  succeeded: string[];
  failed: { user_id: string; reason: string }[];
  total: number;
}
