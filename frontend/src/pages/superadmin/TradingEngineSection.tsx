// superadmin/TradingEngineSection.tsx — engine config, kill switch, metrics
import React, { useEffect, useState, useCallback, useRef } from 'react';
import { superadminApi } from '../../hooks/useApi';
import { usePolling } from '../../hooks/usePolling';
import {
  SectionCard, StatusBadge, ActionBtn, Input, Select, Toggle,
  KpiTile, ErrorState, LoadingRows, ConfirmDialog,
} from './ui';
import { extractApiError } from '../../lib/utils';

interface EngineConfig {
  paper_trading_mode: boolean;
  live_trading_enabled: boolean;
  max_open_positions: number;
  max_risk_per_trade: number;
  max_daily_loss_pct: number;
  max_drawdown_pct: number;
  default_lot_size: number;
  slippage_tolerance: number;
  default_leverage: number;
  auto_trade_enabled: boolean;
  signal_confidence_threshold: number;
  kill_switch_active: boolean;
  engine_status: string;
  broker_type: string;
  execution_mode: string;
}

interface EngineMetrics {
  trades_today: number;
  open_positions: number;
  pnl_today: number;
  win_rate_today: number;
  avg_execution_ms: number;
  rejected_orders: number;
  kill_switch_triggers: number;
  uptime_hours: number;
}

interface EngineStatus {
  running: boolean;
  status?: string;  // 'running' | 'standby' | 'stopped' | 'paused'
  uptime_seconds: number;
  last_signal_at: string | null;
  positions_open: number;
  heartbeat_ok: boolean;
  mode: string;
  // Optional live fields from HopeFXEngine._get_status()
  last_signal_direction?: string;
  last_signal_confidence?: number;
}

const TradingEngineSection: React.FC = () => {
  const [cfg, setCfg]         = useState<EngineConfig | null>(null);
  const [metrics, setMetrics] = useState<EngineMetrics | null>(null);
  const [status, setStatus]   = useState<EngineStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving]   = useState(false);
  const [error, setError]     = useState('');
  const [msg, setMsg]         = useState('');
  const [confirm, setConfirm] = useState<string | null>(null);

  const mountedRef = useRef(true);
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const [cfgRes, metRes, stRes] = await Promise.all([
        superadminApi.engineConfig(),
        superadminApi.engineMetrics(),
        superadminApi.engineStatus(),
      ]);
      if (!mountedRef.current) return;
      setCfg(cfgRes.data);
      setMetrics(metRes.data);
      setStatus(stRes.data);
    } catch (e: unknown) {
      if (!mountedRef.current) return;
      setError(extractApiError(e, 'Failed to load engine data'));
    } finally { if (mountedRef.current) setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);
  // Refresh engine status and metrics every 15 s — engine state changes rapidly
  // (positions open/close, PnL updates, kill-switch triggers).
  usePolling(load, 15_000);

  const save = async () => {
    if (!cfg) return;
    setSaving(true); setMsg('');
    try {
      await superadminApi.updateEngineConfig(cfg);
      setMsg('Engine configuration saved');
    } catch (e: unknown) {
      setMsg(extractApiError(e, 'Save failed'));
    } finally { setSaving(false); }
  };

  const toggleKillSwitch = async () => {
    if (!cfg) return;
    setSaving(true); setMsg('');
    try {
      await superadminApi.killSwitch(!cfg.kill_switch_active);
      setCfg(c => c ? { ...c, kill_switch_active: !c.kill_switch_active } : c);
      setMsg(`Kill switch ${!cfg.kill_switch_active ? 'ACTIVATED — all trading halted' : 'deactivated — trading resumed'}`);
    } catch (e: unknown) {
      setMsg(extractApiError(e, 'Kill switch failed'));
    } finally { setSaving(false); setConfirm(null); }
  };

  const pauseResume = async (action: 'pause' | 'resume') => {
    setSaving(true); setMsg('');
    try {
      if (action === 'pause') await superadminApi.pauseTrading('Superadmin manual pause');
      else                    await superadminApi.resumeTrading();
      setMsg(`Trading ${action === 'pause' ? 'paused' : 'resumed'}`);
      setTimeout(load, 1000);
    } catch (e: unknown) {
      setMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? `${action} failed`);
    } finally { setSaving(false); setConfirm(null); }
  };

  const set = (k: keyof EngineConfig, v: unknown) => setCfg(c => c ? { ...c, [k]: v } : c);

  if (loading) return <><LoadingRows rows={8} /></>;
  if (error)   return <><ErrorState message={error} onRetry={load} /></>;
  if (!cfg)    return null;

  return (
    <div style={{ animation: 'sa-fadein 0.2s ease' }}>


      {/* ── Live engine status banner ── */}
      {status && (() => {
        const engineStatus = status.status ?? (status.running ? 'running' : 'stopped');
        const isRunning  = status.running;
        const isStandby  = engineStatus === 'standby';
        const dotColor   = isRunning ? '#4ade80' : isStandby ? '#f59e0b' : '#f87171';
        const textColor  = isRunning ? '#4ade80' : isStandby ? '#f59e0b' : '#f87171';
        const label      = isRunning ? 'RUNNING' : isStandby ? 'STANDBY' : engineStatus.toUpperCase();
        const bgColor    = isRunning ? '#052e16' : isStandby ? '#1c1408' : '#450a0a';
        const borderColor = isRunning ? '#16a34a44' : isStandby ? '#d9770644' : '#dc262644';
        return (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap',
          padding: '12px 18px', borderRadius: 10, marginBottom: 16,
          background: bgColor,
          border: `1px solid ${borderColor}`,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ width: 9, height: 9, borderRadius: '50%', background: dotColor, display: 'inline-block', boxShadow: isRunning ? '0 0 6px #4ade80' : 'none' }} />
            <span style={{ fontSize: 13, fontWeight: 700, color: textColor }}>
              Engine {label}
            </span>
            <span style={{ fontSize: 12, color: '#475569', marginLeft: 4 }}>{status.mode}</span>
          </div>
          {[
            { label: 'Uptime',         value: `${Math.floor(status.uptime_seconds / 3600)}h ${Math.floor((status.uptime_seconds % 3600) / 60)}m` },
            { label: 'Open Positions', value: status.positions_open },
            { label: 'Last Signal',    value: status.last_signal_at ? new Date(status.last_signal_at).toLocaleTimeString() : 'N/A' },
            { label: 'Heartbeat',      value: status.heartbeat_ok ? '✅ OK' : '❌ Miss' },
          ].map(s => (
            <div key={s.label} style={{ fontSize: 12, color: '#94a3b8' }}>
              <span style={{ color: '#475569' }}>{s.label}: </span>
              <span style={{ fontWeight: 600, color: '#f1f5f9' }}>{s.value}</span>
            </div>
          ))}

          {/* Last-signal direction chip + confidence bar (shown when live engine data available) */}
          {status.last_signal_direction && status.last_signal_direction !== 'hold' && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginLeft: 4 }}>
              <span style={{
                fontSize: 11, fontWeight: 800, padding: '2px 8px', borderRadius: 4,
                background: status.last_signal_direction === 'buy' ? '#052e1688' : '#450a0a88',
                color: status.last_signal_direction === 'buy' ? '#4ade80' : '#f87171',
                border: `1px solid ${status.last_signal_direction === 'buy' ? '#16a34a' : '#dc2626'}`,
                textTransform: 'uppercase' as const,
              }}>
                {status.last_signal_direction === 'buy' ? '▲' : '▼'} {status.last_signal_direction}
              </span>
              {typeof status.last_signal_confidence === 'number' && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                  <div style={{ width: 60, height: 5, background: '#1e293b', borderRadius: 3, overflow: 'hidden' }}>
                    <div style={{
                      width: `${Math.round(status.last_signal_confidence * 100)}%`,
                      height: '100%',
                      background: status.last_signal_confidence >= 0.7 ? '#4ade80' : status.last_signal_confidence >= 0.55 ? '#fbbf24' : '#f87171',
                      borderRadius: 3,
                    }} />
                  </div>
                  <span style={{ fontSize: 10, color: '#64748b', fontVariantNumeric: 'tabular-nums' }}>
                    {Math.round(status.last_signal_confidence * 100)}%
                  </span>
                </div>
              )}
            </div>
          )}
        </div>
        );
      })()}

      {confirm === 'kill' && (
        <ConfirmDialog
          title={cfg.kill_switch_active ? 'Deactivate Kill Switch' : '⚠️ Activate Kill Switch'}
          message={cfg.kill_switch_active
            ? 'This will resume all trading activity. Ensure market conditions are safe before proceeding.'
            : 'This will IMMEDIATELY halt ALL trading across the entire platform. All open orders will be cancelled. This affects every user.'}
          confirmLabel={cfg.kill_switch_active ? 'Resume Trading' : 'ACTIVATE KILL SWITCH'}
          variant="danger"
          onConfirm={toggleKillSwitch}
          onCancel={() => setConfirm(null)}
        />
      )}
      {confirm === 'pause' && (
        <ConfirmDialog
          title="Pause Trading Engine"
          message="This will pause the trading engine. No new orders will be placed but existing positions remain open."
          confirmLabel="Pause Engine"
          variant="warning"
          onConfirm={() => pauseResume('pause')}
          onCancel={() => setConfirm(null)}
        />
      )}

      {/* Kill switch banner */}
      {cfg.kill_switch_active && (
        <div style={{
          background: '#450a0a', border: '1px solid #dc2626', borderRadius: 10,
          padding: '14px 18px', marginBottom: 20,
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 20 }}>🛑</span>
            <div>
              <div style={{ fontSize: 14, fontWeight: 700, color: '#f87171' }}>KILL SWITCH ACTIVE</div>
              <div style={{ fontSize: 12, color: '#fca5a5' }}>All trading is halted across the entire platform</div>
            </div>
          </div>
          <ActionBtn label="Resume Trading" onClick={() => setConfirm('kill')} variant="success" icon="▶️" loading={saving} />
        </div>
      )}

      {/* Metrics */}
      {metrics && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(170px, 1fr))', gap: 12, marginBottom: 20 }}>
          <KpiTile label="Trades Today"      value={metrics.trades_today}                    icon="📊" accent="#3b82f6" />
          <KpiTile label="Open Positions"    value={metrics.open_positions}                  icon="📈" accent="#22c55e" />
          <KpiTile label="PnL Today"         value={`$${metrics.pnl_today.toFixed(2)}`}      icon="💰" accent={metrics.pnl_today >= 0 ? '#22c55e' : '#ef4444'} />
          <KpiTile label="Win Rate"          value={`${(metrics.win_rate_today * 100).toFixed(1)}%`} icon="🎯" accent="#8b5cf6" />
          <KpiTile label="Avg Execution"     value={`${metrics.avg_execution_ms}ms`}         icon="⚡" accent="#f59e0b" />
          <KpiTile label="Rejected Orders"   value={metrics.rejected_orders}                 icon="🚫" accent="#ef4444" />
          <KpiTile label="Kill Triggers"     value={metrics.kill_switch_triggers}            icon="🛑" accent="#dc2626" />
          <KpiTile label="Uptime"            value={`${metrics.uptime_hours.toFixed(1)}h`}   icon="⏱️" accent="#06b6d4" />
        </div>
      )}

      {/* Engine status + controls */}
      <SectionCard title="Engine Controls" icon="⚙️" accent="#ef4444"
        subtitle={`Status: ${cfg.engine_status} · Broker: ${cfg.broker_type}`}>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 16 }}>
          <StatusBadge status={cfg.engine_status} />
          <ActionBtn
            label={cfg.kill_switch_active ? '🛑 Kill Switch ACTIVE' : 'Activate Kill Switch'}
            onClick={() => setConfirm('kill')}
            variant={cfg.kill_switch_active ? 'success' : 'danger'}
            loading={saving}
          />
          {cfg.engine_status === 'running'
            ? <ActionBtn label="Pause Engine" onClick={() => setConfirm('pause')} variant="warning" icon="⏸️" loading={saving} />
            : <ActionBtn label="Resume Engine" onClick={() => pauseResume('resume')} variant="success" icon="▶️" loading={saving} />
          }
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <Toggle label="Paper Trading Mode"   checked={cfg.paper_trading_mode}    onChange={v => set('paper_trading_mode', v)} accent="#f59e0b" />
          <Toggle label="Live Trading Enabled" checked={cfg.live_trading_enabled}  onChange={v => set('live_trading_enabled', v)} accent="#22c55e" />
          <Toggle label="Auto-Trade Enabled"   checked={cfg.auto_trade_enabled}    onChange={v => set('auto_trade_enabled', v)} />
        </div>
      </SectionCard>

      {/* Risk parameters */}
      <SectionCard title="Risk Parameters" icon="🛡️" accent="#f59e0b"
        actions={<ActionBtn label={saving ? 'Saving…' : 'Save'} onClick={save} variant="primary" loading={saving} size="sm" />}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
          <Input label="Max Open Positions"        value={cfg.max_open_positions}           onChange={e => set('max_open_positions', Number(e.target.value))}           type="number" />
          <Input label="Max Risk Per Trade (%)"    value={cfg.max_risk_per_trade}           onChange={e => set('max_risk_per_trade', Number(e.target.value))}           type="number" step="0.1" />
          <Input label="Max Daily Loss (%)"        value={cfg.max_daily_loss_pct}           onChange={e => set('max_daily_loss_pct', Number(e.target.value))}           type="number" step="0.1" />
          <Input label="Max Drawdown (%)"          value={cfg.max_drawdown_pct}             onChange={e => set('max_drawdown_pct', Number(e.target.value))}             type="number" step="0.1" />
          <Input label="Default Lot Size"          value={cfg.default_lot_size}             onChange={e => set('default_lot_size', Number(e.target.value))}             type="number" step="0.01" />
          <Input label="Slippage Tolerance (pips)" value={cfg.slippage_tolerance}           onChange={e => set('slippage_tolerance', Number(e.target.value))}           type="number" step="0.1" />
          <Input label="Default Leverage"          value={cfg.default_leverage}             onChange={e => set('default_leverage', Number(e.target.value))}             type="number" />
          <Input label="Signal Confidence Threshold" value={cfg.signal_confidence_threshold} onChange={e => set('signal_confidence_threshold', Number(e.target.value))} type="number" step="0.01" min="0" max="1" />
        </div>
        <div style={{ marginTop: 14, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
          <Select label="Broker Type"
            value={cfg.broker_type}
            onChange={e => set('broker_type', e.target.value)}
            options={[
              { value: 'paper',  label: 'Paper Trading' },
              { value: 'oanda',  label: 'OANDA' },
              { value: 'alpaca', label: 'Alpaca' },
            ]}
          />
          <Select label="Execution Mode"
            value={cfg.execution_mode}
            onChange={e => set('execution_mode', e.target.value)}
            options={[
              { value: 'market', label: 'Market Orders' },
              { value: 'limit',  label: 'Limit Orders' },
              { value: 'smart',  label: 'Smart Routing' },
            ]}
          />
        </div>
      </SectionCard>

      {msg && (
        <div style={{
          padding: '12px 16px', borderRadius: 8, marginTop: 4,
          background: msg.includes('failed') || msg.includes('ACTIVATED') ? '#450a0a' : '#052e16',
          color: msg.includes('failed') || msg.includes('ACTIVATED') ? '#f87171' : '#4ade80',
          fontSize: 13, fontWeight: 600,
        }}>
          {msg}
        </div>
      )}

      {/* ── Decision Engine & Gatekeeper Status ── */}
      <DecisionEnginePanel />
    </div>
  );
};

// ── Decision Engine & Gatekeeper Panel ───────────────────────────────────────

const DecisionEnginePanel: React.FC = () => {
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);

  const mountedRef = useRef(true);
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await superadminApi.engineStatus();
      if (!mountedRef.current) return;
      setStatus(res.data);
    } catch { /* non-fatal */ }
    finally { if (mountedRef.current) setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const phases = [
    { id: 1, name: 'StrategyBrain Consensus', desc: 'Multi-strategy signal aggregation' },
    { id: 2, name: 'ML Enrichment', desc: 'XGBoost + LightGBM + LSTM ensemble + anomaly weighting + online blend' },
    { id: 3, name: 'Gatekeeper (11 checks)', desc: 'Kill switch, news blackout, spread, data quality, sentiment, macro, FIA compliance' },
    { id: 4, name: 'Trade Execution', desc: 'Smart broker router with circuit breaker + failover' },
    { id: 5, name: 'Post-Trade', desc: 'EventBus broadcast + compliance audit + online learner feedback' },
  ];

  const gatekeeperChecks = [
    'Kill switch active', 'Post-breach pause', 'News blackout window', 'Spread limit exceeded',
    'Data quality gate', 'Sentiment blackout', 'Macro impact gate', 'Max daily trades',
    'FIA 2024 compliance', 'Confidence threshold', 'Position correlation',
  ];

  return (
    <>
      <SectionCard title="Decision Engine Pipeline" icon="⚡" accent="#f59e0b">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <div style={{ fontSize: 13, color: '#64748b' }}>5-phase HOPEFXDecisionEngine — runs on every market tick</div>
          <button onClick={load} disabled={loading} style={{ padding: '4px 10px', borderRadius: 6, border: '1px solid #334155', background: 'transparent', color: '#64748b', cursor: 'pointer', fontSize: 12 }}>
            {loading ? '…' : '↻'}
          </button>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {phases.map(p => (
            <div key={p.id} style={{ display: 'flex', alignItems: 'flex-start', gap: 12, padding: '10px 14px', borderRadius: 8, background: '#0f172a', border: '1px solid #1e293b' }}>
              <div style={{ width: 28, height: 28, borderRadius: '50%', background: '#1e3a5f', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, fontWeight: 800, color: '#60a5fa', flexShrink: 0 }}>
                {p.id}
              </div>
              <div>
                <div style={{ fontSize: 13, fontWeight: 700, color: '#f1f5f9' }}>{p.name}</div>
                <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>{p.desc}</div>
              </div>
            </div>
          ))}
        </div>
        {status && (
          <div style={{ marginTop: 16, display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 8 }}>
            {Object.entries(status as Record<string, unknown>).filter(([, v]) => typeof v !== 'object').map(([key, val]) => (
              <div key={key} style={{ background: '#1e293b', borderRadius: 6, padding: '8px 12px' }}>
                <div style={{ fontSize: 10, color: '#64748b', textTransform: 'uppercase', marginBottom: 2 }}>{key.replace(/_/g, ' ')}</div>
                <div style={{ fontSize: 13, fontWeight: 700, color: '#f1f5f9' }}>{String(val)}</div>
              </div>
            ))}
          </div>
        )}
      </SectionCard>

      <SectionCard title="Gatekeeper Checks (11)" icon="🛡️" accent="#22c55e">
        <div style={{ fontSize: 13, color: '#64748b', marginBottom: 12 }}>
          All 11 checks must pass before any trade is executed. Failures are logged to the audit trail.
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 6 }}>
          {gatekeeperChecks.map((check, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', borderRadius: 6, background: '#0f172a', border: '1px solid #1e293b' }}>
              <span style={{ color: '#22c55e', fontSize: 14 }}>✓</span>
              <span style={{ fontSize: 12, color: '#94a3b8' }}>{check}</span>
            </div>
          ))}
        </div>
        <div style={{ marginTop: 12, padding: '10px 14px', borderRadius: 8, background: '#0f172a', border: '1px solid #1e293b' }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: '#f1f5f9', marginBottom: 6 }}>Decision Outcomes</div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {['NO_SIGNAL', 'ML_FILTERED', 'RISK_BLOCKED', 'SIZING_REJECTED', 'EXECUTED', 'EXECUTION_ERROR'].map(o => (
              <span key={o} style={{ fontSize: 11, padding: '3px 8px', borderRadius: 4, background: '#1e293b', color: '#94a3b8', fontFamily: 'monospace' }}>{o}</span>
            ))}
          </div>
        </div>
      </SectionCard>
    </>
  );
};

export default TradingEngineSection;
