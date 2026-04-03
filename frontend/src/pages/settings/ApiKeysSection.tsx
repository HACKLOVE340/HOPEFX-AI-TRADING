// settings/ApiKeysSection.tsx — Create, list, and revoke API keys
import React, { useState, useEffect } from 'react';
import { api } from '../../hooks/useApi';
import type { ApiKey } from './types';
import { Card, SectionHeader, Field, Input, Button, StatusBadge } from './ui';

const SCOPE_OPTIONS = ['read', 'trade', 'admin'];

const ApiKeysSection: React.FC = () => {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [newKeyName, setNewKeyName] = useState('');
  const [newKeyScopes, setNewKeyScopes] = useState<string[]>(['read']);
  const [revealedKey, setRevealedKey] = useState<{ key_id: string; api_key: string } | null>(null);
  const [revoking, setRevoking] = useState<string | null>(null);
  const [createError, setCreateError] = useState('');

  useEffect(() => {
    api.get<{ api_keys: ApiKey[] }>('/settings/api-keys')
      .then((r) => setKeys(r.data.api_keys ?? []))
      .catch((err: unknown) => console.warn('[Settings/ApiKeys] load:', err))
      .finally(() => setLoading(false));
  }, []);

  const handleCreate = async () => {
    if (!newKeyName.trim()) { setCreateError('Key name is required.'); return; }
    setCreating(true);
    setCreateError('');
    try {
      const res = await api.post<{ key_id: string; api_key: string; name: string; scopes: string[] }>(
        '/settings/api-keys',
        { name: newKeyName.trim(), scopes: newKeyScopes },
      );
      setRevealedKey({ key_id: res.data.key_id, api_key: res.data.api_key });
      setKeys((prev) => [...prev, {
        key_id: res.data.key_id,
        name: res.data.name,
        scopes: res.data.scopes,
        key_prefix: res.data.api_key.slice(0, 10) + '…',
        created_at: new Date().toISOString(),
        last_used: null,
        revoked: false,
      }]);
      setNewKeyName('');
      setNewKeyScopes(['read']);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setCreateError(detail ?? 'Failed to create API key.');
    } finally {
      setCreating(false);
    }
  };

  const handleRevoke = async (keyId: string) => {
    if (!window.confirm('Revoke this API key? This cannot be undone.')) return;
    setRevoking(keyId);
    try {
      await api.delete(`/settings/api-keys/${keyId}`);
      setKeys((prev) => prev.filter((k) => k.key_id !== keyId));
      if (revealedKey?.key_id === keyId) setRevealedKey(null);
    } catch (err: unknown) {
      console.warn('[Settings/ApiKeys] revoke:', err);
    } finally {
      setRevoking(null);
    }
  };

  const toggleScope = (scope: string) => {
    setNewKeyScopes((prev) =>
      prev.includes(scope) ? prev.filter((s) => s !== scope) : [...prev, scope],
    );
  };

  return (
    <div>
      <SectionHeader icon="🔑" title="API Keys" description="Generate keys to access HOPEFX programmatically. Keys are shown once — store them securely." />

      {/* Revealed key banner */}
      {revealedKey && (
        <div style={{
          padding: '16px 20px', background: '#052e16', border: '1px solid #166534',
          borderRadius: 12, marginBottom: 20,
        }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: '#22c55e', marginBottom: 8 }}>
            ✅ API key created — copy it now. It will not be shown again.
          </div>
          <div style={{
            fontFamily: 'JetBrains Mono, monospace', fontSize: 13, color: '#f1f5f9',
            background: '#0f172a', padding: '10px 14px', borderRadius: 8,
            wordBreak: 'break-all', letterSpacing: '0.02em',
          }}>
            {revealedKey.api_key}
          </div>
          <div style={{ display: 'flex', gap: 10, marginTop: 10 }}>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => navigator.clipboard.writeText(revealedKey.api_key)}
            >
              📋 Copy
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setRevealedKey(null)}
              style={{ color: '#64748b' }}
            >
              Dismiss
            </Button>
          </div>
        </div>
      )}

      {/* Create new key */}
      <Card>
        <h3 style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginTop: 0, marginBottom: 16 }}>
          Create new key
        </h3>
        <Field label="Key name" description="A label to identify this key (e.g. 'My trading bot').">
          <Input
            value={newKeyName}
            onChange={(e) => setNewKeyName(e.target.value)}
            placeholder="My trading bot"
            maxLength={60}
          />
        </Field>
        <Field label="Scopes" description="Permissions granted to this key.">
          <div style={{ display: 'flex', gap: 8 }}>
            {SCOPE_OPTIONS.map((scope) => (
              <button
                key={scope}
                onClick={() => toggleScope(scope)}
                style={{
                  padding: '6px 14px', borderRadius: 20, fontSize: 13, fontWeight: 600,
                  cursor: 'pointer', transition: 'all 0.15s',
                  background: newKeyScopes.includes(scope) ? '#1e3a5f' : '#0f172a',
                  border: `1px solid ${newKeyScopes.includes(scope) ? '#3b82f6' : '#334155'}`,
                  color: newKeyScopes.includes(scope) ? '#60a5fa' : '#64748b',
                }}
              >
                {scope}
              </button>
            ))}
          </div>
        </Field>
        {createError && <div style={{ fontSize: 13, color: '#f87171', marginBottom: 10 }}>❌ {createError}</div>}
        <Button
          onClick={handleCreate}
          loading={creating}
          disabled={!newKeyName.trim() || newKeyScopes.length === 0}
        >
          Generate key
        </Button>
      </Card>

      {/* Existing keys */}
      <Card>
        <h3 style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginTop: 0, marginBottom: 16 }}>
          Active keys
        </h3>
        {loading ? (
          <div style={{ color: '#64748b', fontSize: 13 }}>Loading keys…</div>
        ) : keys.length === 0 ? (
          <div style={{ color: '#64748b', fontSize: 13 }}>No API keys yet.</div>
        ) : (
          keys.map((key) => (
            <div key={key.key_id} style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
              padding: '14px 0', borderBottom: '1px solid #1e293b',
            }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                  <span style={{ fontSize: 14, fontWeight: 600, color: '#e2e8f0' }}>{key.name}</span>
                  <StatusBadge status="info" label={key.scopes.join(', ')} />
                </div>
                <div style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 12, color: '#64748b', marginBottom: 2 }}>
                  {key.key_prefix}
                </div>
                <div style={{ fontSize: 11, color: '#475569' }}>
                  Created {new Date(key.created_at).toLocaleDateString()}
                  {key.last_used && ` · Last used ${new Date(key.last_used).toLocaleDateString()}`}
                </div>
              </div>
              <Button
                variant="danger"
                size="sm"
                loading={revoking === key.key_id}
                onClick={() => handleRevoke(key.key_id)}
                style={{ marginLeft: 12, flexShrink: 0 }}
              >
                Revoke
              </Button>
            </div>
          ))
        )}
      </Card>
    </div>
  );
};

export default ApiKeysSection;
