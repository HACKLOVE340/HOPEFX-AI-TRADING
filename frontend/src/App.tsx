/**
 * App.tsx
 * Root router and app shell.
 *
 * Access model:
 *  - Public pages (/, /login, /register, /onboarding) — no auth required
 *  - Authenticated pages — require login (AuthGuard)
 *  - Subscription-gated pages — require minimum plan (SubscriptionGate)
 *  - Admin-only pages — require admin/superadmin role (AdminGuard)
 *
 * Admins have free access to every feature regardless of plan.
 * Traders see features based on their active subscription tier.
 */

import React, { useState, Component, Suspense } from 'react';
import {
  BrowserRouter,
  Routes,
  Route,
  Navigate,
} from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import AuthGuard from './components/AuthGuard';
import AdminGuard from './components/AdminGuard';
import SuperAdminGuard from './components/SuperAdminGuard';
import SubscriptionGate from './components/SubscriptionGate';
import Sidebar from './components/sidebar/Sidebar';
import { ThemeToggle } from './components/ThemeToggle';
import { useStore, selectIsAuth } from './store';
import { useWebSocket } from './hooks/useWebSocket';
import { usePlan } from './hooks/usePlan';

// ── Public / auth pages ───────────────────────────────────────────────────────
const LandingPage             = React.lazy(() => import('./pages/LandingPage'));
const Login                   = React.lazy(() => import('./pages/Login'));
const Register                = React.lazy(() => import('./pages/Register'));
const Onboarding              = React.lazy(() => import('./pages/Onboarding'));
const NotFound                = React.lazy(() => import('./pages/NotFound'));
const TermsAndRiskDisclosure  = React.lazy(() => import('./pages/TermsAndRiskDisclosure'));

// ── Core ──────────────────────────────────────────────────────────────────────
const TradingDashboard = React.lazy(() => import('./pages/TradingDashboard'));
const Trade            = React.lazy(() => import('./pages/Trade'));
const Portfolio        = React.lazy(() => import('./pages/Portfolio'));
const WatchlistPage    = React.lazy(() => import('./pages/Watchlist'));
const EconomicCalendar = React.lazy(() => import('./pages/EconomicCalendar'));
const PriceAlerts      = React.lazy(() => import('./pages/PriceAlerts'));
const StatusPage       = React.lazy(() => import('./pages/StatusPage'));

// ── Trading ───────────────────────────────────────────────────────────────────
const ChartDashboard   = React.lazy(() =>
  import('./features/chart-bot').then(m => ({ default: m.ChartDashboard })));
const NuclearDashboard = React.lazy(() => import('./pages/NuclearDashboardPage'));
const TradeJournal     = React.lazy(() => import('./pages/TradeJournal'));
const PropFirmTracker  = React.lazy(() => import('./pages/PropFirmTracker'));
const CopyTrading      = React.lazy(() => import('./pages/CopyTrading'));
const RiskCalculator   = React.lazy(() => import('./pages/RiskCalculator'));

// ── Analytics ─────────────────────────────────────────────────────────────────
const Performance          = React.lazy(() => import('./pages/Performance'));
const AIStrategyGenerator  = React.lazy(() => import('./pages/AIStrategyGenerator'));
const CorrelationDashboard = React.lazy(() => import('./pages/CorrelationDashboard'));
const CustomIndicators     = React.lazy(() => import('./pages/CustomIndicators'));
const WalkForward          = React.lazy(() => import('./pages/WalkForward'));
const ABTesting            = React.lazy(() => import('./pages/ABTesting'));
const TCADashboard         = React.lazy(() => import('./pages/TCADashboard'));

// ── Community ─────────────────────────────────────────────────────────────────
const Leaderboard  = React.lazy(() => import('./pages/Leaderboard'));
const SocialFeed   = React.lazy(() => import('./pages/SocialFeed'));
const Marketplace  = React.lazy(() => import('./pages/Marketplace'));
const Affiliate    = React.lazy(() => import('./pages/Affiliate'));

// ── Account ───────────────────────────────────────────────────────────────────
const Profile        = React.lazy(() => import('./pages/Profile'));
const Wallet         = React.lazy(() => import('./pages/Wallet'));
const SubAccounts    = React.lazy(() => import('./pages/SubAccounts'));
const CryptoCheckout = React.lazy(() => import('./pages/CryptoCheckout'));
const Settings       = React.lazy(() => import('./pages/Settings'));
const TwoFactorSetup = React.lazy(() => import('./pages/TwoFactorSetup'));

// ── Admin-only (redirects to /superadmin — legacy routes preserved for links) ─
const AdminPanel        = React.lazy(() => import('./pages/AdminPanel'));
const AuditLog          = React.lazy(() => import('./pages/AuditLog'));
const SecurityDashboard = React.lazy(() => import('./pages/SecurityDashboard'));
const AutoHealDashboard = React.lazy(() => import('./pages/AutoHealDashboard'));
const WhitelabelAdmin   = React.lazy(() => import('./pages/WhitelabelAdmin'));

// ── Superadmin-only ───────────────────────────────────────────────────────────
const SuperAdminDashboard = React.lazy(() => import('./pages/SuperAdminDashboard'));

// ── React Query ───────────────────────────────────────────────────────────────
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime:            30_000,
      retry:                2,
      retryDelay:           (attempt) => Math.min(1_000 * 2 ** attempt, 10_000),
      refetchOnWindowFocus: false,
    },
  },
});

// ── Loading fallback ──────────────────────────────────────────────────────────
const PageFallback: React.FC = () => (
  <div style={{
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    height: '100vh', background: 'var(--bg, #0f172a)',
  }}>
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12 }}>
      <div style={{
        width: 32, height: 32, border: '3px solid #334155',
        borderTopColor: '#3b82f6', borderRadius: '50%',
        animation: 'spin 0.8s linear infinite',
      }} />
      <span style={{ fontSize: 13, color: '#475569' }}>Loading…</span>
    </div>
  </div>
);

// ── Global unhandled error handlers ──────────────────────────────────────────
// Installed once at module load — catches errors that escape React's tree.
if (typeof window !== 'undefined') {
  window.addEventListener('unhandledrejection', (event) => {
    // Suppress noisy network errors (offline, CORS, 401 auto-logout)
    const reason = event.reason;
    const isNetworkError =
      reason instanceof TypeError ||
      (reason as { response?: unknown })?.response !== undefined;
    if (!isNetworkError) {
      console.error('[App] Unhandled promise rejection:', reason);
    }
  });

  window.addEventListener('error', (event) => {
    // Ignore ResizeObserver loop errors (benign browser quirk)
    if (event.message?.includes('ResizeObserver loop')) return;
    console.error('[App] Uncaught error:', event.error ?? event.message);
  });
}

// ── Error boundary ────────────────────────────────────────────────────────────
const _IS_DEV = import.meta.env.DEV;

interface EBState { hasError: boolean; message: string; stack?: string }
class ErrorBoundary extends Component<{ children: React.ReactNode }, EBState> {
  state: EBState = { hasError: false, message: '', stack: undefined };

  static getDerivedStateFromError(err: Error): EBState {
    return { hasError: true, message: err.message, stack: err.stack };
  }

  componentDidCatch(err: Error, info: React.ErrorInfo) {
    console.error('[ErrorBoundary] Uncaught render error:', err, info.componentStack);
    // Forward to Sentry / monitoring if available
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const Sentry = (window as any).Sentry;
    if (Sentry?.captureException) {
      Sentry.captureException(err, { extra: { componentStack: info.componentStack } });
    }
  }

  handleReset = () => {
    this.setState({ hasError: false, message: '', stack: undefined });
    window.location.reload();
  };

  render() {
    if (!this.state.hasError) return this.props.children;

    return (
      <div style={{
        minHeight: '100vh', display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center',
        background: '#080c14', color: '#e2e8f0', padding: 40, textAlign: 'center',
        fontFamily: "'Inter', system-ui, sans-serif",
      }}>
        {/* Logo */}
        <div style={{ fontSize: 28, fontWeight: 800, letterSpacing: '-0.5px', marginBottom: 8 }}>
          HOPE<span style={{ color: '#3b82f6' }}>FX</span>
        </div>

        <div style={{
          width: 48, height: 48, borderRadius: '50%',
          background: '#ff3b5c22', border: '1px solid #ff3b5c44',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 22, marginBottom: 16,
        }}>
          ⚠
        </div>

        <h2 style={{ fontSize: 20, fontWeight: 700, color: '#f1f5f9', marginBottom: 8 }}>
          Something went wrong
        </h2>
        <p style={{ color: '#64748b', fontSize: 14, marginBottom: 24, maxWidth: 420, lineHeight: 1.6 }}>
          {this.state.message || 'An unexpected error occurred. The page will reload when you click Retry.'}
        </p>

        {/* Stack trace — dev only */}
        {_IS_DEV && this.state.stack && (
          <pre style={{
            background: '#0d1421', border: '1px solid #1e2d3d', borderRadius: 8,
            color: '#94a3b8', fontSize: 11, lineHeight: 1.5, maxWidth: 640,
            maxHeight: 200, overflow: 'auto', padding: '12px 16px',
            textAlign: 'left', marginBottom: 24, whiteSpace: 'pre-wrap',
          }}>
            {this.state.stack}
          </pre>
        )}

        <button
          onClick={this.handleReset}
          style={{
            background: '#3b82f6', border: 'none', borderRadius: 8,
            color: '#fff', cursor: 'pointer', fontSize: 14, fontWeight: 600,
            padding: '10px 24px', transition: 'background 0.2s',
          }}
          onMouseOver={(e) => { (e.target as HTMLButtonElement).style.background = '#2563eb'; }}
          onMouseOut={(e) => { (e.target as HTMLButtonElement).style.background = '#3b82f6'; }}
        >
          Retry
        </button>
      </div>
    );
  }
}

// ── No-live-feed banner ───────────────────────────────────────────────────────
const NoLiveFeedBanner: React.FC = () => {
  const status = useStore((s) => s.wsStatus);
  const [dismissed, setDismissed] = React.useState(false);

  React.useEffect(() => {
    if (status === 'connected') setDismissed(false);
  }, [status]);

  if (status === 'connected' || dismissed) return null;

  const label =
    status === 'connecting' ? 'Connecting to live feed…' :
    status === 'error'      ? 'Live feed error — using REST fallback' :
                              'No live feed — using REST fallback (prices may be delayed)';

  const bg     = status === 'connecting' ? '#78350f' : '#450a0a';
  const border = status === 'connecting' ? '#92400e' : '#7f1d1d';
  const color  = status === 'connecting' ? '#fbbf24' : '#f87171';

  return (
    <div
      role="alert"
      aria-live="polite"
      style={{
        position: 'fixed', top: 0, left: 0, right: 0, zIndex: 9999,
        background: bg, borderBottom: `1px solid ${border}`,
        color, fontSize: 12, fontWeight: 600,
        display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
        padding: '6px 16px',
      }}
    >
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: color, flexShrink: 0 }} />
      {label}
      <button
        onClick={() => setDismissed(true)}
        aria-label="Dismiss"
        style={{
          marginLeft: 'auto', background: 'transparent', border: 'none',
          color, cursor: 'pointer', fontSize: 14, lineHeight: 1, padding: '0 4px',
        }}
      >
        ×
      </button>
    </div>
  );
};

// ── Helpers ───────────────────────────────────────────────────────────────────
const wrap = (el: React.ReactNode) => <ErrorBoundary>{el}</ErrorBoundary>;

const gated = (featureKey: string, el: React.ReactNode) => (
  <AuthGuard>
    <SubscriptionGate featureKey={featureKey}>
      {el}
    </SubscriptionGate>
  </AuthGuard>
);

const adminOnly = (el: React.ReactNode) => (
  <AuthGuard>
    <AdminGuard>
      {el}
    </AdminGuard>
  </AuthGuard>
);

const superAdminOnly = (el: React.ReactNode) => (
  <AuthGuard>
    <SuperAdminGuard>
      {el}
    </SuperAdminGuard>
  </AuthGuard>
);

// ── App shell ─────────────────────────────────────────────────────────────────
const AppShell: React.FC = () => {
  const [collapsed, setCollapsed] = useState(false);
  const isAuth = useStore(selectIsAuth);

  useWebSocket(isAuth);
  usePlan();

  return (
    <div style={{
      display: 'flex', height: '100vh', overflow: 'hidden',
      background: 'var(--bg, #0f172a)',
      color: 'var(--text, #f1f5f9)',
      fontFamily: 'Inter, system-ui, -apple-system, sans-serif',
    }}>
      <NoLiveFeedBanner />
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed(c => !c)} />
      <main style={{
        flex: 1, overflowY: 'auto', overflowX: 'hidden',
        background: 'var(--bg, #0f172a)', height: '100vh',
      }}>
        <Suspense fallback={<PageFallback />}>
          <Routes>
            {/* Core */}
            <Route path="/dashboard"    element={wrap(gated('dashboard',    <TradingDashboard />))} />
            <Route path="/trade"        element={wrap(gated('trade',        <Trade />))} />
            <Route path="/portfolio"    element={wrap(gated('portfolio',    <Portfolio />))} />
            <Route path="/watchlist"    element={wrap(gated('watchlist',    <WatchlistPage />))} />
            <Route path="/calendar"     element={wrap(gated('calendar',     <EconomicCalendar />))} />
            <Route path="/alerts"       element={wrap(gated('alerts',       <PriceAlerts />))} />
            <Route path="/status"       element={wrap(<StatusPage />)} />

            {/* Trading */}
            <Route path="/trading"      element={wrap(gated('trading',      <ChartDashboard />))} />
            <Route path="/nuclear"      element={wrap(gated('nuclear',      <NuclearDashboard />))} />
            <Route path="/journal"      element={wrap(gated('journal',      <TradeJournal />))} />
            <Route path="/prop-firm"    element={wrap(gated('prop-firm',    <PropFirmTracker />))} />
            <Route path="/copy-trading" element={wrap(gated('copy-trading', <CopyTrading />))} />
            <Route path="/risk-calc"    element={wrap(gated('risk-calc',    <RiskCalculator />))} />

            {/* Analytics */}
            <Route path="/performance"  element={wrap(gated('performance',  <Performance />))} />
            <Route path="/ai-strategy"  element={wrap(gated('ai-strategy',  <AIStrategyGenerator />))} />
            <Route path="/correlation"  element={wrap(gated('correlation',  <CorrelationDashboard />))} />
            <Route path="/indicators"   element={wrap(gated('indicators',   <CustomIndicators />))} />
            <Route path="/walk-forward" element={wrap(gated('walk-forward', <WalkForward />))} />
            <Route path="/ab-testing"   element={wrap(gated('ab-testing',   <ABTesting />))} />
            <Route path="/tca"          element={wrap(gated('tca',          <TCADashboard />))} />

            {/* Community */}
            <Route path="/leaderboard"  element={wrap(<Leaderboard />)} />
            <Route path="/feed"         element={wrap(gated('feed',         <SocialFeed />))} />
            <Route path="/marketplace"  element={wrap(<Marketplace />)} />
            <Route path="/affiliate"    element={wrap(<Affiliate />)} />

            {/* Account */}
            <Route path="/profile"      element={wrap(gated('profile',      <Profile />))} />
            <Route path="/profile/:id"  element={wrap(<Profile />)} />
            <Route path="/wallet"       element={wrap(gated('wallet',       <Wallet />))} />
            <Route path="/sub-accounts" element={wrap(gated('sub-accounts', <SubAccounts />))} />
            <Route path="/checkout"     element={wrap(<AuthGuard><CryptoCheckout /></AuthGuard>)} />
            <Route path="/settings"     element={wrap(gated('settings',     <Settings />))} />
            <Route path="/2fa-setup"    element={wrap(<AuthGuard><TwoFactorSetup /></AuthGuard>)} />

            {/* Legacy admin routes — redirect to /superadmin (single system) */}
            <Route path="/admin"        element={<Navigate to="/superadmin" replace />} />
            <Route path="/audit"        element={wrap(adminOnly(<AuditLog />))} />
            <Route path="/security"     element={wrap(adminOnly(<SecurityDashboard />))} />
            <Route path="/auto-heal"    element={wrap(adminOnly(<AutoHealDashboard />))} />
            <Route path="/whitelabel"   element={<Navigate to="/superadmin" replace />} />

            {/* Superadmin-only */}
            <Route path="/superadmin"   element={wrap(superAdminOnly(<SuperAdminDashboard />))} />

            {/* Fallback — redirect any unmatched route to /dashboard */}
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
        </Suspense>
      </main>
    </div>
  );
};

// ── Root ──────────────────────────────────────────────────────────────────────
const App: React.FC = () => (
  <QueryClientProvider client={queryClient}>
    <BrowserRouter>
      <ErrorBoundary>
        <Suspense fallback={<PageFallback />}>
          <Routes>
            <Route path="/"                element={<LandingPage />} />
            <Route path="/landing"         element={<LandingPage />} />
            <Route path="/login"           element={<Login />} />
            <Route path="/register"        element={<Register />} />
            <Route path="/onboarding"      element={<Onboarding />} />
            {/* Public legal pages — no auth required */}
            <Route path="/terms"           element={<TermsAndRiskDisclosure />} />
            <Route path="/risk-disclosure" element={<TermsAndRiskDisclosure />} />
            <Route path="/privacy"         element={<TermsAndRiskDisclosure />} />
            <Route path="/*"               element={<AppShell />} />
          </Routes>
        </Suspense>
      </ErrorBoundary>
    </BrowserRouter>
  </QueryClientProvider>
);

// suppress unused import warning — ThemeToggle is used inside Sidebar
void ThemeToggle;

export default App;
