/**
 * pages/AIChartDashboard.tsx
 * Multi-symbol AI chart dashboard.
 *
 * Layout:
 *   - Header: regime summary strip, WS status, active strategies
 *   - Grid of AIChart panels (one per symbol, 3-col desktop / 2-col tablet / 1-col mobile)
 *   - Each panel shows candlestick + AI overlays (SL/TP/key levels/entry zone)
 *
 * Data wiring:
 *   - Bootstrapped globally via AppShell (do NOT call useBootstrapData here)
 *   - tradingApi.ohlcv() per symbol (via AIChart internal)
 *   - tradingApi.aiAnalysis() per symbol (via AIChart internal, auto-triggered)
 *   - tradingApi.regime() + brainState() for the header strip
 */

import React, { useEffect, useState, Component } from 'react';
import { useQuery } from '@tanstack/react-query';
import { AIChart } from '../components/charts/AIChart';
import { cn } from '../lib/utils';
import { useStore, selectWsStatus, selectIsAuth, useHasHydrated } from '../store';
import { tradingApi } from '../hooks/useApi';

// ── Constants ─────────────────────────────────────────────────────────────────

const SYMBOLS    = ['XAU/USD', 'EUR/USD', 'GBP/USD', 'USD/JPY', 'BTC/USD', 'ETH/USD'];
const TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h', '1d'] as const;
type  TF         = (typeof TIMEFRAMES)[number];

// ── Types ─────────────────────────────────────────────────────────────────────

interface BrainState {
  status:             string;
  mode:               string;
  active_strategies:  string[];
  confidence?:        number;
  updated_at?:        string;
}

interface MarketRegime {
  regime:     string;
  confidence: number;
  volatility: string;
  trend:      string;
  description?: string;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function apiSym(s: string) { return s.replace('/', '_'); }

function regimeColor(r?: string): string {
  if (!r) return '#64748b';
  const l = r.toLowerCase();
  if (l.includes('bull') || l.includes('trend_up'))   return '#00e676';
  if (l.includes('bear') || l.includes('trend_down')) return '#ff1744';
  if (l.includes('range') || l.includes('chop'))      return '#ffb800';
  return '#00d4ff';
}

// ── Regime strip ──────────────────────────────────────────────────────────────

function RegimeStrip() {
  const isAuth   = useStore(selectIsAuth);
  const hydrated = useHasHydrated();
  const wsStatus = useStore(selectWsStatus);

  const { data: regime } = useQuery<MarketRegime>({
    queryKey: ['regime-strip'],
    queryFn:  async () => {
      const r = await tradingApi.regime();
      return r.data as MarketRegime;
    },
    enabled:         hydrated && isAuth,
    refetchInterval: 30_000,
    staleTime:       15_000,
  });

  const { data: brain } = useQuery<BrainState>({
    queryKey: ['brain-state-strip'],
    queryFn:  async () => {
      const r = await tradingApi.brainState();
      return r.data as BrainState;
    },
    enabled:         hydrated && isAuth,
    refetchInterval: 15_000,
    staleTime:       7_500,
  });

  return (
    <div className="flex items-center gap-4 px-4 py-2.5 bg-[#0a1628] border-b border-[#1e2d3d] text-[11px] flex-wrap shrink-0">

      {/* WS indicator */}
      <div className="flex items-center gap-1.5">
        <span
          className={cn(
            'w-1.5 h-1.5 rounded-full',
            wsStatus === 'connected'  ? 'bg-[#00e676] animate-pulse' :
            wsStatus === 'connecting' ? 'bg-[#ffb800]' : 'bg-[#ff1744]',
          )}
        />
        <span className="text-slate-500 capitalize">{wsStatus}</span>
      </div>

      <div className="w-px h-4 bg-[#1e2d3d]" />

      {/* Regime */}
      {regime ? (
        <>
          <div className="flex items-center gap-1.5">
            <span className="text-slate-500">Regime</span>
            <span className="font-bold uppercase tracking-wider" style={{ color: regimeColor(regime.regime) }}>
              {regime.regime}
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-slate-500">Volatility</span>
            <span className="text-slate-300 uppercase font-semibold">{regime.volatility}</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-slate-500">Trend</span>
            <span className="text-slate-300 uppercase font-semibold">{regime.trend}</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-slate-500">Conf</span>
            <span
              className="font-bold tabular-nums"
              style={{ color: regime.confidence >= 0.7 ? '#00e676' : '#ffb800' }}
            >
              {(regime.confidence * 100).toFixed(0)}%
            </span>
          </div>
        </>
      ) : (
        <span className="text-slate-600">Awaiting regime data…</span>
      )}

      {brain && (
        <>
          <div className="w-px h-4 bg-[#1e2d3d]" />
          <div className="flex items-center gap-1.5">
            <span className="text-slate-500">Brain</span>
            <span className="text-[#00d4ff] font-semibold uppercase">{brain.mode}</span>
          </div>
          {brain.active_strategies?.length > 0 && (
            <div className="flex items-center gap-1 flex-wrap">
              {brain.active_strategies.slice(0, 4).map((s) => (
                <span key={s} className="px-1.5 py-0.5 rounded bg-[#1e2d3d] text-[9px] text-slate-400 font-mono">
                  {s}
                </span>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ── Timeframe selector ────────────────────────────────────────────────────────

function TfSelector({ value, onChange }: { value: TF; onChange: (tf: TF) => void }) {
  return (
    <div className="flex items-center gap-1">
      {TIMEFRAMES.map((tf) => (
        <button
          key={tf}
          onClick={() => onChange(tf)}
          className={cn(
            'px-2 py-0.5 rounded text-[11px] font-semibold border transition-colors',
            value === tf
              ? 'bg-[#1e3a5f] border-[#3b82f6] text-[#60a5fa]'
              : 'bg-transparent border-[#1e2d3d] text-slate-500 hover:border-[#334155]',
          )}
        >
          {tf}
        </button>
      ))}
    </div>
  );
}

// ── Error boundary ────────────────────────────────────────────────────────────

class ChartErrorBoundary extends React.Component<
  { children: React.ReactNode; label: string },
  { hasError: boolean; message: string }
> {
  constructor(props: { children: React.ReactNode; label: string }) {
    super(props);
    this.state = { hasError: false, message: '' };
  }
  static getDerivedStateFromError(err: unknown) {
    return { hasError: true, message: err instanceof Error ? err.message : String(err) };
  }
  render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center h-[300px] bg-[#0d1421] border border-[#1e2d3d] rounded-lg gap-2">
          <span className="text-[#ff1744] text-xs font-semibold">{this.props.label} failed to load</span>
          <span className="text-slate-600 text-[10px]">{this.state.message}</span>
          <button
            className="mt-2 px-3 py-1 text-[11px] bg-[#1e2d3d] text-slate-400 rounded hover:bg-[#263548]"
            onClick={() => this.setState({ hasError: false, message: '' })}
          >
            Retry
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function AIChartDashboard() {
  const [timeframe, setTimeframe] = useState<TF>('1h');

  return (
    <div className="flex flex-col h-screen bg-[#080c14] overflow-hidden">

      {/* ── Top bar ────────────────────────────────────────────────── */}
      <div className="flex items-center gap-4 px-4 py-2.5 bg-[#0a0f1a] border-b border-[#1e2d3d] shrink-0">
        <div>
          <h1 className="text-[14px] font-bold text-slate-100 leading-tight">AI Chart Dashboard</h1>
          <p className="text-[11px] text-slate-500">Multi-symbol AI analysis</p>
        </div>
        <div className="flex-1" />
        <TfSelector value={timeframe} onChange={setTimeframe} />
      </div>

      {/* ── Regime / brain strip ───────────────────────────────────── */}
      <ChartErrorBoundary label="Regime Strip">
        <RegimeStrip />
      </ChartErrorBoundary>

      {/* ── Charts grid ────────────────────────────────────────────── */}
      <div className="flex-1 min-h-0 overflow-y-auto p-2">
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-2">
          {SYMBOLS.map((sym) => (
            <ChartErrorBoundary key={`${sym}-${timeframe}`} label={sym}>
              <AIChart
                symbol={sym}
                timeframe={timeframe}
                height={300}
                autoAnalyze
                showBranding={false}
              />
            </ChartErrorBoundary>
          ))}
        </div>
      </div>
    </div>
  );
}
