/**
 * ChartDashboard.tsx
 * Master layout — wires every chart-bot component into a single
 * institutional-grade trading dashboard. Handles:
 *   - WS initialisation and all live data subscriptions
 *   - Responsive panel layout (chart + sidebar + bottom panels)
 *   - Tab navigation between bottom panels
 *   - Global CSS keyframes injection
 *   - Error boundaries per panel
 *   - WS connection status bar
 */

import React, {
  useEffect, useRef, useState, useCallback, memo, Component,
  type ErrorInfo, type ReactNode,
} from 'react';
import { useChartBotStore } from '../store/chart-bot-store';
import {
  useOrchestratorWS,
  useLivePriceFeed,
  useLiveMicrostructure,
  useLiveSentiment,
  useLiveRisk,
  useLiveSignals,
  useLiveLevels,
} from '../hooks/useOrchestratorWS';
import { useOHLCV, useLevels, useTrendlines, usePatterns, useSignals, useEquityCurve, useSentiment, useNews, useRiskMetrics } from '../hooks/useChartData';
import { ohlcvLimitFor } from '../services/chart-api';
import { COLORS, CSS_VARS } from '../utils/design-tokens';
import CoreChart from './CoreChart';
import AIOverlays from './AIOverlays';
import EquityCurve from './EquityCurve';
import MicrostructurePanel from './MicrostructurePanel';
import SentimentPanel from './SentimentPanel';
import AIChartBot from './AIChartBot';
import RiskHeatmap from './RiskHeatmap';
import SignalFeed from './SignalFeed';
import type { ChartClickContext } from '../types';
import { IChartApi, ISeriesApi, SeriesType } from 'lightweight-charts';

// ─── Global CSS injection ─────────────────────────────────────────────────────

const GLOBAL_CSS = `
${CSS_VARS}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0.4; }
}
@keyframes blink {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0; }
}
@keyframes spin {
  from { transform: rotate(0deg); }
  to   { transform: rotate(360deg); }
}
@keyframes slideIn {
  from { transform: translateX(100%); opacity: 0; }
  to   { transform: translateX(0);    opacity: 1; }
}
@keyframes fadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to   { opacity: 1; transform: translateY(0);   }
}
* { box-sizing: border-box; }
::-webkit-scrollbar { width: 4px; height: 4px; }
::-webkit-scrollbar-track { background: ${COLORS.bg.void}; }
::-webkit-scrollbar-thumb { background: ${COLORS.bg.divider}; border-radius: 2px; }
::-webkit-scrollbar-thumb:hover { background: ${COLORS.bg.overlay}; }
`;

function injectGlobalCSS() {
  const id = 'chart-bot-global-css';
  if (document.getElementById(id)) return;
  const style = document.createElement('style');
  style.id = id;
  style.textContent = GLOBAL_CSS;
  document.head.appendChild(style);
}

// ─── Error Boundary ───────────────────────────────────────────────────────────

interface EBState { hasError: boolean; error: string }

class PanelErrorBoundary extends Component<{ children: ReactNode; label: string }, EBState> {
  state: EBState = { hasError: false, error: '' };

  static getDerivedStateFromError(error: Error): EBState {
    return { hasError: true, error: error.message };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`[ChartBot] Panel "${this.props.label}" error:`, error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={eb.wrapper}>
          <span style={eb.icon}>✕</span>
          <span style={eb.label}>{this.props.label}</span>
          <span style={eb.msg}>{this.state.error}</span>
          <button style={eb.btn} onClick={() => this.setState({ hasError: false, error: '' })}>
            RETRY
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

const eb: Record<string, React.CSSProperties> = {
  wrapper: { display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: 24, gap: 8, background: COLORS.bg.surface, border: `1px solid ${COLORS.bg.border}`, borderRadius: 8, minHeight: 120 },
  icon:    { fontSize: 20, color: COLORS.loss.base },
  label:   { fontFamily: '"JetBrains Mono", monospace', fontSize: 10, color: COLORS.text.muted, letterSpacing: '0.1em' },
  msg:     { fontFamily: '"Inter", sans-serif', fontSize: 11, color: COLORS.text.secondary, textAlign: 'center' },
  btn:     { background: COLORS.bg.elevated, border: `1px solid ${COLORS.bg.divider}`, borderRadius: 4, color: COLORS.text.secondary, cursor: 'pointer', fontFamily: '"JetBrains Mono", monospace', fontSize: 9, padding: '4px 10px', letterSpacing: '0.06em' },
};

// ─── WS Status Bar ────────────────────────────────────────────────────────────

const WSStatusBar = memo(({ status }: { status: string }) => {
  const color = status === 'connected'    ? COLORS.profit.base
              : status === 'connecting'   ? COLORS.neon.gold
              : status === 'error'        ? COLORS.loss.base
              : COLORS.text.muted;
  const label = status === 'connected'    ? 'LIVE'
              : status === 'connecting'   ? 'CONNECTING…'
              : status === 'error'        ? 'ERROR'
              : 'DISCONNECTED';
  return (
    <div style={{ ...wsb.bar, borderColor: `${color}33` }}>
      <div style={{ ...wsb.dot, background: color, boxShadow: status === 'connected' ? `0 0 6px ${color}` : 'none' }} />
      <span style={{ ...wsb.label, color }}>{label}</span>
      {status === 'connected' && (
        <span style={wsb.sub}>MarketDataOrchestrator · XAUUSD</span>
      )}
    </div>
  );
});
WSStatusBar.displayName = 'WSStatusBar';

const wsb: Record<string, React.CSSProperties> = {
  bar:   { display: 'flex', alignItems: 'center', gap: 6, padding: '4px 14px', background: COLORS.bg.surface, borderBottom: `1px solid ${COLORS.bg.border}` },
  dot:   { width: 6, height: 6, borderRadius: '50%', flexShrink: 0 },
  label: { fontFamily: '"JetBrains Mono", monospace', fontSize: 9, fontWeight: 700, letterSpacing: '0.1em' },
  sub:   { fontFamily: '"JetBrains Mono", monospace', fontSize: 9, color: COLORS.text.muted, marginLeft: 8 },
};

// ─── Bottom Panel Tabs ────────────────────────────────────────────────────────

type BottomTab = 'equity' | 'microstructure' | 'sentiment' | 'risk';

const BOTTOM_TABS: { key: BottomTab; label: string }[] = [
  { key: 'equity',         label: 'EQUITY CURVE'   },
  { key: 'microstructure', label: 'MICROSTRUCTURE'  },
  { key: 'sentiment',      label: 'SENTIMENT'       },
  { key: 'risk',           label: 'RISK MONITOR'    },
];

const TabBar = memo(({ active, onChange }: { active: BottomTab; onChange: (t: BottomTab) => void }) => (
  <div style={tb.bar}>
    {BOTTOM_TABS.map((t) => (
      <button
        key={t.key}
        onClick={() => onChange(t.key)}
        style={{ ...tb.btn, ...(active === t.key ? tb.btnActive : {}) }}
      >
        {t.label}
      </button>
    ))}
  </div>
));
TabBar.displayName = 'TabBar';

const tb: Record<string, React.CSSProperties> = {
  bar:       { display: 'flex', borderBottom: `1px solid ${COLORS.bg.border}`, background: COLORS.bg.surface },
  btn:       { background: 'transparent', border: 'none', borderBottom: '2px solid transparent', color: COLORS.text.muted, cursor: 'pointer', fontFamily: '"JetBrains Mono", monospace', fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', padding: '8px 14px', transition: 'all 150ms ease' },
  btnActive: { color: COLORS.neon.cyan, borderBottomColor: COLORS.neon.cyan, background: `${COLORS.neon.cyan}08` },
};

// ─── Data Initialiser ─────────────────────────────────────────────────────────
// Fetches initial REST data and seeds the store on mount

const DataInitialiser: React.FC = () => {
  const symbol    = useChartBotStore((s) => s.symbol);
  const timeframe = useChartBotStore((s) => s.timeframe);
  const setBars   = useChartBotStore((s) => s.setBars);
  const setLevels = useChartBotStore((s) => s.setLevels);
  const setTL     = useChartBotStore((s) => s.setTrendlines);
  const setPat    = useChartBotStore((s) => s.setPatterns);
  const setSig    = useChartBotStore((s) => s.setSignals);
  const setEq     = useChartBotStore((s) => s.setEquityCurve);
  const setSent   = useChartBotStore((s) => s.setSentiment);
  const setNews   = useChartBotStore((s) => s.setNews);
  const setRisk   = useChartBotStore((s) => s.setRiskMetrics);

  // Deep timeframes pull far more bars so the chart can scroll back decades
  // (daily gold history reaches ~2000); intraday stays light for speed.
  // Shared helper keeps this key identical to CoreChart's so they share cache.
  const { data: bars }      = useOHLCV(symbol, timeframe, ohlcvLimitFor(timeframe));
  const { data: levels }    = useLevels(symbol);
  const { data: trendlines }= useTrendlines(symbol);
  const { data: patterns }  = usePatterns(symbol);
  const { data: signals }   = useSignals(symbol);
  const { data: equity }    = useEquityCurve(90);
  const { data: sentiment } = useSentiment(symbol.replace('/', ''));
  const { data: news }      = useNews(symbol.replace('/', ''));
  const { data: risk }      = useRiskMetrics();

  useEffect(() => { if (bars)       setBars(bars);           }, [bars,       setBars]);
  useEffect(() => { if (levels)     setLevels(levels);       }, [levels,     setLevels]);
  useEffect(() => { if (trendlines) setTL(trendlines);       }, [trendlines, setTL]);
  useEffect(() => { if (patterns)   setPat(patterns);        }, [patterns,   setPat]);
  useEffect(() => { if (signals)    setSig(signals);         }, [signals,    setSig]);
  useEffect(() => { if (equity)     setEq(equity);           }, [equity,     setEq]);
  useEffect(() => { if (sentiment)  setSent(sentiment);      }, [sentiment,  setSent]);
  useEffect(() => { if (news)       setNews(news);           }, [news,       setNews]);
  useEffect(() => { if (risk)       setRisk(risk);           }, [risk,       setRisk]);

  return null;
};

// ─── Live Feed Activator ──────────────────────────────────────────────────────
// Activates all WS subscriptions — must be inside useOrchestratorWS context

const LiveFeedActivator: React.FC = () => {
  const symbol = useChartBotStore((s) => s.symbol);
  useLivePriceFeed(symbol);
  useLiveMicrostructure();
  useLiveSentiment();
  useLiveRisk();
  useLiveSignals();
  useLiveLevels();
  return null;
};

// ─── Chart Container (chart + SVG overlays) ───────────────────────────────────

const CHART_HEADER_HEIGHT = 68; // crosshair bar + header

const ChartContainer: React.FC<{ onChartClick: (ctx: ChartClickContext) => void }> = memo(({ onChartClick }) => {
  const containerRef  = useRef<HTMLDivElement>(null);
  const [dims, setDims] = useState({ width: 0, height: 0 });

  // Refs populated by CoreChart's onChartReady callback
  const chartApiRef  = useRef<IChartApi | null>(null);
  const seriesApiRef = useRef<ISeriesApi<SeriesType> | null>(null);

  // Re-render trigger so AIOverlays gets the refs after chart init
  const [chartReady, setChartReady] = useState(false);

  const signals    = useChartBotStore((s) => s.signals);
  const levels     = useChartBotStore((s) => s.levels);
  const trendlines = useChartBotStore((s) => s.trendlines);
  const patterns   = useChartBotStore((s) => s.patterns);

  // Observe container size for SVG overlay dimensions
  useEffect(() => {
    if (!containerRef.current) return;
    const ro = new ResizeObserver((entries) => {
      const rect = entries[0]?.contentRect;
      if (!rect) return;
      setDims({ width: rect.width, height: rect.height });
    });
    ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, []);

  // Called by CoreChart once the chart and candle series are ready
  const handleChartReady = useCallback((chart: IChartApi, series: ISeriesApi<'Candlestick'>) => {
    chartApiRef.current  = chart;
    seriesApiRef.current = series;
    setChartReady(true);
  }, []);

  return (
    <div ref={containerRef} style={{ position: 'relative', flex: 1, minWidth: 0 }}>
      <PanelErrorBoundary label="CORE CHART">
        <CoreChart
          onChartClick={onChartClick}
          onChartReady={handleChartReady}
          signals={signals}
          levels={levels}
          patterns={patterns}
          height={540}
        />
      </PanelErrorBoundary>

      {/* SVG overlays — only rendered once chart refs are available */}
      {chartReady && (
        <div style={{ position: 'absolute', top: CHART_HEADER_HEIGHT, left: 0, right: 0, bottom: 0, pointerEvents: 'none' }}>
          <AIOverlays
            chart={chartApiRef.current}
            series={seriesApiRef.current}
            levels={levels}
            trendlines={trendlines}
            patterns={patterns}
            containerWidth={dims.width}
            containerHeight={Math.max(dims.height - CHART_HEADER_HEIGHT, 0)}
          />
        </div>
      )}
    </div>
  );
});
ChartContainer.displayName = 'ChartContainer';

// ─── Right Sidebar ────────────────────────────────────────────────────────────

type SideTab = 'ai' | 'signals';

const RightSidebar = memo(() => {
  const [tab, setTab] = useState<SideTab>('ai');

  return (
    <div style={rs.wrapper}>
      {/* Tab switcher */}
      <div style={rs.tabs}>
        <button
          onClick={() => setTab('ai')}
          style={{ ...rs.tab, ...(tab === 'ai' ? rs.tabActive : {}) }}
        >
          AI BOT
        </button>
        <button
          onClick={() => setTab('signals')}
          style={{ ...rs.tab, ...(tab === 'signals' ? rs.tabActive : {}) }}
        >
          SIGNALS
        </button>
      </div>

      <div style={rs.content}>
        {tab === 'ai' ? (
          <PanelErrorBoundary label="AI CHART BOT">
            <AIChartBot />
          </PanelErrorBoundary>
        ) : (
          <PanelErrorBoundary label="SIGNAL FEED">
            <SignalFeed />
          </PanelErrorBoundary>
        )}
      </div>
    </div>
  );
});
RightSidebar.displayName = 'RightSidebar';

const rs: Record<string, React.CSSProperties> = {
  wrapper: { width: 340, flexShrink: 0, display: 'flex', flexDirection: 'column', background: COLORS.bg.surface, border: `1px solid ${COLORS.bg.border}`, borderRadius: 8, overflow: 'hidden', height: '100%' },
  tabs:    { display: 'flex', borderBottom: `1px solid ${COLORS.bg.border}` },
  tab:     { flex: 1, background: 'transparent', border: 'none', borderBottom: '2px solid transparent', color: COLORS.text.muted, cursor: 'pointer', fontFamily: '"JetBrains Mono", monospace', fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', padding: '9px 0', transition: 'all 150ms ease' },
  tabActive:{ color: COLORS.neon.purple, borderBottomColor: COLORS.neon.purple, background: `${COLORS.neon.purple}08` },
  content: { flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' },
};

// ─── Bottom Panel ─────────────────────────────────────────────────────────────

const BottomPanel = memo(() => {
  const [tab, setTab] = useState<BottomTab>('equity');

  return (
    <div style={bp.wrapper}>
      <TabBar active={tab} onChange={setTab} />
      <div style={bp.content}>
        {tab === 'equity' && (
          <PanelErrorBoundary label="EQUITY CURVE">
            <EquityCurve />
          </PanelErrorBoundary>
        )}
        {tab === 'microstructure' && (
          <PanelErrorBoundary label="MICROSTRUCTURE">
            <MicrostructurePanel />
          </PanelErrorBoundary>
        )}
        {tab === 'sentiment' && (
          <PanelErrorBoundary label="SENTIMENT">
            <SentimentPanel />
          </PanelErrorBoundary>
        )}
        {tab === 'risk' && (
          <PanelErrorBoundary label="RISK MONITOR">
            <RiskHeatmap />
          </PanelErrorBoundary>
        )}
      </div>
    </div>
  );
});
BottomPanel.displayName = 'BottomPanel';

const bp: Record<string, React.CSSProperties> = {
  wrapper: { background: COLORS.bg.surface, border: `1px solid ${COLORS.bg.border}`, borderRadius: 8, overflow: 'hidden' },
  content: { overflowY: 'auto', maxHeight: 520 },
};

// ─── Main Dashboard ───────────────────────────────────────────────────────────

const ChartDashboard: React.FC = () => {
  const { status } = useOrchestratorWS();
  const setShowAIBot = useChartBotStore((s) => s.setShowAIBot);

  // Inject global CSS once
  useEffect(() => { injectGlobalCSS(); }, []);

  const handleChartClick = useCallback((ctx: ChartClickContext) => {
    setShowAIBot(true);
    // Context is already written to store by CoreChart via setClickContext
    // AIChartBot reads it and auto-triggers analysis
  }, [setShowAIBot]);

  return (
    <div style={d.root}>
      {/* WS status bar */}
      <WSStatusBar status={status} />

      {/* Data initialisation (REST seed) */}
      <DataInitialiser />

      {/* Live WS subscriptions */}
      <LiveFeedActivator />

      {/* Main content area */}
      <div style={d.body}>
        {/* Left: chart + bottom panels */}
        <div style={d.left}>
          {/* Chart row */}
          <div style={d.chartRow}>
            <ChartContainer onChartClick={handleChartClick} />
          </div>

          {/* Bottom panels */}
          <BottomPanel />
        </div>

        {/* Right sidebar: AI Bot + Signal Feed */}
        <RightSidebar />
      </div>
    </div>
  );
};

const d: Record<string, React.CSSProperties> = {
  root: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    minHeight: '100vh',
    background: COLORS.bg.base,
    fontFamily: '"Inter", "SF Pro Display", system-ui, sans-serif',
  },
  body: {
    display: 'flex',
    flex: 1,
    gap: 8,
    padding: 8,
    alignItems: 'flex-start',
    overflow: 'hidden',
    minHeight: 0,
  },
  left: {
    flex: 1,
    minWidth: 0,
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
  },
  chartRow: {
    display: 'flex',
    gap: 8,
    alignItems: 'flex-start',
  },
};

export default ChartDashboard;
