/**
 * chart-bot/index.ts
 * Public API for the AI Chart Bot module.
 */

// Main entry point
export { default as ChartDashboard } from './components/ChartDashboard';

// Individual panels (for embedding in other pages)
export { default as CoreChart }          from './components/CoreChart';
export { default as AIOverlays }         from './components/AIOverlays';
export { default as EquityCurve }        from './components/EquityCurve';
export { default as MicrostructurePanel }from './components/MicrostructurePanel';
export { default as SentimentPanel }     from './components/SentimentPanel';
export { default as AIChartBot }         from './components/AIChartBot';
export { default as RiskHeatmap }        from './components/RiskHeatmap';
export { default as SignalFeed }         from './components/SignalFeed';

// ── Geopolitical intelligence panel ──────────────────────────────────────────
export { default as GeopoliticalPanel }         from './components/GeopoliticalPanel';

// ── Nuclear dashboard (new) ───────────────────────────────────────────────────
export { default as NuclearDashboard }          from './components/NuclearDashboard';
export { default as NuclearCandleChart }        from './components/NuclearCandleChart';
export { default as NuclearGeopoliticalBanner } from './components/NuclearGeopoliticalBanner';
export { default as NuclearAlertOverlay }       from './components/NuclearAlertOverlay';
export { default as NuclearExplainPanel }       from './components/NuclearExplainPanel';
export { default as NuclearEquityPanel }        from './components/NuclearEquityPanel';
export { default as NuclearMobileView }         from './components/NuclearMobileView';
export { default as NuclearDecisionTrace }      from './components/NuclearDecisionTrace';

// Nuclear store + hook
export { useNuclearStore }   from './store/nuclear-store';
export { useNuclearWS }      from './hooks/useNuclearWS';

// Nuclear types
export type * from './types/nuclear';

// Store
export { useChartBotStore }              from './store/chart-bot-store';

// Hooks
export { useOrchestratorWS }             from './hooks/useOrchestratorWS';
export * from './hooks/useChartData';

// Services
export { orchestratorWS }               from './services/orchestrator-ws';

// Types
export type * from './types';

// Utils
export * from './utils/design-tokens';
export * from './utils/formatters';
