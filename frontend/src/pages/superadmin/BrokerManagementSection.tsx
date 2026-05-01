// superadmin/BrokerManagementSection.tsx
// Broker health, TCA, execution quality, routing controls
import React, { useEffect, useState, useCallback, useRef } from 'react';
import { superadminApi } from '../../hooks/useApi';
import { usePolling } from '../../hooks/usePolling';
import {
  SectionCard, StatusBadge, ActionBtn, KpiTile,
  ErrorState, LoadingRows,
} from './ui';
import type { BrokerHealth, TCAMetric } from './types';

const fmtDate = (iso: string) =>
  new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });

const LatencyBar: React.FC<{ ms: number; max?: number }> = ({ ms, max = 500 }) => {
  const pct   = Math.min((ms / max) * 100, 100);
  const color = ms < 50 ? '#4ade80' : ms < 150 ? '#fbbf24' : '#f87171';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{ flex: 1, height: 5, background: '#1e293b', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${pct}%`, background: color, borderRadius: 3, transition: 'width 0.5s' }} />
      </div>
      <span style={{ fontSize: 12, fontWeight: 700, color, minWidth: 50 }}>{ms}ms</span>
    </div>
  );
};

const FillRateBar: React.FC<{ pct: number }> = ({ pct }) => {
  const color = pct >= 98 ? '#4ade80' : pct >= 90 ? '#fbbf24' : '#f87171';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{ flex: 1, height: 5, background: '#1e293b', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${pct}%`, background: color, borderRadius: 3 }} />
      </div>
      <span style={{ fontSize: 12, fontWeight: 700, color, minWidth: 40 }}>{pct.toFixed(1)}%</span>
    </div>
  );
};

interface RoutingRule {
  broker_id: string;
  symbol_pattern: string;
  weight: number;
  active: boolean;
}

const BrokerManagementSection: React.FC = () => {
  const [brokers, setBrokers]   = useState<BrokerHealth[]>([]);
  const [tca, setTca]           = useState<TCAMetric[]>([]);
  const [routing, setRouting]   = useState<RoutingRule[]>([]);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState('');
  const [busy, setBusy]         = useState<string | null>(null);
  const [msg, setMsg]           = useState('');
  const [editRouting, setEditRouting] = useState(false);
  const [routingDraft, setRoutingDraft] = useState<RoutingRule[]>([]);

  const mountedRef = useRef(true);
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [bRes, tRes, rRes] = await Promise.all([
        superadminApi.brokerHealth(),
        superadminApi.tcaMetrics(),
        superadminApi.brokerRouting(),
      ]);
      if (!mountedRef.current) return;
      setBrokers(bRes.data.brokers ?? bRes.data);
      setTca(tRes.data.metrics ?? tRes.data);
      setRouting(rRes.data.rules ?? rRes.data ?? []);
    } catch (e: unknown) {
      if (!mountedRef.current) return;
      setError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to load broker data');
    } finally { if (mountedRef.current) setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);
  // Refresh every 15 s while the tab is active — live operational data.
  usePolling(load, 15_000);

  const reconnect = async (brokerId: string) => {
    setBusy(`reconnect-${brokerId}`); setMsg('');
    try {
      await superadminApi.reconnectBroker(brokerId);
      setMsg(`Reconnect triggered for broker ${brokerId}`);
      setTimeout(load, 2000);
    } catch (e: unknown) {
      setMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Reconnect failed');
    } finally { setBusy(null); }
  };

  const disconnect = async (brokerId: string) => {
    setBusy(`disconnect-${brokerId}`); setMsg('');
    try {
      await superadminApi.disconnectBroker(brokerId);
      setMsg(`Broker ${brokerId} disconnected`);
      setTimeout(load, 1500);
    } catch (e: unknown) {
      setMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Disconnect failed');
    } finally { setBusy(null); }
  };

  const saveRouting = async () => {
    setBusy('routing'); setMsg('');
    try {
      await superadminApi.updateBrokerRouting({ rules: routingDraft });
      setRouting(routingDraft);
      setEditRouting(false);
      setMsg('Routing configuration saved');
    } catch (e: unknown) {
      setMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Save routing failed');
    } finally { setBusy(null); }
  };

  const connectedCount    = brokers.filter(b => b.status === 'connected').length;
  const degradedCount     = brokers.filter(b => b.status === 'degraded').length;
  const disconnectedCount = brokers.filter(b => b.status === 'disconnected').length;
  const avgLatency        = brokers.length ? Math.round(brokers.reduce((s, b) => s + b.latency_ms, 0) / brokers.length) : 0;

  if (loading) return <><LoadingRows rows={6} /></>;
  if (error)   return <><ErrorState message={error} onRetry={load} /></>;

  return (
    <div style={{ animation: 'sa-fadein 0.2s ease' }}>


      {/* KPIs */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12, marginBottom: 20 }}>
        <KpiTile label="Connected"    value={connectedCount}    icon="🟢" accent="#22c55e" />
        <KpiTile label="Degraded"     value={degradedCount}     icon="🟡" accent="#f59e0b" />
        <KpiTile label="Disconnected" value={disconnectedCount} icon="🔴" accent="#ef4444" />
        <KpiTile label="Avg Latency"  value={`${avgLatency}ms`} icon="⚡" accent="#3b82f6" />
      </div>

      {/* Broker health cards */}
      <SectionCard title="Broker Connections" icon="🏦" accent="#3b82f6"
        subtitle="Real-time connection health per broker"
        actions={<ActionBtn label="Refresh" onClick={load} icon="🔄" size="sm" />}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 14 }}>
          {brokers.map(b => (
            <div key={b.broker_id} style={{
              background: '#1e293b', borderRadius: 12, padding: '16px 18px',
              border: `1px solid ${b.status === 'connected' ? '#16a34a33' : b.status === 'degraded' ? '#d9770633' : '#dc262633'}`,
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                <div>
                  <div style={{ fontSize: 14, fontWeight: 700, color: '#f1f5f9' }}>{b.name}</div>
                  <div style={{ fontSize: 11, color: '#475569' }}>{b.type} · {b.broker_id}</div>
                </div>
                <StatusBadge status={b.status} size="sm" />
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 12 }}>
                <div>
                  <div style={{ fontSize: 11, color: '#64748b', marginBottom: 3 }}>Latency</div>
                  <LatencyBar ms={b.latency_ms} />
                </div>
                <div>
                  <div style={{ fontSize: 11, color: '#64748b', marginBottom: 3 }}>Fill Rate</div>
                  <FillRateBar pct={b.fill_rate_pct} />
                </div>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 6, marginBottom: 12 }}>
                {[
                  { label: 'Slippage',    value: `${b.slippage_avg_pips.toFixed(1)} pips` },
                  { label: 'Orders Today', value: b.orders_today.toLocaleString() },
                  { label: 'Uptime',      value: `${b.uptime_pct.toFixed(1)}%` },
                ].map(m => (
                  <div key={m.label} style={{ background: '#0f172a', borderRadius: 6, padding: '6px 8px' }}>
                    <div style={{ fontSize: 10, color: '#475569' }}>{m.label}</div>
                    <div style={{ fontSize: 12, fontWeight: 600, color: '#94a3b8' }}>{m.value}</div>
                  </div>
                ))}
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: 11, color: '#334155' }}>Last heartbeat: {fmtDate(b.last_heartbeat)}</span>
                {b.status !== 'connected' && (
                  <ActionBtn label="Reconnect" onClick={() => reconnect(b.broker_id)} variant="primary" size="sm" loading={busy === `reconnect-${b.broker_id}`} />
                )}
                {b.status === 'connected' && (
                  <ActionBtn label="Disconnect" onClick={() => disconnect(b.broker_id)} variant="danger" size="sm" loading={busy === `disconnect-${b.broker_id}`} />
                )}
              </div>
            </div>
          ))}
          {brokers.length === 0 && <div style={{ color: '#475569', fontSize: 13, padding: '16px 0' }}>No brokers configured.</div>}
        </div>
      </SectionCard>

      {/* TCA Table */}
      <SectionCard title="Transaction Cost Analysis" icon="📊" accent="#8b5cf6"
        subtitle="Execution quality comparison across brokers">
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #1e293b' }}>
                {['Broker', 'Avg Slippage', 'Fill Rate', 'Rejection Rate', 'Avg Execution', 'Total Orders', 'Period'].map(h => (
                  <th key={h} style={{ padding: '8px 12px', textAlign: 'left', fontSize: 11, fontWeight: 600, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em', whiteSpace: 'nowrap' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tca.map(t => (
                <tr key={t.broker_id} className="sa-row" style={{ borderBottom: '1px solid #0f172a' }}>
                  <td style={{ padding: '10px 12px', fontWeight: 600, color: '#f1f5f9' }}>{t.broker_name}</td>
                  <td style={{ padding: '10px 12px', color: t.avg_slippage_pips < 1 ? '#4ade80' : t.avg_slippage_pips < 3 ? '#fbbf24' : '#f87171', fontWeight: 700 }}>
                    {t.avg_slippage_pips.toFixed(2)} pips
                  </td>
                  <td style={{ padding: '10px 12px', minWidth: 120 }}><FillRateBar pct={t.fill_rate_pct} /></td>
                  <td style={{ padding: '10px 12px', color: t.rejection_rate_pct < 1 ? '#4ade80' : '#f87171', fontWeight: 700 }}>
                    {t.rejection_rate_pct.toFixed(2)}%
                  </td>
                  <td style={{ padding: '10px 12px', minWidth: 120 }}><LatencyBar ms={t.avg_execution_ms} /></td>
                  <td style={{ padding: '10px 12px', color: '#94a3b8' }}>{t.total_orders.toLocaleString()}</td>
                  <td style={{ padding: '10px 12px', color: '#64748b', fontSize: 12 }}>{t.period}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {tca.length === 0 && <div style={{ textAlign: 'center', padding: 32, color: '#475569', fontSize: 13 }}>No TCA data available.</div>}
        </div>
      </SectionCard>

      {msg && (
        <div style={{ padding: '12px 16px', borderRadius: 8, marginTop: 4, background: msg.includes('failed') ? '#450a0a' : '#052e16', color: msg.includes('failed') ? '#f87171' : '#4ade80', fontSize: 13, fontWeight: 600 }}>
          {msg}
        </div>
      )}
    </div>
  );
};

export default BrokerManagementSection;
