// superadmin/SecuritySection.tsx — security events, blocked IPs, active sessions
import React, { useEffect, useState, useCallback, useRef } from 'react';
import { superadminApi } from '../../hooks/useApi';
import { usePolling } from '../../hooks/usePolling';
import { EmptyState } from '../../components/EmptyState';
import {
  SectionCard, SeverityBadge, ActionBtn, Input, Select,
  ErrorState, LoadingRows, ConfirmDialog, KpiTile,
} from './ui';
import type { SecurityEvent } from './types';
import { extractApiError } from '../../lib/utils';

interface BlockedIP { ip: string; reason: string; blocked_at: string; blocked_by: string }
interface Session   { session_id: string; user_id: string; username: string; ip: string; device: string; created_at: string; last_active: string }

const fmtDate = (iso: string) =>
  new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });

const timeAgo = (iso: string) => {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60_000);
  if (m < 1)  return 'Just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
};

const SecuritySection: React.FC = () => {
  const [events, setEvents]     = useState<SecurityEvent[]>([]);
  const [blocked, setBlocked]   = useState<BlockedIP[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState('');
  const [sevFilter, setSevFilter] = useState('');
  const [newIP, setNewIP]       = useState('');
  const [newIPReason, setNewIPReason] = useState('');
  const [busy, setBusy]         = useState<string | null>(null);
  const [msg, setMsg]           = useState('');
  const [confirm, setConfirm]   = useState<{ type: string; id: string; label: string } | null>(null);

  const mountedRef = useRef(true);
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const params: Record<string, string> = {};
      if (sevFilter) params.severity = sevFilter;
      const [evRes, blRes, seRes] = await Promise.all([
        superadminApi.securityEvents(params),
        superadminApi.blockedIPs(),
        superadminApi.activeSessions(),
      ]);
      if (!mountedRef.current) return;
      setEvents(evRes.data.events ?? evRes.data);
      setBlocked(blRes.data.blocked_ips ?? blRes.data);
      setSessions(seRes.data.sessions ?? seRes.data);
    } catch (e: unknown) {
      if (!mountedRef.current) return;
      setError(extractApiError(e, 'Failed to load security data'));
    } finally { if (mountedRef.current) setLoading(false); }
  }, [sevFilter]);

  useEffect(() => { load(); }, [load]);
  // Refresh every 15 s while the tab is active — live operational data.
  usePolling(load, 15_000);

  const blockIP = async () => {
    if (!newIP) return;
    setBusy('block-ip'); setMsg('');
    try {
      await superadminApi.blockIP(newIP, newIPReason || 'Manual block');
      setMsg(`IP ${newIP} blocked`);
      setNewIP(''); setNewIPReason('');
      load();
    } catch (e: unknown) {
      setMsg(extractApiError(e, 'Block failed'));
    } finally { setBusy(null); }
  };

  const unblockIP = async (ip: string) => {
    setBusy(`unblock-${ip}`); setMsg('');
    try {
      await superadminApi.unblockIP(ip);
      setMsg(`IP ${ip} unblocked`);
      load();
    } catch (e: unknown) {
      setMsg(extractApiError(e, 'Unblock failed'));
    } finally { setBusy(null); setConfirm(null); }
  };

  const revokeSession = async (sessionId: string) => {
    setBusy(`revoke-${sessionId}`); setMsg('');
    try {
      await superadminApi.revokeSession(sessionId);
      setMsg('Session revoked');
      load();
    } catch (e: unknown) {
      setMsg(extractApiError(e, 'Revoke failed'));
    } finally { setBusy(null); setConfirm(null); }
  };

  const revokeAllForUser = async (userId: string) => {
    setBusy(`revoke-all-${userId}`); setMsg('');
    try {
      await superadminApi.revokeAllSessions(userId);
      setMsg('All sessions revoked for user');
      load();
    } catch (e: unknown) {
      setMsg(extractApiError(e, 'Revoke failed'));
    } finally { setBusy(null); setConfirm(null); }
  };

  const criticalCount = events.filter(e => e.severity === 'critical').length;
  const highCount     = events.filter(e => e.severity === 'high').length;

  if (loading) return <><LoadingRows rows={8} /></>;
  if (error)   return <><ErrorState message={error} onRetry={load} /></>;

  return (
    <div style={{ animation: 'sa-fadein 0.2s ease' }}>


      {confirm && (
        <ConfirmDialog
          title={confirm.label}
          message={`Are you sure you want to ${confirm.label.toLowerCase()}? This action is logged.`}
          confirmLabel={confirm.label}
          variant="danger"
          onConfirm={() => {
            if (confirm.type === 'unblock')      unblockIP(confirm.id);
            if (confirm.type === 'revoke')       revokeSession(confirm.id);
            if (confirm.type === 'revoke-all')   revokeAllForUser(confirm.id);
          }}
          onCancel={() => setConfirm(null)}
        />
      )}

      {/* KPIs */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12, marginBottom: 20 }}>
        <KpiTile label="Total Events"    value={events.length}    icon="🔍" accent="#3b82f6" />
        <KpiTile label="Critical"        value={criticalCount}    icon="🚨" accent="#ef4444" />
        <KpiTile label="High Severity"   value={highCount}        icon="⚠️" accent="#f59e0b" />
        <KpiTile label="Blocked IPs"     value={blocked.length}   icon="🚫" accent="#8b5cf6" />
        <KpiTile label="Active Sessions" value={sessions.length}  icon="🔗" accent="#06b6d4" />
      </div>

      {/* Security events */}
      <SectionCard title="Security Events" icon="🛡️" accent="#ef4444"
        subtitle="Real-time threat and anomaly log"
        actions={
          <div style={{ display: 'flex', gap: 8 }}>
            <Select
              value={sevFilter}
              onChange={e => setSevFilter(e.target.value)}
              options={[
                { value: '', label: 'All Severity' },
                { value: 'critical', label: 'Critical' },
                { value: 'high',     label: 'High' },
                { value: 'medium',   label: 'Medium' },
                { value: 'low',      label: 'Low' },
              ]}
              style={{ width: 140 }}
            />
            <ActionBtn label="Refresh" onClick={load} icon="🔄" size="sm" />
          </div>
        }>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #1e293b' }}>
                {['Severity', 'Type', 'Detail', 'IP', 'User', 'Time'].map(h => (
                  <th key={h} style={{ padding: '8px 12px', textAlign: 'left', fontSize: 11, fontWeight: 600, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em', whiteSpace: 'nowrap' }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {events.slice(0, 50).map(ev => (
                <tr key={ev.event_id} className="sa-row" style={{ borderBottom: '1px solid #0f172a' }}>
                  <td style={{ padding: '10px 12px' }}><SeverityBadge severity={ev.severity} /></td>
                  <td style={{ padding: '10px 12px', color: '#94a3b8', fontSize: 12 }}>{ev.event_type}</td>
                  <td style={{ padding: '10px 12px', color: '#e2e8f0', maxWidth: 280, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{ev.detail}</td>
                  <td style={{ padding: '10px 12px', color: '#64748b', fontSize: 12, fontFamily: 'monospace' }}>{ev.ip_address}</td>
                  <td style={{ padding: '10px 12px', color: '#64748b', fontSize: 12 }}>{ev.user_id ?? '—'}</td>
                  <td style={{ padding: '10px 12px', color: '#475569', fontSize: 12 }}>{timeAgo(ev.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {events.length === 0 && (
            <EmptyState compact icon="🛡️" title="No security events found" description="Security events will appear here when threats are detected." links={[{ label: 'Security Dashboard', href: '/security', icon: '🔍' }]} />
          )}
        </div>
      </SectionCard>

      {/* Block IP */}
      <SectionCard title="IP Blocklist" icon="🚫" accent="#8b5cf6"
        subtitle={`${blocked.length} IPs currently blocked`}>
        <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap' }}>
          <Input placeholder="IP address (e.g. 1.2.3.4)" value={newIP} onChange={e => setNewIP(e.target.value)} style={{ width: 200 }} />
          <Input placeholder="Reason" value={newIPReason} onChange={e => setNewIPReason(e.target.value)} style={{ flex: 1, minWidth: 160 }} />
          <ActionBtn label="Block IP" onClick={blockIP} variant="danger" icon="🚫" loading={busy === 'block-ip'} disabled={!newIP} />
        </div>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #1e293b' }}>
                {['IP Address', 'Reason', 'Blocked By', 'Blocked At', ''].map(h => (
                  <th key={h} style={{ padding: '8px 12px', textAlign: 'left', fontSize: 11, fontWeight: 600, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {blocked.map(b => (
                <tr key={b.ip} className="sa-row" style={{ borderBottom: '1px solid #0f172a' }}>
                  <td style={{ padding: '10px 12px', fontFamily: 'monospace', color: '#f87171' }}>{b.ip}</td>
                  <td style={{ padding: '10px 12px', color: '#94a3b8' }}>{b.reason}</td>
                  <td style={{ padding: '10px 12px', color: '#64748b', fontSize: 12 }}>{b.blocked_by}</td>
                  <td style={{ padding: '10px 12px', color: '#64748b', fontSize: 12 }}>{fmtDate(b.blocked_at)}</td>
                  <td style={{ padding: '10px 12px' }}>
                    <ActionBtn
                      label="Unblock"
                      onClick={() => setConfirm({ type: 'unblock', id: b.ip, label: `Unblock ${b.ip}` })}
                      variant="success" size="sm"
                      loading={busy === `unblock-${b.ip}`}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {blocked.length === 0 && (
            <div style={{ textAlign: 'center', padding: 24, color: '#475569', fontSize: 13 }}>No IPs currently blocked.</div>
          )}
        </div>
      </SectionCard>

      {/* Active sessions */}
      <SectionCard title="Active Sessions" icon="🔗" accent="#06b6d4"
        subtitle={`${sessions.length} sessions active`}>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #1e293b' }}>
                {['User', 'IP', 'Device', 'Started', 'Last Active', ''].map(h => (
                  <th key={h} style={{ padding: '8px 12px', textAlign: 'left', fontSize: 11, fontWeight: 600, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em', whiteSpace: 'nowrap' }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sessions.map(s => (
                <tr key={s.session_id} className="sa-row" style={{ borderBottom: '1px solid #0f172a' }}>
                  <td style={{ padding: '10px 12px', fontWeight: 600, color: '#f1f5f9' }}>{s.username}</td>
                  <td style={{ padding: '10px 12px', fontFamily: 'monospace', color: '#94a3b8', fontSize: 12 }}>{s.ip}</td>
                  <td style={{ padding: '10px 12px', color: '#64748b', fontSize: 12 }}>{s.device}</td>
                  <td style={{ padding: '10px 12px', color: '#64748b', fontSize: 12 }}>{fmtDate(s.created_at)}</td>
                  <td style={{ padding: '10px 12px', color: '#64748b', fontSize: 12 }}>{timeAgo(s.last_active)}</td>
                  <td style={{ padding: '10px 12px' }}>
                    <div style={{ display: 'flex', gap: 6 }}>
                      <ActionBtn
                        label="Revoke"
                        onClick={() => setConfirm({ type: 'revoke', id: s.session_id, label: `Revoke session for ${s.username}` })}
                        variant="danger" size="sm"
                        loading={busy === `revoke-${s.session_id}`}
                      />
                      <ActionBtn
                        label="All"
                        onClick={() => setConfirm({ type: 'revoke-all', id: s.user_id, label: `Revoke all sessions for ${s.username}` })}
                        variant="ghost" size="sm"
                        loading={busy === `revoke-all-${s.user_id}`}
                      />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {sessions.length === 0 && (
            <div style={{ textAlign: 'center', padding: 24, color: '#475569', fontSize: 13 }}>No active sessions.</div>
          )}
        </div>
      </SectionCard>

      {msg && (
        <div style={{
          padding: '12px 16px', borderRadius: 8, marginTop: 4,
          background: msg.includes('failed') || msg.includes('Failed') ? '#450a0a' : '#052e16',
          color: msg.includes('failed') || msg.includes('Failed') ? '#f87171' : '#4ade80',
          fontSize: 13, fontWeight: 600,
        }}>
          {msg}
        </div>
      )}
    </div>
  );
};

export default SecuritySection;
