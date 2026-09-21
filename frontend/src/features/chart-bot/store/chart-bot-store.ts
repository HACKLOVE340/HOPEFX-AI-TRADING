/**
 * chart-bot/store/chart-bot-store.ts
 *
 * Zustand store — single source of truth for all chart-bot real-time state.
 * Slices:
 *   chart       – active symbol, timeframe, OHLCV bars, live tick
 *   microstructure – spread, order flow, trade pressure
 *   signals     – ML signals feed (ring buffer, max 50)
 *   sentiment   – sentiment snapshot + news feed (max 30)
 *   risk        – risk metrics snapshot
 *   levels      – S/R levels, trendlines, patterns
 *   equity      – equity curve points (ring buffer, max 500)
 *   ai          – AI analysis state (pending, result, error)
 *   ui          – selected timeframe, active panel, chart click context
 */

import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import type {
  OHLCVBar,
  PriceTick,
  MicrostructureSnapshot,
  VolumeDeltaBar,
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
} from '../types';

// ─── Constants ────────────────────────────────────────────────────────────────

const MAX_SIGNALS      = 50;
const MAX_NEWS         = 30;
const MAX_EQUITY_PTS   = 500;
const MAX_VOLUME_DELTA = 300;

// ─── Slice types ──────────────────────────────────────────────────────────────

interface ChartSlice {
  symbol:       string;
  timeframe:    string;
  bars:         OHLCVBar[];
  liveTick:     PriceTick | null;
  volumeDelta:  VolumeDeltaBar[];
  setSymbol:    (symbol: string) => void;
  setTimeframe: (tf: string) => void;
  setBars:      (bars: OHLCVBar[]) => void;
  setLiveTick:  (tick: PriceTick | null) => void;
  addVolumeDelta:(bar: VolumeDeltaBar) => void;
}

interface MicrostructureSlice {
  microstructure: MicrostructureSnapshot | null;
  setMicrostructure: (snap: MicrostructureSnapshot) => void;
}

interface SignalSlice {
  signals:    MLSignal[];
  setSignals: (signals: MLSignal[]) => void;
  addSignal:  (signal: MLSignal) => void;
}

interface SentimentSlice {
  sentiment:   SentimentSnapshot | null;
  news:        NewsItem[];
  setSentiment:(snap: SentimentSnapshot) => void;
  addNewsItem: (item: NewsItem) => void;
  setNews:     (items: NewsItem[]) => void;
}

interface RiskSlice {
  riskMetrics:    RiskMetrics | null;
  setRiskMetrics: (metrics: RiskMetrics) => void;
}

interface LevelsSlice {
  levels:      SupportResistanceLevel[];
  trendlines:  TrendLine[];
  patterns:    ChartPattern[];
  setLevels:   (levels: SupportResistanceLevel[]) => void;
  setTrendlines:(lines: TrendLine[]) => void;
  addPattern:  (pattern: ChartPattern) => void;
  setPatterns: (patterns: ChartPattern[]) => void;
}

interface EquitySlice {
  equityCurve:   EquityPoint[];
  setEquityCurve:(points: EquityPoint[]) => void;
  addEquityPoint:(point: EquityPoint) => void;
}

interface AISlice {
  aiAnalysis:       AIAnalysis | null;
  aiPending:        boolean;
  aiError:          string | null;
  clickContext:     ChartClickContext | null;
  setAIAnalysis:    (analysis: AIAnalysis) => void;
  setAIPending:     (pending: boolean) => void;
  setAIError:       (error: string | null) => void;
  setClickContext:  (ctx: ChartClickContext | null) => void;
  clearAI:          () => void;
}

interface UISlice {
  activePanel:      'chart' | 'equity' | 'microstructure' | 'sentiment' | 'risk' | 'signals';
  showAIBot:        boolean;
  showOrderPanel:   boolean;
  selectedSignalId: string | null;
  chartReady:       boolean;
  setActivePanel:   (panel: UISlice['activePanel']) => void;
  setShowAIBot:     (show: boolean) => void;
  setShowOrderPanel:(show: boolean) => void;
  setSelectedSignal:(id: string | null) => void;
  setChartReady:    (ready: boolean) => void;
}

type ChartBotStore =
  ChartSlice &
  MicrostructureSlice &
  SignalSlice &
  SentimentSlice &
  RiskSlice &
  LevelsSlice &
  EquitySlice &
  AISlice &
  UISlice;

// ─── Store ────────────────────────────────────────────────────────────────────

export const useChartBotStore = create<ChartBotStore>()(
  devtools(
    (set) => ({
      // ── Chart ──────────────────────────────────────────────────────────────
      symbol:      'XAU/USD',
      timeframe:   '1h',
      bars:        [],
      liveTick:    null,
      volumeDelta: [],

      setSymbol:    (symbol)    => set({ symbol }, false, 'chart/setSymbol'),
      setTimeframe: (timeframe) => set({ timeframe }, false, 'chart/setTimeframe'),
      setBars:      (bars)      => set({ bars }, false, 'chart/setBars'),

      setLiveTick: (tick) =>
        set({ liveTick: tick }, false, 'chart/setLiveTick'),

      addVolumeDelta: (bar) =>
        set(
          (s) => ({
            volumeDelta: [...s.volumeDelta, bar].slice(-MAX_VOLUME_DELTA),
          }),
          false,
          'chart/addVolumeDelta',
        ),

      // ── Microstructure ─────────────────────────────────────────────────────
      microstructure: null,
      setMicrostructure: (snap) =>
        set({ microstructure: snap }, false, 'micro/set'),

      // ── Signals ────────────────────────────────────────────────────────────
      signals: [],
      setSignals: (signals) => set({ signals }, false, 'signals/set'),
      addSignal: (signal) =>
        set(
          (s) => ({
            signals: [signal, ...s.signals.filter((x) => x.id !== signal.id)].slice(0, MAX_SIGNALS),
          }),
          false,
          'signals/add',
        ),

      // ── Sentiment ──────────────────────────────────────────────────────────
      sentiment: null,
      news:      [],
      setSentiment: (snap)  => set({ sentiment: snap }, false, 'sentiment/set'),
      setNews:      (items) => set({ news: items }, false, 'news/set'),
      addNewsItem: (item) =>
        set(
          (s) => ({
            news: [item, ...s.news.filter((x) => x.id !== item.id)].slice(0, MAX_NEWS),
          }),
          false,
          'news/add',
        ),

      // ── Risk ───────────────────────────────────────────────────────────────
      riskMetrics: null,
      setRiskMetrics: (metrics) => set({ riskMetrics: metrics }, false, 'risk/set'),

      // ── Levels ─────────────────────────────────────────────────────────────
      levels:     [],
      trendlines: [],
      patterns:   [],
      setLevels:    (levels)    => set({ levels }, false, 'levels/set'),
      setTrendlines:(trendlines)=> set({ trendlines }, false, 'trendlines/set'),
      setPatterns:  (patterns)  => set({ patterns }, false, 'patterns/set'),
      addPattern: (pattern) =>
        set(
          (s) => ({
            patterns: [pattern, ...s.patterns.filter((x) => x.id !== pattern.id)].slice(0, 20),
          }),
          false,
          'patterns/add',
        ),

      // ── Equity ─────────────────────────────────────────────────────────────
      equityCurve: [],
      setEquityCurve: (points) => set({ equityCurve: points }, false, 'equity/set'),
      addEquityPoint: (point) =>
        set(
          (s) => ({
            equityCurve: [...s.equityCurve, point].slice(-MAX_EQUITY_PTS),
          }),
          false,
          'equity/add',
        ),

      // ── AI ─────────────────────────────────────────────────────────────────
      aiAnalysis:   null,
      aiPending:    false,
      aiError:      null,
      clickContext: null,

      setAIAnalysis:   (analysis) => set({ aiAnalysis: analysis, aiPending: false, aiError: null }, false, 'ai/setAnalysis'),
      setAIPending:    (pending)  => set({ aiPending: pending }, false, 'ai/setPending'),
      setAIError:      (error)    => set({ aiError: error, aiPending: false }, false, 'ai/setError'),
      setClickContext: (ctx)      => set({ clickContext: ctx }, false, 'ai/setContext'),
      clearAI: () =>
        set({ aiAnalysis: null, aiPending: false, aiError: null, clickContext: null }, false, 'ai/clear'),

      // ── UI ─────────────────────────────────────────────────────────────────
      activePanel:      'chart',
      showAIBot:        false,
      showOrderPanel:   false,
      selectedSignalId: null,
      chartReady:       false,

      setActivePanel:    (panel) => set({ activePanel: panel }, false, 'ui/setPanel'),
      setShowAIBot:      (show)  => set({ showAIBot: show }, false, 'ui/showAIBot'),
      setShowOrderPanel: (show)  => set({ showOrderPanel: show }, false, 'ui/showOrderPanel'),
      setSelectedSignal: (id)    => set({ selectedSignalId: id }, false, 'ui/selectSignal'),
      setChartReady:     (ready) => set({ chartReady: ready }, false, 'ui/chartReady'),
    }),
    { name: 'ChartBot' },
  ),
);

// ─── Selectors ────────────────────────────────────────────────────────────────

export const selectSymbol        = (s: ChartBotStore) => s.symbol;
export const selectTimeframe     = (s: ChartBotStore) => s.timeframe;
export const selectBars          = (s: ChartBotStore) => s.bars;
export const selectLiveTick      = (s: ChartBotStore) => s.liveTick;
export const selectVolumeDelta   = (s: ChartBotStore) => s.volumeDelta;
export const selectMicro         = (s: ChartBotStore) => s.microstructure;
export const selectSignals       = (s: ChartBotStore) => s.signals;
export const selectSentiment     = (s: ChartBotStore) => s.sentiment;
export const selectNews          = (s: ChartBotStore) => s.news;
export const selectRisk          = (s: ChartBotStore) => s.riskMetrics;
export const selectLevels        = (s: ChartBotStore) => s.levels;
export const selectTrendlines    = (s: ChartBotStore) => s.trendlines;
export const selectPatterns      = (s: ChartBotStore) => s.patterns;
export const selectEquityCurve   = (s: ChartBotStore) => s.equityCurve;
export const selectAIAnalysis    = (s: ChartBotStore) => s.aiAnalysis;
export const selectAIPending     = (s: ChartBotStore) => s.aiPending;
export const selectClickContext  = (s: ChartBotStore) => s.clickContext;
export const selectActivePanel   = (s: ChartBotStore) => s.activePanel;
export const selectShowAIBot     = (s: ChartBotStore) => s.showAIBot;
export const selectShowOrderPanel= (s: ChartBotStore) => s.showOrderPanel;
export const selectChartReady    = (s: ChartBotStore) => s.chartReady;
