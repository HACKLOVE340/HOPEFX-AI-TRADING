/**
 * Shared component library — single import point.
 *
 * Usage:
 *   import { Badge, Spinner, Modal, DataTable, ThemeToggle } from '../components';
 */

export { AuthGuard } from './AuthGuard';
export { Badge, type BadgeVariant } from './Badge';
export { Spinner } from './Spinner';
export { Modal } from './Modal';
export { DataTable, type Column } from './DataTable';
export { ThemeToggle } from './ThemeToggle';
export { useTheme, ThemeProvider } from './ThemeContext';
export { CandleChart } from './CandleChart';
export { LineChart } from './LineChart';
export { MetricCard } from './MetricCard';
export { EmptyState } from './EmptyState';
export { ErrorBanner } from './ErrorBanner';
export { PageHeader } from './PageHeader';
export { GlobalAttackMap, type AttackLog, type AttackRecord, type AttackGeo } from './GlobalAttackMap';
export { FixApprovalQueue, type FixRecord } from './FixApprovalQueue';

// ── UI primitives ─────────────────────────────────────────────────────────────
export { Panel } from './ui/Panel';
export { PanelErrorBoundary } from './ui/PanelErrorBoundary';
export { Skeleton, PanelSkeleton, TickerSkeleton, ChartSkeleton } from './ui/Skeleton';
export { withPanelGuard } from './ui/withPanelGuard';
export { Badge as UiBadge } from './ui/Badge';
export { ConfidenceBar } from './ui/ConfidenceBar';
export { MetricTile } from './ui/MetricTile';
export { Sparkline } from './ui/Sparkline';
export { StatusDot } from './ui/StatusDot';

// ── Guarded panel exports ─────────────────────────────────────────────────────
export { LivePriceTicker, LivePriceTickerGuarded } from './panels/LivePriceTicker';
export { LiveSignalFeed, LiveSignalFeedGuarded } from './panels/LiveSignalFeed';
export { MacroCalendar, MacroCalendarGuarded } from './panels/MacroCalendar';
export { MicrostructurePanel, MicrostructurePanelGuarded } from './panels/MicrostructurePanel';
export { OrderBookDepth, OrderBookDepthGuarded } from './panels/OrderBookDepth';
export { RiskDashboard, RiskDashboardGuarded } from './panels/RiskDashboard';
export { SentimentGauge, SentimentGaugeGuarded } from './panels/SentimentGauge';
