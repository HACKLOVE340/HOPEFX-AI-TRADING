/**
 * Settings.tsx
 * Full settings hub — tabs covering every aspect of the platform.
 *
 * Tab visibility rules:
 *   - All authenticated users: profile, security, broker, trading,
 *     appearance, notifications, api-keys, billing, integrations,
 *     privacy, accessibility, danger
 *   - Subscription-gated tabs:
 *       starter+:      integrations
 *       professional+: api-keys, trading (advanced)
 *   - Admin / superadmin only: system, admin
 *   - Super Admin only: sa-users, sa-platform, sa-ml-ai, sa-trading-engine,
 *       sa-financial, sa-security, sa-logs, sa-feature-flags, platform-config
 *
 * Subscription tiers (monetization/pricing.py):
 *   free | starter | professional | enterprise | elite
 *
 * Role hierarchy (lib/subscription.ts):
 *   user < trader < admin < superadmin
 *
 * Super Admin bypasses ALL gates — plan, role, feature flag, everything.
 */

import React, { useState, Suspense, lazy } from 'react';
import { useStore, selectUser } from '../store';
import { isAdmin, isSuperAdmin } from '../lib/subscription';
import type { SettingsTab } from './settings/types';

// ── Lazy-load every section ───────────────────────────────────────────────────
const ProfileSection           = lazy(() => import('./settings/ProfileSection'));
const SecuritySection          = lazy(() => import('./settings/SecuritySection'));
const BrokerSection            = lazy(() => import('./settings/BrokerSection'));
const TradingSection           = lazy(() => import('./settings/TradingSection'));
const AppearanceSection        = lazy(() => import('./settings/AppearanceSection'));
const NotificationsSection     = lazy(() => import('./settings/NotificationsSection'));
const ApiKeysSection           = lazy(() => import('./settings/ApiKeysSection'));
const BillingSection           = lazy(() => import('./settings/BillingSection'));
const IntegrationsSection      = lazy(() => import('./settings/IntegrationsSection'));
const SystemSection            = lazy(() => import('./settings/SystemSection'));
const PrivacySection           = lazy(() => import('./settings/PrivacySection'));
const AccessibilitySection     = lazy(() => import('./settings/AccessibilitySection'));
const AdminSettingsSection     = lazy(() => import('./settings/AdminSettingsSection'));
const DangerSection            = lazy(() => import('./settings/DangerSection'));

// Superadmin-only sections
const SAUsersSection           = lazy(() => import('./superadmin/UsersSection'));
const SAPlatformSection        = lazy(() => import('./superadmin/PlatformSection'));
const SAMLAISection            = lazy(() => import('./superadmin/MLAISection'));
const SATradingEngineSection   = lazy(() => import('./superadmin/TradingEngineSection'));
const SAFinancialSection       = lazy(() => import('./superadmin/FinancialSection'));
const SASecuritySection        = lazy(() => import('./superadmin/SecuritySection'));
const SALogsSection            = lazy(() => import('./superadmin/LogsSection'));
const SAFeatureFlagsSection    = lazy(() => import('./superadmin/FeatureFlagsSection'));
const PlatformConfigSection    = lazy(() => import('./settings/PlatformConfiguration'));
const SystemReliabilitySection = lazy(() => import('./superadmin/SystemReliabilitySection'));

// ── Tab definitions ───────────────────────────────────────────────────────────

interface TabDef {
  id: SettingsTab;
  label: string;
  icon: string;
  adminOnly?: boolean;
  superAdminOnly?: boolean;
  danger?: boolean;
  minPlan?: string; // minimum subscription tier required (non-admin users)
}

interface TabGroup {
  label: string;
  tabs: TabDef[];
}

const TAB_GROUPS: TabGroup[] = [
  {
    label: 'Account',
    tabs: [
      { id: 'profile',       label: 'Profile',        icon: '👤' },
      { id: 'security',      label: 'Security',       icon: '🔒' },
      { id: 'billing',       label: 'Billing',        icon: '💳' },
      { id: 'api-keys',      label: 'API Keys',       icon: '🔑', minPlan: 'professional' },
    ],
  },
  {
    label: 'Trading',
    tabs: [
      { id: 'broker',        label: 'Broker',         icon: '🏦' },
      { id: 'trading',       label: 'Trading',        icon: '📈', minPlan: 'professional' },
      { id: 'integrations',  label: 'Integrations',   icon: '🔌', minPlan: 'starter' },
    ],
  },
  {
    label: 'Preferences',
    tabs: [
      { id: 'appearance',    label: 'Appearance',     icon: '🎨' },
      { id: 'notifications', label: 'Notifications',  icon: '🔔' },
      { id: 'accessibility', label: 'Accessibility',  icon: '♿' },
      { id: 'privacy',       label: 'Privacy & Data', icon: '🔏' },
    ],
  },
  {
    label: 'Administration',
    tabs: [
      { id: 'system',        label: 'System',         icon: '⚙️',  adminOnly: true },
      { id: 'admin',         label: 'Admin Settings', icon: '🔧',  adminOnly: true },
    ],
  },
  {
    label: 'Super Admin',
    tabs: [
      { id: 'sa-users',          label: 'Users',           icon: '👥',  superAdminOnly: true },
      { id: 'sa-platform',       label: 'Platform',        icon: '🌐',  superAdminOnly: true },
      { id: 'sa-ml-ai',          label: 'ML / AI',         icon: '🧠',  superAdminOnly: true },
      { id: 'sa-trading-engine', label: 'Trading Engine',  icon: '📈',  superAdminOnly: true },
      { id: 'sa-financial',      label: 'Financial',       icon: '💰',  superAdminOnly: true },
      { id: 'sa-security',       label: 'Security',        icon: '🛡️',  superAdminOnly: true },
      { id: 'sa-logs',           label: 'Logs',            icon: '📋',  superAdminOnly: true },
      { id: 'sa-feature-flags',  label: 'Feature Flags',   icon: '🚩',  superAdminOnly: true },
      { id: 'platform-config',   label: 'Platform Config', icon: '🛠️',  superAdminOnly: true },
      { id: 'sa-reliability',    label: 'System Reliability', icon: '🔬', superAdminOnly: true },
    ],
  },
  {
    label: 'Danger Zone',
    tabs: [
      { id: 'danger',        label: 'Danger Zone',    icon: '⚠️',  danger: true },
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

// ── Upgrade notice ────────────────────────────────────────────────────────────

const UpgradeNotice: React.FC<{ requiredPlan: string }> = ({ requiredPlan }) => (
  <div style={{
    padding: '48px 32px', textAlign: 'center',
    background: '#0f172a', border: '1px solid #1e293b', borderRadius: 14,
  }}>
    <div style={{ fontSize: 40, marginBottom: 16 }}>🔒</div>
    <div style={{ fontSize: 18, fontWeight: 700, color: '#f1f5f9', marginBottom: 8 }}>
      {requiredPlan.charAt(0).toUpperCase() + requiredPlan.slice(1)} Plan Required
    </div>
    <div style={{ fontSize: 14, color: '#64748b', maxWidth: 360, margin: '0 auto 20px' }}>
      Upgrade your subscription to unlock this feature.
    </div>
    <a
      href="/billing"
      style={{
        display: 'inline-block', padding: '10px 24px',
        background: '#3b82f6', color: '#fff', borderRadius: 8,
        fontWeight: 600, fontSize: 14, textDecoration: 'none',
      }}
    >
      View Plans
    </a>
  </div>
);

// ── Plan rank helper ──────────────────────────────────────────────────────────

const PLAN_RANK: Record<string, number> = {
  free: 0, starter: 1, professional: 2, enterprise: 3, elite: 4,
};

// ── Settings page ─────────────────────────────────────────────────────────────

const Settings: React.FC = () => {
  const user       = useStore(selectUser);
  const admin      = user ? isAdmin(user.role) : false;
  const superAdmin = user ? isSuperAdmin(user.role) : false;

  // superadmin bypasses all plan gates — treat as elite
  const storePlan  = useStore((s) => s.plan) ?? 'free';
  const plan       = superAdmin ? 'elite' : storePlan;
  const planRank   = PLAN_RANK[plan] ?? 0;

  const [activeTab, setActiveTab] = useState<SettingsTab>('profile');

  /** Return the section component, gating by plan where required. */
  const renderSection = () => {
    // Plan gate helper — admins and superadmins bypass
    const gate = (minPlan: string, node: React.ReactNode) => {
      if (superAdmin || admin) return node;
      if (planRank >= (PLAN_RANK[minPlan] ?? 0)) return node;
      return <UpgradeNotice requiredPlan={minPlan} />;
    };

    switch (activeTab) {
      // ── Account ──────────────────────────────────────────────────────────
      case 'profile':           return <ProfileSection />;
      case 'security':          return <SecuritySection />;
      case 'billing':           return <BillingSection />;
      case 'api-keys':          return gate('professional', <ApiKeysSection />);

      // ── Trading ──────────────────────────────────────────────────────────
      case 'broker':            return <BrokerSection />;
      case 'trading':           return gate('professional', <TradingSection />);
      case 'integrations':      return gate('starter', <IntegrationsSection />);

      // ── Preferences ──────────────────────────────────────────────────────
      case 'appearance':        return <AppearanceSection />;
      case 'notifications':     return <NotificationsSection />;
      case 'accessibility':     return <AccessibilitySection />;
      case 'privacy':           return <PrivacySection />;

      // ── Administration ────────────────────────────────────────────────────
      case 'system':            return admin      ? <SystemSection />          : null;
      case 'admin':             return admin      ? <AdminSettingsSection />   : null;

      // ── Super Admin ───────────────────────────────────────────────────────
      case 'sa-users':          return superAdmin ? <SAUsersSection />         : null;
      case 'sa-platform':       return superAdmin ? <SAPlatformSection />      : null;
      case 'sa-ml-ai':          return superAdmin ? <SAMLAISection />          : null;
      case 'sa-trading-engine': return superAdmin ? <SATradingEngineSection /> : null;
      case 'sa-financial':      return superAdmin ? <SAFinancialSection />     : null;
      case 'sa-security':       return superAdmin ? <SASecuritySection />      : null;
      case 'sa-logs':           return superAdmin ? <SALogsSection />          : null;
      case 'sa-feature-flags':  return superAdmin ? <SAFeatureFlagsSection />  : null;
      case 'platform-config':   return superAdmin ? <PlatformConfigSection />       : null;
      case 'sa-reliability':    return superAdmin ? <SystemReliabilitySection />    : null;

      // ── Danger Zone ───────────────────────────────────────────────────────
      case 'danger':            return <DangerSection />;

      default:                  return null;
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
          {/* ── Sidebar nav ─────────────────────────────────────────────── */}
          <nav style={styles.sidebar}>
            {TAB_GROUPS.map((group) => {
              const visibleTabs = group.tabs.filter((t) => {
                if (t.superAdminOnly) return superAdmin;
                if (t.adminOnly)      return admin;
                return true;
              });
              if (visibleTabs.length === 0) return null;

              return (
                <div key={group.label} style={{ marginBottom: 4 }}>
                  <div style={styles.groupLabel}>{group.label}</div>
                  {visibleTabs.map((tab) => {
                    const active   = activeTab === tab.id;
                    const isSA     = !!tab.superAdminOnly;
                    const isDanger = !!tab.danger;
                    const locked   = !superAdmin && !admin && tab.minPlan
                      ? (PLAN_RANK[plan] ?? 0) < (PLAN_RANK[tab.minPlan] ?? 0)
                      : false;

                    const activeColor   = isDanger || isSA ? '#fca5a5' : '#60a5fa';
                    const inactiveColor = locked ? '#475569' : (isDanger || isSA ? '#f87171' : '#94a3b8');
                    const borderColor   = isDanger || isSA ? '#ef4444' : '#3b82f6';

                    return (
                      <button
                        key={tab.id}
                        onClick={() => setActiveTab(tab.id)}
                        style={{
                          ...styles.tabBtn,
                          background: active ? '#1e293b' : 'transparent',
                          color: active ? activeColor : inactiveColor,
                          borderLeft: active
                            ? `3px solid ${borderColor}`
                            : '3px solid transparent',
                          fontWeight: active ? 600 : 400,
                          opacity: locked ? 0.6 : 1,
                        }}
                      >
                        <span style={styles.tabIcon}>{tab.icon}</span>
                        <span style={{ flex: 1 }}>{tab.label}</span>
                        {locked && (
                          <span style={{ fontSize: 11, color: '#475569' }}>🔒</span>
                        )}
                        {isSA && (
                          <span style={styles.superAdminBadge}>SA</span>
                        )}
                        {tab.adminOnly && !isSA && (
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
    width: 220,
    flexShrink: 0,
    background: '#0f172a',
    borderRadius: 12,
    border: '1px solid #1e293b',
    padding: '10px 0',
    position: 'sticky' as const,
    top: 24,
    maxHeight: 'calc(100vh - 48px)',
    overflowY: 'auto' as const,
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
  superAdminBadge: {
    marginLeft: 'auto',
    fontSize: 9,
    fontWeight: 700,
    padding: '2px 5px',
    borderRadius: 4,
    background: '#450a0a',
    color: '#fca5a5',
    border: '1px solid #dc2626',
    letterSpacing: '0.05em',
  },
  content: {
    flex: 1,
    minWidth: 0,
  },
};

export default Settings;
