/**
 * SuperAdminDashboard.tsx — Master control center (superadmin only).
 * Mobile-first: sidebar collapses to drawer on xs/sm, side-by-side on lg+.
 * 23 sections, kill-switch confirm, auto-refresh countdown.
 */

import React, { useState, Suspense, lazy, Component, useEffect, useCallback, useRef } from 'react';
import { Play, OctagonX, RefreshCw } from 'lucide-react';
import { useStore, selectUser } from '../store';
import { isSuperAdmin } from '../lib/subscription';
import VoiceTradingPanel from '../components/voice/VoiceTradingPanel';
import type { SuperAdminTab } from './superadmin/types';
import { SuperAdminNavContext } from './superadmin/types';
import { SAStyles, Spinner } from './superadmin/ui';
import { superadminApi } from '../hooks/useApi';
import { extractApiError } from '../lib/utils';
import { Breadcrumb } from '../components/Breadcrumb';
import { CrossLinkBar } from '../components/CrossLinkBar';

const OverviewSection        = lazy(() => import('./superadmin/OverviewSection'));
const UsersSection           = lazy(() => import('./superadmin/UsersSection'));
const PlatformSection        = lazy(() => import('./superadmin/PlatformSection'));
const MLAISection            = lazy(() => import('./superadmin/MLAISection'));
const TradingEngineSection   = lazy(() => import('./superadmin/TradingEngineSection'));
const FinancialSection       = lazy(() => import('./superadmin/FinancialSection'));
const SecuritySection        = lazy(() => import('./superadmin/SecuritySection'));
const LogsSection            = lazy(() => import('./superadmin/LogsSection'));
const FeatureFlagsSection    = lazy(() => import('./superadmin/FeatureFlagsSection'));
const ComplianceSection      = lazy(() => import('./superadmin/ComplianceSection'));
const RiskManagementSection  = lazy(() => import('./superadmin/RiskManagementSection'));
const BrokerManagementSection = lazy(() => import('./superadmin/BrokerManagementSection'));
const WhiteLabelSection      = lazy(() => import('./superadmin/WhiteLabelSection'));
const NuclearControlsSection = lazy(() => import('./superadmin/NuclearControlsSection'));
const GDPRSection            = lazy(() => import('./superadmin/GDPRSection'));
const RateLimitingSection    = lazy(() => import('./superadmin/RateLimitingSection'));
const AlertingSection        = lazy(() => import('./superadmin/AlertingSection'));
const ReportingSection       = lazy(() => import('./superadmin/ReportingSection'));
const SecurityInfraSection   = lazy(() => import('./superadmin/SecurityInfraSection'));
const AuditTrailSection      = lazy(() => import('./superadmin/AuditTrailSection'));
const SystemHealthSection    = lazy(() => import('./superadmin/SystemHealthSection'));
const AutoHealingSection     = lazy(() => import('./superadmin/AutoHealingSection'));
const SystemReliabilitySection = lazy(() => import('./superadmin/SystemReliabilitySection'));

const SA_CROSS_LINKS = [
  { label: 'Admin Panel',        href: '/admin',              icon: '🔧', color: '#60a5fa' },
  { label: 'Audit Log',          href: '/audit',              icon: '🔍', color: '#a78bfa' },
  { label: 'Security Dashboard', href: '/security',           icon: '🛡️', color: '#f59e0b' },
  { label: 'Auto-Heal',          href: '/auto-heal',          icon: '🩺', color: '#4ade80' },
  { label: 'Whitelabel Admin',   href: '/whitelabel',         icon: '🏷️', color: '#f97316' },
  { label: 'System Reliability', href: '/system-reliability', icon: '🔬', color: '#38bdf8' },
  { label: 'System Status',      href: '/status',             icon: '🟢', color: '#34d399' },
  { label: 'Docs',               href: '/docs',               icon: '📖', color: '#94a3b8' },
];
interface TabDef { id: SuperAdminTab; label: string; icon: string; description: string; accent: string; group: 'core'|'compliance'|'risk'|'ops'; }

/** The tab shown when `activeTab` matches nothing. Named so the fallback is not
    itself an index access (audit #38). */
const OVERVIEW_TAB: TabDef = { id: 'overview', label: 'Overview', icon: '🌐', description: 'Platform health & KPIs', accent: '#3b82f6', group: 'core' };

const TABS: TabDef[] = [
  OVERVIEW_TAB,
  { id: 'users',             label: 'Users',          icon: '👥', description: 'User management & roles',         accent: '#22c55e', group: 'core' },
  { id: 'platform',          label: 'Platform',       icon: '⚙️', description: 'Config, maintenance, banners',    accent: '#8b5cf6', group: 'core' },
  { id: 'ml-ai',             label: 'ML / AI',        icon: '🧠', description: 'Models, RL agent, metrics',       accent: '#a78bfa', group: 'core' },
  { id: 'trading-engine',    label: 'Trading Engine', icon: '📈', description: 'Engine, kill switch, risk',       accent: '#ef4444', group: 'core' },
  { id: 'financial',         label: 'Financial',      icon: '💰', description: 'Revenue, payments, refunds',      accent: '#f59e0b', group: 'core' },
  { id: 'security',          label: 'Security',       icon: '🛡️', description: 'Events, IPs, sessions',           accent: '#dc2626', group: 'core' },
  { id: 'logs',              label: 'Logs',           icon: '📋', description: 'System logs & log levels',        accent: '#06b6d4', group: 'core' },
  { id: 'feature-flags',     label: 'Feature Flags',  icon: '🚩', description: 'Global flags & overrides',        accent: '#f59e0b', group: 'core' },
  { id: 'compliance',        label: 'Compliance',     icon: '⚖️', description: 'KYC, AML, sanctions',             accent: '#fbbf24', group: 'compliance' },
  { id: 'audit-trail',       label: 'Audit Trail',    icon: '🔗', description: 'Immutable hash-chained log',      accent: '#a78bfa', group: 'compliance' },
  { id: 'gdpr',              label: 'GDPR',           icon: '🔒', description: 'Data subject requests, erasure',  accent: '#60a5fa', group: 'compliance' },
  { id: 'risk-management',   label: 'Risk',           icon: '⚡', description: 'Circuit breakers, VaR, stress',   accent: '#f97316', group: 'risk' },
  { id: 'nuclear-controls',  label: 'Nuclear',        icon: '🛑', description: 'Emergency halt, hedge, override', accent: '#ef4444', group: 'risk' },
  { id: 'broker-management', label: 'Brokers',        icon: '🏦', description: 'Health, TCA, routing',            accent: '#22c55e', group: 'risk' },
  { id: 'whitelabel',        label: 'White-Label',    icon: '🏢', description: 'Tenants, branding, API keys',     accent: '#8b5cf6', group: 'ops' },
  { id: 'alerting',          label: 'Alerting',       icon: '🔔', description: 'Alert rules, Prometheus',         accent: '#fbbf24', group: 'ops' },
  { id: 'rate-limiting',     label: 'Rate Limits',    icon: '🔒', description: 'Per-endpoint throttling',         accent: '#60a5fa', group: 'ops' },
  { id: 'reporting',         label: 'Reporting',      icon: '📊', description: 'Generate & download reports',     accent: '#22c55e', group: 'ops' },
  { id: 'security-infra',    label: 'Sec. Infra',     icon: '🔧', description: 'SelfHealer, HSM, Antivirus',      accent: '#f97316', group: 'ops' },
  { id: 'system-health',     label: 'System Health',  icon: '💻', description: 'Services, backups, jobs',         accent: '#06b6d4', group: 'ops' },
  { id: 'auto-healing',      label: 'Auto Healing',   icon: '🛡️', description: 'Autonomous healing engine',       accent: '#22c55e', group: 'ops' },
  { id: 'reliability',       label: 'Reliability',    icon: '🔬', description: 'E2E connectivity & health probes', accent: '#06b6d4', group: 'ops' },
];

const GROUP_LABELS: Record<string, string> = {
  core: 'Core', compliance: 'Compliance & Legal', risk: 'Risk & Trading', ops: 'Operations',
};

const REFRESH_INTERVAL = 30;
const KillSwitchConfirm: React.FC<{
  currentlyActive: boolean; statusUnknown?: boolean; onConfirm: () => void; onCancel: () => void;
}> = ({ currentlyActive, statusUnknown = false, onConfirm, onCancel }) => {
  const [typed, setTyped] = useState('');
  const required = currentlyActive ? 'RESUME TRADING' : 'KILL SWITCH';
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onCancel(); };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [onCancel]);
  return (
    <div className="fixed inset-0 bg-black/85 z-[2000] flex items-center justify-center p-4 sm:p-6"
      onClick={e => { if (e.target === e.currentTarget) onCancel(); }}>
      <div className={`bg-[#0d1421] border-2 rounded-xl p-6 sm:p-8 w-full max-w-sm shadow-2xl ${
        currentlyActive ? 'border-green-500' : 'border-red-500'
      }`}>
        <div className="text-4xl text-center mb-3">{currentlyActive ? '🔓' : '🛑'}</div>
        <div className={`text-lg font-black text-center mb-2 ${currentlyActive ? 'text-green-400' : 'text-red-400'}`}>
          {currentlyActive ? 'Resume Trading?' : 'Activate Kill Switch?'}
        </div>
        <div className="text-slate-400 text-xs text-center leading-relaxed mb-5">
          {currentlyActive
            ? 'This will re-enable the trading engine and allow new positions to be opened.'
            : 'This will immediately halt all trading activity, close open positions, and block new orders.'}
        </div>
        {statusUnknown && (
          <div className="bg-amber-950/50 border border-amber-700 rounded-lg px-3 py-2 mb-4 text-amber-300 text-xs leading-relaxed" role="alert">
            The engine status could not be read, so the current kill-switch state is unknown. This
            action will <strong>halt</strong> trading — the safe direction. Resume is unavailable until
            status can be confirmed.
          </div>
        )}
        <div className="bg-terminal-bg border border-terminal-border rounded-lg px-3 py-3 mb-4">
          <div className="text-slate-500 text-xs mb-2">
            Type <strong className={`font-mono ${currentlyActive ? 'text-green-400' : 'text-red-400'}`}>{required}</strong> to confirm:
          </div>
          <input
            autoFocus
            value={typed}
            onChange={e => setTyped(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && typed === required) onConfirm(); }}
            className="w-full bg-transparent border-0 outline-none text-slate-100 font-mono text-sm"
            placeholder={required}
          />
        </div>
        <div className="flex gap-2">
          <button onClick={onCancel}
            className="flex-1 py-2.5 bg-terminal-raised border border-terminal-border rounded-lg text-slate-400 text-sm font-semibold cursor-pointer hover:border-slate-500 transition-colors">
            Cancel
          </button>
          <button onClick={onConfirm} disabled={typed !== required}
            className={`flex-1 py-2.5 rounded-lg border-0 text-sm font-bold cursor-pointer transition-colors disabled:cursor-not-allowed ${
              typed === required
                ? currentlyActive ? 'bg-green-700 hover:bg-green-600 text-white' : 'bg-red-700 hover:bg-red-600 text-white'
                : 'bg-terminal-raised text-slate-600'
            }`}>
            {currentlyActive ? '▶ Resume Trading' : '🛑 Activate Kill Switch'}
          </button>
        </div>
      </div>
    </div>
  );
};
class SectionErrorBoundary extends Component<
  { children: React.ReactNode; tab: string },
  { hasError: boolean; message: string }
> {
  constructor(props: { children: React.ReactNode; tab: string }) {
    super(props);
    this.state = { hasError: false, message: '' };
  }
  static getDerivedStateFromError(err: unknown) {
    return { hasError: true, message: extractApiError(err, 'An error occurred') };
  }
  render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col gap-3 py-10">
          <span className="text-red-400 font-semibold text-sm">⚠ Section "{this.props.tab}" failed to load</span>
          <span className="text-slate-500 text-xs">{this.state.message}</span>
          <button onClick={() => this.setState({ hasError: false, message: '' })}
            className="self-start px-4 py-2 bg-terminal-raised border border-terminal-border rounded-lg text-slate-400 text-xs cursor-pointer hover:border-slate-500 transition-colors">
            Retry
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

const SectionFallback: React.FC = () => (
  <div className="flex items-center gap-3 text-slate-500 py-10">
    <Spinner size={18} />
    <span className="text-sm">Loading section…</span>
  </div>
);
interface EngineHealth {
  running: boolean; kill_switch_active: boolean;
  mode: string; positions_open: number; heartbeat_ok: boolean;
}

/**
 * Engine health for the header badge.
 *
 * The badge drives an operator's mental model of whether the engine is running
 * and whether the kill switch is on, so a failed poll must never keep rendering
 * as a confirmed green state. We expose the fetch error and the timestamp of the
 * last *successful* read, and the badge degrades to "unconfirmed" on failure.
 */
function useEngineHealth(): {
  health: EngineHealth | null; error: string; okAt: number | null; refresh: () => Promise<void>;
} {
  const [health, setHealth] = useState<EngineHealth | null>(null);
  const [error, setError] = useState('');
  const [okAt, setOkAt] = useState<number | null>(null);
  const mountedRef = useRef(true);
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);
  const fetchHealth = useCallback(async () => {
    try {
      const res = await superadminApi.engineStatus();
      if (!mountedRef.current) return;
      setHealth(res.data as EngineHealth);
      setOkAt(Date.now());
      setError('');
    } catch (e) {
      if (mountedRef.current) setError(extractApiError(e, 'Engine status unreachable'));
    }
  }, []);
  useEffect(() => { fetchHealth(); }, [fetchHealth]);
  useEffect(() => {
    if (document.hidden) return;
    const id = setInterval(() => { if (!document.hidden) fetchHealth(); }, 20_000);
    const onVis = () => { if (!document.hidden) fetchHealth(); };
    document.addEventListener('visibilitychange', onVis);
    return () => { clearInterval(id); document.removeEventListener('visibilitychange', onVis); };
  }, [fetchHealth]);
  return { health, error, okAt, refresh: fetchHealth };
}
const SuperAdminDashboard: React.FC = () => {
  const user = useStore(selectUser);
  const [activeTab, setActiveTab]         = useState<SuperAdminTab>('overview');
  const [sectionLoadedAt, setSectionLoadedAt] = useState<Date>(new Date());
  const [refreshKey, setRefreshKey]       = useState(0);
  const [countdown, setCountdown]         = useState(REFRESH_INTERVAL);
  const [autoRefresh, setAutoRefresh]     = useState(true);
  const [showKillConfirm, setShowKillConfirm] = useState(false);
  const [togglingKill, setTogglingKill]   = useState(false);
  const [killErr, setKillErr]             = useState('');
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const {
    health: engineHealth,
    error: engineHealthErr,
    okAt: engineHealthOkAt,
    refresh: refreshEngineHealth,
  } = useEngineHealth();
  // "Confirmed" means the most recent poll succeeded. Anything else is unknown,
  // not "off".
  const engineStatusConfirmed = engineHealth != null && !engineHealthErr;

  useEffect(() => { setSectionLoadedAt(new Date()); setCountdown(REFRESH_INTERVAL); }, [activeTab]);

  useEffect(() => {
    if (!autoRefresh) return;
    const id = setInterval(() => {
      setCountdown(c => {
        if (c <= 1) { setRefreshKey(k => k + 1); setSectionLoadedAt(new Date()); return REFRESH_INTERVAL; }
        return c - 1;
      });
    }, 1000);
    return () => clearInterval(id);
  }, [autoRefresh]);

  const handleKillSwitch = async () => {
    setTogglingKill(true); setKillErr('');
    try {
      // Resume only on a *confirmed* active kill switch. If the last status read
      // failed we do not know the current state, and the safe direction under
      // uncertainty is always to halt — never to resume trading on a stale read.
      if (engineStatusConfirmed && engineHealth?.kill_switch_active) {
        await superadminApi.resumeTrading?.();
      } else {
        await superadminApi.killSwitch?.(true);
      }
      setShowKillConfirm(false);
      await refreshEngineHealth();
    } catch (e) { setKillErr(extractApiError(e, 'Kill switch toggle failed')); }
    finally { setTogglingKill(false); }
  };

  if (!user) {
    // Still resolving user from store — show spinner instead of blank
    return (
      <div style={{ minHeight: '60vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ width: 32, height: 32, borderRadius: '50%', border: '3px solid #1e293b', borderTopColor: '#3b82f6', animation: 'spin 0.7s linear infinite' }} />
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      </div>
    );
  }
  if (!isSuperAdmin(user.role)) return null;

  const activeTabDef = TABS.find(t => t.id === activeTab) ?? OVERVIEW_TAB;
  const killSwitchActive = engineStatusConfirmed && (engineHealth?.kill_switch_active ?? false);
  const navCtx = { navigateTo: setActiveTab };

  const renderSection = () => {
    switch (activeTab) {
      case 'overview':          return <OverviewSection />;
      case 'users':             return <UsersSection />;
      case 'platform':          return <PlatformSection />;
      case 'ml-ai':             return <MLAISection />;
      case 'trading-engine':    return <><VoiceTradingPanel /><TradingEngineSection /></>;
      case 'financial':         return <FinancialSection />;
      case 'security':          return <SecuritySection />;
      case 'logs':              return <LogsSection />;
      case 'feature-flags':     return <FeatureFlagsSection />;
      case 'compliance':        return <ComplianceSection />;
      case 'risk-management':   return <RiskManagementSection />;
      case 'broker-management': return <BrokerManagementSection />;
      case 'whitelabel':        return <WhiteLabelSection />;
      case 'nuclear-controls':  return <NuclearControlsSection />;
      case 'gdpr':              return <GDPRSection />;
      case 'rate-limiting':     return <RateLimitingSection />;
      case 'alerting':          return <AlertingSection />;
      case 'reporting':         return <ReportingSection />;
      case 'security-infra':    return <SecurityInfraSection />;
      case 'audit-trail':       return <AuditTrailSection />;
      case 'system-health':     return <SystemHealthSection />;
      case 'auto-healing':      return <AutoHealingSection />;
      case 'reliability':       return <SystemReliabilitySection />;
      default:                  return null;
    }
  };

  const groups = ['core', 'compliance', 'risk', 'ops'] as const;

  // Sidebar nav content — shared between desktop sidebar and mobile drawer
  const navContent = (
    <div className="py-2">
      {groups.map(group => (
        <div key={group}>
          <div className="text-2xs font-bold text-slate-700 uppercase tracking-wider px-4 py-2">
            {GROUP_LABELS[group]}
          </div>
          {TABS.filter(t => t.group === group).map(tab => {
            const active = activeTab === tab.id;
            const hasAlert = killSwitchActive && (tab.id === 'nuclear-controls' || tab.id === 'trading-engine');
            return (
              <button
                key={tab.id}
                onClick={() => { setActiveTab(tab.id); setMobileNavOpen(false); }}
                title={tab.description}
                // This is the section navigation: 24 buttons that were ~28px
                // tall with no focus ring (rubric: touch-target-size CRITICAL,
                // focus-states HIGH). `aria-current` tells assistive tech which
                // section is open, which the colour alone did not.
                aria-current={active ? 'page' : undefined}
                className={`flex min-h-[44px] items-center gap-2 w-full px-4 text-xs border-0 border-l-2 cursor-pointer transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-sky-500 ${
                  active
                    ? 'text-slate-100 font-semibold bg-blue-950/30'
                    : 'text-slate-500 font-normal bg-transparent hover:bg-terminal-raised/50 hover:text-slate-300'
                }`}
                style={{ borderLeft: `2px solid ${active ? tab.accent : 'transparent'}` }}
              >
                <span className="text-sm w-4 text-center flex-shrink-0">{tab.icon}</span>
                <span className="flex-1 text-left truncate">{tab.label}</span>
                {hasAlert && (
                  <span className="w-2 h-2 rounded-full bg-red-500 flex-shrink-0 animate-pulse" />
                )}
                {active && !hasAlert && (
                  <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: tab.accent }} />
                )}
              </button>
            );
          })}
        </div>
      ))}
    </div>
  );

  return (
    <>
      <SAStyles />
      {showKillConfirm && (
        <KillSwitchConfirm
          currentlyActive={killSwitchActive}
          statusUnknown={!engineStatusConfirmed}
          onConfirm={() => void handleKillSwitch()}
          onCancel={() => setShowKillConfirm(false)}
        />
      )}

      <div className="page-content">

          {/* Breadcrumbs */}
          <div className="mb-3">
            <Breadcrumb items={[
              { label: 'Home',        href: '/home' },
              { label: 'Admin Panel', href: '/admin' },
              { label: 'Super Admin' },
            ]} />
          </div>

          {/* Page header card */}
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 bg-[#0a1628] border border-[#1e293b] border-t-2 border-t-red-600 rounded-xl p-4 sm:p-5 mb-5">
            {/* Left: icon + title */}
            <div className="flex items-center gap-3">
              <div className="w-12 h-12 rounded-xl flex items-center justify-center text-2xl flex-shrink-0"
                style={{ background: 'linear-gradient(135deg,#450a0a,#7f1d1d)', border: '2px solid #dc2626' }}>
                ⚡
              </div>
              <div>
                <div className="flex items-center gap-2 flex-wrap">
                  <h1 className="text-slate-100 text-lg sm:text-xl font-black m-0 tracking-tight">Super Admin</h1>
                  <span className="text-2xs font-black px-2 py-0.5 rounded bg-red-950 border border-red-700 text-red-300 tracking-widest">
                    MASTER CONTROL
                  </span>
                </div>
                <p className="text-slate-500 text-xs mt-0.5 m-0">
                  Full platform control · <strong className="text-red-300">{user.username}</strong>
                  <span className="text-slate-700 mx-2">·</span>
                  <span>{TABS.length} sections</span>
                </p>
              </div>
            </div>

            {/* Right: engine health + live indicator */}
            <div className="flex items-center gap-2 flex-wrap">
              {engineHealth && !engineHealthErr ? (
                <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full border text-xs ${
                  killSwitchActive
                    ? 'bg-red-950/60 border-red-700'
                    : engineHealth.running
                    ? 'bg-green-950/60 border-green-700'
                    : 'bg-terminal-raised border-terminal-border'
                }`}>
                  <span className={`w-2 h-2 rounded-full flex-shrink-0 ${
                    killSwitchActive ? 'bg-red-500 animate-pulse' : engineHealth.running ? 'bg-green-400' : 'bg-slate-500'
                  }`} />
                  <span className={`font-bold ${
                    killSwitchActive ? 'text-red-400' : engineHealth.running ? 'text-green-400' : 'text-slate-400'
                  }`}>
                    {killSwitchActive ? 'KILL SWITCH ON' : engineHealth.running ? 'ENGINE LIVE' : 'ENGINE STOPPED'}
                  </span>
                  {!killSwitchActive && (
                    <span className="text-slate-500 hidden sm:inline">
                      · {engineHealth.mode} · {engineHealth.positions_open} pos
                    </span>
                  )}
                </div>
              ) : engineHealthErr ? (
                /* Never show a confirmed-looking state we could not confirm. */
                <div
                  className="flex items-center gap-2 px-3 py-1.5 rounded-full border border-amber-700 bg-amber-950/60 text-xs"
                  role="alert"
                  title={engineHealthErr}
                >
                  <span className="w-2 h-2 rounded-full flex-shrink-0 bg-amber-400 animate-pulse" />
                  <span className="font-bold text-amber-300">ENGINE STATUS UNKNOWN</span>
                  <span className="text-amber-500/80 hidden sm:inline">
                    · {engineHealthOkAt
                      ? `last confirmed ${new Date(engineHealthOkAt).toLocaleTimeString()}`
                      : 'never reached'}
                  </span>
                </div>
              ) : (
                <div className="flex items-center gap-2 px-3 py-1.5 rounded-full border border-terminal-border bg-terminal-raised text-xs text-slate-500">
                  <Spinner size={10} /> engine…
                </div>
              )}
              <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-green-950/60 border border-green-700">
                <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
                <span className="text-green-400 text-2xs font-bold">LIVE</span>
              </div>
            </div>
          </div>

          {/* Mobile nav trigger */}
          <div className="lg:hidden mb-4">
            <button
              onClick={() => setMobileNavOpen(v => !v)}
              className="w-full flex items-center justify-between px-4 py-3 bg-[#0a1628] border border-[#1e293b] rounded-xl text-sm font-medium text-slate-200 cursor-pointer"
            >
              <span className="flex items-center gap-2">
                <span>{activeTabDef.icon}</span>
                <span>{activeTabDef.label}</span>
              </span>
              <span className="text-slate-500 text-xs">{mobileNavOpen ? '▲' : '▼'} {TABS.length} sections</span>
            </button>
            {mobileNavOpen && (
              <div className="mt-1 bg-[#0a1628] border border-[#1e293b] rounded-xl overflow-hidden max-h-[60vh] overflow-y-auto">
                {navContent}
              </div>
            )}
          </div>

          {/* Desktop layout: sidebar + content */}
          <div className="flex gap-5 items-start">
            {/* Sidebar — hidden on mobile, visible lg+ */}
            <nav className="hidden lg:block w-52 flex-shrink-0 bg-[#0a1628] border border-[#1e293b] rounded-xl sticky top-6 max-h-[calc(100vh-80px)] overflow-y-auto">
              {navContent}
            </nav>

            {/* Content area */}
            <main className="flex-1 min-w-0">
              {/* Section header */}
              <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 bg-[#0a1628] border border-[#1e293b] rounded-xl px-4 py-3 mb-4">
                <div className="flex items-center gap-3">
                  <div className="w-9 h-9 rounded-lg flex items-center justify-center text-lg flex-shrink-0"
                    style={{ background: `${activeTabDef.accent}22`, border: `1px solid ${activeTabDef.accent}44` }}>
                    {activeTabDef.icon}
                  </div>
                  <div>
                    <div className="text-slate-100 text-sm sm:text-base font-bold">{activeTabDef.label}</div>
                    <div className="text-slate-500 text-xs">{activeTabDef.description}</div>
                  </div>
                </div>

                {/* Controls: kill switch + auto-refresh */}
                <div className="flex items-center gap-2 flex-wrap">
                  <button
                    onClick={() => setShowKillConfirm(true)}
                    disabled={togglingKill}
                    // The emergency stop was a ~24px target with an emoji
                    // label. It is the single control that must never be
                    // mis-tapped or ambiguous.
                    aria-label={killSwitchActive
                      ? 'Resume trading — the kill switch is currently active'
                      : 'Activate the kill switch and halt all trading'}
                    className={`inline-flex min-h-[44px] items-center gap-1.5 px-3.5 rounded-lg border-0 text-2xs font-bold cursor-pointer transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-[#080c14] ${
                      killSwitchActive
                        ? 'bg-green-950 text-green-400 hover:bg-green-900 focus-visible:ring-green-500'
                        : 'bg-red-950 text-red-400 hover:bg-red-900 focus-visible:ring-red-500'
                    }`}
                  >
                    {killSwitchActive
                      ? <><Play size={13} strokeWidth={2.5} aria-hidden /> Resume</>
                      : <><OctagonX size={13} strokeWidth={2.5} aria-hidden /> Kill switch</>}
                  </button>
                  {killErr && <span className="text-red-400 text-2xs">{killErr}</span>}

                  <div className="flex items-center gap-1.5 bg-terminal-bg border border-terminal-border rounded-lg px-2.5 py-1.5">
                    <label className="flex items-center gap-1.5 cursor-pointer">
                      <input type="checkbox" checked={autoRefresh} onChange={e => setAutoRefresh(e.target.checked)}
                        className="w-3 h-3 accent-blue-500" />
                      <span className="text-slate-500 text-2xs">Auto</span>
                    </label>
                    {autoRefresh && (
                      <span className="text-slate-600 text-2xs font-mono min-w-[20px]">{countdown}s</span>
                    )}
                    <button
                      onClick={() => { setRefreshKey(k => k + 1); setSectionLoadedAt(new Date()); setCountdown(REFRESH_INTERVAL); }}
                      className="inline-flex min-h-[44px] min-w-[44px] items-center justify-center text-slate-500 hover:text-slate-300 bg-transparent border-0 cursor-pointer transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
                      title="Refresh now"
                      aria-label="Refresh this section now"
                    ><RefreshCw size={14} strokeWidth={2} aria-hidden /></button>
                  </div>

                  <span className="text-slate-700 text-2xs font-mono hidden sm:block">
                    {sectionLoadedAt.toLocaleTimeString()}
                  </span>
                </div>
              </div>

              {/* Section content */}
              <SectionErrorBoundary key={`${activeTab}-${refreshKey}`} tab={activeTabDef.label}>
                <Suspense fallback={<SectionFallback />}>
                  <SuperAdminNavContext.Provider value={navCtx}>
                    <div className="animate-fade-in">
                      {renderSection()}
                    </div>
                  </SuperAdminNavContext.Provider>
                </Suspense>
              </SectionErrorBoundary>
            </main>
          </div>

          {/* Cross-links */}
          <CrossLinkBar links={SA_CROSS_LINKS} title="Platform Sections" className="mt-6" />
      </div>
    </>
  );
};

export default SuperAdminDashboard;
