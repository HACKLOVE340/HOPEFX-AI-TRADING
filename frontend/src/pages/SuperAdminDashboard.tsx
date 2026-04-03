/**
 * SuperAdminDashboard.tsx
 * Master control center — superadmin only.
 *
 * Sections:
 *   Overview · Users · Platform · ML/AI · Trading Engine
 *   Financial · Security · Logs · Feature Flags
 *
 * Access: isSuperAdmin() only. AdminGuard is NOT sufficient.
 * Wired via /superadmin route behind SuperAdminGuard.
 */

import React, { useState, Suspense, lazy } from 'react';
import { useStore, selectUser } from '../store';
import { isSuperAdmin } from '../lib/subscription';
import type { SuperAdminTab } from './superadmin/types';
import { SAStyles, Spinner } from './superadmin/ui';

// Lazy-load every section for code splitting
const OverviewSection      = lazy(() => import('./superadmin/OverviewSection'));
const UsersSection         = lazy(() => import('./superadmin/UsersSection'));
const PlatformSection      = lazy(() => import('./superadmin/PlatformSection'));
const MLAISection          = lazy(() => import('./superadmin/MLAISection'));
const TradingEngineSection = lazy(() => import('./superadmin/TradingEngineSection'));
const FinancialSection     = lazy(() => import('./superadmin/FinancialSection'));
const SecuritySection      = lazy(() => import('./superadmin/SecuritySection'));
const LogsSection          = lazy(() => import('./superadmin/LogsSection'));
const FeatureFlagsSection  = lazy(() => import('./superadmin/FeatureFlagsSection'));

// ── Tab definitions ───────────────────────────────────────────────────────────

interface TabDef {
  id: SuperAdminTab;
  label: string;
  icon: string;
  description: string;
  accent: string;
}

const TABS: TabDef[] = [
  { id: 'overview',        label: 'Overview',        icon: '🌐', description: 'Platform health & KPIs',       accent: '#3b82f6' },
  { id: 'users',           label: 'Users',           icon: '👥', description: 'User management & roles',      accent: '#22c55e' },
  { id: 'platform',        label: 'Platform',        icon: '⚙️', description: 'Config, maintenance, banners', accent: '#8b5cf6' },
  { id: 'ml-ai',           label: 'ML / AI',         icon: '🧠', description: 'Models, RL agent, metrics',    accent: '#a78bfa' },
  { id: 'trading-engine',  label: 'Trading Engine',  icon: '📈', description: 'Engine, kill switch, risk',    accent: '#ef4444' },
  { id: 'financial',       label: 'Financial',       icon: '💰', description: 'Revenue, payments, refunds',   accent: '#f59e0b' },
  { id: 'security',        label: 'Security',        icon: '🛡️', description: 'Events, IPs, sessions',        accent: '#dc2626' },
  { id: 'logs',            label: 'Logs',            icon: '📋', description: 'System logs & log levels',     accent: '#06b6d4' },
  { id: 'feature-flags',   label: 'Feature Flags',   icon: '🚩', description: 'Global flags & overrides',     accent: '#f59e0b' },
];

// ── Section fallback ──────────────────────────────────────────────────────────

const SectionFallback: React.FC = () => (
  <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: '#64748b', padding: '40px 0' }}>
    <Spinner size={18} />
    <span style={{ fontSize: 13 }}>Loading section…</span>
  </div>
);

// ── Main dashboard ────────────────────────────────────────────────────────────

const SuperAdminDashboard: React.FC = () => {
  const user = useStore(selectUser);
  const [activeTab, setActiveTab] = useState<SuperAdminTab>('overview');

  // Guard — should never render without superadmin, but belt-and-suspenders
  if (!user || !isSuperAdmin(user.role)) return null;

  const activeTabDef = TABS.find(t => t.id === activeTab)!;

  const renderSection = () => {
    switch (activeTab) {
      case 'overview':       return <OverviewSection />;
      case 'users':          return <UsersSection />;
      case 'platform':       return <PlatformSection />;
      case 'ml-ai':          return <MLAISection />;
      case 'trading-engine': return <TradingEngineSection />;
      case 'financial':      return <FinancialSection />;
      case 'security':       return <SecuritySection />;
      case 'logs':           return <LogsSection />;
      case 'feature-flags':  return <FeatureFlagsSection />;
      default:               return null;
    }
  };

  return (
    <>
      <SAStyles />
      <style>{`
        @keyframes sa-fadein { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes sa-spin   { to { transform: rotate(360deg); } }
        @keyframes sa-pulse  { 0%, 100% { opacity: 0.6; } 50% { opacity: 0.3; } }
        .sa-row:hover        { background: #0f1f35 !important; }
        .sa-tab-btn:hover    { background: #1e293b !important; }
      `}</style>

      <div style={styles.page}>
        {/* ── Page header ── */}
        <div style={styles.header}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
            <div style={styles.iconWrap}>⚡</div>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <h1 style={styles.heading}>Super Admin</h1>
                <span style={styles.badge}>MASTER CONTROL</span>
              </div>
              <p style={styles.subheading}>
                Full platform control · Logged in as <strong style={{ color: '#fca5a5' }}>{user.username}</strong>
              </p>
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={styles.liveIndicator}>
              <span style={styles.liveDot} />
              <span style={{ fontSize: 11, color: '#4ade80', fontWeight: 600 }}>LIVE</span>
            </div>
          </div>
        </div>

        <div style={styles.layout}>
          {/* ── Sidebar nav ── */}
          <nav style={styles.sidebar}>
            <div style={styles.sidebarLabel}>Control Center</div>
            {TABS.map(tab => {
              const active = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  className="sa-tab-btn"
                  onClick={() => setActiveTab(tab.id)}
                  title={tab.description}
                  style={{
                    ...styles.tabBtn,
                    background:  active ? '#0f1f35' : 'transparent',
                    borderLeft:  `3px solid ${active ? tab.accent : 'transparent'}`,
                    color:       active ? '#f1f5f9' : '#64748b',
                  }}
                >
                  <span style={styles.tabIcon}>{tab.icon}</span>
                  <span style={{ flex: 1, textAlign: 'left' }}>{tab.label}</span>
                  {active && (
                    <span style={{
                      width: 6, height: 6, borderRadius: '50%',
                      background: tab.accent, flexShrink: 0,
                    }} />
                  )}
                </button>
              );
            })}

            {/* Divider + quick links */}
            <div style={{ height: 1, background: '#1e293b', margin: '12px 0' }} />
            <div style={styles.sidebarLabel}>Quick Links</div>
            {[
              { label: 'Admin Panel',  href: '/admin',    icon: '🔧' },
              { label: 'Audit Log',    href: '/audit',    icon: '🔍' },
              { label: 'Security Ops', href: '/security', icon: '🛡️' },
            ].map(l => (
              <a key={l.href} href={l.href} style={styles.quickLink}>
                <span>{l.icon}</span>
                <span>{l.label}</span>
              </a>
            ))}
          </nav>

          {/* ── Content ── */}
          <main style={styles.content}>
            {/* Section header */}
            <div style={styles.sectionHeader}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <div style={{
                  width: 36, height: 36, borderRadius: 9,
                  background: `${activeTabDef.accent}22`,
                  border: `1px solid ${activeTabDef.accent}44`,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 18,
                }}>
                  {activeTabDef.icon}
                </div>
                <div>
                  <div style={{ fontSize: 18, fontWeight: 700, color: '#f8fafc' }}>{activeTabDef.label}</div>
                  <div style={{ fontSize: 12, color: '#475569' }}>{activeTabDef.description}</div>
                </div>
              </div>
            </div>

            {/* Section content */}
            <Suspense fallback={<SectionFallback />}>
              <div key={activeTab} style={{ animation: 'sa-fadein 0.2s ease' }}>
                {renderSection()}
              </div>
            </Suspense>
          </main>
        </div>
      </div>
    </>
  );
};

// ── Styles ────────────────────────────────────────────────────────────────────

const styles: Record<string, React.CSSProperties> = {
  page: {
    minHeight: '100vh',
    background: '#020817',
    color: '#f1f5f9',
    fontFamily: 'Inter, system-ui, -apple-system, sans-serif',
    padding: '28px 24px',
    boxSizing: 'border-box',
  },
  header: {
    maxWidth: 1400,
    margin: '0 auto 24px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '20px 24px',
    background: '#0a1628',
    border: '1px solid #1e293b',
    borderTop: '3px solid #ef4444',
    borderRadius: 14,
  },
  iconWrap: {
    width: 52, height: 52, borderRadius: 12,
    background: 'linear-gradient(135deg, #450a0a, #7f1d1d)',
    border: '2px solid #dc2626',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    fontSize: 24, flexShrink: 0,
  },
  heading: {
    fontSize: 24, fontWeight: 800, color: '#f8fafc',
    margin: 0, letterSpacing: '-0.02em',
  },
  badge: {
    fontSize: 10, fontWeight: 800, letterSpacing: '0.08em',
    color: '#fca5a5', background: '#450a0a',
    border: '1px solid #dc2626', borderRadius: 4,
    padding: '3px 8px',
  },
  subheading: {
    fontSize: 13, color: '#475569', margin: '4px 0 0',
  },
  liveIndicator: {
    display: 'flex', alignItems: 'center', gap: 6,
    background: '#052e16', border: '1px solid #16a34a',
    borderRadius: 20, padding: '5px 12px',
  },
  liveDot: {
    width: 7, height: 7, borderRadius: '50%',
    background: '#4ade80',
    boxShadow: '0 0 6px #4ade80',
    animation: 'sa-pulse 2s ease-in-out infinite',
  },
  layout: {
    maxWidth: 1400,
    margin: '0 auto',
    display: 'flex',
    gap: 24,
    alignItems: 'flex-start',
  },
  sidebar: {
    width: 220,
    flexShrink: 0,
    background: '#0a1628',
    border: '1px solid #1e293b',
    borderRadius: 12,
    padding: '12px 0',
    position: 'sticky' as const,
    top: 24,
  },
  sidebarLabel: {
    fontSize: 10, fontWeight: 700, color: '#334155',
    textTransform: 'uppercase' as const, letterSpacing: '0.08em',
    padding: '8px 16px 4px',
  },
  tabBtn: {
    display: 'flex', alignItems: 'center', gap: 9,
    width: '100%', padding: '9px 16px',
    border: 'none', borderLeft: '3px solid transparent',
    background: 'transparent', cursor: 'pointer',
    fontSize: 13, transition: 'background 0.12s, color 0.12s',
    borderRadius: 0,
  },
  tabIcon: {
    fontSize: 15, flexShrink: 0, width: 20, textAlign: 'center' as const,
  },
  quickLink: {
    display: 'flex', alignItems: 'center', gap: 9,
    padding: '8px 16px', fontSize: 12, color: '#475569',
    textDecoration: 'none', transition: 'color 0.12s',
  },
  sectionHeader: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    marginBottom: 20, padding: '14px 18px',
    background: '#0a1628', border: '1px solid #1e293b',
    borderRadius: 10,
  },
  content: {
    flex: 1,
    minWidth: 0,
  },
};

export default SuperAdminDashboard;
