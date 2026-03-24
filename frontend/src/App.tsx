import React, { useState } from 'react';
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
import LandingPage    from './pages/LandingPage';
import Dashboard      from './pages/Dashboard';
import Marketplace    from './pages/Marketplace';
import Affiliate      from './pages/Affiliate';
import CryptoCheckout from './pages/CryptoCheckout';
import Settings       from './pages/Settings';
import StatusPage     from './pages/StatusPage';
import Login          from './pages/Login';

// ── Auth + Store ──────────────────────────────────────────────────────────────
import AuthGuard from './components/AuthGuard';
import { useStore, selectIsAuth, selectUser, selectWsStatus } from './store';

// ─── React Query client ───────────────────────────────────────────────────────
const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: 1 } },
});

// ── Nav items ─────────────────────────────────────────────────────────────────
const NAV_ITEMS = [
  { path: '/dashboard',   label: 'Dashboard',   icon: '📊', auth: true  },
  { path: '/marketplace', label: 'Marketplace', icon: '🛒', auth: false },
  { path: '/affiliate',   label: 'Affiliate',   icon: '🤝', auth: false },
  { path: '/checkout',    label: 'Upgrade',     icon: '💳', auth: false },
  { path: '/status',      label: 'Status',      icon: '🟢', auth: false },
  { path: '/settings',    label: 'Settings',    icon: '⚙️', auth: true  },
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
  return (
    <div style={s.shell}>
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((c) => !c)} />
      <main style={s.main}>
        <Routes>
          <Route path="/dashboard"   element={<AuthGuard><Dashboard /></AuthGuard>} />
          <Route path="/settings"    element={<AuthGuard><Settings /></AuthGuard>} />
          <Route path="/marketplace" element={<Marketplace />} />
          <Route path="/affiliate"   element={<Affiliate />} />
          <Route path="/checkout"    element={<CryptoCheckout />} />
          <Route path="/status"      element={<StatusPage />} />
          <Route path="*"            element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </main>
    </div>
  );
};

// ── Root ──────────────────────────────────────────────────────────────────────
const App: React.FC = () => (
  <QueryClientProvider client={queryClient}>
    <BrowserRouter>
      <Routes>
        <Route path="/"        element={<LandingPage />} />
        <Route path="/landing" element={<LandingPage />} />
        <Route path="/login"   element={<Login />} />
        <Route path="/*"       element={<AppShell />} />
      </Routes>
    </BrowserRouter>
  </QueryClientProvider>
);

// ── Styles ────────────────────────────────────────────────────────────────────
const s: Record<string, React.CSSProperties> = {
  shell: {
    display: 'flex', minHeight: '100vh', background: '#0f172a',
    color: '#f1f5f9', fontFamily: 'system-ui, -apple-system, sans-serif',
  },
  sidebar: {
    background: '#1e293b', borderRight: '1px solid #334155',
    display: 'flex', flexDirection: 'column', flexShrink: 0,
    transition: 'width 0.2s ease', overflow: 'hidden',
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
  nav: { flex: 1, padding: '10px 0', display: 'flex', flexDirection: 'column', gap: 2 },
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
  main: { flex: 1, overflowY: 'auto', background: '#0f172a' },
};

export default App;
