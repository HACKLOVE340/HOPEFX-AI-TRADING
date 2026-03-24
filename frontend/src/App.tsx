import React, { useState } from 'react';
import {
  BrowserRouter,
  Routes,
  Route,
  NavLink,
  Navigate,
  useLocation,
} from 'react-router-dom';

// ── Pages ─────────────────────────────────────────────────────────────────────
import LandingPage    from './pages/LandingPage';
import Dashboard      from './pages/Dashboard';
import Marketplace    from './pages/Marketplace';
import Affiliate      from './pages/Affiliate';
import CryptoCheckout from './pages/CryptoCheckout';
import Settings       from './pages/Settings';
import StatusPage     from './pages/StatusPage';

// ── Nav items ─────────────────────────────────────────────────────────────────

interface NavItem {
  path: string;
  label: string;
  icon: string;
}

const NAV_ITEMS: NavItem[] = [
  { path: '/dashboard',   label: 'Dashboard',    icon: '📊' },
  { path: '/marketplace', label: 'Marketplace',  icon: '🛒' },
  { path: '/affiliate',   label: 'Affiliate',    icon: '🤝' },
  { path: '/checkout',    label: 'Upgrade',      icon: '💳' },
  { path: '/status',      label: 'Status',       icon: '🟢' },
  { path: '/settings',    label: 'Settings',     icon: '⚙️' },
];

// ── Sidebar ───────────────────────────────────────────────────────────────────

const Sidebar: React.FC<{ collapsed: boolean; onToggle: () => void }> = ({ collapsed, onToggle }) => {
  const location = useLocation();

  return (
    <aside style={{ ...s.sidebar, width: collapsed ? 60 : 220 }}>
      {/* Logo */}
      <div style={s.sidebarLogo}>
        {collapsed ? (
          <span style={s.logoMark}>H</span>
        ) : (
          <span style={s.logoFull}>HOPE<span style={{ color: '#3b82f6' }}>FX</span></span>
        )}
        <button onClick={onToggle} style={s.collapseBtn} title={collapsed ? 'Expand' : 'Collapse'}>
          {collapsed ? '›' : '‹'}
        </button>
      </div>

      {/* Nav links */}
      <nav style={s.nav}>
        {NAV_ITEMS.map(({ path, label, icon }) => {
          const active = location.pathname.startsWith(path);
          return (
            <NavLink
              key={path}
              to={path}
              style={{
                ...s.navLink,
                background: active ? '#1e3a5f' : 'transparent',
                color: active ? '#60a5fa' : '#94a3b8',
                borderLeft: active ? '3px solid #3b82f6' : '3px solid transparent',
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

      {/* Footer */}
      {!collapsed && (
        <div style={s.sidebarFooter}>
          <a href="/" style={s.footerLink}>← Landing page</a>
          <a href="/docs/" style={s.footerLink} target="_blank" rel="noreferrer">Docs ↗</a>
        </div>
      )}
    </aside>
  );
};

// ── App shell (authenticated layout) ─────────────────────────────────────────

const AppShell: React.FC = () => {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <div style={s.shell}>
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed(c => !c)} />
      <main style={s.main}>
        <Routes>
          <Route path="/dashboard"   element={<Dashboard />} />
          <Route path="/marketplace" element={<Marketplace />} />
          <Route path="/affiliate"   element={<Affiliate />} />
          <Route path="/checkout"    element={<CryptoCheckout />} />
          <Route path="/status"      element={<StatusPage />} />
          <Route path="/settings"    element={<Settings />} />
          {/* Default: redirect /app/* to dashboard */}
          <Route path="*"            element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </main>
    </div>
  );
};

// ── Root router ───────────────────────────────────────────────────────────────

const App: React.FC = () => (
  <BrowserRouter>
    <Routes>
      {/* Public routes */}
      <Route path="/"        element={<LandingPage />} />
      <Route path="/landing" element={<LandingPage />} />

      {/* App routes — all rendered inside the sidebar shell */}
      <Route path="/*" element={<AppShell />} />
    </Routes>
  </BrowserRouter>
);

// ── Styles ────────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  shell: {
    display: 'flex',
    minHeight: '100vh',
    background: '#0f172a',
    color: '#f1f5f9',
    fontFamily: 'system-ui, -apple-system, sans-serif',
  },
  sidebar: {
    background: '#1e293b',
    borderRight: '1px solid #334155',
    display: 'flex',
    flexDirection: 'column',
    flexShrink: 0,
    transition: 'width 0.2s ease',
    overflow: 'hidden',
  },
  sidebarLogo: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '18px 14px 14px',
    borderBottom: '1px solid #334155',
    minHeight: 60,
  },
  logoMark: { fontSize: 20, fontWeight: 800, color: '#3b82f6' },
  logoFull: { fontSize: 18, fontWeight: 800, color: '#f8fafc', letterSpacing: -0.5 },
  collapseBtn: {
    background: 'transparent',
    border: 'none',
    color: '#64748b',
    fontSize: 18,
    cursor: 'pointer',
    padding: '2px 4px',
    lineHeight: 1,
  },
  nav: { flex: 1, padding: '10px 0', display: 'flex', flexDirection: 'column', gap: 2 },
  navLink: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    padding: '10px 14px',
    textDecoration: 'none',
    fontSize: 14,
    fontWeight: 500,
    transition: 'background 0.15s, color 0.15s',
    borderRadius: '0 6px 6px 0',
    marginRight: 8,
  },
  navIcon:  { fontSize: 16, flexShrink: 0, width: 20, textAlign: 'center' },
  navLabel: { whiteSpace: 'nowrap', overflow: 'hidden' },
  sidebarFooter: {
    borderTop: '1px solid #334155',
    padding: '12px 14px',
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
  },
  footerLink: { fontSize: 12, color: '#475569', textDecoration: 'none' },
  main: { flex: 1, overflowY: 'auto', background: '#0f172a' },
};

export default App;
