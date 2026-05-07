/**
 * pages/TradingDashboard.tsx
 * Elite trading terminal dashboard.
 *
 * Layout (desktop):
 * ┌─────────────────────────────────────────────────────────────────┐
 * │  LivePriceTicker (full width)                                   │
 * │  AccountBar (full width)                                        │
 * ├──────────────────────────┬──────────────────┬───────────────────┤
 * │  EquityCurveChart (5)    │  LiveSignalFeed  │  RiskDashboard    │
 * │  (row-span-2)            │  (3, row-span-2) │  (2)              │
 * ├──────────────────────────┤                  ├───────────────────┤
 * │  OrderBookDepth (5)      │                  │  SentimentGauge   │
 * │                          │                  │  + Microstructure │
 * ├──────────────────────────┴──────────────────┴───────────────────┤
 * │  MacroCalendar (5)  │  OrchestratorHealth (4)  │  MLModel (3)   │
 * └─────────────────────────────────────────────────────────────────┘
 *
 * Data wiring:
 *   - WebSocket is managed globally in App.tsx — do NOT call useWebSocket here.
 *   - useBootstrapData() → TanStack Query → Zustand (all orchestrator data)
 */

import React, { Suspense } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useStore } from '../store';
// useBootstrapData and useWebSocket are intentionally NOT imported here —
// both are managed globally in AppShell (App.tsx) to prevent duplicate
// polling and duplicate WebSocket connections on page navigation.
import { PanelErrorBoundary } from '../components/ui/PanelErrorBoundary';
import { PanelSkeleton, ChartSkeleton, TickerSkeleton } from '../components/ui/Skeleton';

// ── Eagerly loaded (above-the-fold, tiny) ─────────────────────────────────────
import { LivePriceTicker }  from '../components/panels/LivePriceTicker';
import { AccountBar }       from '../components/terminal/AccountBar';


// ── Quick-action bar ──────────────────────────────────────────────────────────
const QuickActionBar: React.FC = () => {
  const navigate = useNavigate();
  const positions = useStore((s) => s.positions ?? []);
  const unrealisedPnl = positions.reduce((sum: number, p) => sum + (p.unrealized_pnl ?? 0), 0);
  const pnlColor = unrealisedPnl >= 0 ? '#22c55e' : '#ef4444';

  const actions = [
    { label: '⚡ Trade',           path: '/trade',           color: '#3b82f6' },
    { label: '📊 Portfolio',       path: '/portfolio',       color: '#8b5cf6' },
    { label: '📈 Analytics',       path: '/performance',     color: '#06b6d4' },
    { label: '🧠 AI Strategy',     path: '/ai-strategy',     color: '#f59e0b' },
    { label: '🌍 Geopolitical',    path: '/geopolitical',    color: '#f97316' },
    { label: '📓 Journal',         path: '/journal',         color: '#10b981' },
    { label: '🛡 Risk Calc',       path: '/risk-calculator', color: '#ec4899' },
    { label: '📡 Signals',         path: '/signals',         color: '#a78bfa' },
    { label: '🔁 Copy Trading',    path: '/copy-trading',    color: '#34d399' },
    { label: '👁 Watchlist',       path: '/watchlist',       color: '#38bdf8' },
  ];

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 8,
      padding: '4px 8px',
      background: 'rgba(6,13,24,0.8)',
      borderBottom: '1px solid #1a2e4a',
      overflowX: 'auto', flexShrink: 0,
    }}>
      {/* Breadcrumb */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexShrink: 0, marginRight: 4 }}>
        <Link
          to="/dashboard"
          style={{ fontSize: 10, color: '#475569', textDecoration: 'none', fontWeight: 600, letterSpacing: 0.5 }}
          onMouseEnter={(e) => { (e.currentTarget as HTMLAnchorElement).style.color = '#64748b'; }}
          onMouseLeave={(e) => { (e.currentTarget as HTMLAnchorElement).style.color = '#475569'; }}
        >
          HOME
        </Link>
        <span style={{ fontSize: 10, color: '#1e293b' }}>›</span>
        <span style={{ fontSize: 10, color: '#64748b', fontWeight: 600, letterSpacing: 0.5 }}>TERMINAL</span>
      </div>

      <div style={{ width: 1, height: 20, background: '#1e293b', flexShrink: 0 }} />

      {/* Today P&L */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 6,
        padding: '3px 10px',
        background: `${pnlColor}12`,
        border: `1px solid ${pnlColor}30`,
        borderRadius: 6, flexShrink: 0,
      }}>
        <span style={{ fontSize: 10, color: '#64748b', fontWeight: 700, letterSpacing: 1 }}>OPEN P&L</span>
        <span style={{ fontSize: 13, fontWeight: 800, color: pnlColor, fontFamily: 'monospace' }}>
          {unrealisedPnl >= 0 ? '+' : ''}{unrealisedPnl.toFixed(2)}
        </span>
        {positions.length > 0 && (
          <span style={{ fontSize: 10, color: '#475569' }}>{positions.length} pos</span>
        )}
      </div>

      <div style={{ width: 1, height: 20, background: '#1e293b', flexShrink: 0 }} />

      {/* Quick nav buttons */}
      {actions.map(({ label, path, color }) => (
        <button
          key={path}
          onClick={() => navigate(path)}
          style={{
            background: 'transparent',
            border: `1px solid ${color}30`,
            borderRadius: 6,
            color: '#94a3b8',
            fontSize: 11,
            fontFamily: 'inherit',
            cursor: 'pointer',
            padding: '4px 10px',
            whiteSpace: 'nowrap',
            flexShrink: 0,
            transition: 'all 0.15s ease',
          }}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLButtonElement).style.background = `${color}15`;
            (e.currentTarget as HTMLButtonElement).style.color = color;
            (e.currentTarget as HTMLButtonElement).style.borderColor = `${color}80`;
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLButtonElement).style.background = 'transparent';
            (e.currentTarget as HTMLButtonElement).style.color = '#94a3b8';
            (e.currentTarget as HTMLButtonElement).style.borderColor = `${color}30`;
          }}
        >
          {label}
        </button>
      ))}
    </div>
  );
};

// ── Lazily loaded (heavy Recharts panels — split into separate chunks) ─────────
// Import guarded variants from the barrel so every panel has its own
// PanelErrorBoundary + Suspense wrapper — a crash in one panel never
// takes down the rest of the dashboard.
const EquityCurveChart            = React.lazy(() => import('../components/charts/EquityCurveChart').then(m => ({ default: m.EquityCurveChart })));
const RiskDashboardGuarded        = React.lazy(() => import('../components/panels').then(m => ({ default: m.RiskDashboardGuarded })));
const SentimentGaugeGuarded       = React.lazy(() => import('../components/panels').then(m => ({ default: m.SentimentGaugeGuarded })));
const MicrostructurePanelGuarded  = React.lazy(() => import('../components/panels').then(m => ({ default: m.MicrostructurePanelGuarded })));
const MacroCalendarGuarded        = React.lazy(() => import('../components/panels').then(m => ({ default: m.MacroCalendarGuarded })));
const OrderBookDepthGuarded       = React.lazy(() => import('../components/panels').then(m => ({ default: m.OrderBookDepthGuarded })));
const LiveSignalFeedGuarded       = React.lazy(() => import('../components/panels').then(m => ({ default: m.LiveSignalFeedGuarded })));
const OrchestratorHealthGridGuarded = React.lazy(() => import('../components/panels').then(m => ({ default: m.OrchestratorHealthGridGuarded })));
const MLModelPanelGuarded         = React.lazy(() => import('../components/panels').then(m => ({ default: m.MLModelPanelGuarded })));

// ── Dashboard inner ───────────────────────────────────────────────────────────

function DashboardInner() {
  // wsStatus is consumed by LivePriceTicker (StatusDot) via the store directly.
  // No local read needed here — AppShell manages the WebSocket lifecycle.

  return (
    <div
      className="flex flex-col h-screen bg-[#080c14] overflow-hidden"
      style={{ fontFamily: "'Inter', system-ui, sans-serif", flex: 1, minHeight: 0 }}
    >
      {/* ── Top: price ticker + account bar + quick actions ─────────────── */}
      <PanelErrorBoundary title="Price Ticker">
        <LivePriceTicker />
      </PanelErrorBoundary>
      <PanelErrorBoundary title="Account Bar">
        <AccountBar />
      </PanelErrorBoundary>
      <QuickActionBar />

      {/* ── Main grid ────────────────────────────────────────────────────── */}
      <div className="flex-1 min-h-0 grid grid-cols-12 grid-rows-2 gap-2 p-2 overflow-hidden">

        {/* Equity curve — large center-left, spans 2 rows */}
        <div className="col-span-5 row-span-2 min-h-0">
          <Suspense fallback={<ChartSkeleton />}>
            <EquityCurveChart />
          </Suspense>
        </div>

        {/* Signal feed — center column, spans 2 rows (guarded) */}
        <div className="col-span-3 row-span-2 min-h-0">
          <Suspense fallback={<PanelSkeleton rows={6} />}>
            <LiveSignalFeedGuarded />
          </Suspense>
        </div>

        {/* Risk dashboard — cols 9-10, row 1 (guarded) */}
        <div className="col-span-2 row-span-1 min-h-0">
          <Suspense fallback={<PanelSkeleton rows={4} />}>
            <RiskDashboardGuarded />
          </Suspense>
        </div>

        {/* Order book — cols 11-12, row 1 (guarded) */}
        <div className="col-span-2 row-span-1 min-h-0">
          <Suspense fallback={<PanelSkeleton rows={8} />}>
            <OrderBookDepthGuarded />
          </Suspense>
        </div>

        {/* Sentiment gauge — cols 9-10, row 2 (guarded) */}
        <div className="col-span-2 row-span-1 min-h-0">
          <Suspense fallback={<PanelSkeleton rows={3} />}>
            <SentimentGaugeGuarded />
          </Suspense>
        </div>

        {/* Microstructure — cols 11-12, row 2 (guarded) */}
        <div className="col-span-2 row-span-1 min-h-0">
          <Suspense fallback={<PanelSkeleton rows={5} />}>
            <MicrostructurePanelGuarded />
          </Suspense>
        </div>
      </div>

      {/* ── Bottom row: macro calendar · orchestrator health · ML model ─── */}
      <div className="h-52 shrink-0 grid grid-cols-12 gap-2 px-2 pb-2">
        {/* Macro calendar — left 5 cols (guarded) */}
        <div className="col-span-5 min-h-0">
          <Suspense fallback={<PanelSkeleton rows={3} />}>
            <MacroCalendarGuarded />
          </Suspense>
        </div>

        {/* Orchestrator health — center 4 cols (guarded) */}
        <div className="col-span-4 min-h-0">
          <Suspense fallback={<PanelSkeleton rows={4} />}>
            <OrchestratorHealthGridGuarded />
          </Suspense>
        </div>

        {/* ML model panel — right 3 cols (guarded) */}
        <div className="col-span-3 min-h-0">
          <Suspense fallback={<PanelSkeleton rows={4} />}>
            <MLModelPanelGuarded />
          </Suspense>
        </div>
      </div>
    </div>
  );
}

// ── Exported page ─────────────────────────────────────────────────────────────
// QueryClientProvider is provided by App.tsx root — no wrapper needed here.

export default function TradingDashboard() {
  return <DashboardInner />;
}
