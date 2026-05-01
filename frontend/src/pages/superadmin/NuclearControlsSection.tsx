// superadmin/NuclearControlsSection.tsx
// Emergency halt, hedge activation, max-risk override, nuclear log
import React, { useEffect, useState, useCallback, useRef } from 'react';
import { superadminApi } from '../../hooks/useApi';
import { usePolling } from '../../hooks/usePolling';
import {
  SectionCard, ActionBtn, KpiTile, ErrorState, LoadingRows,
  ConfirmDialog, Input,
} from './ui';

const fmtDate = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—';

interface NuclearStatus {
  halted: boolean;
  halt_reason: string | null;
  halted_at: string | null;
  hedge_active: boolean;
  hedge_ratio: number;
  risk_override: boolean;
  max_risk_fraction: number;
  kill_switch_active: boolean;
}

interface NuclearLogEntry {
  action: string;
  reason?: string;
  actor: string;
  timestamp: string;
}

const ACTION_COLORS: Record<string, string> = {
  halt:             '#f87171',
  resume:           '#4ade80',
  hedge_activate:   '#fbbf24',
  hedge_deactivate: '#94a3b8',
  risk_override:    '#f97316',
};

const NuclearControlsSection: React.FC = () => {
  const [status, setStatus]     = useState<NuclearStatus | null>(null);
  const [log, setLog]           = useState<NuclearLogEntry[]>([]);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState('');
  const [busy, setBusy]         = useState<string | null>(null);
  const [msg, setMsg]           = useState('');
  const [haltReason, setHaltReason] = useState('');
  const [hedgeRatio, setHedgeRatio] = useState('1.0');
  const [riskFraction, setRiskFraction] = useState('0.5');
  const [confirm, setConfirm]   = useState<{ action: string; label: string; danger?: boolean } | null>(null);

  const mountedRef = useRef(true);
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [sRes, lRes] = await Promise.all([
        superadminApi.nuclearStatus(),
        superadminApi.nuclearLog(),
      ]);
      if (!mountedRef.current) return;
      setStatus(sRes.data);
      setLog(lRes.data.log ?? lRes.data.entries ?? []);
    } catch (e: unknown) {
      if (!mountedRef.current) return;
      setError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to load nuclear status');
    } finally { if (mountedRef.current) setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);
  // Refresh every 15 s while the tab is active — live operational data.
  usePolling(load, 15_000);

  const act = async (action: string) => {
    setBusy(action); setMsg('');
    try {
      if (action === 'halt') {
        await superadminApi.nuclearHalt(haltReason || 'Superadmin emergency halt');
        setMsg('Emergency halt activated — all trading stopped');
      } else if (action === 'resume') {
        await superadminApi.nuclearResume();
        setMsg('Trading resumed');
      } else if (action === 'hedge_activate') {
        await superadminApi.activateHedge({ hedge_ratio: parseFloat(hedgeRatio), instrument: 'XAUUSD' });
        setMsg(`Hedge activated at ${hedgeRatio}x ratio`);
      } else if (action === 'hedge_deactivate') {
        await superadminApi.deactivateHedge();
        setMsg('Hedge deactivated');
      } else if (action === 'risk_override') {
        await superadminApi.maxRiskOverride({ max_risk_fraction: parseFloat(riskFraction), reason: 'Superadmin override' });
        setMsg(`Max risk set to ${(parseFloat(riskFraction) * 100).toFixed(0)}%`);
      }
      await load();
    } catch (e: unknown) {
      setMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? `Action "${action}" failed`);
    } finally { setBusy(null); setConfirm(null); }
  };

  if (loading) return <LoadingRows rows={6} />;
  if (error)   return <ErrorState message={error} onRetry={load} />;

  const halted = status?.halted || status?.kill_switch_active;

  return (
    <>

      {confirm && (
        <ConfirmDialog
          title={confirm.label}
          message={confirm.danger
            ? 'This will immediately halt ALL trading activity across the entire platform. Are you absolutely sure?'
            : 'Confirm this action?'}
          confirmLabel={confirm.label}
          danger={confirm.danger}
          onConfirm={() => act(confirm.action)}
          onCancel={() => setConfirm(null)}
        />
      )}

      {msg && (
        <div style={{
          background: msg.includes('fail') || msg.includes('error') ? 'rgba(248,113,113,0.1)' : 'rgba(74,222,128,0.1)',
          border: `1px solid ${msg.includes('fail') || msg.includes('error') ? '#f87171' : '#4ade80'}`,
          borderRadius: 8, padding: '10px 14px', marginBottom: 16, fontSize: 13,
          color: msg.includes('fail') || msg.includes('error') ? '#f87171' : '#4ade80',
          display: 'flex', justifyContent: 'space-between',
        }}>
          {msg}
          <button onClick={() => setMsg('')} style={{ background: 'none', border: 'none', color: '#64748b', cursor: 'pointer' }}>✕</button>
        </div>
      )}

      {/* Status KPIs */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 14, marginBottom: 20 }}>
        <KpiTile label="Platform Status" value={halted ? 'HALTED' : 'RUNNING'} icon={halted ? '🛑' : '✅'} accent={halted ? '#ef4444' : '#22c55e'} />
        <KpiTile label="Kill Switch" value={status?.kill_switch_active ? 'ACTIVE' : 'INACTIVE'} icon="⚡" accent={status?.kill_switch_active ? '#ef4444' : '#22c55e'} />
        <KpiTile label="Hedge" value={status?.hedge_active ? `${((status.hedge_ratio ?? 0) * 100).toFixed(0)}%` : 'OFF'} icon="🛡️" accent={status?.hedge_active ? '#fbbf24' : '#475569'} />
        <KpiTile label="Risk Override" value={status?.risk_override ? `${((status.max_risk_fraction ?? 1) * 100).toFixed(0)}%` : 'NORMAL'} icon="⚠️" accent={status?.risk_override ? '#f97316' : '#475569'} />
      </div>

      {/* Emergency Halt */}
      <SectionCard title="Emergency Halt" icon="🛑" accent="#ef4444"
        subtitle={halted ? `Halted: ${status?.halt_reason ?? 'unknown reason'}` : 'Immediately stops all trading platform-wide'}>
        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <div style={{ flex: 1, minWidth: 240 }}>
            <Input
              label="Halt reason"
              placeholder="e.g. Market circuit breaker, regulatory order…"
              value={haltReason}
              onChange={e => setHaltReason(e.target.value)}
              disabled={!!halted}
            />
          </div>
          {!halted ? (
            <ActionBtn
              label="EMERGENCY HALT"
              onClick={() => setConfirm({ action: 'halt', label: 'EMERGENCY HALT', danger: true })}
              loading={busy === 'halt'}
              accent="#ef4444"
              style={{ minWidth: 160, fontWeight: 800, letterSpacing: '0.05em' }}
            />
          ) : (
            <ActionBtn
              label="Resume Trading"
              onClick={() => setConfirm({ action: 'resume', label: 'Resume Trading' })}
              loading={busy === 'resume'}
              accent="#22c55e"
              style={{ minWidth: 160 }}
            />
          )}
        </div>
        {halted && status?.halted_at && (
          <div style={{ marginTop: 12, fontSize: 12, color: '#f87171' }}>
            Halted at {fmtDate(status.halted_at)} — reason: {status.halt_reason ?? 'not specified'}
          </div>
        )}
      </SectionCard>

      {/* Hedge Activation */}
      <SectionCard title="Emergency Hedge" icon="🛡️" accent="#fbbf24"
        subtitle="Activate a counter-position hedge to neutralise open exposure">
        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <div style={{ width: 160 }}>
            <Input
              label="Hedge ratio (0–1)"
              type="number"
              min="0" max="1" step="0.1"
              value={hedgeRatio}
              onChange={e => setHedgeRatio(e.target.value)}
              disabled={!!status?.hedge_active}
            />
          </div>
          {!status?.hedge_active ? (
            <ActionBtn
              label="Activate Hedge"
              onClick={() => act('hedge_activate')}
              loading={busy === 'hedge_activate'}
              accent="#fbbf24"
            />
          ) : (
            <ActionBtn
              label="Deactivate Hedge"
              onClick={() => act('hedge_deactivate')}
              loading={busy === 'hedge_deactivate'}
              accent="#94a3b8"
            />
          )}
        </div>
      </SectionCard>

      {/* Max Risk Override */}
      <SectionCard title="Max Risk Override" icon="⚠️" accent="#f97316"
        subtitle="Override the platform-wide maximum risk fraction for all new positions">
        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <div style={{ width: 200 }}>
            <Input
              label="Max risk fraction (0–1)"
              type="number"
              min="0" max="1" step="0.05"
              value={riskFraction}
              onChange={e => setRiskFraction(e.target.value)}
            />
          </div>
          <ActionBtn
            label="Apply Override"
            onClick={() => act('risk_override')}
            loading={busy === 'risk_override'}
            accent="#f97316"
          />
        </div>
        {status?.risk_override && (
          <div style={{ marginTop: 10, fontSize: 12, color: '#f97316' }}>
            Active override: max risk = {((status.max_risk_fraction ?? 1) * 100).toFixed(0)}%
          </div>
        )}
      </SectionCard>

      {/* Nuclear Log */}
      <SectionCard title="Nuclear Action Log" icon="📋" accent="#64748b"
        subtitle="Immutable log of all emergency actions">
        {log.length === 0 ? (
          <div style={{ color: '#475569', fontSize: 13, textAlign: 'center', padding: 24 }}>No nuclear actions recorded</div>
        ) : (
          <div>
            {log.slice(0, 50).map((entry, i) => (
              <div key={i} style={{
                display: 'flex', alignItems: 'flex-start', gap: 12,
                padding: '10px 0', borderBottom: '1px solid #0f172a',
              }}>
                <div style={{
                  width: 8, height: 8, borderRadius: '50%', marginTop: 5, flexShrink: 0,
                  background: ACTION_COLORS[entry.action] ?? '#64748b',
                }} />
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <span style={{ fontSize: 12, fontWeight: 700, color: ACTION_COLORS[entry.action] ?? '#94a3b8', textTransform: 'uppercase' }}>
                      {entry.action.replace(/_/g, ' ')}
                    </span>
                    <span style={{ fontSize: 11, color: '#475569' }}>{entry.actor}</span>
                  </div>
                  {entry.reason && <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 2 }}>{entry.reason}</div>}
                </div>
                <div style={{ fontSize: 11, color: '#475569', flexShrink: 0 }}>{fmtDate(entry.timestamp)}</div>
              </div>
            ))}
          </div>
        )}
      </SectionCard>

      {/* ── Prop Firm Breach Tracker ── */}
      <PropFirmBreachPanel />
    </>
  );
};

// ── Prop Firm Breach Tracker Panel ────────────────────────────────────────────

const PropFirmBreachPanel: React.FC = () => {
  const [breaches, setBreaches] = useState<Array<Record<string, unknown>>>([]);
  const [drawdown, setDrawdown] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading]   = useState(false);

  const mountedRef = useRef(true);
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [b, d] = await Promise.allSettled([
        superadminApi.propBreaches(),
        superadminApi.drawdownStats(),
      ]);
      if (!mountedRef.current) return;
      if (b.status === 'fulfilled') setBreaches(b.value.data.breaches ?? b.value.data ?? []);
      if (d.status === 'fulfilled') setDrawdown(d.value.data);
    } catch { /* non-fatal */ }
    finally { if (mountedRef.current) setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const severityColor = (s: string) =>
    s === 'disqualified' ? '#dc2626' : s === 'breach' ? '#ef4444' : '#f59e0b';

  return (
    <SectionCard title="Prop Firm Breach Tracker" icon="📊" accent="#f59e0b">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div style={{ fontSize: 13, color: '#64748b' }}>Real-time prop firm rule violation monitoring</div>
        <button onClick={load} disabled={loading} style={{ padding: '4px 10px', borderRadius: 6, border: '1px solid #334155', background: 'transparent', color: '#64748b', cursor: 'pointer', fontSize: 12 }}>
          {loading ? '…' : '↻'}
        </button>
      </div>

      {drawdown && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 8, marginBottom: 16 }}>
          {[
            { label: 'Current DD', value: `${Number(drawdown.current_drawdown_pct ?? 0).toFixed(2)}%`, color: Number(drawdown.current_drawdown_pct ?? 0) > 5 ? '#ef4444' : '#22c55e' },
            { label: 'Max DD', value: `${Number(drawdown.max_drawdown_pct ?? 0).toFixed(2)}%`, color: '#f59e0b' },
            { label: 'Accounts in DD', value: String(drawdown.accounts_in_drawdown ?? 0), color: '#94a3b8' },
            { label: 'Near Limit', value: String(drawdown.accounts_near_limit ?? 0), color: '#ef4444' },
          ].map(m => (
            <div key={m.label} style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: '10px 14px', textAlign: 'center' }}>
              <div style={{ fontSize: 18, fontWeight: 800, color: m.color }}>{m.value}</div>
              <div style={{ fontSize: 10, color: '#475569', marginTop: 2, textTransform: 'uppercase' }}>{m.label}</div>
            </div>
          ))}
        </div>
      )}

      {breaches.length === 0 && !loading && (
        <div style={{ textAlign: 'center', color: '#475569', fontSize: 13, padding: '16px 0' }}>
          ✅ No active prop firm breaches detected
        </div>
      )}

      {breaches.map((b, i) => (
        <div key={i} style={{
          padding: '12px 14px', borderRadius: 8, marginBottom: 6,
          background: '#1a0a0a', border: `1px solid ${severityColor(String(b.severity ?? ''))}44`,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <span style={{ fontSize: 13, fontWeight: 700, color: '#f1f5f9' }}>{String(b.username ?? b.user_id ?? '')}</span>
              <span style={{ fontSize: 11, color: '#64748b', marginLeft: 8 }}>{String(b.breach_type ?? '').replace(/_/g, ' ')}</span>
            </div>
            <span style={{ fontSize: 11, fontWeight: 700, color: severityColor(String(b.severity ?? '')), textTransform: 'uppercase' }}>
              {String(b.severity ?? '')}
            </span>
          </div>
          <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 4 }}>
            Threshold: {String(b.threshold ?? '')} | Actual: {String(b.actual_value ?? '')}
          </div>
          <div style={{ fontSize: 11, color: '#475569', marginTop: 2 }}>{String(b.detected_at ?? '')}</div>
        </div>
      ))}

      {/* Prop firm modes info */}
      <div style={{ marginTop: 16, padding: '12px 14px', borderRadius: 8, background: '#0f172a', border: '1px solid #1e293b' }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: '#f1f5f9', marginBottom: 8 }}>Supported Prop Firm Modes</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 6 }}>
          {[
            { name: 'FTMO Standard', dd: '10%', daily: '5%', target: '10%' },
            { name: 'FTMO Aggressive', dd: '20%', daily: '10%', target: '10%' },
            { name: 'Goat Funded Standard', dd: '10%', daily: '5%', target: '8%' },
            { name: 'Goat Funded Swing', dd: '15%', daily: '—', target: '8%' },
          ].map(f => (
            <div key={f.name} style={{ padding: '8px 10px', borderRadius: 6, background: '#1e293b' }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#f1f5f9' }}>{f.name}</div>
              <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>DD: {f.dd} | Daily: {f.daily} | Target: {f.target}</div>
            </div>
          ))}
        </div>
      </div>
    </SectionCard>
  );
};

export default NuclearControlsSection;
