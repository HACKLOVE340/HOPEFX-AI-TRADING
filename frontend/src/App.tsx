import React, { useState, Component } from 'react';
import {
  BrowserRouter,
  Routes,
  Route,
  NavLink,
  Navigate,
  useLocation,
} from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// ── Pages ─────────────────────────────────────────────────────────────────────
import LandingPage          from './pages/LandingPage';
import Dashboard            from './pages/Dashboard';
import Marketplace          from './pages/Marketplace';
import Affiliate            from './pages/Affiliate';
import CryptoCheckout       from './pages/CryptoCheckout';
import Settings             from './pages/Settings';
import StatusPage           from './pages/StatusPage';
import Login                from './pages/Login';
import Register             from './pages/Register';

// ── New pages (Tasks 16–47) ───────────────────────────────────────────────────
import RiskCalculator       from './pages/RiskCalculator';
import WalkForward          from './pages/WalkForward';
import Profile              from './pages/Profile';
import SocialFeed           from './pages/SocialFeed';
import WhitelabelAdmin      from './pages/WhitelabelAdmin';
import AdminPanel           from './pages/AdminPanel';
import ABTesting            from './pages/ABTesting';
import CorrelationDashboard from './pages/CorrelationDashboard';
import CustomIndicators     from './pages/CustomIndicators';

// ── Ported pages (dashboard → frontend) ──────────────────────────────────────
import Trading              from './pages/Trading';
import TradeJournal         from './pages/TradeJournal';
import Performance          from './pages/Performance';
import WatchlistPage        from './pages/Watchlist';
import PropFirmTracker      from './pages/PropFirmTracker';
import EconomicCalendar     from './pages/EconomicCalendar';
import PriceAlerts          from './pages/PriceAlerts';
import CopyTrading          from './pages/CopyTrading';
import Leaderboard          from './pages/Leaderboard';
import AIStrategyGenerator  from './pages/AIStrategyGenerator';
import Onboarding           from './pages/Onboarding';
import TwoFactorSetup       from './pages/TwoFactorSetup';
import Wallet               from './pages/Wallet';

// ── Auth + Store ──────────────────────────────────────────────────────────────
import AuthGuard from './components/AuthGuard';
import { useStore, selectIsAuth, selectUser, selectWsStatus } from './store';
import { useWebSocket } from './hooks/useWebSocket';
import { usePriceSimulator } from './hooks/usePriceSimulator';

// ─── React Query client ───────────────────────────────────────────────────────
const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: 1 } },
});

// ─── Error Boundary ───────────────────────────────────────────────────────────
interface EBState { hasError: boolean; message: string }
class ErrorBoundary extends Component<{ children: React.ReactNode }, EBState> {
  state: EBState = { hasError: false, message: '' };
  static getDerivedStateFromError(err: Error): EBState {
    return { hasError: true, message: err.message };
  }
  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: 40, textAlign: 'center', color: '#f87171' }}>
          <h2 style={{ marginBottom: 12 }}>Something went wrong</h2>
          <p style={{ color: '#64748b', fontSize: 14, marginBottom: 20 }}>{this.state.message}</p>
          <button
            onClick={() => { this.setState({ hasError: false, message: '' }); window.location.reload(); }}
            style={{ background: '#3b82f6', border: 'none', borderRadius: 8, color: '#fff', cursor: 'pointer', fontSize: 14, padding: '10px 20px' }}
          >
            Reload page
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

// ── Nav items ─────────────────────────────────────────────────────────────────
const NAV_ITEMS = [
  { path: '/dashboard',     label: 'Dashboard',       icon: '📊', auth: true  },
  { path: '/trading',       label: 'Trading',         icon: '📉', auth: true  },
  { path: '/journal',       label: 'Trade Journal',   icon: '📓', auth: true  },
  { path: '/performance',   label: 'Performance',     icon: '🏆', auth: true  },
  { path: '/watchlist',     label: 'Watchlist',       icon: '👁️', auth: true  },
  { path: '/prop-firm',     label: 'Prop Firm',       icon: '🛡️', auth: true  },
  { path: '/calendar',      label: 'Calendar',        icon: '📅', auth: true  },
  { path: '/alerts',        label: 'Price Alerts',    icon: '🔔', auth: true  },
  { path: '/copy-trading',  label: 'Copy Trading',    icon: '🔁', auth: true  },
  { path: '/leaderboard',   label: 'Leaderboard',     icon: '🥇', auth: false },
  { path: '/ai-strategy',   label: 'AI Strategy',     icon: '🤖', auth: true  },
  { path: '/feed',          label: 'Signal Feed',     icon: '📡', auth: true  },
  { path: '/risk-calc',     label: 'Risk Calc',       icon: '🧮', auth: true  },
  { path: '/walk-forward',  label: 'Walk-Forward',    icon: '📈', auth: true  },
  { path: '/ab-testing',    label: 'A/B Testing',     icon: '⚗️', auth: true  },
  { path: '/correlation',   label: 'Correlation',     icon: '🔗', auth: true  },
  { path: '/indicators',    label: 'Indicators',      icon: '📐', auth: true  },
  { path: '/profile',       label: 'Profile',         icon: '👤', auth: true  },
  { path: '/wallet',        label: 'Wallet',          icon: '💰', auth: true  },
  { path: '/marketplace',   label: 'Marketplace',     icon: '🛒', auth: false },
  { path: '/affiliate',     label: 'Affiliate',       icon: '🤝', auth: false },
  { path: '/checkout',      label: 'Upgrade',         icon: '💳', auth: false },
  { path: '/whitelabel',    label: 'Whitelabel',      icon: '🏷️', auth: true  },
  { path: '/admin',         label: 'Admin',           icon: '🔧', auth: true  },
  { path: '/status',        label: 'Status',          icon: '🟢', auth: false },
  { path: '/settings',      label: 'Settings',        icon: '⚙️', auth: true  },
];

// ── WS dot ────────────────────────────────────────────────────────────────────
const WsDot: React.FC = () => {
  const status = useStore(selectWsStatus);
  const color =
    status === 'connected'    ? '#22c55e' :
    status === 'connecting'   ? '#fbbf24' :
    status === 'error'        ? '#f87171' : '#475569';
  return (
    <span
      title={`WebSocket: ${status}`}
      style={{
        width: 7, height: 7, borderRadius: '50%', display: 'inline-block',
        background: color,
        boxShadow: status === 'connected' ? `0 0 5px ${color}` : 'none',
      }}
    />
  );
};

// ── Sidebar ───────────────────────────────────────────────────────────────────
const Sidebar: React.FC<{ collapsed: boolean; onToggle: () => void }> = ({ collapsed, onToggle }) => {
  const location  = useLocation();
  const isAuth    = useStore(selectIsAuth);
  const user      = useStore(selectUser);
  const clearAuth = useStore((s) => s.clearAuth);

  return (
    <aside style={{ ...s.sidebar, width: collapsed ? 60 : 220 }}>
      <div style={s.sidebarLogo}>
        {collapsed
          ? <span style={s.logoMark}>H</span>
          : <span style={s.logoFull}>HOPE<span style={{ color: '#3b82f6' }}>FX</span></span>}
        <button onClick={onToggle} style={s.collapseBtn} title={collapsed ? 'Expand' : 'Collapse'}>
          {collapsed ? '›' : '‹'}
        </button>
      </div>

      <nav style={s.nav}>
        {NAV_ITEMS.map(({ path, label, icon }) => {
          const active = location.pathname.startsWith(path);
          return (
            <NavLink
              key={path}
              to={path}
              style={{
                ...s.navLink,
                background:     active ? '#1e3a5f' : 'transparent',
                color:          active ? '#60a5fa' : '#94a3b8',
                borderLeft:     active ? '3px solid #3b82f6' : '3px solid transparent',
                justifyContent: collapsed ? 'center' : 'flex-start',
              }}
              title={collapsed ? label : undefined}
            >
              <span style={s.navIcon}>{icon}</span>
              {!collapsed && <span style={s.navLabel}>{label}</span>}
            </NavLink>
          );
        })}
      </nav>

      {!collapsed && (
        <div style={s.sidebarFooter}>
          {isAuth && user ? (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                <WsDot />
                <span style={{ fontSize: 12, color: '#94a3b8', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
                  {user.username}
                </span>
                <span style={{ fontSize: 10, color: '#475569', background: '#0f172a', padding: '1px 5px', borderRadius: 4 }}>
                  {user.role}
                </span>
              </div>
              <button onClick={clearAuth} style={s.logoutBtn}>Sign out</button>
            </>
          ) : (
            <NavLink to="/login" style={{ ...s.footerLink, color: '#60a5fa' }}>Sign in →</NavLink>
          )}
          <a href="/" style={s.footerLink}>← Landing</a>
        </div>
      )}
    </aside>
  );
};

// ── App shell ─────────────────────────────────────────────────────────────────
const AppShell: React.FC = () => {
  const [collapsed, setCollapsed] = useState(false);
  const isAuth   = useStore(selectIsAuth);
  const wsStatus = useStore(selectWsStatus);

  // Live WebSocket — connects when authenticated, handles JWT auth handshake,
  // auto-reconnects with exponential back-off, dispatches ticks into Zustand.
  useWebSocket(isAuth);

  // Price simulator — only active when WS is not connected (dev/demo fallback).
  // Disabled in production once a live broker feed is streaming real ticks.
  usePriceSimulator(wsStatus !== 'connected');

  // Wrap each page in ErrorBoundary so one broken page can't crash the whole shell
  const wrap = (el: React.ReactNode) => <ErrorBoundary>{el}</ErrorBoundary>;

  return (
    <div style={s.shell}>
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((c) => !c)} />
      <main style={s.main}>
        <Routes>
          {/* Core */}
          <Route path="/dashboard"    element={wrap(<AuthGuard><Dashboard /></AuthGuard>)} />
          <Route path="/settings"     element={wrap(<AuthGuard><Settings /></AuthGuard>)} />
          <Route path="/marketplace"  element={wrap(<Marketplace />)} />
          <Route path="/affiliate"    element={wrap(<Affiliate />)} />
          <Route path="/checkout"     element={wrap(<CryptoCheckout />)} />
          <Route path="/status"       element={wrap(<StatusPage />)} />

          {/* Calculator, Walk-Forward, Profile, Feed */}
          <Route path="/risk-calc"    element={wrap(<AuthGuard><RiskCalculator /></AuthGuard>)} />
          <Route path="/walk-forward" element={wrap(<AuthGuard><WalkForward /></AuthGuard>)} />
          <Route path="/profile"      element={wrap(<AuthGuard><Profile /></AuthGuard>)} />
          <Route path="/profile/:id"  element={wrap(<Profile />)} />
          <Route path="/feed"         element={wrap(<AuthGuard><SocialFeed /></AuthGuard>)} />

          {/* Whitelabel + Admin */}
          <Route path="/whitelabel"   element={wrap(<AuthGuard><WhitelabelAdmin /></AuthGuard>)} />
          <Route path="/admin"        element={wrap(<AuthGuard><AdminPanel /></AuthGuard>)} />

          {/* Advanced trading */}
          <Route path="/ab-testing"   element={wrap(<AuthGuard><ABTesting /></AuthGuard>)} />
          <Route path="/correlation"  element={wrap(<AuthGuard><CorrelationDashboard /></AuthGuard>)} />
          <Route path="/indicators"   element={wrap(<AuthGuard><CustomIndicators /></AuthGuard>)} />

          {/* Ported pages */}
          <Route path="/trading"      element={wrap(<AuthGuard><Trading /></AuthGuard>)} />
          <Route path="/journal"      element={wrap(<AuthGuard><TradeJournal /></AuthGuard>)} />
          <Route path="/performance"  element={wrap(<Performance />)} />
          <Route path="/watchlist"    element={wrap(<AuthGuard><WatchlistPage /></AuthGuard>)} />
          <Route path="/prop-firm"    element={wrap(<AuthGuard><PropFirmTracker /></AuthGuard>)} />
          <Route path="/calendar"     element={wrap(<AuthGuard><EconomicCalendar /></AuthGuard>)} />
          <Route path="/alerts"       element={wrap(<AuthGuard><PriceAlerts /></AuthGuard>)} />
          <Route path="/copy-trading" element={wrap(<AuthGuard><CopyTrading /></AuthGuard>)} />
          <Route path="/leaderboard"  element={wrap(<Leaderboard />)} />
          <Route path="/ai-strategy"  element={wrap(<AuthGuard><AIStrategyGenerator /></AuthGuard>)} />
          <Route path="/wallet"       element={wrap(<AuthGuard><Wallet /></AuthGuard>)} />
          <Route path="/2fa-setup"    element={wrap(<AuthGuard><TwoFactorSetup /></AuthGuard>)} />

          {/* Fallback — redirect unknown shell paths to dashboard */}
          <Route path="*"             element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </main>
    </div>
  );
};

// ── Root ──────────────────────────────────────────────────────────────────────
const App: React.FC = () => (
  <QueryClientProvider client={queryClient}>
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <ErrorBoundary>
        <Routes>
          {/* Public full-screen pages — rendered WITHOUT the sidebar shell */}
          <Route path="/"           element={<LandingPage />} />
          <Route path="/landing"    element={<LandingPage />} />
          <Route path="/login"      element={<Login />} />
          <Route path="/register"   element={<Register />} />
          <Route path="/onboarding" element={<Onboarding />} />
          {/* Everything else gets the sidebar shell */}
          <Route path="/*"          element={<AppShell />} />
        </Routes>
      </ErrorBoundary>
    </BrowserRouter>
  </QueryClientProvider>
);

// ── Styles ────────────────────────────────────────────────────────────────────
const s: Record<string, React.CSSProperties> = {
  shell: {
    display: 'flex', height: '100vh', overflow: 'hidden', background: '#0f172a',
    color: '#f1f5f9', fontFamily: 'system-ui, -apple-system, sans-serif',
  },
  sidebar: {
    background: '#1e293b', borderRight: '1px solid #334155',
    display: 'flex', flexDirection: 'column', flexShrink: 0,
    transition: 'width 0.2s ease', overflow: 'hidden',
    height: '100vh',
  },
  sidebarLogo: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    padding: '18px 14px 14px', borderBottom: '1px solid #334155', minHeight: 60,
  },
  logoMark:    { fontSize: 20, fontWeight: 800, color: '#3b82f6' },
  logoFull:    { fontSize: 18, fontWeight: 800, color: '#f8fafc', letterSpacing: -0.5 },
  collapseBtn: {
    background: 'transparent', border: 'none', color: '#64748b',
    fontSize: 18, cursor: 'pointer', padding: '2px 4px', lineHeight: 1,
  },
  nav: { flex: 1, padding: '10px 0', display: 'flex', flexDirection: 'column', gap: 2, overflowY: 'auto', overflowX: 'hidden' },
  navLink: {
    display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px',
    textDecoration: 'none', fontSize: 14, fontWeight: 500,
    transition: 'background 0.15s, color 0.15s',
    borderRadius: '0 6px 6px 0', marginRight: 8,
  },
  navIcon:  { fontSize: 16, flexShrink: 0, width: 20, textAlign: 'center' },
  navLabel: { whiteSpace: 'nowrap', overflow: 'hidden' },
  sidebarFooter: {
    borderTop: '1px solid #334155', padding: '12px 14px',
    display: 'flex', flexDirection: 'column', gap: 6,
  },
  footerLink: { fontSize: 12, color: '#475569', textDecoration: 'none' },
  logoutBtn: {
    background: 'transparent', border: '1px solid #334155', borderRadius: 6,
    color: '#64748b', fontSize: 12, cursor: 'pointer', padding: '4px 8px', textAlign: 'left',
  },
  main: { flex: 1, overflowY: 'auto', overflowX: 'hidden', background: '#0f172a', height: '100vh' },
};

export default App;
