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
 *   - useWebSocket() → Zustand (prices, positions, signals, account)
 *   - useBootstrapData() → TanStack Query → Zustand (all orchestrator data)
 */

import React from 'react';
import { useWebSocket } from '../hooks/useWebSocket';
import { useBootstrapData } from '../hooks/useOrchestratorData';
import { useStore } from '../store';

// ── Components ────────────────────────────────────────────────────────────────
import { LivePriceTicker }    from '../components/panels/LivePriceTicker';
import { AccountBar }         from '../components/terminal/AccountBar';
import { EquityCurveChart }   from '../components/charts/EquityCurveChart';
import { RiskDashboard }      from '../components/panels/RiskDashboard';
import { SentimentGauge }     from '../components/panels/SentimentGauge';
import { MicrostructurePanel } from '../components/panels/MicrostructurePanel';
import { MacroCalendar }      from '../components/panels/MacroCalendar';
import { OrderBookDepth }     from '../components/panels/OrderBookDepth';
import { LiveSignalFeed }     from '../components/panels/LiveSignalFeed';

// ── Dashboard inner ───────────────────────────────────────────────────────────

function DashboardInner() {
  // Connect WebSocket
  useWebSocket(true);

  // Bootstrap all REST data
  useBootstrapData();

  const wsStatus = useStore((s) => s.wsStatus);

  return (
    <div
      className="flex flex-col h-screen bg-[#080c14] overflow-hidden"
      style={{ fontFamily: "'Inter', system-ui, sans-serif" }}
    >
      {/* ── Top: price ticker + account bar ─────────────────────────────── */}
      <LivePriceTicker />
      <AccountBar />

      {/* ── Main grid ────────────────────────────────────────────────────── */}
      <div className="flex-1 min-h-0 grid grid-cols-12 grid-rows-2 gap-2 p-2 overflow-hidden">

        {/* Equity curve — large center-left, spans 2 rows */}
        <div className="col-span-5 row-span-2 min-h-0">
          <EquityCurveChart />
        </div>

        {/* Signal feed — center column, spans 2 rows */}
        <div className="col-span-3 row-span-2 min-h-0">
          <LiveSignalFeed />
        </div>

        {/* Risk dashboard — top right */}
        <div className="col-span-2 row-span-1 min-h-0">
          <RiskDashboard />
        </div>

        {/* Sentiment gauge — bottom right */}
        <div className="col-span-2 row-span-1 min-h-0">
          <SentimentGauge />
        </div>

        {/* Order book — far right top */}
        <div className="col-span-2 row-span-1 min-h-0">
          <OrderBookDepth />
        </div>

        {/* Microstructure — far right bottom */}
        <div className="col-span-2 row-span-1 min-h-0">
          <MicrostructurePanel />
        </div>
      </div>

      {/* ── Bottom row: macro calendar ───────────────────────────────────── */}
      <div className="h-48 shrink-0 px-2 pb-2">
        <MacroCalendar />
      </div>
    </div>
  );
}

// ── Exported page ─────────────────────────────────────────────────────────────
// QueryClientProvider is provided by App.tsx root — no wrapper needed here.

export default function TradingDashboard() {
  return <DashboardInner />;
}
