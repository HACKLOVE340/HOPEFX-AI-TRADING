/**
 * pages/TradingDashboard.tsx
 * Elite trading terminal dashboard.
 *
 * Layout (desktop):
 * ┌─────────────────────────────────────────────────────────────────┐
 * │  LivePriceTicker (full width)                                   │
 * │  AccountBar (full width)                                        │
 * ├──────────────────────────┬──────────────────┬───────────────────┤
 * │  EquityCurveChart        │  LiveSignalFeed  │  RiskDashboard    │
 * │  (col-span-2, row-span-2)│                  │                   │
 * ├──────────────────────────┤                  ├───────────────────┤
 * │  OrderBookDepth          │                  │  SentimentGauge   │
 * ├──────────────────────────┴──────────────────┴───────────────────┤
 * │  MicrostructurePanel     │  MacroCalendar                       │
 * └─────────────────────────────────────────────────────────────────┘
 *
 * Data wiring:
 *   - WebSocket is managed globally in App.tsx — do NOT call useWebSocket here.
 *   - useBootstrapData() → TanStack Query → Zustand (all orchestrator data)
 */

import React, { Suspense } from 'react';
// useBootstrapData and useWebSocket are intentionally NOT imported here —
// both are managed globally in AppShell (App.tsx) to prevent duplicate
// polling and duplicate WebSocket connections on page navigation.
import { useStore } from '../store';
import { PanelErrorBoundary } from '../components/ui/PanelErrorBoundary';
import { PanelSkeleton, ChartSkeleton, TickerSkeleton } from '../components/ui/Skeleton';

// ── Eagerly loaded (above-the-fold, tiny) ─────────────────────────────────────
import { LivePriceTicker }  from '../components/panels/LivePriceTicker';
import { AccountBar }       from '../components/terminal/AccountBar';

// ── Lazily loaded (heavy Recharts panels — split into separate chunks) ─────────
const EquityCurveChart    = React.lazy(() => import('../components/charts/EquityCurveChart').then(m => ({ default: m.EquityCurveChart })));
const RiskDashboard       = React.lazy(() => import('../components/panels/RiskDashboard').then(m => ({ default: m.RiskDashboard })));
const SentimentGauge      = React.lazy(() => import('../components/panels/SentimentGauge').then(m => ({ default: m.SentimentGauge })));
const MicrostructurePanel = React.lazy(() => import('../components/panels/MicrostructurePanel').then(m => ({ default: m.MicrostructurePanel })));
const MacroCalendar       = React.lazy(() => import('../components/panels/MacroCalendar').then(m => ({ default: m.MacroCalendar })));
const OrderBookDepth      = React.lazy(() => import('../components/panels/OrderBookDepth').then(m => ({ default: m.OrderBookDepth })));
const LiveSignalFeed      = React.lazy(() => import('../components/panels/LiveSignalFeed').then(m => ({ default: m.LiveSignalFeed })));

// ── Dashboard inner ───────────────────────────────────────────────────────────

function DashboardInner() {
  // Data is bootstrapped globally in AppShell — read from store directly.
  const wsStatus = useStore((s) => s.wsStatus);

  return (
    <div
      className="flex flex-col h-screen bg-[#080c14] overflow-hidden"
      style={{ fontFamily: "'Inter', system-ui, sans-serif" }}
    >
      {/* ── Top: price ticker + account bar ─────────────────────────────── */}
      <PanelErrorBoundary title="Price Ticker">
        <LivePriceTicker />
      </PanelErrorBoundary>
      <PanelErrorBoundary title="Account Bar">
        <AccountBar />
      </PanelErrorBoundary>

      {/* ── Main grid ────────────────────────────────────────────────────── */}
      <div className="flex-1 min-h-0 grid grid-cols-12 grid-rows-2 gap-2 p-2 overflow-hidden">

        {/* Equity curve — large center-left, spans 2 rows */}
        <div className="col-span-5 row-span-2 min-h-0">
          <PanelErrorBoundary title="Equity Curve">
            <Suspense fallback={<ChartSkeleton />}>
              <EquityCurveChart />
            </Suspense>
          </PanelErrorBoundary>
        </div>

        {/* Signal feed — center column, spans 2 rows */}
        <div className="col-span-3 row-span-2 min-h-0">
          <PanelErrorBoundary title="Signal Feed">
            <Suspense fallback={<PanelSkeleton rows={6} />}>
              <LiveSignalFeed />
            </Suspense>
          </PanelErrorBoundary>
        </div>

        {/* Risk dashboard — top right */}
        <div className="col-span-2 row-span-1 min-h-0">
          <PanelErrorBoundary title="Risk Dashboard">
            <Suspense fallback={<PanelSkeleton rows={4} />}>
              <RiskDashboard />
            </Suspense>
          </PanelErrorBoundary>
        </div>

        {/* Sentiment gauge — bottom right */}
        <div className="col-span-2 row-span-1 min-h-0">
          <PanelErrorBoundary title="Sentiment">
            <Suspense fallback={<PanelSkeleton rows={3} />}>
              <SentimentGauge />
            </Suspense>
          </PanelErrorBoundary>
        </div>

        {/* Order book — far right top */}
        <div className="col-span-2 row-span-1 min-h-0">
          <PanelErrorBoundary title="Order Book">
            <Suspense fallback={<PanelSkeleton rows={8} />}>
              <OrderBookDepth />
            </Suspense>
          </PanelErrorBoundary>
        </div>

        {/* Microstructure — far right bottom */}
        <div className="col-span-2 row-span-1 min-h-0">
          <PanelErrorBoundary title="Microstructure">
            <Suspense fallback={<PanelSkeleton rows={5} />}>
              <MicrostructurePanel />
            </Suspense>
          </PanelErrorBoundary>
        </div>
      </div>

      {/* ── Bottom row: macro calendar ───────────────────────────────────── */}
      <div className="h-48 shrink-0 px-2 pb-2">
        <PanelErrorBoundary title="Macro Calendar">
          <Suspense fallback={<PanelSkeleton rows={3} />}>
            <MacroCalendar />
          </Suspense>
        </PanelErrorBoundary>
      </div>
    </div>
  );
}

// ── Exported page ─────────────────────────────────────────────────────────────
// QueryClientProvider is provided by App.tsx root — no wrapper needed here.

export default function TradingDashboard() {
  return <DashboardInner />;
}
