// settings/BrokerSection.tsx — Broker connection configuration and testing
import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../../hooks/useApi';
import type { BrokerSettings } from './types';
import { Card, SectionHeader, Field, Input, Select, Toggle, Button, StatusBadge, Divider, SaveBar } from './ui';
import { extractApiError } from '../../lib/utils';
import { ErrorBanner } from '../../components/ErrorBanner';

const DEFAULT: BrokerSettings = {
  type: 'paper', api_key: '', account_id: '', practice: true, connected: false,
};

const BROKER_OPTIONS = [
  { value: 'paper',  label: '📄 Paper Trading (no real money)' },
  { value: 'oanda',  label: '🏦 OANDA' },
  { value: 'alpaca', label: '🦙 Alpaca' },
];

const BrokerSection: React.FC = () => {
  const [form, setForm] = useState<BrokerSettings>(DEFAULT);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [testStatus, setTestStatus] = useState<'idle' | 'testing' | 'ok' | 'fail'>('idle');
  const [testMsg, setTestMsg] = useState('');
  const [brokerStatus, setBrokerStatus] = useState<{
    connected: boolean; balance?: number; currency?: string; broker?: string;
  } | null>(null);
  // Last-4 of the API key already saved server-side ('' = none). The full key
  // is never sent to the client.
  const [keyOnFile, setKeyOnFile] = useState<string | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [statusErr, setStatusErr] = useState('');

  const load = useCallback(() => {
    setLoading(true);
    setLoadFailed(false);
    // Hydrate the SAVED broker config so non-secret fields (type/account_id/
    // practice) survive a reload instead of resetting to defaults. The API key
    // is never returned raw — the field stays blank and the user re-enters it
    // only to change it (a blank save keeps the stored key, server-side).
    const cfg = api.get<{ type: string; account_id: string; practice: boolean; api_key_set: boolean; api_key_last4: string }>(
      '/settings/broker')
      .then((r) => {
        setForm((prev) => ({
          ...prev,
          type: (r.data.type as BrokerSettings['type']) ?? prev.type,
          account_id: r.data.account_id ?? prev.account_id,
          practice: r.data.practice ?? prev.practice,
        }));
        if (r.data.api_key_set) setKeyOnFile(r.data.api_key_last4 || '••••');
      })
      .catch((err: unknown) => {
        // A 404 genuinely means "no broker configured yet" and DEFAULT is the
        // right starting point. Anything else means we could not read the saved
        // config, and rendering DEFAULT would show a live OANDA account as
        // 'paper' with a blank account_id — one save away from silently
        // reverting the broker.
        if ((err as { response?: { status?: number } })?.response?.status === 404) return;
        console.warn('[Settings/Broker] config:', err);
        setLoadFailed(true);
      });

    // Load live connection status from the broker endpoint.
    const status = api.get<{ connected: boolean; balance?: number; currency?: string; broker?: string }>('/broker/status')
      .then((r) => {
        setBrokerStatus(r.data);
        setStatusErr('');
        if (r.data.broker) {
          setForm((prev) => ({ ...prev, type: r.data.broker as BrokerSettings['type'], connected: r.data.connected }));
        }
      })
      .catch((err: unknown) => setStatusErr(extractApiError(err, 'Could not read live broker status')));

    void Promise.allSettled([cfg, status]).then(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const update = useCallback((patch: Partial<BrokerSettings>) =>
    setForm((prev) => ({ ...prev, ...patch })), []);

  const handleTest = async () => {
    setTestStatus('testing');
    setTestMsg('');
    try {
      const res = await api.post<{ ok: boolean; latency_ms?: number; error?: string }>(
        '/broker/test-connection',
        { type: form.type, api_key: form.api_key, account_id: form.account_id, practice: form.practice },
      );
      if (res.data.ok) {
        setTestStatus('ok');
        setTestMsg(`Connected in ${res.data.latency_ms ?? '?'}ms`);
      } else {
        setTestStatus('fail');
        setTestMsg(res.data.error ?? 'Connection failed');
      }
    } catch (err: unknown) {
      setTestStatus('fail');
      setTestMsg(extractApiError(err, 'Connection test failed'));
    }
    setTimeout(() => setTestStatus('idle'), 6000);
  };

  const handleSave = async () => {
    setSaving(true);
    setSaveError('');
    try {
      await api.post('/settings/broker', {
        type: form.type,
        api_key: form.api_key,
        account_id: form.account_id,
        practice: form.practice,
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (err: unknown) {
      setSaveError(extractApiError(err, 'Failed to save broker settings.'));
    } finally {
      setSaving(false);
    }
  };

  if (loading) return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: '#64748b', padding: 20 }}>
      <div style={{ width: 18, height: 18, border: '2px solid #334155', borderTopColor: '#3b82f6', borderRadius: '50%', animation: 'spin 0.7s linear infinite' }} />
      Loading broker status…
    </div>
  );

  if (loadFailed) return (
    <div>
      <SectionHeader icon="🏦" title="Broker Connection" description="Connect your live or paper trading account." />
      <ErrorBanner message="Couldn't load your saved broker configuration. Nothing has been changed — saving now would post default values over it." />
      <div style={{ marginTop: 14 }}>
        <Button variant="secondary" onClick={load}>Retry</Button>
      </div>
    </div>
  );

  return (
    <div>
      <SectionHeader icon="🏦" title="Broker Connection" description="Connect your live or paper trading account." />

      {statusErr && (
        <ErrorBanner
          message={`${statusErr}. The connection state below is unknown, not necessarily disconnected.`}
          onDismiss={() => setStatusErr('')}
        />
      )}

      {/* Live status card */}
      {brokerStatus && (
        <Card>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <div style={{ fontSize: 14, fontWeight: 600, color: '#e2e8f0', marginBottom: 4 }}>
                Current connection
              </div>
              {brokerStatus.connected && brokerStatus.balance !== undefined && (
                <div style={{ fontSize: 13, color: '#94a3b8' }}>
                  Balance: <span style={{ color: '#22c55e', fontWeight: 600 }}>
                    {brokerStatus.currency ?? 'USD'} {brokerStatus.balance.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                  </span>
                </div>
              )}
            </div>
            <StatusBadge
              status={brokerStatus.connected ? 'ok' : 'error'}
              label={brokerStatus.connected ? `${brokerStatus.broker ?? 'Broker'} connected` : 'Disconnected'}
            />
          </div>
        </Card>
      )}

      {/* Broker type */}
      <Card>
        <Field label="Broker" description="Select your trading broker or use paper trading to test strategies.">
          <Select
            value={form.type}
            onChange={(e) => update({ type: e.target.value as BrokerSettings['type'], api_key: '', account_id: '' })}
            options={BROKER_OPTIONS}
          />
        </Field>

        {form.type !== 'paper' && (
          <>
            <Field label="API Key" description="Your broker API key. Stored encrypted server-side.">
              <Input
                type="password"
                value={form.api_key}
                onChange={(e) => update({ api_key: e.target.value })}
                placeholder={keyOnFile ? `Saved key on file (••••${keyOnFile}) — leave blank to keep` : 'Enter your API key'}
                autoComplete="off"
              />
              {keyOnFile && !form.api_key && (
                <div style={{ fontSize: 11, color: '#4ade80', marginTop: 4 }}>
                  ✓ API key saved — leave blank to keep it, or enter a new key to replace.
                </div>
              )}
            </Field>

            {form.type === 'oanda' && (
              <Field label="Account ID" description="Your OANDA account ID (e.g. 001-001-1234567-001).">
                <Input
                  value={form.account_id}
                  onChange={(e) => update({ account_id: e.target.value })}
                  placeholder="001-001-1234567-001"
                />
              </Field>
            )}

            <Toggle
              id="broker-practice"
              label="Practice / demo account"
              description={form.type === 'oanda'
                ? 'Use fxpractice.oanda.com instead of fxtrade.oanda.com'
                : 'Use paper trading endpoint'}
              checked={form.practice}
              onChange={(v) => update({ practice: v })}
            />

            <Divider />

            {/* Test connection */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <Button
                variant="secondary"
                onClick={handleTest}
                loading={testStatus === 'testing'}
                disabled={!form.api_key}
              >
                Test connection
              </Button>
              {testStatus === 'ok' && (
                <span style={{ fontSize: 13, color: '#22c55e' }}>✅ {testMsg}</span>
              )}
              {testStatus === 'fail' && (
                <span style={{ fontSize: 13, color: '#f87171' }}>❌ {testMsg}</span>
              )}
            </div>
          </>
        )}

        {form.type === 'paper' && (
          <div style={{
            marginTop: 12, padding: '12px 16px', background: '#0c1a2e',
            border: '1px solid #1e3a5f', borderRadius: 8, fontSize: 13, color: '#60a5fa',
          }}>
            Paper trading uses a simulated account with no real funds. All strategies and risk settings apply normally.
          </div>
        )}
      </Card>

      <SaveBar onSave={handleSave} saving={saving} saved={saved} error={saveError} />
    </div>
  );
};

export default BrokerSection;
