// superadmin/types.ts — shared types for all superadmin sections

export type SuperAdminTab =
  | 'overview'
  | 'users'
  | 'platform'
  | 'ml-ai'
  | 'trading-engine'
  | 'financial'
  | 'security'
  | 'logs'
  | 'feature-flags';

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
  drift_score: number;
  deployed_at: string | null;
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
