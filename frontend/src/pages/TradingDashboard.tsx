/**
 * pages/TradingDashboard.tsx
 * Elite trading terminal dashboard.
 *
 * Layout (12-col × 2-row grid, desktop):
 * ┌──────────────────────────────────────────────────────────────────┐
 * │  LivePriceTicker (full width)                                    │
 * │  AccountBar (full width)                                         │
 * ├─────────────────────┬──────────────┬──────────────┬─────────────┤
 * │  EquityCurveChart   │ LiveSignal   │ RiskDashboard│ OrderBook   │
 * │  (col 1-5, row 1-2) │ (col 6-8,   │ (col 9-10)   │ (col 11-12) │
 * ├─────────────────────┤  row 1-2)   ├──────────────┼─────────────┤
 * │  (equity cont.)     │             │ Sentiment    │ Microstruc. │
 * ├─────────────────────┴─────────────┴──────────────┴─────────────┤
 * │  MacroCalendar (full width, fixed 12rem height)                  │
 * └──────────────────────────────────────────────────────────────────┘
 *
 * Data wiring:
 *   - WebSocket is managed globally in App.tsx — do NOT call useWebSocket here.
 *   - useBootstrapData() is called in AppShell — do NOT call it here.
 */

import React, { Suspense } from 'react';
import { PanelErrorBoundary } from '../components/ui/PanelErrorBoundary';
import { PanelSkeleton, ChartSkeleton, TickerSkeleton } from '../components/ui/Skeleton';

// ── Eagerly loaded (above-the-fold, tiny) ─────────────────────────────────────
import { LivePriceTicker } from '../components/panels/LivePriceTicker';
import { AccountBar }      from '../components/terminal/AccountBar';

// ── Lazily loaded (heavy panels — each in its own chunk) ──────────────────────
const EquityCurveChart    = React.lazy(() => import('../components/charts/EquityCurveChart').then(m => ({ default: m.EquityCurveChart })));
const LiveSignalFeed      = React.lazy(() => import('../components/panels/LiveSignalFeed').then(m => ({ default: m.LiveSignalFeed })));
const RiskDashboard       = React.lazy(() => import('../components/panels/RiskDashboard').then(m => ({ default: m.RiskDashboard })));
const OrderBookDepth      = React.lazy(() => import('../components/panels/OrderBookDepth').then(m => ({ default: m.OrderBookDepth })));
const SentimentGauge      = React.lazy(() => import('../components/panels/SentimentGauge').then(m => ({ default: m.SentimentGauge })));
const MicrostructurePanel = React.lazy(() => import('../components/panels/MicrostructurePanel').then(m => ({ default: m.MicrostructurePanel })));
const MacroCalendar       = React.lazy(() => import('../components/panels/MacroCalendar').then(m => ({ default: m.MacroCalendar })));

// ── Dashboard ─────────────────────────────────────────────────────────────────

export default function TradingDashboard() {
  return (
    <div
      className="flex flex-col h-screen bg-[#080c14] overflow-hidden"
      style={{ fontFamily: "'Inter', system-ui, sans-serif" }}
    >
      {/* ── Top bars ────────────────────────────────────────────────────── */}
      <PanelErrorBoundary title="Price Ticker">
        <Suspense fallback={<TickerSkeleton />}>
          <LivePriceTicker />
        </Suspense>
      </PanelErrorBoundary>

      <PanelErrorBoundary title="Account Bar">
        <AccountBar />
      </PanelErrorBoundary>

      {/* ── Main 12-column, 2-row grid ───────────────────────────────────── */}
      <div className="flex-1 min-h-0 grid grid-cols-12 grid-rows-2 gap-2 p-2 overflow-hidden">

        {/* Equity curve — cols 1-5, spans both rows */}
        <div className="col-span-5 row-span-2 min-h-0">
          <PanelErrorBoundary title="Equity Curve">
            <Suspense fallback={<ChartSkeleton />}>
              <EquityCurveChart />
            </Suspense>
          </PanelErrorBoundary>
        </div>

        {/* Signal feed — cols 6-8, spans both rows */}
        <div className="col-span-3 row-span-2 min-h-0">
          <PanelErrorBoundary title="Signal Feed">
            <Suspense fallback={<PanelSkeleton rows={6} />}>
              <LiveSignalFeed />
            </Suspense>
          </PanelErrorBoundary>
        </div>

        {/* Risk dashboard — row 1, cols 9-10 */}
        <div className="col-span-2 row-span-1 min-h-0">
          <PanelErrorBoundary title="Risk Dashboard">
            <Suspense fallback={<PanelSkeleton rows={4} />}>
              <RiskDashboard />
            </Suspense>
          </PanelErrorBoundary>
        </div>

        {/* Order book depth — row 1, cols 11-12 */}
        <div className="col-span-2 row-span-1 min-h-0">
          <PanelErrorBoundary title="Order Book">
            <Suspense fallback={<PanelSkeleton rows={8} />}>
              <OrderBookDepth />
            </Suspense>
          </PanelErrorBoundary>
        </div>

        {/* Sentiment gauge — row 2, cols 9-10 */}
        <div className="col-span-2 row-span-1 min-h-0">
          <PanelErrorBoundary title="Sentiment">
            <Suspense fallback={<PanelSkeleton rows={3} />}>
              <SentimentGauge />
            </Suspense>
          </PanelErrorBoundary>
        </div>

        {/* Microstructure — row 2, cols 11-12 */}
        <div className="col-span-2 row-span-1 min-h-0">
          <PanelErrorBoundary title="Microstructure">
            <Suspense fallback={<PanelSkeleton rows={5} />}>
              <MicrostructurePanel />
            </Suspense>
          </PanelErrorBoundary>
        </div>
      </div>

      {/* ── Macro calendar — fixed-height footer ────────────────────────── */}
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
