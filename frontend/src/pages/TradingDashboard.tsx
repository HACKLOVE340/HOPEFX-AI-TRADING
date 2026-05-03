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
import { PanelSkeleton, ChartSkeleton, TickerSkeleton } from '../components/ui/Skeleton';

// ── Eagerly loaded (above-the-fold, tiny) ─────────────────────────────────────
import { LivePriceTicker }  from '../components/panels/LivePriceTicker';
import { AccountBar }       from '../components/terminal/AccountBar';

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
      {/* ── Top: price ticker + account bar ─────────────────────────────── */}
      {/* LivePriceTicker is eagerly loaded (above-the-fold) — wrap manually */}
      <Suspense fallback={<TickerSkeleton />}>
        <LivePriceTicker />
      </Suspense>
      <AccountBar />

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
