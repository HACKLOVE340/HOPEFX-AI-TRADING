// settings/TradingSection.tsx — Trading preferences, risk defaults, auto-trade
import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../../hooks/useApi';
import { useStore } from '../../store';
import type { TradingPreferences } from './types';
import { SYMBOLS, TIMEFRAMES } from './types';
import { Card, SectionHeader, Field, Input, Select, Toggle, SaveBar } from './ui';
import { extractApiError } from '../../lib/utils';

const DEFAULT: TradingPreferences = {
  default_symbol: 'XAU_USD',
  default_timeframe: '1h',
  default_lot_size: 0.01,
  max_risk_per_trade: 1.0,
  max_daily_drawdown: 5.0,
  auto_trade_enabled: false,
  kill_switch_enabled: false,
  slippage_tolerance: 3,
  default_leverage: 50,
};

const TradingSection: React.FC = () => {
  const account = useStore((s) => s.account);
  const [form, setForm] = useState<TradingPreferences>(DEFAULT);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    api.get<TradingPreferences>('/settings/trading')
      .then((r) => setForm({ ...DEFAULT, ...r.data }))
      .catch((err: unknown) => console.warn('[Settings/Trading] load:', err))
      .finally(() => setLoading(false));
  }, []);

  const update = useCallback((patch: Partial<TradingPreferences>) =>
    setForm((prev) => ({ ...prev, ...patch })), []);

  const handleSave = async () => {
    setSaving(true);
    setError('');
    try {
      await api.post('/settings/trading', form);
      // If kill switch changed, sync with trading engine
      if (form.kill_switch_enabled) {
        await api.post('/trading/emergency-stop').catch(() => {/* non-fatal */});
      }
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (err: unknown) {
      setError(extractApiError(err, 'Failed to save trading preferences.'));
    } finally {
      setSaving(false);
    }
  };

  if (loading) return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: '#64748b', padding: 20 }}>
      <div style={{ width: 18, height: 18, border: '2px solid #334155', borderTopColor: '#3b82f6', borderRadius: '50%', animation: 'spin 0.7s linear infinite' }} />
      Loading trading preferences…
    </div>
  );

  return (
    <div>
      <SectionHeader icon="📈" title="Trading Preferences" description="Default symbols, risk limits, and automation settings." />

      {/* Account snapshot */}
      {account && (
        <div style={{
          display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(160px,1fr))', gap: 12, marginBottom: 20,
        }}>
          {[
            { label: 'Balance', value: `$${account.balance?.toLocaleString(undefined, { minimumFractionDigits: 2 }) ?? '—'}` },
            { label: 'Equity', value: `$${account.equity?.toLocaleString(undefined, { minimumFractionDigits: 2 }) ?? '—'}` },
            { label: 'Daily P&L', value: `$${account.daily_pnl?.toFixed(2) ?? '—'}`, color: (account.daily_pnl ?? 0) >= 0 ? '#22c55e' : '#f87171' },
          ].map(({ label, value, color }) => (
            <div key={label} style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 10, padding: '12px 16px' }}>
              <div style={{ fontSize: 11, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 4 }}>{label}</div>
              <div style={{ fontSize: 18, fontWeight: 700, color: color ?? '#f1f5f9', fontFamily: 'JetBrains Mono, monospace' }}>{value}</div>
            </div>
          ))}
        </div>
      )}

      {/* Defaults */}
      <Card>
        <h3 style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginTop: 0, marginBottom: 16 }}>Defaults</h3>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <Field label="Default symbol">
            <Select
              value={form.default_symbol}
              onChange={(e) => update({ default_symbol: e.target.value })}
              options={SYMBOLS.map((s) => ({ value: s, label: s }))}
            />
          </Field>
          <Field label="Default timeframe">
            <Select
              value={form.default_timeframe}
              onChange={(e) => update({ default_timeframe: e.target.value })}
              options={TIMEFRAMES.map((t) => ({ value: t, label: t }))}
            />
          </Field>
          <Field label="Default lot size">
            <Input
              type="number"
              min={0.001}
              max={100}
              step={0.001}
              value={form.default_lot_size}
              onChange={(e) => update({ default_lot_size: parseFloat(e.target.value) || 0.01 })}
            />
          </Field>
          <Field label="Default leverage">
            <Select
              value={String(form.default_leverage)}
              onChange={(e) => update({ default_leverage: parseInt(e.target.value) })}
              options={[1, 5, 10, 20, 30, 50, 100, 200, 500].map((l) => ({ value: String(l), label: `${l}:1` }))}
            />
          </Field>
        </div>
      </Card>

      {/* Risk limits */}
      <Card>
        <h3 style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginTop: 0, marginBottom: 16 }}>Risk Limits</h3>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <Field label="Max risk per trade (%)" description="% of account balance risked per trade.">
            <Input
              type="number"
              min={0.1}
              max={10}
              step={0.1}
              value={form.max_risk_per_trade}
              onChange={(e) => update({ max_risk_per_trade: parseFloat(e.target.value) || 1 })}
            />
          </Field>
          <Field label="Max daily drawdown (%)" description="Auto-pause trading if daily loss exceeds this.">
            <Input
              type="number"
              min={1}
              max={50}
              step={0.5}
              value={form.max_daily_drawdown}
              onChange={(e) => update({ max_daily_drawdown: parseFloat(e.target.value) || 5 })}
            />
          </Field>
          <Field label="Slippage tolerance (pips)" description="Maximum acceptable slippage on order fill.">
            <Input
              type="number"
              min={0}
              max={50}
              step={1}
              value={form.slippage_tolerance}
              onChange={(e) => update({ slippage_tolerance: parseInt(e.target.value) || 3 })}
            />
          </Field>
        </div>

        {/* Risk bar visual */}
        <div style={{ marginTop: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: '#64748b', marginBottom: 4 }}>
            <span>Risk per trade</span>
            <span style={{ color: form.max_risk_per_trade > 3 ? '#fbbf24' : '#22c55e', fontWeight: 600 }}>
              {form.max_risk_per_trade}%
            </span>
          </div>
          <div style={{ height: 6, background: '#0f172a', borderRadius: 3, overflow: 'hidden' }}>
            <div style={{
              height: '100%', borderRadius: 3,
              width: `${Math.min(form.max_risk_per_trade * 10, 100)}%`,
              background: form.max_risk_per_trade > 3 ? '#f59e0b' : '#22c55e',
              transition: 'width 0.3s, background 0.3s',
            }} />
          </div>
        </div>
      </Card>

      {/* Automation */}
      <Card>
        <h3 style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginTop: 0, marginBottom: 8 }}>Automation</h3>
        <Toggle
          id="auto-trade"
          label="Auto-trade enabled"
          description="Allow the AI engine to place trades automatically based on signals."
          checked={form.auto_trade_enabled}
          onChange={(v) => update({ auto_trade_enabled: v })}
        />
        <Toggle
          id="kill-switch"
          label="Kill switch"
          description="Immediately halt all automated trading and close open positions."
          checked={form.kill_switch_enabled}
          onChange={(v) => update({ kill_switch_enabled: v })}
        />
        {form.kill_switch_enabled && (
          <div style={{
            marginTop: 8, padding: '10px 14px', background: '#450a0a',
            border: '1px solid #7f1d1d', borderRadius: 8, fontSize: 13, color: '#f87171',
          }}>
            ⚠️ Kill switch is active. All automated trading is halted.
          </div>
        )}
      </Card>

      <SaveBar onSave={handleSave} saving={saving} saved={saved} error={error} />
    </div>
  );
};

export default TradingSection;
