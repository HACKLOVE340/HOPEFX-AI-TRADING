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
import { Link } from 'react-router-dom';
import { api } from '../hooks/useApi';
import { GlobalAttackMap, type AttackLog, type AttackRecord } from '../components/GlobalAttackMap';
import { FixApprovalQueue } from '../components/FixApprovalQueue';
import { MetricCard } from '../components/MetricCard';
import { PageHeader } from '../components/PageHeader';
import { Badge } from '../components/Badge';

// ── Types ─────────────────────────────────────────────────────────────────────

interface LockdownStatus {
  lockdown_active: boolean;
}

interface Alert {
  type: string;
  ip: string;
  ts: string;
}

interface GeoInfo {
  country?: string;
  country_code?: string;
  city?: string;
  region?: string;
  org?: string;
  lat?: number;
  lon?: number;
  isp?: string;
}

interface ThreatDetail {
  ip: string;
  geo: GeoInfo;
  intent: string;
  severity: number;
  time: string;
  raw?: string;
  attack_count?: number;
}

// ── IP Geolocation API helper ─────────────────────────────────────────────────

async function fetchGeoInfo(ip: string): Promise<GeoInfo> {
  try {
    const { data } = await api.get<GeoInfo>(`/security/geo/${encodeURIComponent(ip)}`);
    return data ?? {};
  } catch {
    return {};
  }
}

async function blockIp(ip: string): Promise<void> {
  await api.post('/security/block-ip', { ip });
}

// ── Threat Drill-Down Modal ───────────────────────────────────────────────────

const ThreatModal: React.FC<{
  threat: ThreatDetail;
  onClose: () => void;
  onBlock: (ip: string) => Promise<void>;
  alreadyBlocked: boolean;
}> = ({ threat, onClose, onBlock, alreadyBlocked }) => {
  const [geo, setGeo]         = useState<GeoInfo>(threat.geo ?? {});
  const [geoLoading, setGeoLoading] = useState(false);
  const [blocking, setBlocking]     = useState(false);
  const [blocked, setBlocked]       = useState(alreadyBlocked);
  const [blockErr, setBlockErr]     = useState('');

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  useEffect(() => {
    if (threat.ip && !geo.country) {
      setGeoLoading(true);
      fetchGeoInfo(threat.ip)
        .then(g => setGeo(g))
        .finally(() => setGeoLoading(false));
    }
  }, [threat.ip]);

  const handleBlock = async () => {
    setBlocking(true); setBlockErr('');
    try {
      await onBlock(threat.ip);
      setBlocked(true);
    } catch { setBlockErr('Block failed — try again'); }
    finally { setBlocking(false); }
  };

  const severityColor = threat.severity >= 0.8 ? '#ef4444' : threat.severity >= 0.5 ? '#f59e0b' : '#22c55e';
  const flagEmoji = geo.country_code ? String.fromCodePoint(...[...geo.country_code.toUpperCase()].map(c => 0x1F1E6 + c.charCodeAt(0) - 65)) : '🌐';

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div style={{ background: '#0d1421', border: '1px solid #334155', borderRadius: 14, padding: 28, maxWidth: 580, width: '100%', boxShadow: '0 24px 64px rgba(0,0,0,0.7)' }}>
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 20 }}>
          <div>
            <div style={{ fontSize: 22, marginBottom: 4 }}>🚨</div>
            <div style={{ fontSize: 16, fontWeight: 700, color: '#f1f5f9', fontFamily: 'monospace' }}>{threat.ip}</div>
            <div style={{ fontSize: 11, color: '#475569', marginTop: 2 }}>{new Date(threat.time).toLocaleString()}</div>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#64748b', cursor: 'pointer', fontSize: 20 }}>✕</button>
        </div>

        {/* Severity bar */}
        <div style={{ marginBottom: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
            <span style={{ fontSize: 11, color: '#64748b', fontWeight: 700, textTransform: 'uppercase' }}>Severity</span>
            <span style={{ fontSize: 12, color: severityColor, fontWeight: 700 }}>{(threat.severity * 100).toFixed(0)}%</span>
          </div>
          <div style={{ height: 6, background: '#1e293b', borderRadius: 3, overflow: 'hidden' }}>
            <div style={{ height: '100%', width: `${threat.severity * 100}%`, background: severityColor, borderRadius: 3, transition: 'width 0.5s' }} />
          </div>
        </div>

        {/* Details grid */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 16 }}>
          {[
            { label: 'Intent',    value: threat.intent,                    color: '#f59e0b' },
            { label: 'Raw Event', value: threat.raw ?? '—',                color: '#94a3b8' },
            { label: 'Attacks',   value: String(threat.attack_count ?? 1), color: '#f87171' },
            { label: 'Time',      value: new Date(threat.time).toLocaleTimeString(), color: '#94a3b8' },
          ].map(({ label, value, color }) => (
            <div key={label} style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: '10px 12px' }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>{label}</div>
              <div style={{ fontSize: 13, color, fontFamily: 'monospace', textTransform: 'capitalize' }}>{value}</div>
            </div>
          ))}
        </div>

        {/* Geolocation */}
        <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: '12px 14px', marginBottom: 16 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>
            IP Geolocation {geoLoading && <span style={{ color: '#3b82f6' }}>· Loading…</span>}
          </div>
          {geo.country ? (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
              <div style={{ fontSize: 13, color: '#e2e8f0' }}>{flagEmoji} {geo.country}</div>
              <div style={{ fontSize: 12, color: '#94a3b8' }}>{geo.city}{geo.region ? `, ${geo.region}` : ''}</div>
              <div style={{ fontSize: 12, color: '#64748b', fontFamily: 'monospace' }}>{geo.org ?? geo.isp ?? '—'}</div>
              {geo.lat && geo.lon && (
                <div style={{ fontSize: 11, color: '#475569' }}>{geo.lat.toFixed(2)}, {geo.lon.toFixed(2)}</div>
              )}
            </div>
          ) : (
            <div style={{ fontSize: 12, color: '#475569' }}>{geoLoading ? 'Fetching geolocation…' : 'Geolocation unavailable'}</div>
          )}
        </div>

        {/* Actions */}
        {blockErr && <div style={{ fontSize: 12, color: '#f87171', marginBottom: 8 }}>{blockErr}</div>}
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            onClick={() => void handleBlock()}
            disabled={blocking || blocked}
            style={{
              flex: 1, padding: '9px 0', borderRadius: 8, border: 'none', cursor: blocked ? 'not-allowed' : 'pointer',
              background: blocked ? '#14532d' : '#ef4444', color: '#fff', fontSize: 13, fontWeight: 700,
              opacity: blocking ? 0.7 : 1,
            }}
          >
            {blocked ? '✓ IP Blocked' : blocking ? 'Blocking…' : '🚫 Block IP'}
          </button>
          <Link to={`/audit?ip=${threat.ip}`}
            style={{ flex: 1, textAlign: 'center', padding: '9px 0', borderRadius: 8, background: 'rgba(167,139,250,0.1)', border: '1px solid rgba(167,139,250,0.3)', color: '#a78bfa', fontSize: 13, fontWeight: 700, textDecoration: 'none' }}>
            📋 Audit Trail
          </Link>
        </div>
      </div>
    </div>
  );
};

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
  const [drillThreat, setDrillThreat]           = useState<ThreatDetail | null>(null);
  const [blockingIp, setBlockingIp]             = useState<string | null>(null);

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

  const handleBlockIp = async (ip: string): Promise<void> => {
    setBlockingIp(ip);
    try {
      await blockIp(ip);
      setBlockedIPs(prev => prev.includes(ip) ? prev : [...prev, ip]);
    } finally {
      setBlockingIp(null);
    }
  };

  const openThreatDrill = (ip: string) => {
    const record = attacks[ip];
    if (!record) return;
    setDrillThreat({
      ip,
      geo:    record.geo ?? {},
      intent: record.intent ?? 'unknown',
      severity: record.severity ?? 0.5,
      time:   record.time ?? new Date().toISOString(),
      raw:    record.raw,
    });
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
        icon="🛡️"
        subtitle="HOPEFXBrain — 24/7 autonomous threat monitoring and incident response."
        breadcrumbs={[
          { label: 'Home',        href: '/home' },
          { label: 'Admin Panel', href: '/admin' },
          { label: 'Security Operations' },
        ]}
        badge={
          lockdown.lockdown_active
            ? <Badge variant="danger" style={{ fontSize: 11 }}>⚠ LOCKDOWN</Badge>
            : highSeverity > 0
            ? <Badge variant="warning" style={{ fontSize: 11 }}>{highSeverity} High Severity</Badge>
            : <Badge variant="success" style={{ fontSize: 11 }}>● Monitoring</Badge>
        }
        actions={
          <div style={{ display: 'flex', gap: 8 }}>
            <Link to="/audit"
              style={{ padding: '6px 14px', background: 'rgba(167,139,250,0.12)', border: '1px solid rgba(167,139,250,0.35)', borderRadius: 7, color: '#a78bfa', fontSize: 12, fontWeight: 700, cursor: 'pointer', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: 4 }}>
              📋 Audit Log
            </Link>
            <Link to="/auto-heal"
              style={{ padding: '6px 14px', background: 'rgba(34,197,94,0.12)', border: '1px solid rgba(34,197,94,0.35)', borderRadius: 7, color: '#4ade80', fontSize: 12, fontWeight: 700, cursor: 'pointer', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: 4 }}>
              🩺 Auto-Heal
            </Link>
            <Link to="/admin"
              style={{ padding: '6px 14px', background: 'rgba(100,116,139,0.12)', border: '1px solid rgba(100,116,139,0.35)', borderRadius: 7, color: '#94a3b8', fontSize: 12, fontWeight: 700, cursor: 'pointer', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: 4 }}>
              🔧 Admin
            </Link>
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

      {/* Intent breakdown + clickable threat IPs */}
      {totalAttacks > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div style={intentRowStyle}>
            {Object.entries(intentCounts).map(([intent, count]) => (
              <span key={intent} style={intentChipStyle(intent)}>
                {intent}: {count}
              </span>
            ))}
          </div>
          {/* Top threats — click to drill down */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {Object.entries(attacks)
              .sort(([, a], [, b]) => b.severity - a.severity)
              .slice(0, 12)
              .map(([ip, rec]) => (
                <button key={ip} onClick={() => openThreatDrill(ip)}
                  style={{
                    background: rec.severity >= 0.8 ? 'rgba(239,68,68,0.12)' : 'rgba(245,158,11,0.1)',
                    border: `1px solid ${rec.severity >= 0.8 ? 'rgba(239,68,68,0.4)' : 'rgba(245,158,11,0.3)'}`,
                    borderRadius: 6, color: rec.severity >= 0.8 ? '#f87171' : '#fbbf24',
                    cursor: 'pointer', fontSize: 11, fontFamily: 'monospace', padding: '3px 10px',
                  }}
                  title={`${rec.intent} · severity ${(rec.severity * 100).toFixed(0)}% — click to drill down`}
                >
                  {ip}
                </button>
              ))}
          </div>
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
                <div key={i} style={{ ...alertRowStyle, cursor: 'pointer' }}
                  onClick={() => {
                    const rec = attacks[alert.ip];
                    if (rec) openThreatDrill(alert.ip);
                  }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ color: '#ef4444', fontSize: 10 }}>⬤</span>
                    <span style={ipTextStyle}>{alert.type.toUpperCase()}</span>
                    <span style={{ color: '#94a3b8', fontSize: 11 }}>{alert.ip}</span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={timeStyle}>
                      {alert.ts ? new Date(alert.ts).toLocaleTimeString() : '—'}
                    </span>
                    {!blockedIPs.includes(alert.ip) && (
                      <button
                        onClick={e => { e.stopPropagation(); void handleBlockIp(alert.ip); }}
                        disabled={blockingIp === alert.ip}
                        style={{ padding: '2px 8px', background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 4, color: '#f87171', fontSize: 10, cursor: 'pointer' }}>
                        {blockingIp === alert.ip ? '…' : '🚫 Block'}
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Threat drill-down modal */}
      {drillThreat && (
        <ThreatModal
          threat={drillThreat}
          onClose={() => setDrillThreat(null)}
          onBlock={handleBlockIp}
          alreadyBlocked={blockedIPs.includes(drillThreat.ip)}
        />
      )}

      {/* Cross-links */}
      <div style={{ borderTop: '1px solid #1e293b', paddingTop: 20, marginTop: 8 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 12 }}>
          Related
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 10 }}>
          {[
            { icon: '🔧', label: 'Admin Panel',          desc: 'Platform overview & KPIs',         to: '/admin' },
            { icon: '🔍', label: 'Audit Log',            desc: 'Full event trail with filters',    to: '/audit' },
            { icon: '🩺', label: 'Auto-Heal',            desc: 'Self-healing & fix approvals',     to: '/auto-heal' },
            { icon: '🏷️', label: 'Whitelabel Admin',     desc: 'Tenant branding & feature flags',  to: '/whitelabel' },
            { icon: '⚡', label: 'Super Admin',          desc: 'Master control panel',             to: '/superadmin' },
            { icon: '🔬', label: 'System Reliability',   desc: 'OTel tracing & self-test suite',   to: '/system-reliability' },
          ].map(({ icon, label, desc, to }) => (
            <Link
              key={to}
              to={to}
              style={{ display: 'flex', alignItems: 'center', gap: 12, background: '#0d1421', border: '1px solid #1e293b', borderRadius: 10, padding: '12px 16px', textDecoration: 'none' }}
              onMouseEnter={e => { (e.currentTarget as HTMLAnchorElement).style.borderColor = '#334155'; (e.currentTarget as HTMLAnchorElement).style.background = '#111827'; }}
              onMouseLeave={e => { (e.currentTarget as HTMLAnchorElement).style.borderColor = '#1e293b'; (e.currentTarget as HTMLAnchorElement).style.background = '#0d1421'; }}
            >
              <span style={{ fontSize: 20, flexShrink: 0 }}>{icon}</span>
              <div>
                <div style={{ fontSize: 13, fontWeight: 600, color: '#f1f5f9' }}>{label}</div>
                <div style={{ fontSize: 11, color: '#64748b', marginTop: 1 }}>{desc}</div>
              </div>
              <span style={{ marginLeft: 'auto', color: '#334155', fontSize: 16 }}>›</span>
            </Link>
          ))}
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
