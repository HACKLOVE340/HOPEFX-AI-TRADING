// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * Shared TypeScript types for the HopeFX mobile app.
 * Covers all domains: auth, market data, microstructure, trading,
 * risk, signals, sentiment, notifications, navigation, WebSocket.
 */

// ── Auth ──────────────────────────────────────────────────────────────────────

export interface AuthTokens {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  token_type: string;
}

export interface User {
  id: string;
  email: string;
  username: string;
  role: 'user' | 'trader' | 'admin' | 'superadmin';
  kyc_verified: boolean;
  two_factor_enabled: boolean;
  biometric_enabled?: boolean;
  created_at: string;
}

// ── Market data ───────────────────────────────────────────────────────────────

export interface Quote {
  symbol: string;
  bid: number;
  ask: number;
  mid: number;
  spread: number;
  spread_pct?: number;
  timestamp: string;
  change_pct: number;
  change_abs?: number;
  session_high?: number;
  session_low?: number;
  volume?: number;
}

export interface OHLCV {
  time: number;   // Unix seconds
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

// ── Microstructure ────────────────────────────────────────────────────────────

export interface Microstructure {
  symbol: string;
  timestamp: string;
  spread: number;
  spread_pct: number;
  spread_z: number;           // z-score vs rolling mean
  spread_ema_fast: number;
  spread_ema_slow: number;
  volume_delta: number;       // buy vol - sell vol
  cumulative_delta: number;
  buy_pressure: number;       // 0–1
  sell_pressure: number;      // 0–1
  ofi: number;                // order flow imbalance
  trade_pressure: number;
  depth_imbalance: number;    // bid depth / ask depth
  vwap_deviation: number;
  kyles_lambda: number;       // price impact per unit volume
  delta_divergence: number;
  absorption: number;         // large order absorption ratio
}

// ── Sentiment ─────────────────────────────────────────────────────────────────

export interface SentimentData {
  symbol: string;
  timestamp: string;
  score: number;              // -1 to +1
  momentum: number;           // rate of change
  article_count_1h: number;
  bullish_ratio: number;      // 0–1
  bearish_ratio: number;      // 0–1
  intensity: number;          // 0–1 (how strong the signal is)
  regime: 'bullish' | 'bearish' | 'neutral' | 'mixed';
  top_headlines: NewsHeadline[];
}

export interface NewsHeadline {
  id: string;
  title: string;
  source: string;
  published_at: string;
  sentiment_score: number;    // -1 to +1
  impact: 'high' | 'medium' | 'low';
  url?: string;
}

// ── Risk ──────────────────────────────────────────────────────────────────────

export interface RiskMetrics {
  timestamp: string;
  // CVaR / VaR
  var_95: number;
  var_99: number;
  cvar_95: number;            // Conditional VaR (Expected Shortfall)
  cvar_99: number;
  // Drawdown
  current_drawdown: number;   // current drawdown from peak (negative)
  max_drawdown: number;       // max historical drawdown (negative)
  drawdown_duration_days: number;
  // Position sizing
  position_size_pct: number;  // current position as % of equity
  max_position_pct: number;   // configured max
  kelly_fraction: number;     // Kelly criterion optimal fraction
  // Ratios
  sharpe_ratio: number;
  sortino_ratio: number;
  calmar_ratio: number;
  // Risk utilization
  risk_utilization: number;   // 0–1 (how much of risk budget is used)
  margin_utilization: number; // 0–1
  // Kill switch
  kill_switch_active: boolean;
  kill_switch_reason?: string;
  kill_switch_triggered_at?: string;
  // Data quality
  data_quality_score: number; // 0–1
  tick_confidence: number;    // 0–1
  source_count: number;
  // Macro
  macro_impact_score: number; // 0–1
  is_blackout_window: boolean;
  hours_to_next_event?: number;
}

// ── Trading ───────────────────────────────────────────────────────────────────

export type OrderSide   = 'buy' | 'sell';
export type OrderType   = 'market' | 'limit' | 'stop' | 'stop_limit';
export type OrderStatus = 'pending' | 'open' | 'filled' | 'cancelled' | 'rejected' | 'expired';

export interface Order {
  id: string;
  symbol: string;
  side: OrderSide;
  type: OrderType;
  quantity: number;
  price?: number;
  stop_loss?: number;
  take_profit?: number;
  status: OrderStatus;
  created_at: string;
  filled_at?: string;
  fill_price?: number;
  commission?: number;
  slippage?: number;
}

export interface Position {
  id: string;
  symbol: string;
  side: OrderSide;
  quantity: number;
  entry_price: number;
  current_price: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  stop_loss?: number;
  take_profit?: number;
  opened_at: string;
  margin_used?: number;
  swap?: number;
}

export interface Trade {
  id: string;
  symbol: string;
  side: OrderSide;
  quantity: number;
  entry_price: number;
  exit_price: number;
  pnl: number;
  pnl_pct: number;
  commission?: number;
  swap?: number;
  opened_at: string;
  closed_at: string;
  duration_hours?: number;
  exit_reason?: 'tp' | 'sl' | 'manual' | 'kill_switch';
}

// ── Account ───────────────────────────────────────────────────────────────────

export interface Account {
  account_id: string;
  balance: number;
  equity: number;
  margin_used: number;
  margin_available: number;
  unrealized_pnl: number;
  daily_pnl: number;
  daily_pnl_pct: number;
  weekly_pnl?: number;
  monthly_pnl?: number;
  currency: string;
  leverage?: number;
  account_type?: 'live' | 'paper' | 'demo';
}

// ── Signals ───────────────────────────────────────────────────────────────────

export interface Signal {
  id: string;
  symbol: string;
  direction: 'long' | 'short' | 'neutral';
  confidence: number;         // 0–1
  entry_price: number;
  stop_loss: number;
  take_profit: number;
  risk_reward: number;
  generated_at: string;
  expires_at: string;
  regime: string;
  ml_probability: number;     // 0–1
  // Extended fields from orchestrator
  reasoning?: string;         // human-readable explanation
  contributing_factors?: SignalFactor[];
  microstructure_score?: number;
  sentiment_score?: number;
  macro_score?: number;
  data_quality?: number;
  approved?: boolean;         // one-tap approval state
  approved_at?: string;
}

export interface SignalFactor {
  name: string;
  weight: number;             // contribution to signal (0–1)
  value: number;
  direction: 'bullish' | 'bearish' | 'neutral';
}

// ── Performance ───────────────────────────────────────────────────────────────

export interface PerformanceSummary {
  period: string;
  total_trades: number;
  win_rate: number;
  total_pnl: number;
  total_pnl_pct: number;
  avg_win: number;
  avg_loss: number;
  best_trade: number;
  worst_trade: number;
  profit_factor: number;
  sharpe_ratio: number | null;
  sortino_ratio: number | null;
  max_drawdown_pct: number;
  avg_hold_hours: number;
  data_source: string;
}

// ── Notifications ─────────────────────────────────────────────────────────────

export interface PushToken {
  token: string;
  platform: 'ios' | 'android';
  device_id: string;
}

export interface NotificationPrefs {
  signals: boolean;
  trade_fills: boolean;
  price_alerts: boolean;
  daily_summary: boolean;
  risk_warnings: boolean;
  kill_switch: boolean;
  news_impact: boolean;
}

// ── Offline cache ─────────────────────────────────────────────────────────────

export interface CachedState {
  account: Account | null;
  quotes: Record<string, Quote>;
  positions: Position[];
  signals: Signal[];
  riskMetrics: RiskMetrics | null;
  sentiment: SentimentData | null;
  cachedAt: string;
}

// ── Navigation ────────────────────────────────────────────────────────────────

export type RootStackParamList = {
  Auth: undefined;
  Main: undefined;
};

export type AuthStackParamList = {
  Login: undefined;
  Register: undefined;
  ForgotPassword: undefined;
  TwoFactor: { email: string; password: string };
  BiometricSetup: undefined;
};

export type MainTabParamList = {
  Dashboard: undefined;
  Trading: undefined;
  Risk: undefined;
  Signals: undefined;
  More: undefined;
  Settings: undefined;
};

export type PortfolioStackParamList = {
  PortfolioHome: undefined;
  Performance: undefined;
};

export type TradingStackParamList = {
  TradingHome: undefined;
  PlaceOrder: { symbol: string; side?: OrderSide };
  OrderDetail: { orderId: string };
  PositionDetail: { positionId: string };
  Watchlist: undefined;
  Orders: undefined;
};

export type RiskStackParamList = {
  RiskHome: undefined;
};

export type SettingsStackParamList = {
  SettingsHome: undefined;
  Notifications: undefined;
  Alerts: undefined;
  BiometricSettings: undefined;
  ConnectionSettings: undefined;
};

// ── WebSocket ─────────────────────────────────────────────────────────────────

export type WSMessageType =
  // Market data
  | 'price_tick'
  | 'price_update'
  // Microstructure
  | 'microstructure_update'
  // Signals
  | 'signal'
  // Risk
  | 'risk_update'
  | 'kill_switch_trigger'
  // Sentiment
  | 'sentiment_update'
  // Positions / account
  | 'position_update'
  | 'position_close'
  | 'account_update'
  | 'order_update'
  // Protocol
  | 'heartbeat'
  | 'error'
  | 'auth'
  | 'auth_ok'
  | 'subscribe'
  | 'unsubscribe'
  | 'ping'
  | 'pong'
  | 'alert';

export interface WSMessage<T = unknown> {
  type: WSMessageType;
  data: T;
  timestamp: string;
}

export type WSConnectionStatus = 'connecting' | 'connected' | 'disconnected' | 'reconnecting';
