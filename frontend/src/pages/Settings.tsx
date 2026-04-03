/**
 * Settings.tsx
 * Full-featured settings hub covering every aspect of the application.
 *
 * Sections:
 *   Profile       — identity, avatar, bio, timezone, language
 *   Security      — password change, 2FA, active sessions
 *   Broker        — broker connection, API keys, live/paper toggle
 *   Trading       — defaults, risk limits, automation, kill switch
 *   Appearance    — theme, accent color, chart style, display prefs
 *   Notifications — Discord, Slack, Telegram, Email, alert triggers
 *   API Keys      — generate, list, revoke programmatic access keys
 *   Billing       — subscription plan, wallet, transaction history
 *   Danger Zone   — export data, emergency stop, delete account
 */

import React, { useState, Suspense, lazy } from 'react';
import type { SettingsTab } from './settings/types';

const ProfileSection       = lazy(() => import('./settings/ProfileSection'));
const SecuritySection      = lazy(() => import('./settings/SecuritySection'));
const BrokerSection        = lazy(() => import('./settings/BrokerSection'));
const TradingSection       = lazy(() => import('./settings/TradingSection'));
const AppearanceSection    = lazy(() => import('./settings/AppearanceSection'));
const NotificationsSection = lazy(() => import('./settings/NotificationsSection'));
const ApiKeysSection       = lazy(() => import('./settings/ApiKeysSection'));
const BillingSection       = lazy(() => import('./settings/BillingSection'));
const DangerSection        = lazy(() => import('./settings/DangerSection'));

interface TabDef {
  id: SettingsTab;
  label: string;
  icon: string;
  danger?: boolean;
}

const TABS: TabDef[] = [
  { id: 'profile',       label: 'Profile',       icon: '👤' },
  { id: 'security',      label: 'Security',       icon: '🔒' },
  { id: 'broker',        label: 'Broker',         icon: '🏦' },
  { id: 'trading',       label: 'Trading',        icon: '📈' },
  { id: 'appearance',    label: 'Appearance',     icon: '🎨' },
  { id: 'notifications', label: 'Notifications',  icon: '🔔' },
  { id: 'api-keys',      label: 'API Keys',       icon: '🔑' },
  { id: 'billing',       label: 'Billing',        icon: '💳' },
  { id: 'danger',        label: 'Danger Zone',    icon: '⚠️', danger: true },
];

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

const Settings: React.FC = () => {
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
      case 'danger':        return <DangerSection />;
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
          <p style={styles.subheading}>Manage your account, trading preferences, and integrations.</p>
        </div>

        <div style={styles.layout}>
          <nav style={styles.sidebar}>
            {TABS.map((tab) => {
              const active = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  style={{
                    ...styles.tabBtn,
                    background:  active ? '#1e293b' : 'transparent',
                    color:       active ? (tab.danger ? '#fca5a5' : '#60a5fa') : (tab.danger ? '#f87171' : '#94a3b8'),
                    borderLeft:  active ? `3px solid ${tab.danger ? '#ef4444' : '#3b82f6'}` : '3px solid transparent',
                    fontWeight:  active ? 600 : 400,
                  }}
                >
                  <span style={styles.tabIcon}>{tab.icon}</span>
                  <span>{tab.label}</span>
                </button>
              );
            })}
          </nav>

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
    maxWidth: 1100,
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
    maxWidth: 1100,
    margin: '0 auto',
    display: 'flex',
    gap: 28,
    alignItems: 'flex-start',
  },
  sidebar: {
    width: 200,
    flexShrink: 0,
    background: '#0f172a',
    borderRadius: 12,
    border: '1px solid #1e293b',
    padding: '8px 0',
    position: 'sticky',
    top: 24,
  },
  tabBtn: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    width: '100%',
    padding: '10px 16px',
    border: 'none',
    borderLeft: '3px solid transparent',
    background: 'transparent',
    cursor: 'pointer',
    fontSize: 14,
    textAlign: 'left',
    transition: 'background 0.15s, color 0.15s',
    borderRadius: 0,
  },
  tabIcon: {
    fontSize: 16,
    flexShrink: 0,
  },
  content: {
    flex: 1,
    minWidth: 0,
  },
};

export default Settings;
