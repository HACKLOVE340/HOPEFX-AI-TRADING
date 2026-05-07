/**
 * Settings.tsx — Full settings hub wired to every backend endpoint.
 * Mobile-first: sidebar collapses to bottom drawer on xs/sm,
 * side-by-side layout on md+.
 */

import React, { useState, Suspense, lazy } from 'react';
import { Link } from 'react-router-dom';
import { useStore, selectUser } from '../store';
import { isAdmin, isSuperAdmin } from '../lib/subscription';
import type { SettingsTab } from './settings/types';
import { PageHeader } from '../components/PageHeader';
import { Badge } from '../components/Badge';
import { CrossLinkBar } from '../components/CrossLinkBar';

// ── Lazy sections — user-facing ───────────────────────────────────────────────
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

// ── Lazy sections — superadmin ────────────────────────────────────────────────
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

// ── Types ─────────────────────────────────────────────────────────────────────

interface TabDef {
  id: SettingsTab;
  label: string;
  icon: string;
  adminOnly?: boolean;
  superAdminOnly?: boolean;
  danger?: boolean;
  minPlan?: string;
}
interface TabGroup { label: string; tabs: TabDef[]; }

// ── Tab groups ────────────────────────────────────────────────────────────────
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
      { id: 'system', label: 'System',         icon: '⚙️', adminOnly: true },
      { id: 'admin',  label: 'Admin Settings', icon: '🔧', adminOnly: true },
    ],
  },
  {
    label: 'SA — Overview',
    tabs: [{ id: 'sa-overview', label: 'Overview', icon: '📊', superAdminOnly: true }],
  },
  {
    label: 'SA — Users & Access',
    tabs: [
      { id: 'sa-users',         label: 'Users',         icon: '👥', superAdminOnly: true },
      { id: 'sa-feature-flags', label: 'Feature Flags', icon: '🚩', superAdminOnly: true },
      { id: 'sa-audit-trail',   label: 'Audit Trail',   icon: '📜', superAdminOnly: true },
      { id: 'sa-logs',          label: 'Logs',          icon: '📋', superAdminOnly: true },
    ],
  },
  {
    label: 'SA — Platform',
    tabs: [
      { id: 'sa-platform',      label: 'Platform',       icon: '🌐', superAdminOnly: true },
      { id: 'platform-config',  label: 'Platform Config',icon: '🛠️', superAdminOnly: true },
      { id: 'sa-rate-limiting', label: 'Rate Limiting',  icon: '🚦', superAdminOnly: true },
      { id: 'sa-alerting',      label: 'Alerting',       icon: '🔔', superAdminOnly: true },
      { id: 'sa-whitelabel',    label: 'White Label',    icon: '🏷️', superAdminOnly: true },
      { id: 'sa-reporting',     label: 'Reporting',      icon: '📑', superAdminOnly: true },
    ],
  },
  {
    label: 'SA — Trading Engine',
    tabs: [
      { id: 'sa-trading-engine', label: 'Trading Engine',   icon: '⚡', superAdminOnly: true },
      { id: 'sa-ml-ai',          label: 'ML / AI',          icon: '🧠', superAdminOnly: true },
      { id: 'sa-risk',           label: 'Risk Management',  icon: '⚖️', superAdminOnly: true },
      { id: 'sa-broker-mgmt',    label: 'Broker Mgmt',      icon: '🏦', superAdminOnly: true },
      { id: 'sa-nuclear',        label: 'Nuclear Controls', icon: '☢️', superAdminOnly: true },
    ],
  },
  {
    label: 'SA — Finance & Compliance',
    tabs: [
      { id: 'sa-financial',  label: 'Financial',    icon: '💰', superAdminOnly: true },
      { id: 'sa-compliance', label: 'Compliance',   icon: '📋', superAdminOnly: true },
      { id: 'sa-gdpr',       label: 'GDPR/Privacy', icon: '🔏', superAdminOnly: true },
    ],
  },
  {
    label: 'SA — Security & Infra',
    tabs: [
      { id: 'sa-security',       label: 'Security',       icon: '🛡️', superAdminOnly: true },
      { id: 'sa-security-infra', label: 'Security Infra', icon: '🔐', superAdminOnly: true },
      { id: 'sa-auto-healing',   label: 'Auto-Healing',   icon: '🩺', superAdminOnly: true },
      { id: 'sa-system-health',  label: 'System Health',  icon: '💓', superAdminOnly: true },
      { id: 'sa-reliability',    label: 'Reliability',    icon: '🔬', superAdminOnly: true },
    ],
  },
  {
    label: 'Danger Zone',
    tabs: [{ id: 'danger', label: 'Danger Zone', icon: '⚠️', danger: true }],
  },
];

// ── Helpers ───────────────────────────────────────────────────────────────────
const PLAN_RANK: Record<string, number> = {
  free: 0, starter: 1, professional: 2, enterprise: 3, elite: 4,
};

const SectionFallback: React.FC = () => (
  <div className="flex items-center gap-3 text-slate-500 py-8">
    <div className="w-5 h-5 border-2 border-terminal-border border-t-blue-500 rounded-full animate-spin" />
    Loading…
  </div>
);

const UpgradeNotice: React.FC<{ requiredPlan: string }> = ({ requiredPlan }) => (
  <div className="text-center py-12 px-6 bg-terminal-surface border border-terminal-border rounded-xl">
    <div className="text-4xl mb-4">🔒</div>
    <div className="text-slate-100 text-lg font-bold mb-2">
      {requiredPlan.charAt(0).toUpperCase() + requiredPlan.slice(1)} Plan Required
    </div>
    <div className="text-slate-500 text-sm max-w-xs mx-auto mb-5">
      Upgrade your subscription to unlock this feature.
    </div>
    <Link
      to="/pricing"
      className="inline-block px-6 py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded-lg font-semibold text-sm no-underline transition-colors"
    >
      View Plans
    </Link>
  </div>
);

// ── Sidebar nav item ──────────────────────────────────────────────────────────
interface NavItemProps {
  tab: TabDef;
  active: boolean;
  locked: boolean;
  onClick: () => void;
}
const NavItem: React.FC<NavItemProps> = ({ tab, active, locked, onClick }) => {
  const isDanger = !!tab.danger;
  const isSA     = !!tab.superAdminOnly;
  const activeText   = isDanger || isSA ? 'text-red-300' : 'text-blue-400';
  const inactiveText = locked ? 'text-slate-600' : isDanger || isSA ? 'text-red-400' : 'text-slate-400';
  const activeBorder = isDanger || isSA ? 'border-l-red-500' : 'border-l-blue-500';

  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-2 w-full px-3 py-2 text-xs text-left transition-colors border-0 border-l-2 rounded-none cursor-pointer
        ${active
          ? `bg-terminal-raised ${activeText} ${activeBorder} font-semibold`
          : `bg-transparent ${inactiveText} border-l-transparent hover:bg-terminal-raised/50 font-normal`
        }
        ${locked ? 'opacity-50' : ''}
      `}
    >
      <span className="text-sm w-4 text-center flex-shrink-0">{tab.icon}</span>
      <span className="flex-1 truncate">{tab.label}</span>
      {locked && <span className="text-2xs text-slate-600">🔒</span>}
      {isSA && (
        <span className="text-2xs font-bold px-1 py-0.5 rounded bg-red-950 text-red-400 border border-red-900">SA</span>
      )}
      {tab.adminOnly && !isSA && (
        <span className="text-2xs font-bold px-1 py-0.5 rounded bg-blue-950 text-blue-400 border border-blue-900">ADM</span>
      )}
    </button>
  );
};

// ── Main component ────────────────────────────────────────────────────────────
const Settings: React.FC = () => {
  const user       = useStore(selectUser);
  const admin      = user ? isAdmin(user.role) : false;
  const superAdmin = user ? isSuperAdmin(user.role) : false;

  const storePlan = useStore((s) => s.plan) ?? 'free';
  const plan      = superAdmin ? 'elite' : storePlan;
  const planRank  = PLAN_RANK[plan] ?? 0;

  const [activeTab, setActiveTab]   = useState<SettingsTab>('profile');
  const [search, setSearch]         = useState('');
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  const renderSection = () => {
    const gate = (minPlan: string, node: React.ReactNode) => {
      if (superAdmin || admin) return node;
      if (planRank >= (PLAN_RANK[minPlan] ?? 0)) return node;
      return <UpgradeNotice requiredPlan={minPlan} />;
    };
    switch (activeTab) {
      case 'profile':           return <ProfileSection />;
      case 'security':          return <SecuritySection />;
      case 'billing':           return <BillingSection />;
      case 'api-keys':          return gate('professional', <ApiKeysSection />);
      case 'broker':            return <BrokerSection />;
      case 'trading':           return gate('professional', <TradingSection />);
      case 'integrations':      return gate('starter', <IntegrationsSection />);
      case 'appearance':        return <AppearanceSection />;
      case 'notifications':     return <NotificationsSection />;
      case 'accessibility':     return <AccessibilitySection />;
      case 'privacy':           return <PrivacySection />;
      case 'system':            return admin      ? <SystemSection />            : null;
      case 'admin':             return admin      ? <AdminSettingsSection />     : null;
      case 'sa-overview':       return superAdmin ? <SAOverviewSection />        : null;
      case 'sa-users':          return superAdmin ? <SAUsersSection />           : null;
      case 'sa-feature-flags':  return superAdmin ? <SAFeatureFlagsSection />    : null;
      case 'sa-audit-trail':    return superAdmin ? <SAAuditTrailSection />      : null;
      case 'sa-logs':           return superAdmin ? <SALogsSection />            : null;
      case 'sa-platform':       return superAdmin ? <SAPlatformSection />        : null;
      case 'platform-config':   return superAdmin ? <PlatformConfigSection />    : null;
      case 'sa-rate-limiting':  return superAdmin ? <SARateLimitingSection />    : null;
      case 'sa-alerting':       return superAdmin ? <SAAlertingSection />        : null;
      case 'sa-whitelabel':     return superAdmin ? <SAWhitelabelSection />      : null;
      case 'sa-reporting':      return superAdmin ? <SAReportingSection />       : null;
      case 'sa-trading-engine': return superAdmin ? <SATradingEngineSection />   : null;
      case 'sa-ml-ai':          return superAdmin ? <SAMLAISection />            : null;
      case 'sa-risk':           return superAdmin ? <SARiskSection />            : null;
      case 'sa-broker-mgmt':    return superAdmin ? <SABrokerMgmtSection />      : null;
      case 'sa-nuclear':        return superAdmin ? <SANuclearSection />         : null;
      case 'sa-financial':      return superAdmin ? <SAFinancialSection />       : null;
      case 'sa-compliance':     return superAdmin ? <SAComplianceSection />      : null;
      case 'sa-gdpr':           return superAdmin ? <SAGDPRSection />            : null;
      case 'sa-security':       return superAdmin ? <SASecuritySection />        : null;
      case 'sa-security-infra': return superAdmin ? <SASecurityInfraSection />   : null;
      case 'sa-auto-healing':   return superAdmin ? <SAAutoHealingSection />     : null;
      case 'sa-system-health':  return superAdmin ? <SASystemHealthSection />    : null;
      case 'sa-reliability':    return superAdmin ? <SystemReliabilitySection /> : null;
      case 'danger':            return <DangerSection />;
      default:                  return null;
    }
  };

  // Active tab label for mobile trigger
  const activeLabel = TAB_GROUPS.flatMap(g => g.tabs).find(t => t.id === activeTab);

  const handleTabSelect = (id: SettingsTab) => {
    setActiveTab(id);
    setMobileNavOpen(false);
  };

  const navContent = (
    <>
      {/* Search */}
      <div className="px-2 pb-3 sticky top-0 bg-terminal-bg z-10">
        <div className="flex items-center gap-2 bg-terminal-raised border border-terminal-border rounded-lg px-3 py-2">
          <span className="text-slate-500 text-xs flex-shrink-0">🔍</span>
          <input
            type="text"
            placeholder="Search settings…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="bg-transparent border-0 outline-none text-slate-200 text-xs w-full placeholder-slate-600"
          />
          {search && (
            <button
              onClick={() => setSearch('')}
              className="text-slate-500 hover:text-slate-300 bg-transparent border-0 cursor-pointer text-base leading-none p-0"
            >×</button>
          )}
        </div>
      </div>

      {/* Quick access chips */}
      {!search && (
        <div className="px-2 pb-3">
          <div className="text-2xs font-bold text-slate-600 uppercase tracking-wider px-1 pb-1">Quick Access</div>
          <div className="flex flex-wrap gap-1.5">
            {(['profile','security','broker','notifications','billing','danger'] as SettingsTab[]).map(id => {
              const t = TAB_GROUPS.flatMap(g => g.tabs).find(x => x.id === id);
              if (!t) return null;
              return (
                <button
                  key={id}
                  onClick={() => handleTabSelect(id)}
                  className={`px-2 py-1 rounded text-2xs font-semibold border cursor-pointer transition-colors ${
                    activeTab === id
                      ? 'bg-blue-500/15 border-blue-500/50 text-blue-400'
                      : 'bg-terminal-raised border-terminal-border text-slate-500 hover:text-slate-300'
                  }`}
                >
                  {t.icon} {t.label}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Tab groups */}
      {TAB_GROUPS.map((group) => {
        const visibleTabs = group.tabs.filter((tab) => {
          if (tab.superAdminOnly && !superAdmin) return false;
          if (tab.adminOnly && !admin && !superAdmin) return false;
          if (search) {
            return (
              tab.label.toLowerCase().includes(search.toLowerCase()) ||
              tab.id.toLowerCase().includes(search.toLowerCase())
            );
          }
          return true;
        });
        if (visibleTabs.length === 0) return null;
        return (
          <div key={group.label} className="mb-1">
            <div className="text-2xs font-bold text-slate-700 uppercase tracking-wider px-3 py-1.5">
              {group.label}
            </div>
            {visibleTabs.map((tab) => {
              const locked = !superAdmin && !admin && tab.minPlan
                ? planRank < (PLAN_RANK[tab.minPlan] ?? 0)
                : false;
              return (
                <NavItem
                  key={tab.id}
                  tab={tab}
                  active={activeTab === tab.id}
                  locked={locked}
                  onClick={() => handleTabSelect(tab.id)}
                />
              );
            })}
          </div>
        );
      })}
    </>
  );

  return (
    <div className="min-h-screen bg-terminal-bg text-slate-100 px-3 sm:px-6 py-4 sm:py-8">
      <div className="max-w-screen-xl mx-auto">
        <PageHeader
          title="Settings"
          icon="⚙️"
          subtitle="Manage your account, trading preferences, integrations, and platform configuration."
          breadcrumbs={[
            { label: 'Home',    href: '/dashboard' },
            { label: 'Profile', href: '/profile' },
            { label: 'Settings' },
          ]}
          badge={
            superAdmin
              ? <Badge variant="danger" className="text-2xs">SUPER ADMIN</Badge>
              : admin
              ? <Badge variant="warning" className="text-2xs">ADMIN</Badge>
              : undefined
          }
          actions={
            <div className="flex gap-2 flex-wrap">
              <Link to="/trade"
                className="px-3 py-1.5 bg-blue-500/10 border border-blue-500/30 rounded-lg text-blue-400 text-xs font-bold no-underline hover:bg-blue-500/20 transition-colors flex items-center gap-1">
                ⚡ Trade
              </Link>
              <Link to="/journal"
                className="px-3 py-1.5 bg-emerald-500/10 border border-emerald-500/30 rounded-lg text-emerald-400 text-xs font-bold no-underline hover:bg-emerald-500/20 transition-colors hidden sm:flex items-center gap-1">
                📓 Journal
              </Link>
              <Link to="/wallet"
                className="px-3 py-1.5 bg-amber-500/10 border border-amber-500/30 rounded-lg text-amber-400 text-xs font-bold no-underline hover:bg-amber-500/20 transition-colors hidden sm:flex items-center gap-1">
                💰 Wallet
              </Link>
            </div>
          }
        />

        {/* Mobile nav trigger */}
        <div className="md:hidden mb-4">
          <button
            onClick={() => setMobileNavOpen(v => !v)}
            className="w-full flex items-center justify-between px-4 py-3 bg-terminal-surface border border-terminal-border rounded-xl text-sm font-medium text-slate-200 cursor-pointer"
          >
            <span className="flex items-center gap-2">
              <span>{activeLabel?.icon}</span>
              <span>{activeLabel?.label ?? 'Settings'}</span>
            </span>
            <span className="text-slate-500 text-xs">{mobileNavOpen ? '▲' : '▼'} Menu</span>
          </button>
          {mobileNavOpen && (
            <div className="mt-1 bg-terminal-surface border border-terminal-border rounded-xl overflow-hidden max-h-[60vh] overflow-y-auto py-2">
              {navContent}
            </div>
          )}
        </div>

        {/* Desktop layout: sidebar + content */}
        <div className="flex gap-6 items-start">
          {/* Sidebar — hidden on mobile, visible md+ */}
          <nav className="hidden md:block w-56 flex-shrink-0 bg-terminal-bg border border-terminal-border rounded-xl py-2 sticky top-6 max-h-[calc(100vh-80px)] overflow-y-auto">
            {navContent}
          </nav>

          {/* Content */}
          <main className="flex-1 min-w-0">
            <Suspense fallback={<SectionFallback />}>
              <div key={activeTab} className="animate-fade-in">
                {renderSection()}
              </div>
            </Suspense>
          </main>
        </div>

        <CrossLinkBar
          title="Quick Links"
          className="mt-8"
          links={[
            { label: '📊 Dashboard', href: '/dashboard', color: '#60a5fa' },
            { label: '👤 Profile',   href: '/profile',   color: '#a78bfa' },
            { label: '🔐 2FA Setup', href: '/2fa-setup', color: '#f97316' },
            { label: '💳 Wallet',    href: '/wallet',    color: '#34d399' },
            { label: '📋 Audit Log', href: '/audit-log', color: '#94a3b8' },
          ]}
        />
      </div>
    </div>
  );
};

export default Settings;
