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

import React, { useState, useEffect, useCallback, Component, Suspense } from 'react';
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
import TrialBanner from './components/TrialBanner';
import Sidebar from './components/sidebar/Sidebar';
import { ThemeToggle } from './components/ThemeToggle';
import { ToastProvider } from './components/Toast';
import { ConfirmDialogProvider } from './components/ConfirmDialog';
import { CommandPalette } from './components/CommandPalette';
import { useStore, selectIsAuth, useHasHydrated } from './store';
import { useWebSocket } from './hooks/useWebSocket';
import { usePlan } from './hooks/usePlan';
import { useBootstrapData } from './hooks/useOrchestratorData';
import { getCsrfToken } from './hooks/useApi';

// ── Public / auth pages ───────────────────────────────────────────────────────
const LandingPage             = React.lazy(() => import('./pages/LandingPage'));
const Login                   = React.lazy(() => import('./pages/Login'));
const Register                = React.lazy(() => import('./pages/Register'));
const ForgotPassword          = React.lazy(() => import('./pages/ForgotPassword'));
const ResetPassword           = React.lazy(() => import('./pages/ResetPassword'));
const PrivacyPolicy           = React.lazy(() => import('./pages/PrivacyPolicy'));
const Onboarding              = React.lazy(() => import('./pages/Onboarding'));
const NotFound                = React.lazy(() => import('./pages/NotFound'));
const TermsAndRiskDisclosure  = React.lazy(() => import('./pages/TermsAndRiskDisclosure'));
const DocsPage                = React.lazy(() => import('./pages/DocsPage'));

// ── Core ──────────────────────────────────────────────────────────────────────
const Dashboard        = React.lazy(() => import('./pages/Dashboard'));
const TradingDashboard = React.lazy(() => import('./pages/TradingDashboard'));
const TradingTerminal  = React.lazy(() => import('./pages/Trading'));
const Trade            = React.lazy(() => import('./pages/Trade'));
const Portfolio        = React.lazy(() => import('./pages/Portfolio'));
const WatchlistPage    = React.lazy(() => import('./pages/Watchlist'));
const EconomicCalendar = React.lazy(() => import('./pages/EconomicCalendar'));
const PriceAlerts      = React.lazy(() => import('./pages/PriceAlerts'));
const StatusPage       = React.lazy(() => import('./pages/StatusPage'));

// ── Trading ───────────────────────────────────────────────────────────────────
const ChartDashboard   = React.lazy(() =>
  import('./features/chart-bot').then(m => ({ default: m.ChartDashboard })));
const AIChartDashboard = React.lazy(() => import('./pages/AIChartDashboard'));
const NuclearDashboard      = React.lazy(() => import('./pages/NuclearDashboardPage'));
const GeopoliticalRiskPage  = React.lazy(() => import('./pages/GeopoliticalRiskPage'));
const TradeJournal     = React.lazy(() => import('./pages/TradeJournal'));
const PropFirmTracker  = React.lazy(() => import('./pages/PropFirmTracker'));
const CopyTrading      = React.lazy(() => import('./pages/CopyTrading'));
const RiskCalculator   = React.lazy(() => import('./pages/RiskCalculator'));

// ── Analytics ─────────────────────────────────────────────────────────────────
const Performance          = React.lazy(() => import('./pages/Performance'));
const PnLDashboard         = React.lazy(() => import('./pages/PnLDashboard'));
const AIStrategyGenerator  = React.lazy(() => import('./pages/AIStrategyGenerator'));
const CorrelationDashboard = React.lazy(() => import('./pages/CorrelationDashboard'));
const CustomIndicators     = React.lazy(() => import('./pages/CustomIndicators'));
const WalkForward          = React.lazy(() => import('./pages/WalkForward'));
const ABTesting            = React.lazy(() => import('./pages/ABTesting'));
const TCADashboard         = React.lazy(() => import('./pages/TCADashboard'));
const PatternDetector      = React.lazy(() => import('./pages/PatternDetector'));

// ── Community ─────────────────────────────────────────────────────────────────
const Leaderboard  = React.lazy(() => import('./pages/Leaderboard'));
const SocialFeed   = React.lazy(() => import('./pages/SocialFeed'));
const Marketplace  = React.lazy(() => import('./pages/Marketplace'));
const Affiliate    = React.lazy(() => import('./pages/Affiliate'));

// ── Enterprise features ───────────────────────────────────────────────────────
const ResearchPage = React.lazy(() => import('./pages/ResearchPage'));
const TeamsPage    = React.lazy(() => import('./pages/TeamsPage'));
const ReplayPage   = React.lazy(() => import('./pages/ReplayPage'));

// ── Account ───────────────────────────────────────────────────────────────────
const Profile             = React.lazy(() => import('./pages/Profile'));
const Wallet              = React.lazy(() => import('./pages/Wallet'));
const SubAccounts         = React.lazy(() => import('./pages/SubAccounts'));
const EliteDashboard      = React.lazy(() => import('./pages/EliteDashboard'));
const CryptoCheckout      = React.lazy(() => import('./pages/CryptoCheckout'));
const PricingPage         = React.lazy(() => import('./pages/PricingPage'));
const Settings            = React.lazy(() => import('./pages/Settings'));
const TwoFactorSetup      = React.lazy(() => import('./pages/TwoFactorSetup'));
const NotificationsPage   = React.lazy(() => import('./pages/NotificationsPage'));
const KYCPage             = React.lazy(() => import('./pages/KYCPage'));
const ChatPage            = React.lazy(() => import('./pages/ChatPage'));
const MobilePage          = React.lazy(() => import('./pages/MobilePage'));

// ── Admin-only (legacy /admin route redirects to /audit — the admin landing) ──
const AdminPanel        = React.lazy(() => import('./pages/AdminPanel'));
const AuditLog          = React.lazy(() => import('./pages/AuditLog'));
const SecurityDashboard = React.lazy(() => import('./pages/SecurityDashboard'));
const AutoHealDashboard = React.lazy(() => import('./pages/AutoHealDashboard'));
const Observability = React.lazy(() => import('./pages/Observability'));
const Transparency = React.lazy(() => import('./pages/Transparency'));
const NewsSentiment = React.lazy(() => import('./pages/NewsSentiment'));
const MLDashboard = React.lazy(() => import('./pages/MLDashboard'));
const StrategyBuilder = React.lazy(() => import('./pages/StrategyBuilder'));
const WhitelabelAdmin   = React.lazy(() => import('./pages/WhitelabelAdmin'));

// ── Superadmin-only ───────────────────────────────────────────────────────────
const SuperAdminDashboard  = React.lazy(() => import('./pages/SuperAdminDashboard'));
const SystemReliability    = React.lazy(() => import('./pages/SystemReliability'));

// ── React Query ───────────────────────────────────────────────────────────────
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime:            30_000,
      // Don't retry on 401/403/404/503 — these are definitive responses.
      // Only retry on network errors (no response) or 5xx server errors
      // that aren't 503 (server starting up).
      retry: (failureCount, error) => {
        const status = (error as { response?: { status?: number } })?.response?.status;
        if (status === 401 || status === 403 || status === 404) return false;
        if (status === 503) return failureCount < 3; // server starting — retry up to 3×
        return failureCount < 2;
      },
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
  const status       = useStore((s) => s.wsStatus);
  const noLiveFeed   = useStore((s) => s.noLiveFeed);
  const noLiveFeedMsg = useStore((s) => s.noLiveFeedMsg);
  const isAuth       = useStore(selectIsAuth);
  const [dismissed, setDismissed]   = React.useState(false);
  const [attempted, setAttempted]   = React.useState(false);

  React.useEffect(() => {
    if (status === 'connecting' || status === 'connected') setAttempted(true);
  }, [status]);

  React.useEffect(() => {
    // Re-show banner on reconnect if server still reports no live feed.
    if (status === 'connected' && !noLiveFeed) setDismissed(false);
  }, [status, noLiveFeed]);

  // Show when: authenticated, attempted, and either WS is down OR server sent no_live_feed
  const showWsDown    = isAuth && attempted && status !== 'connected' && !dismissed;
  const showNoFeed    = isAuth && status === 'connected' && noLiveFeed && !dismissed;
  if (!showWsDown && !showNoFeed) return null;

  // Determine severity: connecting = amber, no_live_feed = amber, error/disconnected = amber
  // All states use amber — this is informational, not a critical error.
  const isConnecting = status === 'connecting';

  const label =
    showNoFeed
      ? (noLiveFeedMsg ?? 'No live broker feed — connect a broker in Settings to receive real-time prices.')
      : isConnecting
        ? 'Connecting to live feed…'
        : 'No live broker feed — prices updating via REST (30 s). Connect a broker in Settings.';

  // Always amber — this is an informational notice, not an error state.
  const bg     = '#451a03';
  const border = '#78350f';
  const color  = '#fbbf24';

  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        background: bg, borderBottom: `1px solid ${border}`,
        color, fontSize: 12, fontWeight: 600,
        display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
        padding: '6px 16px', flexShrink: 0,
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

// ── useMediaQuery hook ────────────────────────────────────────────────────────
function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() =>
    typeof window !== 'undefined' ? window.matchMedia(query).matches : false
  );
  useEffect(() => {
    const mql = window.matchMedia(query);
    const handler = (e: MediaQueryListEvent) => setMatches(e.matches);
    mql.addEventListener('change', handler);
    setMatches(mql.matches);
    return () => mql.removeEventListener('change', handler);
  }, [query]);
  return matches;
}

// ── Mobile top bar ────────────────────────────────────────────────────────────
interface MobileTopBarProps {
  onMenuOpen: () => void;
}
const MobileTopBar: React.FC<MobileTopBarProps> = ({ onMenuOpen }) => (
  <div className="mobile-topbar">
    <button
      onClick={onMenuOpen}
      aria-label="Open navigation menu"
      style={{
        background: 'transparent', border: 'none', color: '#94a3b8',
        cursor: 'pointer', padding: '8px', borderRadius: 6,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        minWidth: 44, minHeight: 44,
      }}
    >
      {/* Hamburger icon */}
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
        <rect x="2" y="4"  width="16" height="2" rx="1" fill="currentColor" />
        <rect x="2" y="9"  width="16" height="2" rx="1" fill="currentColor" />
        <rect x="2" y="14" width="16" height="2" rx="1" fill="currentColor" />
      </svg>
    </button>
    <span style={{ fontSize: 17, fontWeight: 800, color: '#f8fafc', letterSpacing: -0.5 }}>
      HOPE<span style={{ color: '#3b82f6' }}>FX</span>
    </span>
    {/* Right side spacer to keep title centred */}
    <div style={{ width: 44 }} />
  </div>
);

// ── App shell ─────────────────────────────────────────────────────────────────
const AppShell: React.FC = () => {
  const isMobile = useMediaQuery('(max-width: 767px)');
  // On desktop: sidebar can be collapsed (icon-only). On mobile: sidebar is a drawer.
  const [collapsed,    setCollapsed]    = useState(false);
  const [drawerOpen,   setDrawerOpen]   = useState(false);
  const isAuth   = useStore(selectIsAuth);
  const hydrated = useHasHydrated();

  // Lock body scroll when mobile drawer is open
  useEffect(() => {
    if (isMobile && drawerOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => { document.body.style.overflow = ''; };
  }, [isMobile, drawerOpen]);

  // Close drawer on route change (navigation)
  const closeDrawer = useCallback(() => setDrawerOpen(false), []);

  // Mark body so index.html CSS can lock the viewport height
  useEffect(() => {
    document.body.classList.add('app-shell-active');
    return () => document.body.classList.remove('app-shell-active');
  }, []);

  // Prefetch CSRF token on mount so it's ready before any POST/PUT/DELETE fires.
  React.useEffect(() => {
    getCsrfToken().catch(() => {/* non-fatal — middleware will retry */});
  }, []);

  useWebSocket(isAuth && hydrated);
  usePlan();
  // Bootstrap all global data (orchestrator health, positions, signals, ML health,
  // calendar, feeds, etc.) for every authenticated session — not just TradingDashboard.
  useBootstrapData();

  // Hold the entire shell until localStorage rehydration is complete.
  if (!hydrated) return <PageFallback />;

  return (
    <div
      className="app-shell"
      style={{ fontFamily: 'Inter, system-ui, -apple-system, sans-serif' }}
    >
      {/* Banners push content down instead of overlapping */}
      <TrialBanner />
      <NoLiveFeedBanner />

      {/* Mobile top bar — only visible on small screens */}
      {isMobile && <MobileTopBar onMenuOpen={() => setDrawerOpen(true)} />}

      <div className="app-shell-body">
        {/* ── Desktop sidebar (always in flow) ── */}
        {!isMobile && (
          <Sidebar collapsed={collapsed} onToggle={() => setCollapsed(c => !c)} />
        )}

        {/* ── Mobile drawer overlay ── */}
        {isMobile && drawerOpen && (
          <>
            {/* Backdrop */}
            <div
              className="sidebar-backdrop"
              onClick={closeDrawer}
              aria-hidden="true"
            />
            {/* Drawer — full sidebar in expanded mode, slides in from left */}
            <div
              className="sidebar-slide-in"
              style={{
                position: 'fixed', top: 0, left: 0, bottom: 0,
                width: 'min(280px, 85vw)',
                zIndex: 35,
                overflowY: 'auto',
                overflowX: 'hidden',
              }}
            >
              <Sidebar
                collapsed={false}
                onToggle={closeDrawer}
                onNavigate={closeDrawer}
              />
            </div>
          </>
        )}

      <main className="app-shell-main" style={{ background: 'var(--bg, #0f172a)' }}>
        {/* PageScroller: scrollable wrapper for all non-terminal pages.
            Terminal pages (TradingDashboard, ChartDashboard) manage their own
            overflow internally and use flex:1 to fill this container. */}
        <div className="app-shell-scroller">
        <Suspense fallback={<PageFallback />}>
          <Routes>
            {/* Core */}
            <Route path="/dashboard"    element={wrap(gated('dashboard',    <TradingDashboard />))} />
            <Route path="/home"         element={wrap(gated('dashboard',    <Dashboard />))} />
            <Route path="/trade"        element={wrap(gated('trade',        <Trade />))} />
            <Route path="/portfolio"    element={wrap(gated('portfolio',    <Portfolio />))} />
            <Route path="/watchlist"    element={wrap(gated('watchlist',    <WatchlistPage />))} />
            <Route path="/calendar"     element={wrap(gated('calendar',     <EconomicCalendar />))} />
            <Route path="/alerts"       element={wrap(gated('alerts',       <PriceAlerts />))} />
            {/* /system-status is the canonical route; /status kept as backward-compat alias */}
            <Route path="/system-status" element={wrap(<StatusPage />)} />
            <Route path="/status"        element={<Navigate to="/system-status" replace />} />

            {/* Trading */}
            {/* /ai-chart = AI Chart Bot (canonical); /ai-charts kept as alias */}
            <Route path="/ai-chart"           element={wrap(gated('ai-chart',     <ChartDashboard />))} />
            <Route path="/ai-charts"          element={<Navigate to="/ai-chart" replace />} />
            {/* /ai-chart-dashboard = AI Chart Dashboard (full AI analysis view) */}
            <Route path="/ai-chart-dashboard" element={wrap(gated('ai-chart',     <AIChartDashboard />))} />
            {/* /terminal = classic trading terminal */}
            <Route path="/terminal"           element={wrap(gated('terminal',     <TradingTerminal />))} />
            {/* /trading kept as alias for backward compat */}
            <Route path="/trading"            element={<Navigate to="/ai-chart" replace />} />
            <Route path="/nuclear"      element={wrap(gated('nuclear',      <NuclearDashboard />))} />
            <Route path="/geopolitical" element={wrap(gated('geopolitical', <GeopoliticalRiskPage />))} />

            {/* Tools */}
            <Route path="/journal"           element={wrap(gated('journal',         <TradeJournal />))} />
            <Route path="/prop-firm"         element={wrap(gated('prop-firm',       <PropFirmTracker />))} />
            <Route path="/copy-trading"      element={wrap(gated('copy-trading',    <CopyTrading />))} />
            {/* /risk-calculator = canonical; /risk-calc kept as alias */}
            <Route path="/risk-calculator"   element={wrap(gated('risk-calculator', <RiskCalculator />))} />
            <Route path="/risk-calc"         element={<Navigate to="/risk-calculator" replace />} />

            {/* Analytics */}
            <Route path="/performance"  element={wrap(gated('performance',  <Performance />))} />
            <Route path="/pnl"          element={wrap(gated('performance',  <PnLDashboard />))} />
            <Route path="/ai-strategy"  element={wrap(gated('ai-strategy',  <AIStrategyGenerator />))} />
            <Route path="/correlation"  element={wrap(gated('correlation',  <CorrelationDashboard />))} />
            <Route path="/indicators"        element={wrap(gated('indicators',        <CustomIndicators />))} />
            <Route path="/pattern-detector"  element={wrap(gated('pattern-detector',  <PatternDetector />))} />
            <Route path="/walk-forward"      element={wrap(gated('walk-forward',      <WalkForward />))} />
            <Route path="/ab-testing"   element={wrap(gated('ab-testing',   <ABTesting />))} />
            <Route path="/tca"          element={wrap(gated('tca',          <TCADashboard />))} />

            {/* Community */}
            {/* Leaderboard and Marketplace are public-preview pages — no login required.
                Authenticated users get full interactive features; anonymous visitors see
                the read-only view.  Removing AuthGuard here prevents the redirect to
                /login for unauthenticated visitors and makes the pages discoverable. */}
            <Route path="/leaderboard"  element={wrap(<Leaderboard />)} />
            {/* /signals = canonical Signal Feed; /feed and /social kept as aliases */}
            <Route path="/signals"      element={wrap(gated('signals',      <SocialFeed />))} />
            <Route path="/feed"         element={<Navigate to="/signals" replace />} />
            <Route path="/social"       element={<Navigate to="/signals" replace />} />
            <Route path="/social-feed"  element={<Navigate to="/signals" replace />} />
            <Route path="/marketplace"  element={wrap(<Marketplace />)} />
            <Route path="/affiliate"    element={wrap(gated('affiliate',    <Affiliate />))} />

            {/* Enterprise features */}
            <Route path="/research"     element={wrap(gated('research',     <ResearchPage />))} />
            <Route path="/teams"        element={wrap(gated('teams',        <TeamsPage />))} />
            <Route path="/replay"       element={wrap(gated('replay',       <ReplayPage />))} />

            {/* Account */}
            <Route path="/profile"         element={wrap(gated('profile',      <Profile />))} />
            <Route path="/profile/:id"     element={wrap(<Profile />)} />
            <Route path="/wallet"          element={wrap(gated('wallet',       <Wallet />))} />
            <Route path="/sub-accounts"    element={wrap(gated('sub-accounts', <SubAccounts />))} />
            <Route path="/elite"           element={wrap(gated('elite',        <EliteDashboard />))} />
            <Route path="/checkout"        element={wrap(<AuthGuard><CryptoCheckout /></AuthGuard>)} />
            {/* /upgrade = canonical in-app Upgrade Plan. Public /pricing lives in
                the public route group below so logged-out visitors get the clean
                pricing page (no app shell) the landing footer links to. */}
            <Route path="/upgrade"         element={wrap(<PricingPage />)} />
            {/* /docs inside AppShell so sidebar stays visible for logged-in users */}
            <Route path="/docs"            element={wrap(<DocsPage />)} />
            <Route path="/settings"        element={wrap(gated('settings',     <Settings />))} />
            <Route path="/2fa-setup"       element={wrap(<AuthGuard><TwoFactorSetup /></AuthGuard>)} />
            <Route path="/notifications"   element={wrap(<AuthGuard><NotificationsPage /></AuthGuard>)} />
            <Route path="/kyc"             element={wrap(<AuthGuard><KYCPage /></AuthGuard>)} />
            <Route path="/chat"            element={wrap(<AuthGuard><ChatPage /></AuthGuard>)} />
            <Route path="/mobile"          element={wrap(<AuthGuard><MobilePage /></AuthGuard>)} />

            {/* Admin */}
            <Route path="/admin"        element={wrap(adminOnly(<AdminPanel />))} />
            <Route path="/audit"        element={wrap(adminOnly(<AuditLog />))} />
            <Route path="/audit-log"    element={<Navigate to="/audit" replace />} />
            <Route path="/backtest"     element={<Navigate to="/ai-strategy" replace />} />
            <Route path="/security"     element={wrap(adminOnly(<SecurityDashboard />))} />
            <Route path="/auto-heal"    element={wrap(adminOnly(<AutoHealDashboard />))} />
            <Route path="/observability" element={wrap(adminOnly(<Observability />))} />
            <Route path="/ml-ops"        element={wrap(adminOnly(<MLDashboard />))} />
            <Route path="/strategy-builder" element={wrap(<StrategyBuilder />)} />
            <Route path="/transparency"  element={wrap(<Transparency />)} />
            <Route path="/news"          element={wrap(<NewsSentiment />)} />
            <Route path="/whitelabel"   element={wrap(adminOnly(<WhitelabelAdmin />))} />

            {/* Superadmin-only — /master-control canonical; /superadmin kept as alias */}
            <Route path="/master-control"      element={wrap(superAdminOnly(<SuperAdminDashboard />))} />
            <Route path="/superadmin"          element={<Navigate to="/master-control" replace />} />
            {/* /reliability canonical; /system-reliability kept as alias */}
            <Route path="/reliability"         element={wrap(superAdminOnly(<SystemReliability />))} />
            <Route path="/system-reliability"  element={<Navigate to="/reliability" replace />} />

            {/* Fallback — authenticated users see 404 page, others redirect to /login */}
            <Route
              path="*"
              element={
                isAuth
                  ? <NotFound />
                  : <Navigate to="/login" replace />
              }
            />
          </Routes>
        </Suspense>
        </div>
      </main>
      </div>
    </div>
  );
};


// ── Root ──────────────────────────────────────────────────────────────────────
const App: React.FC = () => (
  <QueryClientProvider client={queryClient}>
    <ToastProvider>
      <ConfirmDialogProvider>
        <BrowserRouter>
          <ErrorBoundary>
            <Suspense fallback={<PageFallback />}>
              <Routes>
                <Route path="/"                element={<LandingPage />} />
                <Route path="/landing"         element={<LandingPage />} />
                <Route path="/login"           element={<Login />} />
                <Route path="/register"        element={<Register />} />
                <Route path="/forgot-password" element={<ForgotPassword />} />
                <Route path="/reset-password"  element={<ResetPassword />} />
                <Route path="/onboarding"      element={<Onboarding />} />
                {/* Public pages — no auth required */}
                {/* /pricing = public marketing pricing page for unauthenticated visitors */}
                {/* /upgrade = authenticated plan upgrade page (inside AppShell) */}
                <Route path="/pricing"         element={<PricingPage />} />
                <Route path="/docs"            element={<DocsPage />} />
                <Route path="/terms"           element={<TermsAndRiskDisclosure />} />
                <Route path="/risk-disclosure" element={<TermsAndRiskDisclosure />} />
                <Route path="/privacy"         element={<PrivacyPolicy />} />
                <Route path="/*"               element={<AppShell />} />
              </Routes>
              {/* Global command palette — available on all authenticated pages */}
              <CommandPalette />
            </Suspense>
          </ErrorBoundary>
        </BrowserRouter>
      </ConfirmDialogProvider>
    </ToastProvider>
  </QueryClientProvider>
);

// suppress unused import warning — ThemeToggle is used inside Sidebar
void ThemeToggle;

export default App;
