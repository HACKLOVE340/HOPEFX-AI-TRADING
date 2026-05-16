// settings/IntegrationsSection.tsx
// TradingView webhooks, MT4/MT5, cTrader, Zapier, Google Sheets, custom webhooks
import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../../hooks/useApi';
import type { IntegrationSettings } from './types';
import { Card, SectionHeader, Field, Input, Toggle, Button, StatusBadge, Divider, SaveBar } from './ui';
import { extractApiError } from '../../lib/utils';

const DEFAULT: IntegrationSettings = {
  tradingview_enabled: false, tradingview_webhook_secret: '',
  zapier_enabled: false, zapier_webhook_url: '',
  google_sheets_enabled: false, google_sheets_id: '',
  mt4_enabled: false, mt4_server: '', mt4_login: '', mt4_password: '',
  mt5_enabled: false, mt5_server: '', mt5_login: '', mt5_password: '',
  ctrader_enabled: false, ctrader_client_id: '', ctrader_client_secret: '',
  webhook_enabled: false, webhook_url: '', webhook_secret: '',
};

const IntegrationsSection: React.FC = () => {
  const [form, setForm] = useState<IntegrationSettings>(DEFAULT);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');
  const [testingWebhook, setTestingWebhook] = useState(false);
  const [webhookTestResult, setWebhookTestResult] = useState<'ok' | 'fail' | null>(null);

  useEffect(() => {
    api.get<IntegrationSettings>('/settings/integrations')
      .then((r) => setForm({ ...DEFAULT, ...r.data }))
      .catch((err: unknown) => console.warn('[Settings/Integrations] load:', err))
      .finally(() => setLoading(false));
  }, []);

  const update = useCallback((patch: Partial<IntegrationSettings>) =>
    setForm((prev) => ({ ...prev, ...patch })), []);

  const handleSave = async () => {
    setSaving(true); setError('');
    try {
      await api.post('/settings/integrations', form);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (err: unknown) {
      setError(extractApiError(err, 'Failed to save integrations.'));
    } finally { setSaving(false); }
  };

  const testWebhook = async () => {
    if (!form.webhook_url) return;
    setTestingWebhook(true); setWebhookTestResult(null);
    try {
      await api.post('/settings/integrations/test-webhook', { url: form.webhook_url, secret: form.webhook_secret });
      setWebhookTestResult('ok');
    } catch { setWebhookTestResult('fail'); }
    finally { setTestingWebhook(false); }
  };

  if (loading) return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: '#64748b', padding: 20 }}>
      <div style={{ width: 18, height: 18, border: '2px solid #334155', borderTopColor: '#3b82f6', borderRadius: '50%', animation: 'spin 0.7s linear infinite' }} />
      Loading integrations…
    </div>
  );

  return (
    <div>
      <SectionHeader icon="🔌" title="Integrations" description="Connect external platforms, trading terminals, and automation tools." />

      {/* TradingView */}
      <Card>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0' }}>TradingView Webhooks</div>
            <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>Receive alerts from TradingView Pine Script strategies.</div>
          </div>
          <Toggle id="tv-enabled" label="" checked={form.tradingview_enabled} onChange={(v) => update({ tradingview_enabled: v })} />
        </div>
        {form.tradingview_enabled && (
          <>
            <Divider />
            <Field label="Webhook Secret" description="Add this secret to your TradingView alert message to authenticate requests.">
              <Input
                value={form.tradingview_webhook_secret}
                onChange={(e) => update({ tradingview_webhook_secret: e.target.value })}
                placeholder="Generate a random secret…"
                type="password"
              />
            </Field>
            <div style={{ fontSize: 12, color: '#64748b', background: '#0f172a', padding: '10px 14px', borderRadius: 8, border: '1px solid #1e293b' }}>
              Webhook URL: <code style={{ color: '#60a5fa' }}>{window.location.origin}/api/webhooks/tradingview</code>
            </div>
          </>
        )}
      </Card>

      {/* MT4 */}
      <Card>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0' }}>MetaTrader 4</div>
            <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>Connect via MT4 bridge for signal execution.</div>
          </div>
          <Toggle id="mt4-enabled" label="" checked={form.mt4_enabled} onChange={(v) => update({ mt4_enabled: v })} />
        </div>
        {form.mt4_enabled && (
          <>
            <Divider />
            <Field label="Server"><Input value={form.mt4_server} onChange={(e) => update({ mt4_server: e.target.value })} placeholder="broker-server:443" /></Field>
            <Field label="Login"><Input value={form.mt4_login} onChange={(e) => update({ mt4_login: e.target.value })} placeholder="Account number" /></Field>
            <Field label="Password"><Input type="password" value={form.mt4_password} onChange={(e) => update({ mt4_password: e.target.value })} placeholder="••••••••" /></Field>
          </>
        )}
      </Card>

      {/* MT5 */}
      <Card>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0' }}>MetaTrader 5</div>
            <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>Connect via MT5 bridge for signal execution.</div>
          </div>
          <Toggle id="mt5-enabled" label="" checked={form.mt5_enabled} onChange={(v) => update({ mt5_enabled: v })} />
        </div>
        {form.mt5_enabled && (
          <>
            <Divider />
            <Field label="Server"><Input value={form.mt5_server} onChange={(e) => update({ mt5_server: e.target.value })} placeholder="broker-server:443" /></Field>
            <Field label="Login"><Input value={form.mt5_login} onChange={(e) => update({ mt5_login: e.target.value })} placeholder="Account number" /></Field>
            <Field label="Password"><Input type="password" value={form.mt5_password} onChange={(e) => update({ mt5_password: e.target.value })} placeholder="••••••••" /></Field>
          </>
        )}
      </Card>

      {/* cTrader */}
      <Card>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0' }}>cTrader Open API</div>
            <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>OAuth2 connection to cTrader-compatible brokers.</div>
          </div>
          <Toggle id="ctrader-enabled" label="" checked={form.ctrader_enabled} onChange={(v) => update({ ctrader_enabled: v })} />
        </div>
        {form.ctrader_enabled && (
          <>
            <Divider />
            <Field label="Client ID"><Input value={form.ctrader_client_id} onChange={(e) => update({ ctrader_client_id: e.target.value })} placeholder="cTrader app client ID" /></Field>
            <Field label="Client Secret"><Input type="password" value={form.ctrader_client_secret} onChange={(e) => update({ ctrader_client_secret: e.target.value })} placeholder="••••••••" /></Field>
          </>
        )}
      </Card>

      {/* Zapier */}
      <Card>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0' }}>Zapier</div>
            <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>Trigger Zaps on trade events.</div>
          </div>
          <Toggle id="zapier-enabled" label="" checked={form.zapier_enabled} onChange={(v) => update({ zapier_enabled: v })} />
        </div>
        {form.zapier_enabled && (
          <>
            <Divider />
            <Field label="Zapier Webhook URL"><Input value={form.zapier_webhook_url} onChange={(e) => update({ zapier_webhook_url: e.target.value })} placeholder="https://hooks.zapier.com/…" /></Field>
          </>
        )}
      </Card>

      {/* Google Sheets */}
      <Card>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0' }}>Google Sheets</div>
            <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>Auto-log trades to a Google Sheet.</div>
          </div>
          <Toggle id="sheets-enabled" label="" checked={form.google_sheets_enabled} onChange={(v) => update({ google_sheets_enabled: v })} />
        </div>
        {form.google_sheets_enabled && (
          <>
            <Divider />
            <Field label="Spreadsheet ID" description="Found in the Google Sheets URL.">
              <Input value={form.google_sheets_id} onChange={(e) => update({ google_sheets_id: e.target.value })} placeholder="1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms" />
            </Field>
          </>
        )}
      </Card>

      {/* Custom Webhook */}
      <Card>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0' }}>Custom Webhook</div>
            <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>POST trade events to any HTTP endpoint.</div>
          </div>
          <Toggle id="webhook-enabled" label="" checked={form.webhook_enabled} onChange={(v) => update({ webhook_enabled: v })} />
        </div>
        {form.webhook_enabled && (
          <>
            <Divider />
            <Field label="Endpoint URL"><Input value={form.webhook_url} onChange={(e) => update({ webhook_url: e.target.value })} placeholder="https://your-server.com/hook" /></Field>
            <Field label="Signing Secret" description="HMAC-SHA256 signature added to X-HopeFX-Signature header.">
              <Input type="password" value={form.webhook_secret} onChange={(e) => update({ webhook_secret: e.target.value })} placeholder="••••••••" />
            </Field>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <Button variant="secondary" size="sm" onClick={testWebhook} loading={testingWebhook} disabled={!form.webhook_url}>
                Send test event
              </Button>
              {webhookTestResult === 'ok' && <StatusBadge status="ok" label="Delivered" />}
              {webhookTestResult === 'fail' && <StatusBadge status="error" label="Failed" />}
            </div>
          </>
        )}
      </Card>

      <SaveBar onSave={handleSave} saving={saving} saved={saved} error={error} />
    </div>
  );
};

export default IntegrationsSection;
