// settings/types.ts — shared types for all Settings sections

export type SettingsTab =
  | 'profile'
  | 'security'
  | 'broker'
  | 'trading'
  | 'appearance'
  | 'notifications'
  | 'api-keys'
  | 'billing'
  | 'integrations'
  | 'system'
  | 'privacy'
  | 'accessibility'
  | 'admin'
  | 'danger'
  // Superadmin-only tabs
  | 'sa-users'
  | 'sa-platform'
  | 'sa-ml-ai'
  | 'sa-trading-engine'
  | 'sa-financial'
  | 'sa-security'
  | 'sa-logs'
  | 'sa-feature-flags';

export interface ProfileSettings {
  username: string;
  email: string;
  bio: string;
  avatar_url: string;
  website: string;
  is_public: boolean;
  timezone: string;
  language: string;
}

export interface SecuritySettings {
  two_fa_enabled: boolean;
  sessions: SessionInfo[];
}

export interface SessionInfo {
  session_id: string;
  device_info: string;
  ip_address: string;
  created_at: string;
  last_active: string;
  current: boolean;
}

export interface BrokerSettings {
  type: 'paper' | 'oanda' | 'alpaca';
  api_key: string;
  account_id: string;
  practice: boolean;
  connected: boolean;
  balance?: number;
  currency?: string;
}

export interface TradingPreferences {
  default_symbol: string;
  default_timeframe: string;
  default_lot_size: number;
  max_risk_per_trade: number;
  max_daily_drawdown: number;
  auto_trade_enabled: boolean;
  kill_switch_enabled: boolean;
  slippage_tolerance: number;
  default_leverage: number;
}

export interface AppearanceSettings {
  theme: 'dark' | 'light' | 'system';
  accent_color: string;
  chart_style: 'candles' | 'bars' | 'line' | 'area';
  compact_sidebar: boolean;
  show_pnl_in_header: boolean;
  number_format: 'standard' | 'compact';
  currency_display: 'USD' | 'EUR' | 'GBP';
}

export interface NotificationSettings {
  discord_enabled: boolean;
  discord_webhook_url: string;
  slack_enabled: boolean;
  slack_webhook_url: string;
  telegram_enabled: boolean;
  telegram_bot_token: string;
  telegram_chat_id: string;
  email_enabled: boolean;
  email_address: string;
  notify_on_trade: boolean;
  notify_on_signal: boolean;
  notify_on_error: boolean;
  notify_on_daily_summary: boolean;
}

export interface ApiKey {
  key_id: string;
  name: string;
  scopes: string[];
  key_prefix: string;
  created_at: string;
  last_used: string | null;
  revoked: boolean;
}

export interface BillingInfo {
  plan: string;
  status: string;
  renewal_date: string | null;
  features: string[];
  balance: number;
  currency: string;
}

export interface IntegrationSettings {
  tradingview_enabled: boolean;
  tradingview_webhook_secret: string;
  zapier_enabled: boolean;
  zapier_webhook_url: string;
  google_sheets_enabled: boolean;
  google_sheets_id: string;
  mt4_enabled: boolean;
  mt4_server: string;
  mt4_login: string;
  mt4_password: string;
  mt5_enabled: boolean;
  mt5_server: string;
  mt5_login: string;
  mt5_password: string;
  ctrader_enabled: boolean;
  ctrader_client_id: string;
  ctrader_client_secret: string;
  webhook_enabled: boolean;
  webhook_url: string;
  webhook_secret: string;
}

export interface SystemSettings {
  data_refresh_interval: number;
  max_open_positions: number;
  session_timeout_minutes: number;
  log_level: 'debug' | 'info' | 'warning' | 'error';
  enable_paper_trading: boolean;
  enable_live_trading: boolean;
  maintenance_mode: boolean;
  rate_limit_per_minute: number;
  cache_ttl_seconds: number;
  backup_enabled: boolean;
  backup_frequency: 'hourly' | 'daily' | 'weekly';
}

export interface PrivacySettings {
  share_performance: boolean;
  share_trades: boolean;
  share_signals: boolean;
  allow_copy_trading: boolean;
  show_in_leaderboard: boolean;
  analytics_opt_in: boolean;
  marketing_emails: boolean;
  data_retention_days: number;
}

export interface AccessibilitySettings {
  reduce_motion: boolean;
  high_contrast: boolean;
  large_text: boolean;
  keyboard_shortcuts: boolean;
  screen_reader_hints: boolean;
  color_blind_mode: 'none' | 'deuteranopia' | 'protanopia' | 'tritanopia';
  font_size: 'small' | 'medium' | 'large' | 'xlarge';
}

export interface AdminSettings {
  allow_new_registrations: boolean;
  require_email_verification: boolean;
  default_new_user_plan: string;
  max_users: number;
  force_2fa_for_admins: boolean;
  ip_whitelist_enabled: boolean;
  ip_whitelist: string[];
  global_kill_switch: boolean;
  announcement_banner: string;
  announcement_enabled: boolean;
  smtp_host: string;
  smtp_port: number;
  smtp_user: string;
  smtp_password: string;
  smtp_from: string;
  smtp_tls: boolean;
}

export const TIMEZONES = [
  'UTC', 'America/New_York', 'America/Chicago', 'America/Los_Angeles',
  'Europe/London', 'Europe/Paris', 'Europe/Berlin', 'Asia/Tokyo',
  'Asia/Singapore', 'Asia/Dubai', 'Australia/Sydney',
];

export const LANGUAGES = [
  { code: 'en', label: 'English' },
  { code: 'es', label: 'Español' },
  { code: 'fr', label: 'Français' },
  { code: 'de', label: 'Deutsch' },
  { code: 'zh', label: '中文' },
  { code: 'ja', label: '日本語' },
  { code: 'ar', label: 'العربية' },
];

export const SYMBOLS = ['XAU_USD', 'EUR_USD', 'GBP_USD', 'USD_JPY', 'BTC_USD', 'ETH_USD'];
export const TIMEFRAMES = ['1m', '5m', '15m', '30m', '1h', '4h', '1d', '1w'];
export const ACCENT_COLORS = ['#3b82f6', '#8b5cf6', '#10b981', '#f59e0b', '#ef4444', '#06b6d4'];
