/**
 * types/trading.ts
 * Canonical TypeScript types mirroring backend data_layer/types.py and API schemas.
 * All types are readonly where possible to prevent accidental mutation.
 */

// ── Enumerations ──────────────────────────────────────────────────────────────

export type FeedSource =
  | 'goldapi'
  | 'metalpriceapi'
  | 'metals_api'
  | 'metals_dev'
  | 'commodity_api'
  | 'synthetic'
  | 'replay';

export type TickQuality = 'good' | 'stale' | 'suspect' | 'rejected';

export type MacroImpact = 'high' | 'medium' | 'low' | 'none';

export type Direction = 'long' | 'short' | 'neutral';

export type SignalStatus = 'active' | 'triggered' | 'expired' | 'cancelled';

export type WsStatus = 'connecting' | 'connected' | 'disconnected' | 'error';

export type UserRole = 'user' | 'trader' | 'admin' | 'superadmin';

// ── Core tick ─────────────────────────────────────────────────────────────────

export interface GoldTick {
  readonly symbol:      string;       // 'XAU_USD'
  readonly timestamp:   string;       // ISO-8601 UTC
  readonly bid:         number;
  readonly ask:         number;
  readonly mid:         number;
  readonly spread:      number;
  readonly source:      FeedSource;
  readonly quality:     TickQuality;
  readonly confidence:  number;       // 0–1
  readonly lineage_id:  string;
}

// ── Price tick (WebSocket stream) ─────────────────────────────────────────────

export interface PriceTick {
  readonly symbol:      string;
  readonly bid:         number;
  readonly ask:         number;
  readonly mid:         number;
  readonly spread:      number;
  readonly timestamp:   number;       // unix ms
  readonly change_pct:  number;
  readonly quality?:    TickQuality;
  readonly confidence?: number;
}

// ── Microstructure ────────────────────────────────────────────────────────────

export interface MicrostructureSnapshot {
  readonly timestamp:             string;
  readonly bid:                   number;
  readonly ask:                   number;
  readonly spread:                number;
  readonly spread_pct:            number;
  readonly volume_delta:          number;   // buy_vol - sell_vol (signed)
  readonly cumulative_delta:      number;
  readonly buy_pressure:          number;   // 0–1
  readonly sell_pressure:         number;   // 0–1
  readonly order_flow_imbalance:  number;   // (buy - sell) / (buy + sell)
  readonly trade_pressure:        number;
  readonly vwap:                  number;
  readonly tick_count:            number;
  readonly bid_depth?:            number;
  readonly ask_depth?:            number;
  readonly depth_imbalance?:      number;
}

export interface MicrostructureFeatures {
  readonly micro_spread:          number;
  readonly micro_spread_pct:      number;
  readonly micro_spread_z:        number;
  readonly micro_volume_delta:    number;
  readonly micro_cumulative_delta: number;
  readonly micro_buy_pressure:    number;
  readonly micro_sell_pressure:   number;
  readonly micro_ofi:             number;
  readonly micro_trade_pressure:  number;
  readonly micro_depth_imbalance: number;
  readonly micro_vwap_dev:        number;
  readonly micro_kyles_lambda:    number;
  readonly micro_delta_divergence: number;
  readonly micro_absorption:      number;
}

// ── Sentiment ─────────────────────────────────────────────────────────────────

export interface SentimentSignal {
  readonly news_sentiment_score:    number;   // -1 (bearish) to +1 (bullish)
  readonly news_sentiment_momentum: number;
  readonly news_article_count_1h:   number;
  readonly news_bullish_ratio:      number;   // 0–1
}

export interface NewsArticle {
  readonly headline:        string;
  readonly source:          string;
  readonly published_at:    string;
  readonly sentiment_score: number;
  readonly sentiment_label: 'bullish' | 'bearish' | 'neutral';
  readonly gold_relevance:  number;
  readonly impact_score:    number;
}

export interface SentimentResponse {
  readonly signal:           SentimentSignal;
  readonly recent_articles:  NewsArticle[];
}

// ── Macro calendar ────────────────────────────────────────────────────────────

export interface MacroEvent {
  readonly name:              string;
  readonly country:           string;
  readonly scheduled_at:      string;
  readonly impact:            MacroImpact;
  readonly gold_impact_score: number;   // 0–1
  readonly forecast:          number | null;
  readonly actual:            number | null;
  readonly surprise_pct:      number | null;
}

export interface MacroResponse {
  readonly calendar_features: Record<string, number>;
  readonly macro_features:    Record<string, number>;
  readonly is_blackout:       boolean;
  readonly impact_score:      number;
  readonly upcoming_events:   MacroEvent[];
}

// ── Data quality ──────────────────────────────────────────────────────────────

export interface QualityReport {
  readonly timestamp:                    string;
  readonly symbol:                       string;
  readonly ticks_received:               number;
  readonly ticks_accepted:               number;
  readonly ticks_rejected:               number;
  readonly stale_count:                  number;
  readonly jump_count:                   number;
  readonly active_sources:               string[];
  readonly primary_source:               string;
  readonly consensus_price:              number;
  readonly price_spread_across_sources:  number;
  readonly source_health:                Record<string, unknown>;
}

// ── Orchestrator health ───────────────────────────────────────────────────────

export interface OrchestratorHealth {
  readonly status:          'healthy' | 'degraded' | 'unhealthy';
  readonly uptime_seconds:  number;
  readonly components:      Record<string, ComponentHealth>;
  readonly latest_tick?:    GoldTick;
  readonly quality_score:   number;   // 0–1
  readonly data_quality?:   QualityReport;
}

export interface ComponentHealth {
  readonly status:    'ok' | 'degraded' | 'error' | 'offline';
  readonly latency_ms?: number;
  readonly last_update?: string;
  readonly error?:    string;
}

// ── Positions ─────────────────────────────────────────────────────────────────

export interface Position {
  readonly id:             string;
  readonly symbol:         string;
  readonly side:           Direction;
  readonly size:           number;
  readonly entry_price:    number;
  readonly current_price:  number;
  readonly unrealized_pnl: number;
  readonly realized_pnl:   number;
  readonly opened_at:      string;
  readonly stop_loss?:     number;
  readonly take_profit?:   number;
}

// ── Signals ───────────────────────────────────────────────────────────────────

export interface Signal {
  readonly id:           string;
  readonly symbol:       string;
  readonly direction:    Direction;
  readonly confidence:   number;       // 0–1
  readonly model:        string;
  readonly entry_price:  number;
  readonly stop_loss:    number;
  readonly take_profit:  number;
  readonly generated_at: string;
  readonly status:       SignalStatus;
  readonly features?:    Record<string, number>;
  readonly risk_reward?: number;
}

// ── Account metrics ───────────────────────────────────────────────────────────

export interface AccountMetrics {
  readonly balance:        number;
  readonly equity:         number;
  readonly margin_used:    number;
  readonly margin_free:    number;
  readonly margin_level:   number;
  readonly daily_pnl:      number;
  readonly daily_pnl_pct:  number;
  readonly total_pnl:      number;
  readonly win_rate:       number;
  readonly sharpe_ratio:   number;
  readonly sortino_ratio?: number;
  readonly max_drawdown:   number;
  readonly open_trades:    number;
  readonly open_risk_pct?: number;   // % of equity at risk across open positions
  readonly cvar_95?:       number;   // Conditional Value at Risk 95%
  readonly kill_switch?:   boolean;
}

// ── Equity curve ──────────────────────────────────────────────────────────────

export interface EquityPoint {
  readonly timestamp:  string;
  readonly equity:     number;
  readonly drawdown:   number;   // negative fraction, e.g. -0.05 = -5%
  readonly balance?:   number;
}

export interface PerformanceSummary {
  readonly total_return_pct:  number;
  readonly sharpe_ratio:      number;
  readonly sortino_ratio:     number;
  readonly max_drawdown_pct:  number;
  readonly win_rate:          number;
  readonly profit_factor:     number;
  readonly total_trades:      number;
  readonly avg_trade_pnl:     number;
  readonly best_trade:        number;
  readonly worst_trade:       number;
  readonly cvar_95:           number;
}

// ── Order book ────────────────────────────────────────────────────────────────

export interface OrderBookLevel {
  readonly price:    number;
  readonly size:     number;
  readonly total:    number;   // cumulative
}

export interface OrderBook {
  readonly symbol:    string;
  readonly timestamp: string;
  readonly bids:      OrderBookLevel[];
  readonly asks:      OrderBookLevel[];
  readonly mid:       number;
  readonly spread:    number;
}

// ── User ──────────────────────────────────────────────────────────────────────

export interface User {
  readonly id:               string;
  readonly email:            string;
  readonly username:         string;
  readonly role:             UserRole;
  // Fields returned by /api/auth/login and /api/auth/me
  readonly plan?:            string;
  readonly kyc_status?:      string;
  readonly totp_enabled?:    boolean;
  readonly status?:          string;
  readonly is_email_verified?: boolean;
  readonly created_at?:      string;
  readonly last_login_at?:   string;
}

// ── WebSocket message envelope ────────────────────────────────────────────────

export interface WsMessage<T = unknown> {
  readonly type:           string;
  readonly data?:          T;
  readonly auth_required?: boolean;
  readonly user_id?:       string;
  readonly code?:          string;
  readonly message?:       string;
}
