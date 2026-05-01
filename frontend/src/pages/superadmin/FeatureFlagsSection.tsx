// superadmin/FeatureFlagsSection.tsx — global feature flags + per-user overrides
import React, { useEffect, useState, useCallback, useRef } from 'react';
import { superadminApi } from '../../hooks/useApi';
import { usePolling } from '../../hooks/usePolling';
import {
  SectionCard, ActionBtn, Input, Toggle,
  ErrorState, LoadingRows,
} from './ui';
import type { FeatureFlag } from './types';

interface UserOverride { flag: string; enabled: boolean }

const FeatureFlagsSection: React.FC = () => {
  const [flags, setFlags]       = useState<FeatureFlag[]>([]);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState('');
  const [busy, setBusy]         = useState<string | null>(null);
  const [msg, setMsg]           = useState('');
  const [userIdInput, setUserIdInput] = useState('');
  const [userOverrides, setUserOverrides] = useState<UserOverride[]>([]);
  const [overrideLoading, setOverrideLoading] = useState(false);
  const [overrideMsg, setOverrideMsg] = useState('');

  const mountedRef = useRef(true);
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const res = await superadminApi.featureFlags();
      if (!mountedRef.current) return;
      setFlags(res.data.flags ?? res.data);
    } catch (e: unknown) {
      if (!mountedRef.current) return;
      setError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to load feature flags');
    } finally { if (mountedRef.current) setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);
  // Refresh every 60 s — compliance and financial data is not real-time.
  usePolling(load, 60_000);

  const toggleFlag = async (name: string, enabled: boolean) => {
    setBusy(name); setMsg('');
    try {
      await superadminApi.setFeatureFlag(name, enabled);
      setFlags(prev => prev.map(f => f.name === name ? { ...f, enabled } : f));
      setMsg(`Flag "${name}" ${enabled ? 'enabled' : 'disabled'}`);
    } catch (e: unknown) {
      setMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Toggle failed');
    } finally { setBusy(null); }
  };

  const loadUserOverrides = async () => {
    if (!userIdInput.trim()) return;
    setOverrideLoading(true); setOverrideMsg('');
    try {
      const res = await superadminApi.userFlagOverrides(userIdInput.trim());
      setUserOverrides(res.data.overrides ?? res.data);
    } catch (e: unknown) {
      setOverrideMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to load overrides');
    } finally { setOverrideLoading(false); }
  };

  const setUserOverride = async (flag: string, enabled: boolean) => {
    setBusy(`user-${flag}`); setOverrideMsg('');
    try {
      await superadminApi.setUserFlagOverride(userIdInput.trim(), flag, enabled);
      setUserOverrides(prev => {
        const exists = prev.find(o => o.flag === flag);
        if (exists) return prev.map(o => o.flag === flag ? { ...o, enabled } : o);
        return [...prev, { flag, enabled }];
      });
      setOverrideMsg(`Override for "${flag}" set to ${enabled ? 'enabled' : 'disabled'}`);
    } catch (e: unknown) {
      setOverrideMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Override failed');
    } finally { setBusy(null); }
  };

  if (loading) return <><LoadingRows rows={8} /></>;
  if (error)   return <><ErrorState message={error} onRetry={load} /></>;

  const enabledCount  = flags.filter(f => f.enabled).length;
  const disabledCount = flags.length - enabledCount;

  return (
    <div style={{ animation: 'sa-fadein 0.2s ease' }}>


      {/* Summary */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 20 }}>
        {[
          { label: 'Total Flags',  value: flags.length,   color: '#3b82f6' },
          { label: 'Enabled',      value: enabledCount,   color: '#22c55e' },
          { label: 'Disabled',     value: disabledCount,  color: '#64748b' },
          { label: 'With Overrides', value: flags.filter(f => f.user_overrides > 0).length, color: '#f59e0b' },
        ].map(s => (
          <div key={s.label} style={{
            flex: 1, background: '#0f172a', border: '1px solid #1e293b',
            borderTop: `3px solid ${s.color}`, borderRadius: 10, padding: '14px 16px',
          }}>
            <div style={{ fontSize: 10, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.07em' }}>{s.label}</div>
            <div style={{ fontSize: 24, fontWeight: 800, color: s.color, marginTop: 4 }}>{s.value}</div>
          </div>
        ))}
      </div>

      {/* Global flags */}
      <SectionCard title="Global Feature Flags" icon="🚩" accent="#3b82f6"
        subtitle="Changes take effect immediately for all users"
        actions={<ActionBtn label="Refresh" onClick={load} icon="🔄" size="sm" />}>
        {flags.map(flag => (
          <div key={flag.name} style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '12px 0', borderBottom: '1px solid #1e293b',
          }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: '#f1f5f9' }}>{flag.name}</span>
                {flag.user_overrides > 0 && (
                  <span style={{
                    fontSize: 10, fontWeight: 700, color: '#fbbf24',
                    background: '#78350f', border: '1px solid #d97706',
                    borderRadius: 4, padding: '1px 6px',
                  }}>
                    {flag.user_overrides} override{flag.user_overrides !== 1 ? 's' : ''}
                  </span>
                )}
                {flag.rollout_pct < 100 && flag.enabled && (
                  <span style={{
                    fontSize: 10, fontWeight: 700, color: '#60a5fa',
                    background: '#1e3a5f', border: '1px solid #1d4ed8',
                    borderRadius: 4, padding: '1px 6px',
                  }}>
                    {flag.rollout_pct}% rollout
                  </span>
                )}
              </div>
              <div style={{ fontSize: 11, color: '#475569', marginTop: 2 }}>{flag.description}</div>
              <div style={{ fontSize: 10, color: '#334155', marginTop: 1, fontFamily: 'monospace' }}>{flag.env_var}</div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginLeft: 16 }}>
              {busy === flag.name && (
                <div style={{ width: 14, height: 14, border: '2px solid #334155', borderTopColor: '#60a5fa', borderRadius: '50%', animation: 'sa-spin 0.7s linear infinite' }} />
              )}
              <div
                role="switch"
                aria-checked={flag.enabled}
                tabIndex={0}
                onClick={() => !busy && toggleFlag(flag.name, !flag.enabled)}
                onKeyDown={e => !busy && (e.key === 'Enter' || e.key === ' ') && toggleFlag(flag.name, !flag.enabled)}
                style={{
                  width: 44, height: 24, borderRadius: 12, flexShrink: 0,
                  background: flag.enabled ? '#22c55e' : '#374151',
                  position: 'relative', cursor: busy ? 'not-allowed' : 'pointer',
                  transition: 'background 0.2s', opacity: busy === flag.name ? 0.5 : 1,
                }}
              >
                <div style={{
                  position: 'absolute', top: 2, width: 20, height: 20, borderRadius: '50%',
                  background: '#fff', transition: 'transform 0.2s',
                  transform: flag.enabled ? 'translateX(20px)' : 'translateX(2px)',
                  boxShadow: '0 1px 3px rgba(0,0,0,0.4)',
                }} />
              </div>
            </div>
          </div>
        ))}
        {flags.length === 0 && (
          <div style={{ textAlign: 'center', padding: 32, color: '#475569', fontSize: 13 }}>No feature flags configured.</div>
        )}
        {msg && (
          <div style={{
            marginTop: 12, padding: '10px 14px', borderRadius: 8,
            background: msg.includes('failed') ? '#450a0a' : '#052e16',
            color: msg.includes('failed') ? '#f87171' : '#4ade80',
            fontSize: 12, fontWeight: 600,
          }}>
            {msg}
          </div>
        )}
      </SectionCard>

      {/* Per-user overrides */}
      <SectionCard title="Per-User Flag Overrides" icon="👤" accent="#f59e0b"
        subtitle="Override global flags for a specific user">
        <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
          <Input
            placeholder="User ID or username…"
            value={userIdInput}
            onChange={e => setUserIdInput(e.target.value)}
            style={{ flex: 1 }}
          />
          <ActionBtn
            label={overrideLoading ? 'Loading…' : 'Load Overrides'}
            onClick={loadUserOverrides}
            variant="primary"
            loading={overrideLoading}
            disabled={!userIdInput.trim()}
          />
        </div>

        {userOverrides.length > 0 && (
          <div>
            <div style={{ fontSize: 12, color: '#64748b', marginBottom: 10 }}>
              Overrides for user: <span style={{ color: '#60a5fa', fontWeight: 600 }}>{userIdInput}</span>
            </div>
            {flags.map(flag => {
              const override = userOverrides.find(o => o.flag === flag.name);
              const effectiveValue = override !== undefined ? override.enabled : flag.enabled;
              const hasOverride = override !== undefined;
              return (
                <div key={flag.name} style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: '10px 0', borderBottom: '1px solid #1e293b',
                }}>
                  <div>
                    <span style={{ fontSize: 13, color: '#f1f5f9', fontWeight: 500 }}>{flag.name}</span>
                    {hasOverride && (
                      <span style={{ marginLeft: 8, fontSize: 10, color: '#fbbf24', fontWeight: 700 }}>OVERRIDDEN</span>
                    )}
                    <div style={{ fontSize: 11, color: '#475569' }}>
                      Global: {flag.enabled ? 'on' : 'off'} → User: {effectiveValue ? 'on' : 'off'}
                    </div>
                  </div>
                  <div
                    role="switch"
                    aria-checked={effectiveValue}
                    tabIndex={0}
                    onClick={() => !busy && setUserOverride(flag.name, !effectiveValue)}
                    onKeyDown={e => !busy && (e.key === 'Enter' || e.key === ' ') && setUserOverride(flag.name, !effectiveValue)}
                    style={{
                      width: 44, height: 24, borderRadius: 12, flexShrink: 0,
                      background: effectiveValue ? '#f59e0b' : '#374151',
                      position: 'relative', cursor: 'pointer', transition: 'background 0.2s',
                      opacity: busy === `user-${flag.name}` ? 0.5 : 1,
                    }}
                  >
                    <div style={{
                      position: 'absolute', top: 2, width: 20, height: 20, borderRadius: '50%',
                      background: '#fff', transition: 'transform 0.2s',
                      transform: effectiveValue ? 'translateX(20px)' : 'translateX(2px)',
                      boxShadow: '0 1px 3px rgba(0,0,0,0.4)',
                    }} />
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {overrideMsg && (
          <div style={{
            marginTop: 12, padding: '10px 14px', borderRadius: 8,
            background: overrideMsg.includes('failed') ? '#450a0a' : '#052e16',
            color: overrideMsg.includes('failed') ? '#f87171' : '#4ade80',
            fontSize: 12, fontWeight: 600,
          }}>
            {overrideMsg}
          </div>
        )}
      </SectionCard>
    </div>
  );
};

export default FeatureFlagsSection;
