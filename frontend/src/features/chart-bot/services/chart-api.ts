/**
 * chart-bot/services/chart-api.ts
 *
 * REST API client for all chart-bot data fetching.
 * Uses the shared axios instance (JWT injected via interceptor) with
 * TanStack Query for caching and background refetch.
 */

import { api } from '../../../hooks/useApi';
import type {
  OHLCVBar,
  MLSignal,
  SentimentSnapshot,
  NewsItem,
  RiskMetrics,
  SupportResistanceLevel,
  TrendLine,
  ChartPattern,
  EquityPoint,
  AIAnalysis,
  ChartClickContext,
  TradeOrder,
  TradeResult,
  MicrostructureSnapshot,
} from '../types';

// ─── OHLCV ────────────────────────────────────────────────────────────────────

export interface OHLCVParams {
  symbol: string;
  timeframe: string;
  limit?: number;
  from?: number;
  to?: number;
}

/**
 * Bars to request per timeframe. Deep timeframes pull far more history so the
 * chart can scroll back years (daily gold reaches ~2000); intraday stays
 * lighter for speed but still deep enough to analyse. Centralised so every
 * caller (CoreChart, DataInitialiser) shares the same TanStack Query cache key.
 */
export function ohlcvLimitFor(timeframe: string): number {
  switch (timeframe) {
    case '1d': return 8000;
    case '1w': return 2000;
    case '4h': return 2000;
    case '1h': return 1500;
    default:   return 1000;
  }
}

export async function fetchOHLCV(params: OHLCVParams): Promise<OHLCVBar[]> {
  const { symbol, timeframe, limit = 500, from, to } = params;
  const query = new URLSearchParams({
    timeframe,
    limit: String(limit),
    ...(from ? { from: String(from) } : {}),
    ...(to   ? { to:   String(to)   } : {}),
  });
  // OHLCV may fetch from yfinance on the backend — allow up to 30s
  const res = await api.get<OHLCVBar[] | { data?: OHLCVBar[] }>(
    `/trading/ohlcv/${encodeURIComponent(symbol)}?${query}`,
    { timeout: 30_000 },
  );
  const raw = res.data;
  const bars: OHLCVBar[] = Array.isArray(raw) ? raw : (raw.data ?? []);
  // Backend returns `timestamp` (unix seconds float from price engine / yfinance).
  // Normalise to unix seconds integer and map to the `time` field the chart types expect.
  return bars
    .map((b) => {
      // Accept either `time` or `timestamp` from the server
      const rawTs = (b as unknown as Record<string, unknown>).timestamp as number | undefined;
      const ts = rawTs ?? b.time;
      if (ts == null) return null;
      // Auto-detect ms vs seconds: values > 1e10 are milliseconds
      const timeSec = ts > 1e10 ? Math.floor(ts / 1000) : Math.floor(ts);
      return { ...b, time: timeSec };
    })
    .filter((b): b is OHLCVBar => b !== null && b.time > 0)
    .sort((a, b) => a.time - b.time); // lightweight-charts requires ascending order
}

// ─── Signals ──────────────────────────────────────────────────────────────────

/**
 * Map one wire signal onto MLSignal.
 *
 * The server and this module disagreed about the shape, and `as MLSignal[]`
 * hid it — a cast asserts a shape, it does not produce one. `/api/signals`
 * serialises `TradingSignal.to_dict()`, which emits:
 *
 *   direction: "buy" | "sell"        MLSignal wants "long" | "short" | "neutral"
 *   risk_reward_ratio                MLSignal wants risk_reward
 *   timestamp / expiry               MLSignal wants generated_at / expires_at
 *   (no status, model, features, reasoning at all)
 *
 * Two visible consequences. `signal.status.toUpperCase()` threw
 * "undefined is not an object (evaluating 'e.toUpperCase')", which is the error
 * the SIGNAL FEED panel showed instead of any signals. And worse where it did
 * render: `direction === 'long'` is false for "buy", and false again for
 * 'neutral', so a BUY signal drew a red ▼ — a trading UI showing the opposite
 * of the signal it received.
 *
 * Normalising here, at the boundary, means the component keeps one shape to
 * reason about and an added or renamed server field degrades to a default
 * instead of a blank panel.
 */
type WireSignal = Record<string, unknown>;

const _DIRECTION: Record<string, MLSignal['direction']> = {
  buy: 'long', long: 'long',
  sell: 'short', short: 'short',
  hold: 'neutral', neutral: 'neutral', flat: 'neutral',
};

const _STATUS: Record<string, MLSignal['status']> = {
  active: 'active', open: 'active',
  triggered: 'triggered', hit_tp: 'triggered', hit_sl: 'triggered',
  expired: 'expired', cancelled: 'cancelled', canceled: 'cancelled',
};

const _REGIMES: MLSignal['regime'][] = [
  'trending_bull', 'trending_bear', 'ranging', 'volatile', 'breakout', 'reversal',
];

function _num(v: unknown, fallback = 0): number {
  const n = typeof v === 'number' ? v : Number(v);
  return Number.isFinite(n) ? n : fallback;
}

function _str(v: unknown, fallback = ''): string {
  return typeof v === 'string' && v ? v : fallback;
}

export function normaliseSignal(raw: WireSignal): MLSignal {
  const expiresAt = _str(raw.expires_at) || _str(raw.expiry);
  // No status on the wire: derive one, because "expired" and "active" render
  // very differently and defaulting everything to active would show stale
  // signals as live.
  const expired = expiresAt ? Date.parse(expiresAt) < Date.now() : false;
  const status =
    _STATUS[_str(raw.status).toLowerCase()] ?? (expired ? 'expired' : 'active');

  const regimeRaw = _str(raw.regime).toLowerCase() as MLSignal['regime'];

  return {
    id: _str(raw.id) || _str(raw.signal_id) || `${_str(raw.symbol, '?')}-${_str(raw.timestamp)}`,
    symbol: _str(raw.symbol, '—'),
    direction: _DIRECTION[_str(raw.direction).toLowerCase()] ?? 'neutral',
    confidence: Math.max(0, Math.min(1, _num(raw.confidence))),
    model: _str(raw.model) || _str(raw.strategy) || 'ensemble',
    regime: _REGIMES.includes(regimeRaw) ? regimeRaw : 'ranging',
    entry_price: _num(raw.entry_price ?? raw.price),
    stop_loss: _num(raw.stop_loss),
    take_profit: _num(raw.take_profit),
    risk_reward: _num(raw.risk_reward ?? raw.risk_reward_ratio),
    features: Array.isArray(raw.features) ? (raw.features as MLSignal['features']) : [],
    generated_at: _str(raw.generated_at) || _str(raw.timestamp) || new Date().toISOString(),
    expires_at: expiresAt,
    status,
    reasoning: _str(raw.reasoning) || _str(raw.rationale),
  };
}

export async function fetchSignals(symbol: string, limit = 20): Promise<MLSignal[]> {
  const res = await api.get<WireSignal[] | { signals?: WireSignal[]; data?: WireSignal[] }>(
    `/signals?symbol=${encodeURIComponent(symbol)}&limit=${limit}`
  );
  const raw = res.data;
  const items: WireSignal[] = Array.isArray(raw) ? raw : (raw.signals ?? raw.data ?? []);
  return items.map(normaliseSignal);
}

// ─── Sentiment ────────────────────────────────────────────────────────────────

export async function fetchSentiment(symbol = 'XAUUSD'): Promise<SentimentSnapshot> {
  const res = await api.get<SentimentSnapshot | { data?: SentimentSnapshot }>(
    `/signals/sentiment?symbol=${encodeURIComponent(symbol)}`
  );
  const raw = res.data;
  if ('score' in raw) return raw as SentimentSnapshot;
  return (raw as { data?: SentimentSnapshot }).data ?? {
    score: 0, label: 'neutral', confidence: 0.5, sources: 0,
    goldSpecificScore: 0, usdScore: 0, geopoliticalScore: 0, updatedAt: Date.now(),
  };
}

export async function fetchNews(symbol = 'XAUUSD', limit = 15): Promise<NewsItem[]> {
  const res = await api.get<NewsItem[] | { items?: NewsItem[]; data?: NewsItem[] }>(
    `/signals/news?symbol=${encodeURIComponent(symbol)}&limit=${limit}`
  );
  const raw = res.data;
  if (Array.isArray(raw)) return raw;
  return (raw as { items?: NewsItem[]; data?: NewsItem[] }).items ?? (raw as { data?: NewsItem[] }).data ?? [];
}

// ─── Risk ─────────────────────────────────────────────────────────────────────

export async function fetchRiskMetrics(): Promise<RiskMetrics> {
  const res = await api.get<RiskMetrics | { data?: RiskMetrics }>('/trading/risk');
  const raw = res.data;
  if ('cvar95' in raw) return raw as RiskMetrics;
  return (raw as { data?: RiskMetrics }).data ?? buildDefaultRisk();
}

function buildDefaultRisk(): RiskMetrics {
  return {
    cvar95: 0, cvar99: 0, var95: 0, var99: 0,
    positionSizePct: 0, maxPositionSize: 0,
    currentDrawdown: 0, maxDrawdown: 0,
    dailyLossLimit: 0, dailyLossUsed: 0,
    killSwitchActive: false, killSwitchReason: null,
    dataQualityScore: 1, marginUtilisation: 0, riskScore: 0,
  };
}

// ─── Technical Levels ─────────────────────────────────────────────────────────

export async function fetchLevels(symbol: string): Promise<SupportResistanceLevel[]> {
  const res = await api.get<SupportResistanceLevel[] | { levels?: SupportResistanceLevel[] }>(
    `/trading/levels?symbol=${encodeURIComponent(symbol)}`
  );
  const raw = res.data;
  if (Array.isArray(raw)) return raw;
  return (raw as { levels?: SupportResistanceLevel[] }).levels ?? [];
}

export async function fetchTrendlines(symbol: string): Promise<TrendLine[]> {
  const res = await api.get<TrendLine[] | { trendlines?: TrendLine[] }>(
    `/trading/trendlines?symbol=${encodeURIComponent(symbol)}`
  );
  const raw = res.data;
  if (Array.isArray(raw)) return raw;
  return (raw as { trendlines?: TrendLine[] }).trendlines ?? [];
}

export async function fetchPatterns(symbol: string): Promise<ChartPattern[]> {
  const res = await api.get<ChartPattern[] | { patterns?: ChartPattern[] }>(
    `/trading/patterns?symbol=${encodeURIComponent(symbol)}`
  );
  const raw = res.data;
  if (Array.isArray(raw)) return raw;
  return (raw as { patterns?: ChartPattern[] }).patterns ?? [];
}

// ─── Equity Curve ─────────────────────────────────────────────────────────────

export async function fetchEquityCurve(days = 90): Promise<EquityPoint[]> {
  const res = await api.get<EquityPoint[] | { data?: EquityPoint[] }>(
    `/trading/equity-curve?days=${days}`
  );
  const raw = res.data;
  if (Array.isArray(raw)) return raw;
  return (raw as { data?: EquityPoint[] }).data ?? [];
}

// ─── Microstructure ───────────────────────────────────────────────────────────

export async function fetchMicrostructure(symbol: string): Promise<MicrostructureSnapshot> {
  const res = await api.get<MicrostructureSnapshot | { data?: MicrostructureSnapshot }>(
    `/trading/microstructure?symbol=${encodeURIComponent(symbol)}`
  );
  const raw = res.data;
  if ('spread' in raw) return raw as MicrostructureSnapshot;
  return (raw as { data?: MicrostructureSnapshot }).data ?? buildDefaultMicro();
}

function buildDefaultMicro(): MicrostructureSnapshot {
  return {
    timestamp: Date.now(), spread: 0, spreadPct: 0,
    bidDepth: 0, askDepth: 0, orderFlowImbalance: 0,
    tradePressure: 50, tickDirection: 'flat', vwap: 0, twap: 0, marketImpact: 0,
  };
}

// ─── AI Analysis ──────────────────────────────────────────────────────────────

export async function requestAIAnalysis(context: ChartClickContext): Promise<AIAnalysis> {
  // AI analysis involves regime detection + signal lookup — allow up to 30s
  const res = await api.post<AIAnalysis | { data?: AIAnalysis }>('/trading/ai-analysis', context, { timeout: 30_000 });
  const raw = res.data;
  if ('summary' in raw) return raw as AIAnalysis;
  return (raw as { data?: AIAnalysis }).data ?? buildDefaultAnalysis(context);
}

function buildDefaultAnalysis(context: ChartClickContext): AIAnalysis {
  return {
    id: crypto.randomUUID(),
    timestamp: Date.now(),
    context,
    regime: 'ranging',
    regimeConfidence: 0.5,
    summary: 'Insufficient data for analysis at this point.',
    keyDrivers: [],
    riskAssessment: 'Unable to assess risk without live ML data.',
    recommendedAction: 'wait',
    actionConfidence: 0.3,
    priceTargets: { bull: context.price * 1.005, bear: context.price * 0.995, base: context.price },
    timeHorizon: '1–4 hours',
    warnings: ['Live ML feed unavailable — analysis is indicative only'],
  };
}

// ─── Trade Execution ──────────────────────────────────────────────────────────

export async function placeOrder(order: TradeOrder): Promise<TradeResult> {
  const res = await api.post<TradeResult>('/trading/orders', order);
  return res.data;
}

export async function closePosition(positionId: string): Promise<void> {
  await api.delete(`/trading/positions/${positionId}`);
}

// ─── Geopolitical Intelligence (/api/news) ────────────────────────────────────

export interface GeopoliticalSignal {
  symbol: string;
  direction: 'BUY' | 'SELL' | 'HOLD';
  strength: number;
  confidence: number;
  risk_score: number;
  gold_outlook: string;
  active_conflicts: number;
  key_regions: string[];
  recommendations: string[];
  timestamp: string;
}

export interface GeopoliticalEvent {
  event_type: string;
  severity: string;
  title: string;
  description: string;
  region: string;
  countries: string[];
  timestamp: string;
  source: string;
  confidence: number;
  gold_impact: string | null;
  risk_score: number;
}

export interface GeopoliticalAssessment {
  global_risk_score: number;
  gold_outlook: string;
  active_conflicts: number;
  sanctions_count: number;
  hotspots: number;
  high_risk_regions: string[];
  key_events: GeopoliticalEvent[];
  trading_recommendations: string[];
  timestamp: string;
}

export async function fetchGeopoliticalSignal(): Promise<GeopoliticalSignal> {
  const res = await api.get<GeopoliticalSignal>('/news/geopolitical/signal');
  return res.data;
}

export async function fetchGeopoliticalEvents(forceRefresh = false): Promise<GeopoliticalEvent[]> {
  const res = await api.get<{ events: GeopoliticalEvent[]; count: number }>(
    `/news/geopolitical/events${forceRefresh ? '?force_refresh=true' : ''}`
  );
  return res.data.events ?? [];
}

export async function fetchGeopoliticalAssessment(): Promise<GeopoliticalAssessment> {
  const res = await api.get<GeopoliticalAssessment>('/news/geopolitical/assessment');
  return res.data;
}

export async function fetchNewsSentiment(symbol: string): Promise<{ symbol: string; sentiment_score: number; label: string }> {
  const res = await api.get<{ symbol: string; sentiment_score: number; label: string }>(
    `/news/sentiment/${encodeURIComponent(symbol)}`
  );
  return res.data;
}

// World Monitor returns curated deep-link URLs — no API key required.
// The backend builds these from WorldMonitorIntegration.get_enhanced_views().
export interface WorldMonitorViews {
  gold_relevant_views: Record<string, string>;
  crisis_views: Record<string, string>;
  all_region_views: Record<string, string>;
  full_global_url: string;
  available_layers: string[];
  base_url: string;
  crisis_labels: Record<string, string>;
  region_labels: Record<string, string>;
}

export async function fetchWorldMonitorViews(): Promise<WorldMonitorViews> {
  const res = await api.get<WorldMonitorViews>('/news/geopolitical/world-monitor');
  return res.data;
}

// ─── Query Keys ───────────────────────────────────────────────────────────────
// Centralised key factory for TanStack Query cache management

export const queryKeys = {
  ohlcv:              (symbol: string, tf: string, limit: number) => ['ohlcv', symbol, tf, limit] as const,
  signals:            (symbol: string)             => ['signals', symbol] as const,
  sentiment:          (symbol: string)             => ['sentiment', symbol] as const,
  news:               (symbol: string)             => ['news', symbol] as const,
  risk:               ()                           => ['risk'] as const,
  levels:             (symbol: string)             => ['levels', symbol] as const,
  trendlines:         (symbol: string)             => ['trendlines', symbol] as const,
  patterns:           (symbol: string)             => ['patterns', symbol] as const,
  equityCurve:        (days: number)               => ['equity-curve', days] as const,
  microstructure:     (symbol: string)             => ['microstructure', symbol] as const,
  geoSignal:          ()                           => ['geo-signal'] as const,
  geoEvents:          ()                           => ['geo-events'] as const,
  geoAssessment:      ()                           => ['geo-assessment'] as const,
  geoWorldMonitor:    ()                           => ['geo-world-monitor'] as const,
  newsSentiment:      (symbol: string)             => ['news-sentiment', symbol] as const,
};
