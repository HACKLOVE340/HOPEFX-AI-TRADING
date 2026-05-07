/**
 * components/panels/index.ts
 * Barrel export for all dashboard panel components.
 *
 * Each panel exports two variants:
 *   - Named export (e.g. LivePriceTicker)       — use when you control the
 *     error boundary yourself.
 *   - Guarded export (e.g. LivePriceTickerGuarded) — pre-wrapped with
 *     withPanelGuard (PanelErrorBoundary + Suspense + PanelSkeleton).
 *
 * Import from this barrel to avoid deep relative paths and to ensure
 * tree-shaking works correctly with Vite's module graph.
 */

export {
  LivePriceTicker,
  LivePriceTickerGuarded,
} from './LivePriceTicker';

export {
  LiveSignalFeed,
  LiveSignalFeedGuarded,
} from './LiveSignalFeed';

export {
  MLModelPanel,
  MLModelPanelGuarded,
} from './MLModelPanel';

export {
  MacroCalendar,
  MacroCalendarGuarded,
} from './MacroCalendar';

export {
  MicrostructurePanel,
  MicrostructurePanelGuarded,
} from './MicrostructurePanel';

export {
  OrchestratorHealthGrid,
  OrchestratorHealthGridGuarded,
} from './OrchestratorHealthGrid';

export {
  OrderBookDepth,
  OrderBookDepthGuarded,
} from './OrderBookDepth';

export {
  OrderEntryForm,
  OrderEntryFormGuarded,
} from './OrderEntryForm';

export {
  PositionsTable,
  PositionsTableGuarded,
  PositionsTableSkeleton,
} from './PositionsTable';

export {
  RiskDashboard,
  RiskDashboardGuarded,
} from './RiskDashboard';

export {
  SentimentGauge,
  SentimentGaugeGuarded,
} from './SentimentGauge';

export { NewsTicker } from './NewsTicker';
