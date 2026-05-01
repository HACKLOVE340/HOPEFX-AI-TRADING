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
// useBootstrapData and useWebSocket are intentionally NOT imported here —
// both are managed globally in AppShell (App.tsx) to prevent duplicate
// polling and duplicate WebSocket connections on page navigation.
// useStore is intentionally not imported here — all data flows through
// AppShell (WebSocket, bootstrap queries) into Zustand; panels read directly.
import { PanelErrorBoundary } from '../components/ui/PanelErrorBoundary';
import { PanelSkeleton, ChartSkeleton, TickerSkeleton } from '../components/ui/Skeleton';

// ── Eagerly loaded (above-the-fold, tiny) ─────────────────────────────────────
import { LivePriceTicker }  from '../components/panels/LivePriceTicker';
import { AccountBar }       from '../components/terminal/AccountBar';

// ── Lazily loaded (heavy Recharts panels — split into separate chunks) ─────────
const EquityCurveChart       = React.lazy(() => import('../components/charts/EquityCurveChart').then(m => ({ default: m.EquityCurveChart })));
const RiskDashboard          = React.lazy(() => import('../components/panels/RiskDashboard').then(m => ({ default: m.RiskDashboard })));
const SentimentGauge         = React.lazy(() => import('../components/panels/SentimentGauge').then(m => ({ default: m.SentimentGauge })));
const MicrostructurePanel    = React.lazy(() => import('../components/panels/MicrostructurePanel').then(m => ({ default: m.MicrostructurePanel })));
const MacroCalendar          = React.lazy(() => import('../components/panels/MacroCalendar').then(m => ({ default: m.MacroCalendar })));
const OrderBookDepth         = React.lazy(() => import('../components/panels/OrderBookDepth').then(m => ({ default: m.OrderBookDepth })));
const LiveSignalFeed         = React.lazy(() => import('../components/panels/LiveSignalFeed').then(m => ({ default: m.LiveSignalFeed })));
const OrchestratorHealthGrid = React.lazy(() => import('../components/panels/OrchestratorHealthGrid').then(m => ({ default: m.OrchestratorHealthGrid })));
const MLModelPanel           = React.lazy(() => import('../components/panels/MLModelPanel').then(m => ({ default: m.MLModelPanel })));

// ── Dashboard inner ───────────────────────────────────────────────────────────

function DashboardInner() {
  // wsStatus is consumed by LivePriceTicker (StatusDot) via the store directly.
  // No local read needed here — AppShell manages the WebSocket lifecycle.

  return (
    <div
      className="flex flex-col h-screen bg-[#080c14] overflow-hidden"
      style={{ fontFamily: "'Inter', system-ui, sans-serif", flex: 1, minHeight: 0 }}
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

        {/* Risk dashboard — cols 9-10, row 1 */}
        <div className="col-span-2 row-span-1 min-h-0">
          <PanelErrorBoundary title="Risk Dashboard">
            <Suspense fallback={<PanelSkeleton rows={4} />}>
              <RiskDashboard />
            </Suspense>
          </PanelErrorBoundary>
        </div>

        {/* Order book — cols 11-12, row 1 */}
        <div className="col-span-2 row-span-1 min-h-0">
          <PanelErrorBoundary title="Order Book">
            <Suspense fallback={<PanelSkeleton rows={8} />}>
              <OrderBookDepth />
            </Suspense>
          </PanelErrorBoundary>
        </div>

        {/* Sentiment gauge — cols 9-10, row 2 */}
        <div className="col-span-2 row-span-1 min-h-0">
          <PanelErrorBoundary title="Sentiment">
            <Suspense fallback={<PanelSkeleton rows={3} />}>
              <SentimentGauge />
            </Suspense>
          </PanelErrorBoundary>
        </div>

        {/* Microstructure — cols 11-12, row 2 */}
        <div className="col-span-2 row-span-1 min-h-0">
          <PanelErrorBoundary title="Microstructure">
            <Suspense fallback={<PanelSkeleton rows={5} />}>
              <MicrostructurePanel />
            </Suspense>
          </PanelErrorBoundary>
        </div>
      </div>

      {/* ── Bottom row: macro calendar · orchestrator health · ML model ─── */}
      <div className="h-52 shrink-0 grid grid-cols-12 gap-2 px-2 pb-2">
        {/* Macro calendar — left 5 cols */}
        <div className="col-span-5 min-h-0">
          <PanelErrorBoundary title="Macro Calendar">
            <Suspense fallback={<PanelSkeleton rows={3} />}>
              <MacroCalendar />
            </Suspense>
          </PanelErrorBoundary>
        </div>

        {/* Orchestrator health — center 4 cols */}
        <div className="col-span-4 min-h-0">
          <PanelErrorBoundary title="Orchestrator Health">
            <Suspense fallback={<PanelSkeleton rows={4} />}>
              <OrchestratorHealthGrid />
            </Suspense>
          </PanelErrorBoundary>
        </div>

        {/* ML model panel — right 3 cols */}
        <div className="col-span-3 min-h-0">
          <PanelErrorBoundary title="ML Model">
            <Suspense fallback={<PanelSkeleton rows={4} />}>
              <MLModelPanel />
            </Suspense>
          </PanelErrorBoundary>
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
