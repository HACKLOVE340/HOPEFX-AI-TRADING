// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * Shared TypeScript types for the HopeFX mobile app.
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
  created_at: string;
}

// ── Market data ───────────────────────────────────────────────────────────────

export interface Quote {
  symbol: string;
  bid: number;
  ask: number;
  mid: number;
  spread: number;
  timestamp: string;
  change_pct: number;
}

export interface OHLCV {
  time: number;   // Unix seconds
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

// ── Trading ───────────────────────────────────────────────────────────────────

export type OrderSide = 'buy' | 'sell';
export type OrderType = 'market' | 'limit' | 'stop';
export type OrderStatus = 'pending' | 'open' | 'filled' | 'cancelled' | 'rejected';

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
  opened_at: string;
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
  opened_at: string;
  closed_at: string;
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
  currency: string;
}

// ── Signals ───────────────────────────────────────────────────────────────────

export interface Signal {
  id: string;
  symbol: string;
  direction: 'long' | 'short' | 'neutral';
  confidence: number;       // 0–1
  entry_price: number;
  stop_loss: number;
  take_profit: number;
  risk_reward: number;
  generated_at: string;
  expires_at: string;
  regime: string;
  ml_probability: number;
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
};

export type MainTabParamList = {
  Dashboard: undefined;
  Trading: undefined;
  Portfolio: undefined;
  Signals: undefined;
  Settings: undefined;
};

export type PortfolioStackParamList = {
  PortfolioHome: undefined;
  Performance: undefined;
};

export type SettingsStackParamList = {
  SettingsHome: undefined;
  Notifications: undefined;
  Alerts: undefined;
};

export type TradingStackParamList = {
  TradingHome: undefined;
  PlaceOrder: { symbol: string; side?: OrderSide };
  OrderDetail: { orderId: string };
  PositionDetail: { positionId: string };
  Watchlist: undefined;
  Orders: undefined;
};

// ── WebSocket ─────────────────────────────────────────────────────────────────

export type WSMessageType =
  // Backend canonical types (from api/ws_live.py)
  | 'price_tick'       // live bid/ask tick
  | 'signal'           // new AI signal
  | 'position_update'  // position state change
  | 'position_close'   // position closed
  | 'account_update'   // account metrics update
  | 'heartbeat'        // server keepalive
  | 'error'            // server error
  // Client → server
  | 'auth'
  | 'subscribe'
  | 'unsubscribe'
  | 'ping'
  | 'pong'
  // Legacy aliases kept for backward compat
  | 'price_update'
  | 'order_update'
  | 'alert';

export interface WSMessage<T = unknown> {
  type: WSMessageType;
  data: T;
  timestamp: string;
}
