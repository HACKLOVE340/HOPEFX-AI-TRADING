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

export async function fetchOHLCV(params: OHLCVParams): Promise<OHLCVBar[]> {
  const { symbol, timeframe, limit = 500, from, to } = params;
  const query = new URLSearchParams({
    timeframe,
    limit: String(limit),
    ...(from ? { from: String(from) } : {}),
    ...(to   ? { to:   String(to)   } : {}),
  });
  const res = await api.get<OHLCVBar[] | { data?: OHLCVBar[] }>(
    `/trading/ohlcv/${encodeURIComponent(symbol)}?${query}`
  );
  const raw = res.data;
  const bars: OHLCVBar[] = Array.isArray(raw) ? raw : (raw.data ?? []);
  // Normalise timestamps to unix seconds
  return bars.map((b) => ({
    ...b,
    time: b.time > 1e10 ? Math.floor(b.time / 1000) : b.time,
  }));
}

// ─── Signals ──────────────────────────────────────────────────────────────────

export async function fetchSignals(symbol: string, limit = 20): Promise<MLSignal[]> {
  const res = await api.get<MLSignal[] | { signals?: MLSignal[]; data?: MLSignal[] }>(
    `/signals?symbol=${encodeURIComponent(symbol)}&limit=${limit}`
  );
  const raw = res.data;
  if (Array.isArray(raw)) return raw;
  return raw.signals ?? raw.data ?? [];
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
  const res = await api.post<AIAnalysis | { data?: AIAnalysis }>('/trading/ai-analysis', context);
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

// ─── Query Keys ───────────────────────────────────────────────────────────────
// Centralised key factory for TanStack Query cache management

export const queryKeys = {
  ohlcv:              (symbol: string, tf: string) => ['ohlcv', symbol, tf] as const,
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
  newsSentiment:      (symbol: string)             => ['news-sentiment', symbol] as const,
};
