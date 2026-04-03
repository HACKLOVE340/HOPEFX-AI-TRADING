/**
 * Settings.tsx
 * Full settings hub — 14 tabs covering every aspect of the platform.
 *
 * Tab visibility rules:
 *   - All authenticated users: profile, security, broker, trading,
 *     appearance, notifications, api-keys, billing, integrations,
 *     privacy, accessibility, danger
 *   - Admin/superadmin only: system, admin
 */

import React, { useState, Suspense, lazy } from 'react';
import { useStore, selectUser } from '../store';
import { isAdmin } from '../lib/subscription';
import type { SettingsTab } from './settings/types';

// Lazy-load every section for code splitting
const ProfileSection       = lazy(() => import('./settings/ProfileSection'));
const SecuritySection      = lazy(() => import('./settings/SecuritySection'));
const BrokerSection        = lazy(() => import('./settings/BrokerSection'));
const TradingSection       = lazy(() => import('./settings/TradingSection'));
const AppearanceSection    = lazy(() => import('./settings/AppearanceSection'));
const NotificationsSection = lazy(() => import('./settings/NotificationsSection'));
const ApiKeysSection       = lazy(() => import('./settings/ApiKeysSection'));
const BillingSection       = lazy(() => import('./settings/BillingSection'));
const IntegrationsSection  = lazy(() => import('./settings/IntegrationsSection'));
const SystemSection        = lazy(() => import('./settings/SystemSection'));
const PrivacySection       = lazy(() => import('./settings/PrivacySection'));
const AccessibilitySection = lazy(() => import('./settings/AccessibilitySection'));
const AdminSettingsSection = lazy(() => import('./settings/AdminSettingsSection'));
const DangerSection        = lazy(() => import('./settings/DangerSection'));

// ── Tab definitions ───────────────────────────────────────────────────────────

interface TabGroup {
  label: string;
  tabs: TabDef[];
}

interface TabDef {
  id: SettingsTab;
  label: string;
  icon: string;
  adminOnly?: boolean;
  danger?: boolean;
}

const TAB_GROUPS: TabGroup[] = [
  {
    label: 'Account',
    tabs: [
      { id: 'profile',       label: 'Profile',        icon: '👤' },
      { id: 'security',      label: 'Security',        icon: '🔒' },
      { id: 'billing',       label: 'Billing',         icon: '💳' },
      { id: 'api-keys',      label: 'API Keys',        icon: '🔑' },
    ],
  },
  {
    label: 'Trading',
    tabs: [
      { id: 'broker',        label: 'Broker',          icon: '🏦' },
      { id: 'trading',       label: 'Trading',         icon: '📈' },
      { id: 'integrations',  label: 'Integrations',    icon: '🔌' },
    ],
  },
  {
    label: 'Preferences',
    tabs: [
      { id: 'appearance',    label: 'Appearance',      icon: '🎨' },
      { id: 'notifications', label: 'Notifications',   icon: '🔔' },
      { id: 'accessibility', label: 'Accessibility',   icon: '♿' },
      { id: 'privacy',       label: 'Privacy & Data',  icon: '🔏' },
    ],
  },
  {
    label: 'Administration',
    tabs: [
      { id: 'system',        label: 'System',          icon: '⚙️',  adminOnly: true },
      { id: 'admin',         label: 'Admin Settings',  icon: '🔧',  adminOnly: true },
    ],
  },
  {
    label: 'Danger Zone',
    tabs: [
      { id: 'danger',        label: 'Danger Zone',     icon: '⚠️',  danger: true },
    ],
  },
];

// ── Section fallback ──────────────────────────────────────────────────────────

const SectionFallback: React.FC = () => (
  <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: '#64748b', padding: '32px 0' }}>
    <div style={{
      width: 20, height: 20, border: '2px solid #334155',
      borderTopColor: '#3b82f6', borderRadius: '50%',
      animation: 'spin 0.7s linear infinite',
    }} />
    Loading…
  </div>
);

// ── Settings page ─────────────────────────────────────────────────────────────

const Settings: React.FC = () => {
  const user = useStore(selectUser);
  const admin = user ? isAdmin(user.role) : false;
  const [activeTab, setActiveTab] = useState<SettingsTab>('profile');

  const renderSection = () => {
    switch (activeTab) {
      case 'profile':       return <ProfileSection />;
      case 'security':      return <SecuritySection />;
      case 'broker':        return <BrokerSection />;
      case 'trading':       return <TradingSection />;
      case 'appearance':    return <AppearanceSection />;
      case 'notifications': return <NotificationsSection />;
      case 'api-keys':      return <ApiKeysSection />;
      case 'billing':       return <BillingSection />;
      case 'integrations':  return <IntegrationsSection />;
      case 'system':        return admin ? <SystemSection /> : null;
      case 'privacy':       return <PrivacySection />;
      case 'accessibility': return <AccessibilitySection />;
      case 'admin':         return admin ? <AdminSettingsSection /> : null;
      case 'danger':        return <DangerSection />;
      default:              return null;
    }
  };

  return (
    <>
      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
      `}</style>

      <div style={styles.page}>
        <div style={styles.header}>
          <h1 style={styles.heading}>Settings</h1>
          <p style={styles.subheading}>
            Manage your account, trading preferences, integrations, and platform configuration.
          </p>
        </div>

        <div style={styles.layout}>
          {/* Sidebar nav */}
          <nav style={styles.sidebar}>
            {TAB_GROUPS.map((group) => {
              const visibleTabs = group.tabs.filter((t) => !t.adminOnly || admin);
              if (visibleTabs.length === 0) return null;

              return (
                <div key={group.label} style={{ marginBottom: 4 }}>
                  <div style={styles.groupLabel}>{group.label}</div>
                  {visibleTabs.map((tab) => {
                    const active = activeTab === tab.id;
                    return (
                      <button
                        key={tab.id}
                        onClick={() => setActiveTab(tab.id)}
                        style={{
                          ...styles.tabBtn,
                          background:  active ? '#1e293b' : 'transparent',
                          color:       active
                            ? (tab.danger ? '#fca5a5' : '#60a5fa')
                            : (tab.danger ? '#f87171' : '#94a3b8'),
                          borderLeft:  active
                            ? `3px solid ${tab.danger ? '#ef4444' : '#3b82f6'}`
                            : '3px solid transparent',
                          fontWeight:  active ? 600 : 400,
                        }}
                      >
                        <span style={styles.tabIcon}>{tab.icon}</span>
                        <span>{tab.label}</span>
                        {tab.adminOnly && (
                          <span style={styles.adminBadge}>ADMIN</span>
                        )}
                      </button>
                    );
                  })}
                </div>
              );
            })}
          </nav>

          {/* Content */}
          <main style={styles.content}>
            <Suspense fallback={<SectionFallback />}>
              <div key={activeTab} style={{ animation: 'fadeIn 0.2s ease' }}>
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
    background: '#0f172a',
    color: '#f1f5f9',
    fontFamily: 'Inter, system-ui, -apple-system, sans-serif',
    padding: '32px 24px',
    boxSizing: 'border-box',
  },
  header: {
    maxWidth: 1200,
    margin: '0 auto 28px',
  },
  heading: {
    fontSize: 28,
    fontWeight: 800,
    color: '#f8fafc',
    margin: 0,
    letterSpacing: '-0.02em',
  },
  subheading: {
    fontSize: 14,
    color: '#64748b',
    marginTop: 6,
    marginBottom: 0,
  },
  layout: {
    maxWidth: 1200,
    margin: '0 auto',
    display: 'flex',
    gap: 28,
    alignItems: 'flex-start',
  },
  sidebar: {
    width: 210,
    flexShrink: 0,
    background: '#0f172a',
    borderRadius: 12,
    border: '1px solid #1e293b',
    padding: '10px 0',
    position: 'sticky' as const,
    top: 24,
  },
  groupLabel: {
    fontSize: 10,
    fontWeight: 700,
    color: '#334155',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.08em',
    padding: '10px 16px 4px',
  },
  tabBtn: {
    display: 'flex',
    alignItems: 'center',
    gap: 9,
    width: '100%',
    padding: '9px 16px',
    border: 'none',
    borderLeft: '3px solid transparent',
    background: 'transparent',
    cursor: 'pointer',
    fontSize: 13,
    textAlign: 'left' as const,
    transition: 'background 0.15s, color 0.15s',
    borderRadius: 0,
  },
  tabIcon: {
    fontSize: 15,
    flexShrink: 0,
    width: 18,
    textAlign: 'center' as const,
  },
  adminBadge: {
    marginLeft: 'auto',
    fontSize: 9,
    fontWeight: 700,
    padding: '2px 5px',
    borderRadius: 4,
    background: '#1e3a5f',
    color: '#60a5fa',
    border: '1px solid #1e3a5f',
    letterSpacing: '0.05em',
  },
  content: {
    flex: 1,
    minWidth: 0,
  },
};

export default Settings;
