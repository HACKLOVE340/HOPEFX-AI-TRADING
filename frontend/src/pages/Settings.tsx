/**
 * Settings.tsx — Full settings hub wired to every backend endpoint.
 *
 * Tab visibility:
 *   All users:      profile, security, billing, api-keys, broker, trading,
 *                   integrations, appearance, notifications, accessibility,
 *                   privacy, danger
 *   admin+:         system, admin
 *   superadmin:     all 24 SA tabs below
 *
 * Subscription gates (non-admin):
 *   starter+:      integrations
 *   professional+: api-keys, trading
 */

import React, { useState, Suspense, lazy } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useStore, selectUser } from '../store';
import { isAdmin, isSuperAdmin } from '../lib/subscription';
import type { SettingsTab } from './settings/types';

// ── User-facing sections ──────────────────────────────────────────────────────
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
const PerformanceSection       = lazy(() => import('./settings/PerformanceSection'));
const PrivacySection           = lazy(() => import('./settings/PrivacySection'));
const AccessibilitySection     = lazy(() => import('./settings/AccessibilitySection'));
const AdminSettingsSection     = lazy(() => import('./settings/AdminSettingsSection'));
const DangerSection            = lazy(() => import('./settings/DangerSection'));

// ── Superadmin sections (all 24) ──────────────────────────────────────────────
const SAOverviewSection        = lazy(() => import('./superadmin/OverviewSection'));
const SAUsersSection           = lazy(() => import('./superadmin/UsersSection'));
const SAPlatformSection        = lazy(() => import('./superadmin/PlatformSection'));
const SAMLAISection            = lazy(() => import('./superadmin/MLAISection'));
const SATradingEngineSection   = lazy(() => import('./superadmin/TradingEngineSection'));
const SARiskSection            = lazy(() => import('./superadmin/RiskManagementSection'));
const SAFinancialSection       = lazy(() => import('./superadmin/FinancialSection'));
const SASecuritySection        = lazy(() => import('./superadmin/SecuritySection'));
const SASecurityInfraSection   = lazy(() => import('./superadmin/SecurityInfraSection'));
const SALogsSection            = lazy(() => import('./superadmin/LogsSection'));
const SAAuditTrailSection      = lazy(() => import('./superadmin/AuditTrailSection'));
const SAFeatureFlagsSection    = lazy(() => import('./superadmin/FeatureFlagsSection'));
const SAAlertingSection        = lazy(() => import('./superadmin/AlertingSection'));
const SARateLimitingSection    = lazy(() => import('./superadmin/RateLimitingSection'));
const SABrokerMgmtSection      = lazy(() => import('./superadmin/BrokerManagementSection'));
const SAComplianceSection      = lazy(() => import('./superadmin/ComplianceSection'));
const SAGDPRSection            = lazy(() => import('./superadmin/GDPRSection'));
const SANuclearSection         = lazy(() => import('./superadmin/NuclearControlsSection'));
const SAReportingSection       = lazy(() => import('./superadmin/ReportingSection'));
const SAWhitelabelSection      = lazy(() => import('./superadmin/WhiteLabelSection'));
const SASystemHealthSection    = lazy(() => import('./superadmin/SystemHealthSection'));
const SAAutoHealingSection     = lazy(() => import('./superadmin/AutoHealingSection'));
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
  minPlan?: string;
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
      { id: 'performance',   label: 'Performance',    icon: '📊',  adminOnly: true },
      { id: 'admin',         label: 'Admin Settings', icon: '🔧',  adminOnly: true },
    ],
  },
  {
    label: 'SA — Overview',
    tabs: [
      { id: 'sa-overview',       label: 'Overview',         icon: '📊',  superAdminOnly: true },
    ],
  },
  {
    label: 'SA — Users & Access',
    tabs: [
      { id: 'sa-users',          label: 'Users',            icon: '👥',  superAdminOnly: true },
      { id: 'sa-feature-flags',  label: 'Feature Flags',    icon: '🚩',  superAdminOnly: true },
      { id: 'sa-audit-trail',    label: 'Audit Trail',      icon: '📜',  superAdminOnly: true },
      { id: 'sa-logs',           label: 'Logs',             icon: '📋',  superAdminOnly: true },
    ],
  },
  {
    label: 'SA — Platform',
    tabs: [
      { id: 'sa-platform',       label: 'Platform',         icon: '🌐',  superAdminOnly: true },
      { id: 'platform-config',   label: 'Platform Config',  icon: '🛠️',  superAdminOnly: true },
      { id: 'sa-rate-limiting',  label: 'Rate Limiting',    icon: '🚦',  superAdminOnly: true },
      { id: 'sa-alerting',       label: 'Alerting',         icon: '🔔',  superAdminOnly: true },
      { id: 'sa-whitelabel',     label: 'White Label',      icon: '🏷️',  superAdminOnly: true },
      { id: 'sa-reporting',      label: 'Reporting',        icon: '📑',  superAdminOnly: true },
    ],
  },
  {
    label: 'SA — Trading Engine',
    tabs: [
      { id: 'sa-trading-engine', label: 'Trading Engine',   icon: '⚡',  superAdminOnly: true },
      { id: 'sa-ml-ai',          label: 'ML / AI',          icon: '🧠',  superAdminOnly: true },
      { id: 'sa-risk',           label: 'Risk Management',  icon: '⚖️',  superAdminOnly: true },
      { id: 'sa-broker-mgmt',    label: 'Broker Mgmt',      icon: '🏦',  superAdminOnly: true },
      { id: 'sa-nuclear',        label: 'Nuclear Controls', icon: '☢️',  superAdminOnly: true },
    ],
  },
  {
    label: 'SA — Finance & Compliance',
    tabs: [
      { id: 'sa-financial',      label: 'Financial',        icon: '💰',  superAdminOnly: true },
      { id: 'sa-compliance',     label: 'Compliance',       icon: '📋',  superAdminOnly: true },
      { id: 'sa-gdpr',           label: 'GDPR / Privacy',   icon: '🔏',  superAdminOnly: true },
    ],
  },
  {
    label: 'SA — Security & Infra',
    tabs: [
      { id: 'sa-security',       label: 'Security',         icon: '🛡️',  superAdminOnly: true },
      { id: 'sa-security-infra', label: 'Security Infra',   icon: '🔐',  superAdminOnly: true },
      { id: 'sa-auto-healing',   label: 'Auto-Healing',     icon: '🩺',  superAdminOnly: true },
      { id: 'sa-system-health',  label: 'System Health',    icon: '💓',  superAdminOnly: true },
      { id: 'sa-reliability',    label: 'Reliability',      icon: '🔬',  superAdminOnly: true },
    ],
  },
  {
    label: 'Danger Zone',
    tabs: [
      { id: 'danger',        label: 'Danger Zone',    icon: '⚠️',  danger: true },
    ],
  },
];

// ── Helpers ───────────────────────────────────────────────────────────────────

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
    <Link to="/pricing" style={{
      display: 'inline-block', padding: '10px 24px',
      background: '#3b82f6', color: '#fff', borderRadius: 8,
      fontWeight: 600, fontSize: 14, textDecoration: 'none',
    }}>
      View Plans
    </Link>
  </div>
);

const PLAN_RANK: Record<string, number> = {
  free: 0, starter: 1, professional: 2, enterprise: 3, elite: 4,
};

// ── Settings page ─────────────────────────────────────────────────────────────

const Settings: React.FC = () => {
  const navigate   = useNavigate();
  const user       = useStore(selectUser);
  const admin      = user ? isAdmin(user.role) : false;
  const superAdmin = user ? isSuperAdmin(user.role) : false;

  const storePlan  = useStore((s) => s.plan) ?? 'free';
  const plan       = superAdmin ? 'elite' : storePlan;
  const planRank   = PLAN_RANK[plan] ?? 0;

  const [activeTab, setActiveTab] = useState<SettingsTab>('profile');
  const [search, setSearch]       = useState('');

  const renderSection = () => {
    const gate = (minPlan: string, node: React.ReactNode) => {
      if (superAdmin || admin) return node;
      if (planRank >= (PLAN_RANK[minPlan] ?? 0)) return node;
      return <UpgradeNotice requiredPlan={minPlan} />;
    };

    switch (activeTab) {
      // Account
      case 'profile':           return <ProfileSection />;
      case 'security':          return <SecuritySection />;
      case 'billing':           return <BillingSection />;
      case 'api-keys':          return gate('professional', <ApiKeysSection />);
      // Trading
      case 'broker':            return <BrokerSection />;
      case 'trading':           return gate('professional', <TradingSection />);
      case 'integrations':      return gate('starter', <IntegrationsSection />);
      // Preferences
      case 'appearance':        return <AppearanceSection />;
      case 'notifications':     return <NotificationsSection />;
      case 'accessibility':     return <AccessibilitySection />;
      case 'privacy':           return <PrivacySection />;
      // Administration
      case 'system':            return admin      ? <SystemSection />          : null;
      case 'performance':       return admin      ? <PerformanceSection />     : null;
      case 'admin':             return admin      ? <AdminSettingsSection />   : null;
      // SA — Overview
      case 'sa-overview':       return superAdmin ? <SAOverviewSection />      : null;
      // SA — Users & Access
      case 'sa-users':          return superAdmin ? <SAUsersSection />         : null;
      case 'sa-feature-flags':  return superAdmin ? <SAFeatureFlagsSection />  : null;
      case 'sa-audit-trail':    return superAdmin ? <SAAuditTrailSection />    : null;
      case 'sa-logs':           return superAdmin ? <SALogsSection />          : null;
      // SA — Platform
      case 'sa-platform':       return superAdmin ? <SAPlatformSection />      : null;
      case 'platform-config':   return superAdmin ? <PlatformConfigSection />  : null;
      case 'sa-rate-limiting':  return superAdmin ? <SARateLimitingSection />  : null;
      case 'sa-alerting':       return superAdmin ? <SAAlertingSection />      : null;
      case 'sa-whitelabel':     return superAdmin ? <SAWhitelabelSection />    : null;
      case 'sa-reporting':      return superAdmin ? <SAReportingSection />     : null;
      // SA — Trading Engine
      case 'sa-trading-engine': return superAdmin ? <SATradingEngineSection /> : null;
      case 'sa-ml-ai':          return superAdmin ? <SAMLAISection />          : null;
      case 'sa-risk':           return superAdmin ? <SARiskSection />          : null;
      case 'sa-broker-mgmt':    return superAdmin ? <SABrokerMgmtSection />    : null;
      case 'sa-nuclear':        return superAdmin ? <SANuclearSection />       : null;
      // SA — Finance & Compliance
      case 'sa-financial':      return superAdmin ? <SAFinancialSection />     : null;
      case 'sa-compliance':     return superAdmin ? <SAComplianceSection />    : null;
      case 'sa-gdpr':           return superAdmin ? <SAGDPRSection />          : null;
      // SA — Security & Infra
      case 'sa-security':       return superAdmin ? <SASecuritySection />      : null;
      case 'sa-security-infra': return superAdmin ? <SASecurityInfraSection /> : null;
      case 'sa-auto-healing':   return superAdmin ? <SAAutoHealingSection />   : null;
      case 'sa-system-health':  return superAdmin ? <SASystemHealthSection />  : null;
      case 'sa-reliability':    return superAdmin ? <SystemReliabilitySection /> : null;
      // Danger
      case 'danger':            return <DangerSection />;
      default:                  return <ProfileSection />;
    }
  };

  return (
    <>
      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
      `}</style>

      <div className="page-content">
        <div style={S.header}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 12 }}>
            <h1 style={S.heading}>Settings</h1>
            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={() => navigate('/trade')}
                style={{ padding: '6px 14px', background: 'rgba(59,130,246,0.12)', border: '1px solid rgba(59,130,246,0.35)', borderRadius: 7, color: '#60a5fa', fontSize: 12, fontWeight: 700, cursor: 'pointer' }}>
                ⚡ Trade
              </button>
              <button onClick={() => navigate('/journal')}
                style={{ padding: '6px 14px', background: 'rgba(16,185,129,0.12)', border: '1px solid rgba(16,185,129,0.35)', borderRadius: 7, color: '#10b981', fontSize: 12, fontWeight: 700, cursor: 'pointer' }}>
                📓 Journal
              </button>
              <button onClick={() => navigate('/wallet')}
                style={{ padding: '6px 14px', background: 'rgba(245,158,11,0.12)', border: '1px solid rgba(245,158,11,0.35)', borderRadius: 7, color: '#f59e0b', fontSize: 12, fontWeight: 700, cursor: 'pointer' }}>
                💰 Wallet
              </button>
            </div>
          </div>
          <p style={S.subheading}>
            Manage your account, trading preferences, integrations, and platform configuration.
            {superAdmin && (
              <span style={S.saBadge}>SUPER ADMIN — Full Platform Control</span>
            )}
          </p>
        </div>

        <div style={S.layout}>
          <nav style={S.sidebar}>
            {/* Search box */}
            <div style={{ padding: '0 0 12px', position: 'sticky', top: 0, background: '#0f172a', zIndex: 1 }}>
              <div style={{
                display: 'flex', alignItems: 'center', gap: 6,
                background: '#1e293b', border: '1px solid #334155',
                borderRadius: 8, padding: '7px 10px',
              }}>
                <span style={{ fontSize: 12, color: '#475569', flexShrink: 0 }}>🔍</span>
                <input
                  type="text"
                  placeholder="Search settings…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  style={{
                    background: 'transparent', border: 'none', outline: 'none',
                    color: '#e2e8f0', fontSize: 13, width: '100%', fontFamily: 'inherit',
                  }}
                />
                {search && (
                  <button onClick={() => setSearch('')} style={{
                    background: 'transparent', border: 'none', cursor: 'pointer',
                    color: '#64748b', fontSize: 16, padding: 0, lineHeight: 1,
                  }}>×</button>
                )}
              </div>
            </div>

            {/* Quick-access shortcuts (always visible) */}
            {!search && (
              <div style={{ marginBottom: 16 }}>
                <div style={S.groupLabel}>Quick Access</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, padding: '2px 0 8px' }}>
                  {[
                    { id: 'profile' as SettingsTab,        label: '👤 Profile' },
                    { id: 'security' as SettingsTab,       label: '🔒 Security' },
                    { id: 'broker' as SettingsTab,         label: '🏦 Broker' },
                    { id: 'notifications' as SettingsTab,  label: '🔔 Alerts' },
                    { id: 'billing' as SettingsTab,        label: '💳 Billing' },
                    { id: 'danger' as SettingsTab,         label: '⚠️ Danger' },
                  ].map(({ id, label }) => (
                    <button
                      key={id}
                      onClick={() => setActiveTab(id)}
                      style={{
                        padding: '4px 10px',
                        background: activeTab === id ? 'rgba(59,130,246,0.15)' : 'rgba(255,255,255,0.04)',
                        border: `1px solid ${activeTab === id ? '#3b82f6' : '#1e293b'}`,
                        borderRadius: 6,
                        color: activeTab === id ? '#60a5fa' : '#64748b',
                        fontSize: 11, cursor: 'pointer', fontFamily: 'inherit',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {TAB_GROUPS.map((group) => {
              const visibleTabs = group.tabs.filter((t) => {
                if (t.superAdminOnly) return superAdmin;
                if (t.adminOnly)      return admin;
                // Filter by search
                if (search) return t.label.toLowerCase().includes(search.toLowerCase());
                return true;
              });
              if (visibleTabs.length === 0) return null;

              return (
                <div key={group.label} style={{ marginBottom: 2 }}>
                  <div style={S.groupLabel}>{group.label}</div>
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
                          ...S.tabBtn,
                          background: active ? '#1e293b' : 'transparent',
                          color: active ? activeColor : inactiveColor,
                          borderLeft: active ? `3px solid ${borderColor}` : '3px solid transparent',
                          fontWeight: active ? 600 : 400,
                          opacity: locked ? 0.6 : 1,
                        }}
                      >
                        <span style={S.tabIcon}>{tab.icon}</span>
                        <span style={{ flex: 1 }}>{tab.label}</span>
                        {locked && <span style={{ fontSize: 10, color: '#475569' }}>🔒</span>}
                        {isSA && <span style={S.saBadgeSmall}>SA</span>}
                        {tab.adminOnly && !isSA && <span style={S.adminBadge}>ADM</span>}
                      </button>
                    );
                  })}
                </div>
              );
            })}
          </nav>

          <main style={S.content}>
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

const S: Record<string, React.CSSProperties> = {
  page: {
    minHeight: '100vh', background: '#0f172a', color: '#f1f5f9',
    fontFamily: 'Inter, system-ui, -apple-system, sans-serif',
    padding: '32px 24px', boxSizing: 'border-box',
  },
  header:    { maxWidth: 1400, margin: '0 auto 28px' },
  heading:   { fontSize: 28, fontWeight: 800, color: '#f8fafc', margin: 0, letterSpacing: '-0.02em' },
  subheading: { fontSize: 14, color: '#64748b', marginTop: 6, marginBottom: 0, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' },
  saBadge:   { fontSize: 11, fontWeight: 700, padding: '2px 8px', borderRadius: 4, background: '#450a0a', color: '#fca5a5', border: '1px solid #dc2626' },
  layout:    { maxWidth: 1400, margin: '0 auto', display: 'flex', gap: 28, alignItems: 'flex-start' },
  sidebar: {
    width: 230, flexShrink: 0, background: '#0f172a', borderRadius: 12,
    border: '1px solid #1e293b', padding: '10px 0',
    position: 'sticky' as const, top: 24,
    maxHeight: 'calc(100vh - 48px)', overflowY: 'auto' as const,
  },
  groupLabel: {
    fontSize: 10, fontWeight: 700, color: '#334155',
    textTransform: 'uppercase' as const, letterSpacing: '0.08em',
    padding: '8px 16px 3px',
  },
  tabBtn: {
    display: 'flex', alignItems: 'center', gap: 8, width: '100%',
    padding: '7px 14px', border: 'none', borderLeft: '3px solid transparent',
    background: 'transparent', cursor: 'pointer', fontSize: 12,
    textAlign: 'left' as const, transition: 'background 0.15s, color 0.15s', borderRadius: 0,
  },
  tabIcon:     { fontSize: 13, flexShrink: 0, width: 16, textAlign: 'center' as const },
  adminBadge:  { fontSize: 9, fontWeight: 700, padding: '1px 4px', borderRadius: 3, background: '#1e3a5f', color: '#60a5fa', border: '1px solid #1e3a5f' },
  saBadgeSmall: { fontSize: 9, fontWeight: 700, padding: '1px 4px', borderRadius: 3, background: '#450a0a', color: '#fca5a5', border: '1px solid #dc2626' },
  content:     { flex: 1, minWidth: 0 },
};

export default Settings;
