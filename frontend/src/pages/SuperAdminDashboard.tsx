/**
 * SuperAdminDashboard.tsx
 * Master control center — superadmin only.
 *
 * Sections (23 total):
 *   Overview · Users · Platform · ML/AI · Trading Engine
 *   Financial · Security · Logs · Feature Flags
 *   Compliance · Audit Trail · GDPR
 *   Risk Management · Nuclear Controls · Broker Management
 *   White-Label · Alerting · Rate Limiting · Reporting
 *   Security Infrastructure · System Health · Auto Healing · Reliability
 *
 * Access: isSuperAdmin() only. AdminGuard is NOT sufficient.
 * Wired via /superadmin route behind SuperAdminGuard.
 */

import React, { useState, Suspense, lazy, Component, useEffect, useCallback, useRef } from 'react';
import { useStore, selectUser } from '../store';
import { isSuperAdmin } from '../lib/subscription';
import type { SuperAdminTab } from './superadmin/types';
import { SuperAdminNavContext } from './superadmin/types';
import { SAStyles, Spinner } from './superadmin/ui';
import { superadminApi } from '../hooks/useApi';

// ── Section error boundary ────────────────────────────────────────────────────

class SectionErrorBoundary extends Component<
  { children: React.ReactNode; tab: string },
  { hasError: boolean; message: string }
> {
  constructor(props: { children: React.ReactNode; tab: string }) {
    super(props);
    this.state = { hasError: false, message: '' };
  }
  static getDerivedStateFromError(err: unknown) {
    return { hasError: true, message: err instanceof Error ? err.message : String(err) };
  }
  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: '32px 0', display: 'flex', flexDirection: 'column', gap: 10 }}>
          <span style={{ color: '#f87171', fontWeight: 600 }}>
            ⚠ Section "{this.props.tab}" failed to load
          </span>
          <span style={{ color: '#64748b', fontSize: 13 }}>{this.state.message}</span>
          <button
            onClick={() => this.setState({ hasError: false, message: '' })}
            style={{ alignSelf: 'flex-start', padding: '6px 14px', background: '#1e293b',
              border: '1px solid #334155', borderRadius: 6, color: '#94a3b8',
              cursor: 'pointer', fontSize: 13 }}
          >
            Retry
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

// ── Lazy-load every section ───────────────────────────────────────────────────
const OverviewSection        = lazy(() => import('./superadmin/OverviewSection'));
const UsersSection           = lazy(() => import('./superadmin/UsersSection'));
const PlatformSection        = lazy(() => import('./superadmin/PlatformSection'));
const MLAISection            = lazy(() => import('./superadmin/MLAISection'));
const TradingEngineSection   = lazy(() => import('./superadmin/TradingEngineSection'));
const FinancialSection       = lazy(() => import('./superadmin/FinancialSection'));
const SecuritySection        = lazy(() => import('./superadmin/SecuritySection'));
const LogsSection            = lazy(() => import('./superadmin/LogsSection'));
const FeatureFlagsSection    = lazy(() => import('./superadmin/FeatureFlagsSection'));
// Institutional-grade sections
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
const AutoHealingSection        = lazy(() => import('./superadmin/AutoHealingSection'));
const SystemReliabilitySection  = lazy(() => import('./superadmin/SystemReliabilitySection'));

// ── Tab definitions ───────────────────────────────────────────────────────────

interface TabDef {
  id: SuperAdminTab;
  label: string;
  icon: string;
  description: string;
  accent: string;
  group: 'core' | 'compliance' | 'risk' | 'ops';
}

const TABS: TabDef[] = [
  // Core
  { id: 'overview',          label: 'Overview',          icon: '🌐', description: 'Platform health & KPIs',          accent: '#3b82f6',  group: 'core' },
  { id: 'users',             label: 'Users',             icon: '👥', description: 'User management & roles',         accent: '#22c55e',  group: 'core' },
  { id: 'platform',          label: 'Platform',          icon: '⚙️', description: 'Config, maintenance, banners',    accent: '#8b5cf6',  group: 'core' },
  { id: 'ml-ai',             label: 'ML / AI',           icon: '🧠', description: 'Models, RL agent, metrics',       accent: '#a78bfa',  group: 'core' },
  { id: 'trading-engine',    label: 'Trading Engine',    icon: '📈', description: 'Engine, kill switch, risk',       accent: '#ef4444',  group: 'core' },
  { id: 'financial',         label: 'Financial',         icon: '💰', description: 'Revenue, payments, refunds',      accent: '#f59e0b',  group: 'core' },
  { id: 'security',          label: 'Security',          icon: '🛡️', description: 'Events, IPs, sessions',           accent: '#dc2626',  group: 'core' },
  { id: 'logs',              label: 'Logs',              icon: '📋', description: 'System logs & log levels',        accent: '#06b6d4',  group: 'core' },
  { id: 'feature-flags',     label: 'Feature Flags',     icon: '🚩', description: 'Global flags & overrides',        accent: '#f59e0b',  group: 'core' },
  // Compliance
  { id: 'compliance',        label: 'Compliance',        icon: '⚖️', description: 'KYC, AML, sanctions, regulatory', accent: '#fbbf24',  group: 'compliance' },
  { id: 'audit-trail',       label: 'Audit Trail',       icon: '🔗', description: 'Immutable hash-chained log',      accent: '#a78bfa',  group: 'compliance' },
  { id: 'gdpr',              label: 'GDPR',              icon: '🔒', description: 'Data subject requests, erasure',  accent: '#60a5fa',  group: 'compliance' },
  // Risk
  { id: 'risk-management',   label: 'Risk',              icon: '⚡', description: 'Circuit breakers, VaR, stress',   accent: '#f97316',  group: 'risk' },
  { id: 'nuclear-controls',  label: 'Nuclear',           icon: '🛑', description: 'Emergency halt, hedge, override', accent: '#ef4444',  group: 'risk' },
  { id: 'broker-management', label: 'Brokers',           icon: '🏦', description: 'Health, TCA, routing',            accent: '#22c55e',  group: 'risk' },
  // Ops
  { id: 'whitelabel',        label: 'White-Label',       icon: '🏢', description: 'Tenants, branding, API keys',     accent: '#8b5cf6',  group: 'ops' },
  { id: 'alerting',          label: 'Alerting',          icon: '🔔', description: 'Alert rules, Prometheus',         accent: '#fbbf24',  group: 'ops' },
  { id: 'rate-limiting',     label: 'Rate Limits',       icon: '🔒', description: 'Per-endpoint throttling',         accent: '#60a5fa',  group: 'ops' },
  { id: 'reporting',         label: 'Reporting',         icon: '📊', description: 'Generate & download reports',     accent: '#22c55e',  group: 'ops' },
  { id: 'security-infra',    label: 'Sec. Infra',        icon: '🔧', description: 'SelfHealer, HSM, Antivirus',      accent: '#f97316',  group: 'ops' },
  { id: 'system-health',     label: 'System Health',     icon: '💻', description: 'Services, backups, jobs',         accent: '#06b6d4',  group: 'ops' },
  { id: 'auto-healing',      label: 'Auto Healing',      icon: '🛡️', description: 'Autonomous healing engine',       accent: '#22c55e',  group: 'ops' },
  { id: 'reliability',       label: 'Reliability',       icon: '🔬', description: 'E2E connectivity & health probes',  accent: '#06b6d4',  group: 'ops' },
];

const GROUP_LABELS: Record<string, string> = {
  core:       'Core',
  compliance: 'Compliance & Legal',
  risk:       'Risk & Trading',
  ops:        'Operations',
};

// ── Section fallback ──────────────────────────────────────────────────────────

const SectionFallback: React.FC = () => (
  <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: '#64748b', padding: '40px 0' }}>
    <Spinner size={18} />
    <span style={{ fontSize: 13 }}>Loading section…</span>
  </div>
);

// ── Engine health hook (polls /superadmin/engine/status every 20 s) ──────────

interface EngineHealth {
  running: boolean;
  kill_switch_active: boolean;
  mode: string;
  positions_open: number;
  heartbeat_ok: boolean;
}

function useEngineHealth(): EngineHealth | null {
  const [health, setHealth] = useState<EngineHealth | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const fetchHealth = useCallback(async () => {
    try {
      const res = await superadminApi.engineStatus();
      if (mountedRef.current) setHealth(res.data as EngineHealth);
    } catch {
      // non-fatal — header pill just stays stale
    }
  }, []);

  useEffect(() => { fetchHealth(); }, [fetchHealth]);

  // Poll every 20 s while tab is visible
  useEffect(() => {
    if (document.hidden) return;
    const id = setInterval(() => { if (!document.hidden) fetchHealth(); }, 20_000);
    const onVis = () => { if (!document.hidden) fetchHealth(); };
    document.addEventListener('visibilitychange', onVis);
    return () => { clearInterval(id); document.removeEventListener('visibilitychange', onVis); };
  }, [fetchHealth]);

  return health;
}

// ── Main dashboard ────────────────────────────────────────────────────────────

const SuperAdminDashboard: React.FC = () => {
  const user = useStore(selectUser);
  const [activeTab, setActiveTab] = useState<SuperAdminTab>('overview');
  const [sectionLoadedAt, setSectionLoadedAt] = useState<Date>(new Date());
  const engineHealth = useEngineHealth();

  // Reset the "loaded at" timestamp whenever the active tab changes
  useEffect(() => { setSectionLoadedAt(new Date()); }, [activeTab]);

  if (!user || !isSuperAdmin(user.role)) return null;

  const activeTabDef = TABS.find(t => t.id === activeTab) ?? TABS[0]!;

  // Stable nav context value — sections use this to switch tabs without prop-drilling
  const navCtx = { navigateTo: setActiveTab };

  const renderSection = () => {
    switch (activeTab) {
      case 'overview':          return <OverviewSection />;
      case 'users':             return <UsersSection />;
      case 'platform':          return <PlatformSection />;
      case 'ml-ai':             return <MLAISection />;
      case 'trading-engine':    return <TradingEngineSection />;
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

  // Kill-switch alert dot: show red badge on "nuclear-controls" and "trading-engine" tabs
  const killSwitchActive = engineHealth?.kill_switch_active ?? false;

  return (
    <>
      <SAStyles />

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
                <span style={{ color: '#334155', margin: '0 8px' }}>·</span>
                <span style={{ color: '#475569' }}>{TABS.length} sections</span>
              </p>
            </div>
          </div>

          {/* Right side: engine health pill + live indicator */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            {/* Engine health pill — always visible once data loads */}
            {engineHealth ? (
              <div style={{
                display: 'flex', alignItems: 'center', gap: 8,
                padding: '5px 12px', borderRadius: 20,
                background: killSwitchActive ? '#450a0a' : engineHealth.running ? '#052e16' : '#1c1f26',
                border: `1px solid ${killSwitchActive ? '#dc2626' : engineHealth.running ? '#16a34a' : '#334155'}`,
              }}>
                <span style={{
                  width: 7, height: 7, borderRadius: '50%', flexShrink: 0,
                  background: killSwitchActive ? '#ef4444' : engineHealth.running ? '#4ade80' : '#94a3b8',
                  boxShadow: engineHealth.running && !killSwitchActive ? '0 0 6px #4ade80' : undefined,
                  animation: killSwitchActive ? 'sa-pulse 1s ease-in-out infinite' : undefined,
                }} />
                <span style={{
                  fontSize: 11, fontWeight: 700,
                  color: killSwitchActive ? '#f87171' : engineHealth.running ? '#4ade80' : '#94a3b8',
                }}>
                  {killSwitchActive ? 'KILL SWITCH ON' : engineHealth.running ? 'ENGINE LIVE' : 'ENGINE STOPPED'}
                </span>
                {!killSwitchActive && (
                  <span style={{ fontSize: 11, color: '#475569' }}>
                    · {engineHealth.mode} · {engineHealth.positions_open} pos
                  </span>
                )}
              </div>
            ) : (
              <div style={{
                display: 'flex', alignItems: 'center', gap: 6,
                padding: '5px 12px', borderRadius: 20,
                background: '#0f172a', border: '1px solid #1e293b',
              }}>
                <Spinner size={10} />
                <span style={{ fontSize: 11, color: '#475569' }}>engine…</span>
              </div>
            )}

            <div style={styles.liveIndicator}>
              <span style={styles.liveDot} />
              <span style={{ fontSize: 11, color: '#4ade80', fontWeight: 600 }}>LIVE</span>
            </div>
          </div>
        </div>

        <div style={styles.layout}>
          {/* ── Sidebar nav ── */}
          <nav style={styles.sidebar}>
            {groups.map(group => (
              <div key={group}>
                <div style={styles.sidebarLabel}>{GROUP_LABELS[group]}</div>
                {TABS.filter(t => t.group === group).map(tab => {
                  const active = activeTab === tab.id;
                  // Show a red alert dot on Nuclear Controls and Trading Engine when kill switch is on
                  const hasAlert = killSwitchActive && (tab.id === 'nuclear-controls' || tab.id === 'trading-engine');
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
                      {/* Kill-switch alert badge */}
                      {hasAlert && (
                        <span style={{
                          width: 7, height: 7, borderRadius: '50%',
                          background: '#ef4444',
                          boxShadow: '0 0 5px #ef4444',
                          flexShrink: 0,
                          animation: 'sa-pulse 1.2s ease-in-out infinite',
                        }} />
                      )}
                      {/* Active tab indicator */}
                      {active && !hasAlert && (
                        <span style={{ width: 6, height: 6, borderRadius: '50%', background: tab.accent, flexShrink: 0 }} />
                      )}
                    </button>
                  );
                })}
              </div>
            ))}
          </nav>

          {/* ── Content ── */}
          <main style={styles.content}>
            {/* Section header with freshness timestamp */}
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
              {/* Data freshness timestamp */}
              <div style={{ fontSize: 11, color: '#334155', textAlign: 'right' as const }}>
                <div>Loaded</div>
                <div style={{ color: '#475569', fontVariantNumeric: 'tabular-nums' }}>
                  {sectionLoadedAt.toLocaleTimeString()}
                </div>
              </div>
            </div>

            {/* Section content */}
            <SectionErrorBoundary key={activeTab} tab={activeTabDef.label}>
              <Suspense fallback={<SectionFallback />}>
                <SuperAdminNavContext.Provider value={navCtx}>
                  <div style={{ animation: 'sa-fadein 0.2s ease' }}>
                    {renderSection()}
                  </div>
                </SuperAdminNavContext.Provider>
              </Suspense>
            </SectionErrorBoundary>
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
    maxHeight: 'calc(100vh - 80px)',
    overflowY: 'auto' as const,
  },
  sidebarLabel: {
    fontSize: 10, fontWeight: 700, color: '#334155',
    textTransform: 'uppercase' as const, letterSpacing: '0.08em',
    padding: '10px 16px 4px',
  },
  tabBtn: {
    display: 'flex', alignItems: 'center', gap: 9,
    width: '100%', padding: '8px 16px',
    border: 'none', borderLeft: '3px solid transparent',
    background: 'transparent', cursor: 'pointer',
    fontSize: 12, transition: 'background 0.12s, color 0.12s',
    borderRadius: 0,
  },
  tabIcon: {
    fontSize: 14, flexShrink: 0, width: 18, textAlign: 'center' as const,
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
