/**
 * pages/SecurityDashboard.tsx
 * Route: /security
 *
 * Full security operations centre:
 *   - KPI strip: total attacks, active lockdown, blocked IPs, pending fixes
 *   - GlobalAttackMap: world map with live attack pins
 *   - FixApprovalQueue: LLM-generated code fix review
 *   - Blocked IPs table
 *   - Critical alerts feed
 *
 * All data polled from /api/security/* (HOPEFXBrain sub-router).
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../hooks/useApi';
import { GlobalAttackMap, type AttackLog, type AttackRecord } from '../components/GlobalAttackMap';
import { FixApprovalQueue } from '../components/FixApprovalQueue';
import { MetricCard } from '../components/MetricCard';
import { PageHeader } from '../components/PageHeader';

// ── Types ─────────────────────────────────────────────────────────────────────

interface LockdownStatus {
  lockdown_active: boolean;
}

interface Alert {
  type: string;
  ip: string;
  ts: string;
}

// ── API helpers ───────────────────────────────────────────────────────────────

async function fetchAttacks(): Promise<AttackLog> {
  const { data } = await api.get<
    // Backend may return either a map (IP → record) or { events: [...], total: N }
    AttackLog | { events: Array<{ ip?: string; event_type?: string; timestamp?: string; details?: Record<string, unknown> }>; total?: number }
  >('/security/attacks');
  if (!data) return {};
  // Already a map format
  if (!('events' in data)) return data as AttackLog;
  // Convert array format → map keyed by IP
  const map: AttackLog = {};
  for (const ev of (data as { events: Array<{ ip?: string; event_type?: string; timestamp?: string; details?: Record<string, unknown> }> }).events) {
    const ip = ev.ip ?? 'unknown';
    map[ip] = {
      geo:      (ev.details?.geo as AttackRecord['geo']) ?? {},
      intent:   (ev.details?.intent as AttackRecord['intent']) ?? 'unknown',
      severity: (ev.details?.severity as number) ?? 0.5,
      time:     ev.timestamp ?? new Date().toISOString(),
      raw:      ev.event_type,
    };
  }
  return map;
}

async function fetchLockdown(): Promise<LockdownStatus> {
  const { data } = await api.get<LockdownStatus>('/security/lockdown');
  return data;
}

async function fetchBlockedIPs(): Promise<string[]> {
  const { data } = await api.get<string[] | { blocked_ips?: string[] }>('/security/blocked-ips');
  if (!data) return [];
  // Handle both plain array and { blocked_ips: [...] } shapes
  if (Array.isArray(data)) return data;
  return (data as { blocked_ips?: string[] }).blocked_ips ?? [];
}

async function fetchAlerts(): Promise<Alert[]> {
  try {
    const { data } = await api.get<Alert[] | { alerts?: Alert[] }>('/security/alerts');
    if (!data) return [];
    if (Array.isArray(data)) return data;
    return (data as { alerts?: Alert[] }).alerts ?? [];
  } catch {
    return [];
  }
}

async function clearLockdown(): Promise<void> {
  await api.post('/security/lockdown/clear');
}

// ── Component ─────────────────────────────────────────────────────────────────

const SecurityDashboard: React.FC = () => {
  const navigate = useNavigate();
  const [attacks, setAttacks] = useState<AttackLog>({});
  const [lockdown, setLockdown] = useState<LockdownStatus>({ lockdown_active: false });
  const [blockedIPs, setBlockedIPs] = useState<string[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [clearingLockdown, setClearingLockdown] = useState(false);
  const [togglingLockdown, setTogglingLockdown] = useState(false);
  const [unblockingIp, setUnblockingIp]         = useState<string | null>(null);
  const [unblockErr, setUnblockErr]             = useState<string | null>(null);

  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const loadAll = useCallback(async () => {
    try {
      const [a, l, b, al] = await Promise.all([
        fetchAttacks(),
        fetchLockdown(),
        fetchBlockedIPs(),
        fetchAlerts(),
      ]);
      if (!mountedRef.current) return;
      setAttacks(a);
      setLockdown(l);
      setBlockedIPs(b);
      setAlerts(al);
      setError(null);
    } catch (err) {
      if (!mountedRef.current) return;
      setError('Failed to load security data — backend may be offline');
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAll();
    const id = setInterval(loadAll, 15_000); // refresh every 15 s
    return () => clearInterval(id);
  }, [loadAll]);

  const handleClearLockdown = async () => {
    setClearingLockdown(true);
    try {
      await clearLockdown();
      setLockdown({ lockdown_active: false });
    } catch {
      setError('Failed to clear lockdown');
    } finally {
      setClearingLockdown(false);
    }
  };

  const handleToggleLockdown = async () => {
    setTogglingLockdown(true);
    try {
      const { adminApi } = await import('../hooks/useApi');
      await adminApi.lockdown(!lockdown.lockdown_active);
      setLockdown({ lockdown_active: !lockdown.lockdown_active });
    } catch {
      setError('Failed to toggle lockdown');
    } finally {
      setTogglingLockdown(false);
    }
  };

  const handleUnblockIp = async (ip: string) => {
    setUnblockingIp(ip);
    setUnblockErr(null);
    try {
      const { adminApi } = await import('../hooks/useApi');
      await adminApi.unblockIp(ip);
      setBlockedIPs(prev => prev.filter(b => b !== ip));
    } catch {
      setUnblockErr(`Failed to unblock ${ip}`);
    } finally {
      setUnblockingIp(null);
    }
  };

  // Derived stats
  const totalAttacks = Object.keys(attacks).length;
  const highSeverity = Object.values(attacks).filter(a => a.severity >= 0.7).length;
  const intentCounts = Object.values(attacks).reduce<Record<string, number>>((acc, a) => {
    acc[a.intent] = (acc[a.intent] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div style={pageStyle}>
      <PageHeader
        title="Security Operations"
        subtitle="HOPEFXBrain — 24/7 autonomous threat monitoring"
        actions={
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={() => navigate('/')}
              style={{ padding: '6px 14px', background: 'rgba(59,130,246,0.12)', border: '1px solid rgba(59,130,246,0.35)', borderRadius: 7, color: '#60a5fa', fontSize: 12, fontWeight: 700, cursor: 'pointer' }}>
              📊 Dashboard
            </button>
            <button onClick={() => navigate('/audit')}
              style={{ padding: '6px 14px', background: 'rgba(167,139,250,0.12)', border: '1px solid rgba(167,139,250,0.35)', borderRadius: 7, color: '#a78bfa', fontSize: 12, fontWeight: 700, cursor: 'pointer' }}>
              📋 Audit Log
            </button>
            <button onClick={() => navigate('/admin')}
              style={{ padding: '6px 14px', background: 'rgba(100,116,139,0.12)', border: '1px solid rgba(100,116,139,0.35)', borderRadius: 7, color: '#94a3b8', fontSize: 12, fontWeight: 700, cursor: 'pointer' }}>
              🛡 Admin Panel
            </button>
          </div>
        }
      />

      {/* Lockdown banner + toggle */}
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        {lockdown.lockdown_active && (
          <div style={{ ...lockdownBannerStyle, flex: 1 }}>
            <span style={{ fontWeight: 700, fontSize: 14 }}>
              ⚠ FULL LOCKDOWN ACTIVE — Trading paused, IPs blocked
            </span>
            <button style={clearBtnStyle} onClick={handleClearLockdown} disabled={clearingLockdown}>
              {clearingLockdown ? 'Clearing…' : 'Clear Lockdown'}
            </button>
          </div>
        )}
        <button
          onClick={handleToggleLockdown}
          disabled={togglingLockdown}
          style={{
            background: lockdown.lockdown_active ? '#14532d' : '#450a0a',
            border: `1px solid ${lockdown.lockdown_active ? '#166534' : '#7f1d1d'}`,
            borderRadius: 8, color: lockdown.lockdown_active ? '#4ade80' : '#f87171',
            cursor: 'pointer', fontSize: 13, fontWeight: 700, padding: '8px 18px',
            flexShrink: 0,
          }}
        >
          {togglingLockdown ? '…' : lockdown.lockdown_active ? '🔓 Disable Lockdown' : '🔒 Enable Lockdown'}
        </button>
      </div>

      {/* Error banner */}
      {error && (
        <div style={errorBannerStyle}>{error}</div>
      )}

      {/* KPI strip */}
      <div style={kpiGridStyle}>
        <MetricCard
          label="Total Threats"
          value={totalAttacks}
          delta={highSeverity > 0 ? `${highSeverity} high severity` : undefined}
          deltaPositive={false}
          icon="🌐"
          loading={loading}
        />
        <MetricCard
          label="Lockdown"
          value={lockdown.lockdown_active ? 'ACTIVE' : 'Clear'}
          delta={lockdown.lockdown_active ? 'Trading paused' : 'All systems go'}
          deltaPositive={!lockdown.lockdown_active}
          icon="🔒"
          loading={loading}
        />
        <MetricCard
          label="Blocked IPs"
          value={blockedIPs.length}
          icon="🚫"
          loading={loading}
        />
        <MetricCard
          label="Critical Alerts"
          value={alerts.length}
          delta={alerts.length > 0 ? 'Requires review' : undefined}
          deltaPositive={alerts.length === 0}
          icon="🚨"
          loading={loading}
        />
      </div>

      {/* Intent breakdown */}
      {totalAttacks > 0 && (
        <div style={intentRowStyle}>
          {Object.entries(intentCounts).map(([intent, count]) => (
            <span key={intent} style={intentChipStyle(intent)}>
              {intent}: {count}
            </span>
          ))}
        </div>
      )}

      {/* Main grid: map + fix queue */}
      <div style={mainGridStyle}>
        <div style={{ gridColumn: 'span 2' }}>
          <GlobalAttackMap attacks={attacks} loading={loading} height={400} />
        </div>
        <div style={{ gridColumn: 'span 2' }}>
          <FixApprovalQueue />
        </div>
      </div>

      {/* Bottom row: blocked IPs + alerts */}
      <div style={bottomGridStyle}>
        {/* Blocked IPs */}
        <div style={panelStyle}>
          <div style={panelHeaderStyle}>
            <span style={panelTitleStyle}>Blocked IPs</span>
            <span style={panelCountStyle}>{blockedIPs.length}</span>
          </div>
          {unblockErr && (
            <div style={{ background: '#450a0a', border: '1px solid #7f1d1d', borderRadius: 6, color: '#f87171', fontSize: 12, padding: '6px 10px', margin: '0 0 8px' }}>
              {unblockErr}
            </div>
          )}
          {blockedIPs.length === 0 ? (
            <div style={emptyStyle}>No IPs currently blocked</div>
          ) : (
            <div style={ipListStyle}>
              {blockedIPs.map(ip => (
                <div key={ip} style={{ ...ipRowStyle, justifyContent: 'space-between' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={ipTextStyle}>{ip}</span>
                    <span style={blockedBadgeStyle}>blocked</span>
                  </div>
                  <button
                    onClick={() => handleUnblockIp(ip)}
                    disabled={unblockingIp === ip}
                    style={{
                      background: 'transparent', border: '1px solid #334155',
                      borderRadius: 5, color: '#94a3b8', cursor: 'pointer',
                      fontSize: 11, padding: '2px 8px',
                    }}
                  >
                    {unblockingIp === ip ? '…' : 'Unblock'}
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Critical alerts */}
        <div style={panelStyle}>
          <div style={panelHeaderStyle}>
            <span style={panelTitleStyle}>Critical Alerts</span>
            <span style={panelCountStyle}>{alerts.length}</span>
          </div>
          {alerts.length === 0 ? (
            <div style={emptyStyle}>No critical alerts</div>
          ) : (
            <div style={ipListStyle}>
              {alerts.slice(0, 20).map((alert, i) => (
                <div key={i} style={alertRowStyle}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ color: '#ef4444', fontSize: 10 }}>⬤</span>
                    <span style={ipTextStyle}>{alert.type.toUpperCase()}</span>
                    <span style={{ color: '#94a3b8', fontSize: 11 }}>{alert.ip}</span>
                  </div>
                  <span style={timeStyle}>
                    {alert.ts ? new Date(alert.ts).toLocaleTimeString() : '—'}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

// ── Intent chip colour ────────────────────────────────────────────────────────

const INTENT_COLOUR: Record<string, string> = {
  probe: '#facc15',
  bruteforce: '#f97316',
  unknown: '#94a3b8',
  exfil: '#ef4444',
  ddos: '#dc2626',
};

function intentChipStyle(intent: string): React.CSSProperties {
  const colour = INTENT_COLOUR[intent] ?? '#94a3b8';
  return {
    background: colour + '22',
    border: `1px solid ${colour}`,
    borderRadius: 12,
    color: colour,
    fontSize: 11,
    fontWeight: 700,
    padding: '3px 10px',
    textTransform: 'capitalize',
  };
}

// ── Styles ────────────────────────────────────────────────────────────────────

const pageStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 16,
  padding: '20px 24px',
  maxWidth: 1400,
  margin: '0 auto',
};

const lockdownBannerStyle: React.CSSProperties = {
  alignItems: 'center',
  background: '#ef444422',
  border: '1px solid #ef4444',
  borderRadius: 8,
  color: '#fca5a5',
  display: 'flex',
  gap: 16,
  justifyContent: 'space-between',
  padding: '12px 16px',
};

const clearBtnStyle: React.CSSProperties = {
  background: '#ef4444',
  border: 'none',
  borderRadius: 6,
  color: '#fff',
  cursor: 'pointer',
  fontSize: 12,
  fontWeight: 700,
  padding: '6px 14px',
  flexShrink: 0,
};

const errorBannerStyle: React.CSSProperties = {
  background: '#f9731622',
  border: '1px solid #f97316',
  borderRadius: 8,
  color: '#fdba74',
  fontSize: 12,
  padding: '10px 16px',
};

const kpiGridStyle: React.CSSProperties = {
  display: 'grid',
  gap: 12,
  gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
};

const intentRowStyle: React.CSSProperties = {
  display: 'flex',
  flexWrap: 'wrap',
  gap: 8,
};

const mainGridStyle: React.CSSProperties = {
  display: 'grid',
  gap: 16,
  gridTemplateColumns: 'repeat(2, 1fr)',
};

const bottomGridStyle: React.CSSProperties = {
  display: 'grid',
  gap: 16,
  gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))',
};

const panelStyle: React.CSSProperties = {
  background: 'var(--surface, #1e293b)',
  border: '1px solid var(--border, #334155)',
  borderRadius: 10,
  display: 'flex',
  flexDirection: 'column',
  overflow: 'hidden',
};

const panelHeaderStyle: React.CSSProperties = {
  alignItems: 'center',
  borderBottom: '1px solid var(--border, #334155)',
  display: 'flex',
  justifyContent: 'space-between',
  padding: '12px 16px',
};

const panelTitleStyle: React.CSSProperties = {
  color: 'var(--text, #f1f5f9)',
  fontSize: 13,
  fontWeight: 700,
};

const panelCountStyle: React.CSSProperties = {
  background: '#334155',
  borderRadius: 10,
  color: '#94a3b8',
  fontSize: 11,
  fontWeight: 700,
  padding: '2px 8px',
};

const emptyStyle: React.CSSProperties = {
  color: '#64748b',
  fontSize: 12,
  padding: '20px 16px',
  textAlign: 'center',
};

const ipListStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  maxHeight: 280,
  overflowY: 'auto',
};

const ipRowStyle: React.CSSProperties = {
  alignItems: 'center',
  borderBottom: '1px solid #1e293b',
  display: 'flex',
  justifyContent: 'space-between',
  padding: '8px 16px',
};

const alertRowStyle: React.CSSProperties = {
  alignItems: 'center',
  borderBottom: '1px solid #1e293b',
  display: 'flex',
  justifyContent: 'space-between',
  padding: '8px 16px',
};

const ipTextStyle: React.CSSProperties = {
  color: 'var(--text, #f1f5f9)',
  fontFamily: 'monospace',
  fontSize: 12,
};

const blockedBadgeStyle: React.CSSProperties = {
  background: '#ef444422',
  border: '1px solid #ef4444',
  borderRadius: 10,
  color: '#f87171',
  fontSize: 10,
  fontWeight: 700,
  padding: '2px 7px',
};

const timeStyle: React.CSSProperties = {
  color: '#64748b',
  fontSize: 11,
  flexShrink: 0,
};

export default SecurityDashboard;
