/**
 * chart-bot/types/index.ts
 * Central type definitions for the AI Chart Bot module.
 */

// ─── Market Data ──────────────────────────────────────────────────────────────

export interface OHLCVBar {
  time: number; // unix seconds (UTCTimestamp)
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface PriceTick {
  symbol: string;
  bid: number;
  ask: number;
  mid: number;
  spread: number;
  timestamp: number; // unix ms
  change_pct: number;
}

export interface VolumeDeltaBar {
  time: number;
  buyVolume: number;
  sellVolume: number;
  delta: number;
  cumDelta: number;
  imbalance: number; // -1 to 1
}

// ─── Microstructure ───────────────────────────────────────────────────────────

export interface MicrostructureSnapshot {
  timestamp: number;
  spread: number;
  spreadPct: number;
  bidDepth: number;
  askDepth: number;
  orderFlowImbalance: number; // -1 (sell) to +1 (buy)
  tradePressure: number;      // 0–100
  tickDirection: 'up' | 'down' | 'flat';
  vwap: number;
  twap: number;
  marketImpact: number;
}

export interface OrderFlowCell {
  price: number;
  buyVolume: number;
  sellVolume: number;
  delta: number;
  intensity: number; // 0–1 normalised
}

// ─── ML Signals ───────────────────────────────────────────────────────────────

export type SignalDirection = 'long' | 'short' | 'neutral';
export type MarketRegime = 'trending_bull' | 'trending_bear' | 'ranging' | 'volatile' | 'breakout' | 'reversal';

export interface MLSignal {
  id: string;
  symbol: string;
  direction: SignalDirection;
  confidence: number;       // 0–1
  model: string;
  regime: MarketRegime;
  entry_price: number;
  stop_loss: number;
  take_profit: number;
  risk_reward: number;
  features: SignalFeature[];
  generated_at: string;
  expires_at: string;
  status: 'active' | 'triggered' | 'expired' | 'cancelled';
  reasoning: string;
}

export interface SignalFeature {
  name: string;
  value: number;
  importance: number; // 0–1 SHAP-style
  direction: 'bullish' | 'bearish' | 'neutral';
}

// ─── AI Analysis ──────────────────────────────────────────────────────────────

export interface ChartClickContext {
  /**
   * The instrument the user is actually looking at.
   *
   * This field did not exist. The backend read `context.get("symbol", "XAUUSD")`
   * and the click handler never sent one — so clicking a EURUSD chart returned
   * an XAUUSD analysis, rendered inside the EURUSD panel with no indication
   * that the two were different instruments. Same for `timeframe`, which
   * defaulted to "1h" no matter which timeframe was selected.
   */
  symbol: string;
  timeframe: string;
  price: number;
  time: number;
  bar: OHLCVBar | null;
  nearestSignal: MLSignal | null;
  nearestLevel: SupportResistanceLevel | null;
  nearestPattern: ChartPattern | null;
}

export interface AIAnalysis {
  id: string;
  timestamp: number;
  context: ChartClickContext;
  regime: MarketRegime;
  regimeConfidence: number;
  summary: string;
  keyDrivers: string[];
  riskAssessment: string;
  recommendedAction: 'buy' | 'sell' | 'hold' | 'wait';
  actionConfidence: number;
  priceTargets: { bull: number; bear: number; base: number };
  timeHorizon: string;
  warnings: string[];

  /**
   * Provenance. The backend has always returned `data_source` and
   * `bars_analyzed`; nothing in the UI read either, so a fallback answer with
   * zero bars rendered the same confident badge as a real one — "RANGING 50%,
   * Recommended: HOLD at 0.0000" with no warnings attached.
   *
   * Optional because a cached analysis from an older build will not carry them.
   */
  modelVersion?: string;
  modelAvailable?: boolean;
  barsAnalyzed?: number;
  dataSource?: string;
  degraded?: boolean;
  rsi?: number | null;
  atr?: number | null;
  /** Feature importances from the model that produced this verdict. */
  features?: SignalFeature[];
}

// ─── Technical Levels ─────────────────────────────────────────────────────────

export interface SupportResistanceLevel {
  id: string;
  price: number;
  type: 'support' | 'resistance' | 'pivot';
  strength: number;   // 0–1
  touches: number;
  lastTouched: number;
  aiGenerated: boolean;
}

export interface TrendLine {
  id: string;
  startTime: number;
  startPrice: number;
  endTime: number;
  endPrice: number;
  type: 'uptrend' | 'downtrend' | 'horizontal';
  strength: number;
  aiGenerated: boolean;
}

export interface ChartPattern {
  id: string;
  type: string; // 'head_shoulders' | 'double_top' | 'bull_flag' | etc.
  direction: 'bullish' | 'bearish' | 'neutral';
  confidence: number;
  startTime: number;
  endTime: number;
  targetPrice: number;
  stopPrice: number;
  description: string;
}

// ─── Equity Curve ─────────────────────────────────────────────────────────────

export interface EquityPoint {
  time: number;
  equity: number;
  drawdown: number;      // negative pct
  drawdownAbs: number;   // absolute $
  sharpe: number;
  sortino: number;
  annotation?: string;
}

// ─── Sentiment ────────────────────────────────────────────────────────────────

export type SentimentLabel = 'very_bullish' | 'bullish' | 'neutral' | 'bearish' | 'very_bearish';

export interface SentimentSnapshot {
  score: number;          // -1 to +1
  label: SentimentLabel;
  confidence: number;
  sources: number;
  goldSpecificScore: number;
  usdScore: number;
  geopoliticalScore: number;
  updatedAt: number;
}

export interface NewsItem {
  id: string;
  headline: string;
  source: string;
  publishedAt: number;
  sentimentScore: number;   // -1 to +1
  goldImpactScore: number;  // 0–1
  impactLabel: 'high' | 'medium' | 'low';
  url: string;
  summary: string;
  tags: string[];
}

// ─── Risk ─────────────────────────────────────────────────────────────────────

export interface RiskMetrics {
  cvar95: number;
  cvar99: number;
  var95: number;
  var99: number;
  positionSizePct: number;
  maxPositionSize: number;
  currentDrawdown: number;
  maxDrawdown: number;
  dailyLossLimit: number;
  dailyLossUsed: number;
  killSwitchActive: boolean;
  killSwitchReason: string | null;
  dataQualityScore: number; // 0–1
  marginUtilisation: number;
  riskScore: number;        // 0–100 composite
}

// ─── WebSocket Messages ───────────────────────────────────────────────────────

export type WsMessageType =
  | 'price_tick'
  | 'microstructure'
  | 'volume_delta'
  | 'signal'
  | 'sentiment_update'
  | 'risk_update'
  | 'pattern_detected'
  | 'level_update'
  | 'equity_update'
  | 'news_item'
  | 'ai_analysis'
  | 'account_update'
  | 'position_update'
  | 'position_close'
  | 'heartbeat'
  | 'connected'
  | 'auth_ok'
  | 'error';

export interface WsEnvelope<T = unknown> {
  type: WsMessageType;
  data?: T;
  ts?: number;
}

// ─── Trade Execution ──────────────────────────────────────────────────────────

export interface TradeOrder {
  symbol: string;
  side: 'buy' | 'sell';
  size: number;
  order_type: 'market' | 'limit' | 'stop';
  price?: number;
  stop_loss?: number;
  take_profit?: number;
  signal_id?: string;
}

export interface TradeResult {
  order_id: string;
  status: 'filled' | 'pending' | 'rejected';
  fill_price: number;
  fill_time: string;
  message?: string;
}
