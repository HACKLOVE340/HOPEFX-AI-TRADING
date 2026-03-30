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
