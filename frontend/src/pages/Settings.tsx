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

import React, { useState, useEffect, useCallback, Suspense, lazy } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useStore, selectUser } from '../store';
import { isAdmin, isSuperAdmin, planRank } from '../lib/subscription';
import type { SettingsTab } from './settings/types';
import { Accessibility, AlertTriangle, Banknote, BarChart3, Bell, Brain, ClipboardList, CreditCard, FileLock2, Files, Flag, Globe, Hammer, HeartPulse, KeyRound, Landmark, Lock, Microscope, MoveHorizontal, Palette, Plug, Radiation, Scale, Scroll, Settings as SettingsIcon, Shield, ShieldCheck, Stethoscope, Tag, TrafficCone, TrendingUp, User, Users, Wrench, Zap } from 'lucide-react';

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
const ProfessionalControlPlane = lazy(() => import('./settings/ProfessionalControlPlane'));

// ── Tab definitions ───────────────────────────────────────────────────────────

interface TabDef {
  id: SettingsTab;
  label: string;
  icon: React.ReactNode;
  adminOnly?: boolean;
  superAdminOnly?: boolean;
  danger?: boolean;
  minPlan?: string;
  /**
   * Extra search terms, so a tab is findable by the word the user actually
   * types: "2FA" for Two-Factor, "card" for Billing, "webhook" for
   * Integrations. Optional — the filter's `?? ''` keeps untagged tabs working.
   */
  keywords?: string;
}

interface TabGroup {
  label: string;
  tabs: TabDef[];
}

/** Every tab id that can appear in ?tab= — derived from the groups below. */
function isKnownTab(value: string | null): value is SettingsTab {
  return !!value && TAB_GROUPS.some((g) => g.tabs.some((t) => t.id === value));
}

const TAB_GROUPS: TabGroup[] = [
  {
    label: 'Account',
    tabs: [
      { id: 'profile',       label: 'Profile',        icon: <User size={16} aria-hidden />, keywords: 'name username avatar bio timezone language' },
      { id: 'security',      label: 'Security',       icon: <Lock size={16} aria-hidden />, keywords: '2fa two-factor mfa password sessions devices login' },
      { id: 'billing',       label: 'Billing',        icon: <CreditCard size={16} aria-hidden />, keywords: 'card payment invoice subscription plan upgrade receipt' },
      { id: 'api-keys',      label: 'API Keys',       icon: <KeyRound size={16} aria-hidden />, minPlan: 'professional', keywords: 'token secret credentials developer' },
    ],
  },
  {
    label: 'Trading',
    tabs: [
      { id: 'broker',        label: 'Broker',         icon: <Landmark size={16} aria-hidden />, keywords: 'oanda alpaca paper account connection live' },
      { id: 'trading',       label: 'Trading',        icon: <TrendingUp size={16} aria-hidden />, minPlan: 'professional', keywords: 'risk drawdown lot leverage kill switch limits' },
      { id: 'integrations',  label: 'Integrations',   icon: <Plug size={16} aria-hidden />, minPlan: 'starter', keywords: 'webhook tradingview mt4 mt5 ctrader zapier sheets' },
    ],
  },
  {
    label: 'Preferences',
    tabs: [
      { id: 'appearance',    label: 'Appearance',     icon: <Palette size={16} aria-hidden />, keywords: 'theme dark light colour color font display' },
      { id: 'notifications', label: 'Notifications',  icon: <Bell size={16} aria-hidden />, keywords: 'alerts email discord slack telegram webhook' },
      { id: 'accessibility', label: 'Accessibility',  icon: <Accessibility size={16} aria-hidden />, keywords: 'contrast motion screen reader colour blind text size' },
      { id: 'privacy',       label: 'Privacy & Data', icon: <FileLock2 size={16} aria-hidden />, keywords: 'gdpr export delete consent sharing leaderboard retention' },
    ],
  },
  {
    label: 'Professional Operations',
    tabs: [
      { id: 'control-overview', label: 'Readiness', icon: '◈', adminOnly: true, keywords: 'startup health degraded status' },
      { id: 'control-brain', label: 'Core Brain', icon: '◎', adminOnly: true, keywords: 'brain policy approval' },
      { id: 'control-models', label: 'Models', icon: '⌁', adminOnly: true, keywords: 'model routing fallback provider' },
      { id: 'control-agents', label: 'Agents', icon: '◇', adminOnly: true, keywords: 'agents teams schedules' },
      { id: 'control-connectors', label: 'Connectors', icon: <MoveHorizontal size={16} aria-hidden />, adminOnly: true, keywords: 'plugins tools integrations' },
      { id: 'control-sandbox', label: 'Sandbox', icon: '□', adminOnly: true, keywords: 'sandbox sessions limits network' },
      { id: 'control-startup', label: 'Startup', icon: '↻', adminOnly: true, keywords: 'lifecycle boot restart' },
      { id: 'control-audit', label: 'Config Audit', icon: '≡', adminOnly: true, keywords: 'audit versions revision rollback' },
      { id: 'safe-supervisor', label: 'Supervisor', icon: '◎', adminOnly: true, keywords: 'multi agent orchestration delegation' },
      { id: 'safe-agents', label: 'Specialist Agents', icon: '◇', adminOnly: true, keywords: 'agents teams capabilities' },
      { id: 'safe-models', label: 'Model Router', icon: '⌁', adminOnly: true, keywords: 'models fallback routing costs' },
      { id: 'safe-integrations', label: 'External Access', icon: <MoveHorizontal size={16} aria-hidden />, adminOnly: true, keywords: 'api tokens connectors vault scopes' },
      { id: 'safe-repairs', label: 'Repairs & Upgrades', icon: <SettingsIcon size={16} aria-hidden />, adminOnly: true, keywords: 'diagnostics repair upgrade rollback approval' },
      { id: 'safe-chat', label: 'Operator Chat', icon: '◌', adminOnly: true, keywords: 'chat voice tools citations' },
    ],
  },
  {
    label: 'Administration',
    tabs: [
      { id: 'system',        label: 'System',         icon: <SettingsIcon size={16} aria-hidden />,  adminOnly: true },
      { id: 'performance',   label: 'Performance',    icon: <BarChart3 size={16} aria-hidden />,  adminOnly: true },
      { id: 'admin',         label: 'Admin Settings', icon: <Wrench size={16} aria-hidden />,  adminOnly: true },
    ],
  },
  {
    label: 'SA — Overview',
    tabs: [
      { id: 'sa-overview',       label: 'Overview',         icon: <BarChart3 size={16} aria-hidden />,  superAdminOnly: true },
    ],
  },
  {
    label: 'SA — Users & Access',
    tabs: [
      { id: 'sa-users',          label: 'Users',            icon: <Users size={16} aria-hidden />,  superAdminOnly: true },
      { id: 'sa-feature-flags',  label: 'Feature Flags',    icon: <Flag size={16} aria-hidden />,  superAdminOnly: true },
      { id: 'sa-audit-trail',    label: 'Audit Trail',      icon: <Scroll size={16} aria-hidden />,  superAdminOnly: true },
      { id: 'sa-logs',           label: 'Logs',             icon: <ClipboardList size={16} aria-hidden />,  superAdminOnly: true },
    ],
  },
  {
    label: 'SA — Platform',
    tabs: [
      { id: 'sa-platform',       label: 'Platform',         icon: <Globe size={16} aria-hidden />,  superAdminOnly: true },
      { id: 'platform-config',   label: 'Platform Config',  icon: <Hammer size={16} aria-hidden />,  superAdminOnly: true },
      { id: 'sa-rate-limiting',  label: 'Rate Limiting',    icon: <TrafficCone size={16} aria-hidden />,  superAdminOnly: true },
      { id: 'sa-alerting',       label: 'Alerting',         icon: <Bell size={16} aria-hidden />,  superAdminOnly: true },
      { id: 'sa-whitelabel',     label: 'White Label',      icon: <Tag size={16} aria-hidden />,  superAdminOnly: true },
      { id: 'sa-reporting',      label: 'Reporting',        icon: <Files size={16} aria-hidden />,  superAdminOnly: true },
    ],
  },
  {
    label: 'SA — Trading Engine',
    tabs: [
      { id: 'sa-trading-engine', label: 'Trading Engine',   icon: <Zap size={16} aria-hidden />,  superAdminOnly: true },
      { id: 'sa-ml-ai',          label: 'ML / AI',          icon: <Brain size={16} aria-hidden />,  superAdminOnly: true },
      { id: 'sa-risk',           label: 'Risk Management',  icon: <Scale size={16} aria-hidden />,  superAdminOnly: true },
      { id: 'sa-broker-mgmt',    label: 'Broker Mgmt',      icon: <Landmark size={16} aria-hidden />,  superAdminOnly: true },
      { id: 'sa-nuclear',        label: 'Nuclear Controls', icon: <Radiation size={16} aria-hidden />,  superAdminOnly: true },
    ],
  },
  {
    label: 'SA — Finance & Compliance',
    tabs: [
      { id: 'sa-financial',      label: 'Financial',        icon: <Banknote size={16} aria-hidden />,  superAdminOnly: true },
      { id: 'sa-compliance',     label: 'Compliance',       icon: <ClipboardList size={16} aria-hidden />,  superAdminOnly: true },
      { id: 'sa-gdpr',           label: 'GDPR / Privacy',   icon: <FileLock2 size={16} aria-hidden />,  superAdminOnly: true },
    ],
  },
  {
    label: 'SA — Security & Infra',
    tabs: [
      { id: 'sa-security',       label: 'Security',         icon: <Shield size={16} aria-hidden />,  superAdminOnly: true },
      { id: 'sa-security-infra', label: 'Security Infra',   icon: <ShieldCheck size={16} aria-hidden />,  superAdminOnly: true },
      { id: 'sa-auto-healing',   label: 'Auto-Healing',     icon: <Stethoscope size={16} aria-hidden />,  superAdminOnly: true },
      { id: 'sa-system-health',  label: 'System Health',    icon: <HeartPulse size={16} aria-hidden />,  superAdminOnly: true },
      { id: 'sa-reliability',    label: 'Reliability',      icon: <Microscope size={16} aria-hidden />,  superAdminOnly: true },
    ],
  },
  {
    label: 'Danger Zone',
    tabs: [
      { id: 'danger',        label: 'Danger Zone',    icon: <AlertTriangle size={16} aria-hidden />,  danger: true },
    ],
  },
];

// ── Helpers ───────────────────────────────────────────────────────────────────

const SectionFallback: React.FC = () => (
  <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: 'var(--text-muted)', padding: '32px 0' }}>
    <div style={{
      width: 20, height: 20, border: '2px solid var(--border-strong)',
      borderTopColor: '#3b82f6', borderRadius: '50%',
      animation: 'spin 0.7s linear infinite',
    }} />
    Loading…
  </div>
);

const UpgradeNotice: React.FC<{ requiredPlan: string }> = ({ requiredPlan }) => (
  <div style={{
    padding: '48px 32px', textAlign: 'center',
    background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 14,
  }}>
    <div style={{ fontSize: 40, marginBottom: 16 }}>🔒</div>
    <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text-strong)', marginBottom: 8 }}>
      {requiredPlan.charAt(0).toUpperCase() + requiredPlan.slice(1)} Plan Required
    </div>
    <div style={{ fontSize: 14, color: 'var(--text-muted)', maxWidth: 360, margin: '0 auto 20px' }}>
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

// Plan ranking comes from lib/subscription — this file used to declare a
// second, identical copy. Two tables mean two things to keep in step, and the
// one that drifts silently gates the wrong tabs.

// ── Settings page ─────────────────────────────────────────────────────────────

const Settings: React.FC = () => {
  const navigate   = useNavigate();
  const user       = useStore(selectUser);
  const admin      = user ? isAdmin(user.role) : false;
  const superAdmin = user ? isSuperAdmin(user.role) : false;

  const storePlan  = useStore((s) => s.plan) ?? 'free';
  const plan       = superAdmin ? 'elite' : storePlan;
  const userPlanRank = planRank(plan);

  // Honour ?tab= deep links. KYCPage and MobilePage both link to
  // /settings?tab=security, and the param was ignored entirely — both landed on
  // Profile, so the "Security" shortcut went somewhere else without saying so.
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedTab = searchParams.get('tab');
  const [activeTab, setActiveTab] = useState<SettingsTab>(
    isKnownTab(requestedTab) ? requestedTab : 'profile',
  );

  // Keep the URL in step, so the tab survives a refresh or a shared link.
  const selectTab = useCallback((tab: SettingsTab) => {
    setActiveTab(tab);
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.set('tab', tab);
      return next;
    }, { replace: true });
  }, [setSearchParams]);

  // A later ?tab= change (e.g. clicking a cross-link while already on Settings)
  // must move the panel too.
  useEffect(() => {
    if (isKnownTab(requestedTab) && requestedTab !== activeTab) setActiveTab(requestedTab);
  }, [requestedTab, activeTab]);
  const [search, setSearch]       = useState('');

  const renderSection = () => {
    const gate = (minPlan: string, node: React.ReactNode) => {
      if (superAdmin || admin) return node;
      if (userPlanRank >= planRank(minPlan)) return node;
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
      // Professional operations
      case 'control-overview': case 'control-brain': case 'control-models': case 'control-agents':
      case 'control-connectors': case 'control-sandbox': case 'control-startup': case 'control-audit':
      case 'safe-supervisor': case 'safe-agents': case 'safe-models': case 'safe-integrations': case 'safe-repairs': case 'safe-chat':
        return admin ? <ProfessionalControlPlane tab={activeTab} /> : null;
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
                style={{ padding: '6px 14px', background: 'rgba(59,130,246,0.12)', border: '1px solid rgba(59,130,246,0.35)', borderRadius: 7, color: 'var(--link)', fontSize: 12, fontWeight: 700, cursor: 'pointer' }}>
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
            <div style={{ padding: '0 0 12px', position: 'sticky', top: 0, background: 'var(--surface)', zIndex: 1 }}>
              <div style={{
                display: 'flex', alignItems: 'center', gap: 6,
                background: 'var(--raised)', border: '1px solid var(--border-strong)',
                borderRadius: 8, padding: '7px 10px',
              }}>
                <span style={{ fontSize: 12, color: 'var(--text-faint)', flexShrink: 0 }}>🔍</span>
                <input aria-label="Search settings"
                  type="text"
                  placeholder="Search settings…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  style={{
                    background: 'transparent', border: 'none', outline: 'none',
                    color: 'var(--text)', fontSize: 'var(--fs-body)', width: '100%', fontFamily: 'inherit',
                  }}
                />
                {search && (
                  <button onClick={() => setSearch('')} style={{
                    background: 'transparent', border: 'none', cursor: 'pointer',
                    color: 'var(--text-muted)', fontSize: 16, padding: 0, lineHeight: 1,
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
                      onClick={() => selectTab(id)}
                      style={{
                        padding: '4px 10px',
                        background: activeTab === id ? 'rgba(59,130,246,0.15)' : 'rgba(255,255,255,0.04)',
                        border: `1px solid ${activeTab === id ? '#3b82f6' : '#1e293b'}`,
                        borderRadius: 6,
                        color: activeTab === id ? 'var(--link)' : 'var(--text-muted)',
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
                // Two independent passes: visibility, THEN the query (audit #23).
                // The role checks used to `return` outright, so the search box
                // never applied to admin or superadmin tabs — leaving it useless
                // for the only people who have 39 tabs across 11 groups.
                if (t.superAdminOnly && !superAdmin) return false;
                if (t.adminOnly && !admin)           return false;
                if (!search) return true;
                const q = search.toLowerCase();
                return t.label.toLowerCase().includes(q)
                  || (t.keywords ?? '').toLowerCase().includes(q);
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
                      ? userPlanRank < planRank(tab.minPlan)
                      : false;

                    const activeColor   = isDanger || isSA ? '#fca5a5' : '#60a5fa';
                    const inactiveColor = locked ? '#475569' : (isDanger || isSA ? '#f87171' : '#94a3b8');
                    const borderColor   = isDanger || isSA ? '#ef4444' : '#3b82f6';

                    return (
                      <button
                        key={tab.id}
                        onClick={() => selectTab(tab.id)}
                        style={{
                          ...S.tabBtn,
                          background: active ? 'var(--raised)' : 'transparent',
                          color: active ? activeColor : inactiveColor,
                          borderLeft: active ? `3px solid ${borderColor}` : '3px solid transparent',
                          fontWeight: active ? 600 : 400,
                          opacity: locked ? 0.6 : 1,
                        }}
                      >
                        <span style={S.tabIcon}>{tab.icon}</span>
                        <span style={{ flex: 1 }}>{tab.label}</span>
                        {locked && <span style={{ fontSize: 10, color: 'var(--text-faint)' }}>🔒</span>}
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
    minHeight: '100vh', background: 'var(--surface)', color: 'var(--text-strong)',
    fontFamily: 'Inter, system-ui, -apple-system, sans-serif',
    padding: '32px 24px', boxSizing: 'border-box',
  },
  header:    { maxWidth: 1400, margin: '0 auto 28px' },
  heading:   { fontSize: 'var(--fs-hero)', fontWeight: 800, color: 'var(--text-strong)', margin: 0, letterSpacing: '-0.02em' },
  subheading: { fontSize: 14, color: 'var(--text-muted)', marginTop: 6, marginBottom: 0, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' },
  saBadge:   { fontSize: 11, fontWeight: 700, padding: '2px 8px', borderRadius: 4, background: '#450a0a', color: '#fca5a5', border: '1px solid #dc2626' },
  layout:    { maxWidth: 1400, margin: '0 auto', display: 'flex', gap: 28, alignItems: 'flex-start' },
  sidebar: {
    width: 230, flexShrink: 0, background: 'var(--surface)', borderRadius: 12,
    border: '1px solid var(--border)', padding: '10px 0',
    position: 'sticky' as const, top: 24,
    maxHeight: 'calc(100vh - 48px)', overflowY: 'auto' as const,
  },
  groupLabel: {
    fontSize: 10, fontWeight: 700, color: 'var(--text-faint)',
    textTransform: 'uppercase' as const, letterSpacing: '0.08em',
    padding: '8px 16px 3px',
  },
  tabBtn: {
    display: 'flex', alignItems: 'center', gap: 8, width: '100%',
    padding: '7px 14px', border: 'none', borderLeft: '3px solid transparent',
    background: 'transparent', cursor: 'pointer', fontSize: 12,
    textAlign: 'left' as const, transition: 'background 0.15s, color 0.15s', borderRadius: 0,
  },
  tabIcon:     { fontSize: 'var(--fs-body)', flexShrink: 0, width: 16, textAlign: 'center' as const },
  adminBadge:  { fontSize: 9, fontWeight: 700, padding: '1px 4px', borderRadius: 3, background: '#1e3a5f', color: 'var(--link)', border: '1px solid #1e3a5f' },
  saBadgeSmall: { fontSize: 9, fontWeight: 700, padding: '1px 4px', borderRadius: 3, background: '#450a0a', color: '#fca5a5', border: '1px solid #dc2626' },
  content:     { flex: 1, minWidth: 0 },
};

export default Settings;
