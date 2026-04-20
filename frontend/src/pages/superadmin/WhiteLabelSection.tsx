// superadmin/WhiteLabelSection.tsx
// Tenant management, branding, per-tenant feature flags, usage/billing
import React, { useEffect, useState, useCallback } from 'react';
import { superadminApi } from '../../hooks/useApi';
import { usePolling } from '../../hooks/usePolling';
import {
  SectionCard, StatusBadge, ActionBtn, Input, Select,
  KpiTile, ErrorState, LoadingRows, ConfirmDialog, SAStyles,
} from './ui';
import type { Tenant } from './types';

const fmtMoney = (n: number) =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(n);
const fmtDate = (iso: string) =>
  new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });

interface TenantApiKey { key_id: string; prefix: string; created_at: string; last_used: string | null; active: boolean }
interface TenantUsage  { api_calls_today: number; active_users: number; storage_mb: number; bandwidth_mb: number; trades_today: number }

interface TenantDrawerProps { tenant: Tenant; onClose: () => void; onRefresh: () => void }

const TenantDrawer: React.FC<TenantDrawerProps> = ({ tenant: initial, onClose, onRefresh }) => {
  const [tenant, setTenant]   = useState<Tenant>(initial);
  const [tab, setTab]         = useState<'overview' | 'keys' | 'usage'>('overview');
  const [form, setForm]       = useState({ ...initial.branding, status: initial.status, plan: initial.plan });
  const [keys, setKeys]       = useState<TenantApiKey[]>([]);
  const [usage, setUsage]     = useState<TenantUsage | null>(null);
  const [keysLoading, setKeysLoading]   = useState(false);
  const [usageLoading, setUsageLoading] = useState(false);
  const [saving, setSaving]   = useState(false);
  const [busy, setBusy]       = useState<string | null>(null);
  const [msg, setMsg]         = useState('');
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [suspendConfirm, setSuspendConfirm] = useState(false);

  // Load full tenant detail on mount
  useEffect(() => {
    superadminApi.getTenant(initial.tenant_id)
      .then(r => { setTenant(r.data); setForm({ ...r.data.branding, status: r.data.status, plan: r.data.plan }); })
      .catch(() => {});
  }, [initial.tenant_id]);

  // Load API keys on keys tab
  useEffect(() => {
    if (tab !== 'keys') return;
    setKeysLoading(true);
    superadminApi.tenantApiKeys(tenant.tenant_id)
      .then(r => setKeys(r.data.keys ?? r.data ?? []))
      .catch(() => setKeys([]))
      .finally(() => setKeysLoading(false));
  }, [tab, tenant.tenant_id]);

  // Load usage on usage tab
  useEffect(() => {
    if (tab !== 'usage') return;
    setUsageLoading(true);
    superadminApi.tenantUsage(tenant.tenant_id)
      .then(r => setUsage(r.data))
      .catch(() => setUsage(null))
      .finally(() => setUsageLoading(false));
  }, [tab, tenant.tenant_id]);

  const save = async () => {
    setSaving(true); setMsg('');
    try {
      await superadminApi.updateTenant(tenant.tenant_id, form);
      setMsg('Tenant updated');
      onRefresh();
    } catch (e: unknown) {
      setMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Save failed');
    } finally { setSaving(false); }
  };

  const activate = async () => {
    setBusy('activate'); setMsg('');
    try {
      await superadminApi.activateTenant(tenant.tenant_id);
      setMsg('Tenant activated');
      onRefresh();
    } catch (e: unknown) {
      setMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Activate failed');
    } finally { setBusy(null); }
  };

  const suspend = async () => {
    setBusy('suspend'); setMsg('');
    try {
      await superadminApi.suspendTenant(tenant.tenant_id);
      setMsg('Tenant suspended');
      setSuspendConfirm(false);
      onRefresh();
    } catch (e: unknown) {
      setMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Suspend failed');
    } finally { setBusy(null); }
  };

  const deleteTenant = async () => {
    setBusy('delete'); setMsg('');
    try {
      await superadminApi.deleteTenant(tenant.tenant_id);
      setMsg('Tenant deleted');
      onRefresh();
      setTimeout(onClose, 600);
    } catch (e: unknown) {
      setMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Delete failed');
    } finally { setBusy(null); setDeleteConfirm(false); }
  };

  const rotateKey = async () => {
    setBusy('rotate'); setMsg('');
    try {
      await superadminApi.rotateTenantKey(tenant.tenant_id);
      setMsg('API key rotated — new key active');
      // Reload keys
      setKeysLoading(true);
      superadminApi.tenantApiKeys(tenant.tenant_id)
        .then(r => setKeys(r.data.keys ?? r.data ?? []))
        .catch(() => {})
        .finally(() => setKeysLoading(false));
    } catch (e: unknown) {
      setMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Key rotation failed');
    } finally { setBusy(null); }
  };

  return (
    <>
      {suspendConfirm && (
        <ConfirmDialog title={`Suspend: ${tenant.name}`}
          message="All users under this tenant will be locked out. Their data is preserved."
          confirmLabel="Suspend" variant="danger"
          onConfirm={suspend} onCancel={() => setSuspendConfirm(false)} />
      )}
      {deleteConfirm && (
        <ConfirmDialog title={`Delete Tenant: ${tenant.name}`}
          message="Permanently delete this tenant and all associated data. This cannot be undone."
          confirmLabel="Delete Tenant" variant="danger"
          onConfirm={deleteTenant} onCancel={() => setDeleteConfirm(false)} />
      )}

      <div style={{ position: 'fixed', inset: 0, zIndex: 800, background: 'rgba(0,0,0,0.5)', backdropFilter: 'blur(3px)' }} onClick={onClose} />
      <div style={{ position: 'fixed', right: 0, top: 0, bottom: 0, zIndex: 801, width: 480, background: '#0a1628', borderLeft: '1px solid #1e293b', overflowY: 'auto', padding: 24, animation: 'sa-fadein 0.2s ease' }}>

        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ width: 36, height: 36, borderRadius: 8, background: `${tenant.branding.primary_color}33`, border: `2px solid ${tenant.branding.primary_color}`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 16, fontWeight: 700, color: tenant.branding.primary_color }}>
              {tenant.name[0]}
            </div>
            <div>
              <div style={{ fontSize: 14, fontWeight: 700, color: '#f1f5f9' }}>{tenant.name}</div>
              <div style={{ fontSize: 11, color: '#64748b' }}>{tenant.domain}</div>
            </div>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#64748b', cursor: 'pointer', fontSize: 20 }}>×</button>
        </div>

        {/* Tabs */}
        <div style={{ display: 'flex', gap: 4, marginBottom: 18 }}>
          {(['overview', 'keys', 'usage'] as const).map(t => (
            <button key={t} onClick={() => setTab(t)} style={{ background: tab === t ? '#1e293b' : 'transparent', border: `1px solid ${tab === t ? '#475569' : '#1e293b'}`, borderRadius: 7, color: tab === t ? '#f8fafc' : '#64748b', padding: '6px 14px', fontSize: 12, cursor: 'pointer' }}>
              {{ overview: 'Overview', keys: 'API Keys', usage: 'Usage' }[t]}
            </button>
          ))}
        </div>

        {/* ── TAB: Overview ── */}
        {tab === 'overview' && (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 16 }}>
              {[
                { label: 'Users',   value: tenant.user_count },
                { label: 'Revenue', value: fmtMoney(tenant.monthly_revenue) },
                { label: 'Status',  value: <StatusBadge status={tenant.status} size="sm" /> },
                { label: 'Created', value: fmtDate(tenant.created_at) },
              ].map(m => (
                <div key={m.label} style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: '10px 12px' }}>
                  <div style={{ fontSize: 10, color: '#475569', marginBottom: 3 }}>{m.label}</div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0' }}>{m.value}</div>
                </div>
              ))}
            </div>

            {/* Status + Plan */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 14 }}>
              <Select label="Status" value={form.status} onChange={e => setForm(f => ({ ...f, status: e.target.value as 'active' | 'suspended' | 'trial' }))}
                options={[{ value: 'active', label: 'Active' }, { value: 'trial', label: 'Trial' }, { value: 'suspended', label: 'Suspended' }]} />
              <Select label="Plan" value={form.plan} onChange={e => setForm(f => ({ ...f, plan: e.target.value }))}
                options={[{ value: 'starter', label: 'Starter' }, { value: 'professional', label: 'Professional' }, { value: 'enterprise', label: 'Enterprise' }]} />
            </div>

            {/* Branding */}
            <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 10, padding: 14, marginBottom: 14 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: '#94a3b8', marginBottom: 10 }}>Branding</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                <Input label="Company Name" value={form.company_name ?? ''} onChange={e => setForm(f => ({ ...f, company_name: e.target.value }))} />
                <Input label="Logo URL"     value={form.logo_url ?? ''}     onChange={e => setForm(f => ({ ...f, logo_url: e.target.value }))} />
                <div>
                  <label style={{ fontSize: 12, color: '#94a3b8', display: 'block', marginBottom: 5 }}>Primary Colour</label>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <input type="color" value={form.primary_color ?? '#3b82f6'} onChange={e => setForm(f => ({ ...f, primary_color: e.target.value }))}
                      style={{ width: 40, height: 32, border: '1px solid #334155', borderRadius: 6, cursor: 'pointer', background: 'none' }} />
                    <Input value={form.primary_color ?? ''} onChange={e => setForm(f => ({ ...f, primary_color: e.target.value }))} style={{ flex: 1 }} />
                  </div>
                </div>
              </div>
            </div>

            <ActionBtn label={saving ? 'Saving…' : 'Save Changes'} onClick={save} variant="primary" loading={saving} />

            {/* Danger zone */}
            <div style={{ borderTop: '1px solid #1e293b', marginTop: 16, paddingTop: 14, display: 'flex', flexDirection: 'column', gap: 8 }}>
              {tenant.status === 'suspended'
                ? <ActionBtn label="Activate Tenant" onClick={activate}                      variant="success" icon="✅" loading={busy === 'activate'} />
                : <ActionBtn label="Suspend Tenant"  onClick={() => setSuspendConfirm(true)} variant="warning" icon="��" loading={busy === 'suspend'} />
              }
              <ActionBtn label="Delete Tenant" onClick={() => setDeleteConfirm(true)} variant="danger" icon="🗑️" loading={busy === 'delete'} />
            </div>
          </>
        )}

        {/* ── TAB: API Keys ── */}
        {tab === 'keys' && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12 }}>
              <ActionBtn label="Rotate Key" onClick={rotateKey} loading={busy === 'rotate'} variant="warning" icon="🔄" size="sm" />
            </div>
            {keysLoading ? (
              <div style={{ color: '#475569', fontSize: 13, padding: 24 }}>Loading keys…</div>
            ) : keys.length === 0 ? (
              <div style={{ color: '#475569', fontSize: 13, textAlign: 'center', padding: 24 }}>No API keys found.</div>
            ) : (
              keys.map(k => (
                <div key={k.key_id} style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: '12px 14px', marginBottom: 8 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontFamily: 'monospace', fontSize: 12, color: '#a78bfa' }}>{k.prefix}…</span>
                    <span style={{ fontSize: 11, fontWeight: 700, color: k.active ? '#4ade80' : '#f87171' }}>{k.active ? 'Active' : 'Revoked'}</span>
                  </div>
                  <div style={{ fontSize: 11, color: '#475569', marginTop: 4 }}>
                    Created: {fmtDate(k.created_at)} · Last used: {k.last_used ? fmtDate(k.last_used) : 'Never'}
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {/* ── TAB: Usage ── */}
        {tab === 'usage' && (
          <div>
            {usageLoading ? (
              <div style={{ color: '#475569', fontSize: 13, padding: 24 }}>Loading usage…</div>
            ) : !usage ? (
              <div style={{ color: '#475569', fontSize: 13, textAlign: 'center', padding: 24 }}>No usage data available.</div>
            ) : (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                {[
                  { label: 'API Calls Today',  value: usage.api_calls_today.toLocaleString(), icon: '🔌', color: '#3b82f6' },
                  { label: 'Active Users',     value: usage.active_users,                    icon: '👥', color: '#22c55e' },
                  { label: 'Storage',          value: `${usage.storage_mb.toFixed(1)} MB`,   icon: '💾', color: '#f59e0b' },
                  { label: 'Bandwidth',        value: `${usage.bandwidth_mb.toFixed(1)} MB`, icon: '📡', color: '#8b5cf6' },
                  { label: 'Trades Today',     value: usage.trades_today.toLocaleString(),   icon: '📊', color: '#06b6d4' },
                ].map(m => (
                  <div key={m.label} style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 10, padding: '14px 16px' }}>
                    <div style={{ fontSize: 12, color: '#475569', marginBottom: 6 }}>{m.icon} {m.label}</div>
                    <div style={{ fontSize: 20, fontWeight: 700, color: m.color }}>{m.value}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {msg && (
          <div style={{ marginTop: 14, padding: '10px 14px', borderRadius: 8, background: msg.includes('fail') ? '#450a0a' : '#052e16', color: msg.includes('fail') ? '#f87171' : '#4ade80', fontSize: 12, fontWeight: 600 }}>
            {msg}
          </div>
        )}
      </div>
    </>
  );
};

// ── Create Tenant Form ────────────────────────────────────────────────────────

interface CreateTenantFormProps { onClose: () => void; onCreated: () => void }

const CreateTenantForm: React.FC<CreateTenantFormProps> = ({ onClose, onCreated }) => {
  const [form, setForm] = useState({ name: '', domain: '', plan: 'starter', company_name: '', primary_color: '#3b82f6' });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');
  const set = (k: keyof typeof form, v: string) => setForm(f => ({ ...f, [k]: v }));

  const create = async () => {
    if (!form.name.trim() || !form.domain.trim()) { setErr('Name and domain are required'); return; }
    setSaving(true); setErr('');
    try {
      await superadminApi.createTenant({ ...form });
      onCreated();
      onClose();
    } catch (e: unknown) {
      setErr((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Create failed');
    } finally { setSaving(false); }
  };

  return (
    <>
      <div style={{ position: 'fixed', inset: 0, zIndex: 800, background: 'rgba(0,0,0,0.5)', backdropFilter: 'blur(3px)' }} onClick={onClose} />
      <div style={{ position: 'fixed', left: '50%', top: '50%', transform: 'translate(-50%,-50%)', zIndex: 801, width: 420, background: '#0a1628', border: '1px solid #1e293b', borderRadius: 14, padding: 28, animation: 'sa-fadein 0.2s ease' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: '#f8fafc' }}>Create New Tenant</h3>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#64748b', cursor: 'pointer', fontSize: 20 }}>×</button>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <Input label="Tenant Name *"   value={form.name}         onChange={e => set('name', e.target.value)}         placeholder="Acme Capital" />
          <Input label="Domain *"        value={form.domain}       onChange={e => set('domain', e.target.value)}       placeholder="app.acmecapital.com" />
          <Input label="Company Name"    value={form.company_name} onChange={e => set('company_name', e.target.value)} placeholder="Acme Capital Ltd" />
          <Select label="Plan" value={form.plan} onChange={e => set('plan', e.target.value)}
            options={[{ value: 'starter', label: 'Starter' }, { value: 'professional', label: 'Professional' }, { value: 'enterprise', label: 'Enterprise' }]} />
          <div>
            <label style={{ fontSize: 12, color: '#94a3b8', display: 'block', marginBottom: 5 }}>Primary Colour</label>
            <div style={{ display: 'flex', gap: 8 }}>
              <input type="color" value={form.primary_color} onChange={e => set('primary_color', e.target.value)}
                style={{ width: 40, height: 32, border: '1px solid #334155', borderRadius: 6, cursor: 'pointer', background: 'none' }} />
              <Input value={form.primary_color} onChange={e => set('primary_color', e.target.value)} style={{ flex: 1 }} />
            </div>
          </div>
        </div>
        {err && <div style={{ marginTop: 12, padding: '8px 12px', borderRadius: 6, background: '#450a0a', color: '#f87171', fontSize: 12 }}>{err}</div>}
        <div style={{ display: 'flex', gap: 8, marginTop: 20 }}>
          <ActionBtn label="Cancel" onClick={onClose} variant="ghost" style={{ flex: 1 }} />
          <ActionBtn label={saving ? 'Creating…' : 'Create Tenant'} onClick={create} variant="primary" loading={saving} style={{ flex: 2 }} />
        </div>
      </div>
    </>
  );
};

// ── Main section ──────────────────────────────────────────────────────────────

const WhiteLabelSection: React.FC = () => {
  const [tenants, setTenants]   = useState<Tenant[]>([]);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState('');
  const [selected, setSelected] = useState<Tenant | null>(null);
  const [creating, setCreating] = useState(false);
  const [search, setSearch]     = useState('');

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const res = await superadminApi.tenants({ search });
      setTenants(res.data.tenants ?? res.data);
    } catch (e: unknown) {
      setError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to load tenants');
    } finally { setLoading(false); }
  }, [search]);

  useEffect(() => { load(); }, [load]);
  // Refresh every 60 s — compliance and financial data is not real-time.
  usePolling(load, 60_000);

  const activeCount  = tenants.filter(t => t.status === 'active').length;
  const trialCount   = tenants.filter(t => t.status === 'trial').length;
  const totalRevenue = tenants.reduce((s, t) => s + t.monthly_revenue, 0);
  const totalUsers   = tenants.reduce((s, t) => s + t.user_count, 0);

  if (loading) return <><SAStyles /><LoadingRows rows={6} /></>;
  if (error)   return <><SAStyles /><ErrorState message={error} onRetry={load} /></>;

  return (
    <div style={{ animation: 'sa-fadein 0.2s ease' }}>
      <SAStyles />
      {selected  && <TenantDrawer    tenant={selected} onClose={() => setSelected(null)} onRefresh={load} />}
      {creating  && <CreateTenantForm onClose={() => setCreating(false)} onCreated={load} />}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12, marginBottom: 20 }}>
        <KpiTile label="Active Tenants"  value={activeCount}           icon="🏢" accent="#22c55e" />
        <KpiTile label="Trial"           value={trialCount}            icon="🔬" accent="#f59e0b" />
        <KpiTile label="Total Users"     value={totalUsers}            icon="👥" accent="#3b82f6" />
        <KpiTile label="Monthly Revenue" value={fmtMoney(totalRevenue)} icon="💰" accent="#8b5cf6" />
      </div>

      <SectionCard title="White-Label Tenants" icon="🏷️" accent="#8b5cf6"
        subtitle="Manage all white-label deployments"
        actions={
          <div style={{ display: 'flex', gap: 8 }}>
            <Input placeholder="Search tenants…" value={search} onChange={e => setSearch(e.target.value)} style={{ width: 200 }} />
            <ActionBtn label="+ New Tenant" onClick={() => setCreating(true)} variant="primary" size="sm" icon="➕" />
            <ActionBtn label="Refresh"      onClick={load} icon="🔄" size="sm" />
          </div>
        }>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 14 }}>
          {tenants.map(t => (
            <div key={t.tenant_id} className="sa-row" onClick={() => setSelected(t)}
              style={{ background: '#1e293b', borderRadius: 12, padding: '16px 18px', border: '1px solid #334155', cursor: 'pointer', transition: 'border-color 0.15s' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <div style={{ width: 36, height: 36, borderRadius: 8, background: t.branding.primary_color + '33', border: `2px solid ${t.branding.primary_color}`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 16, fontWeight: 700, color: t.branding.primary_color }}>
                    {t.name[0]}
                  </div>
                  <div>
                    <div style={{ fontSize: 14, fontWeight: 700, color: '#f1f5f9' }}>{t.name}</div>
                    <div style={{ fontSize: 11, color: '#475569' }}>{t.domain}</div>
                  </div>
                </div>
                <StatusBadge status={t.status} size="sm" />
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 6 }}>
                {[
                  { label: 'Users',   value: t.user_count },
                  { label: 'Revenue', value: fmtMoney(t.monthly_revenue) },
                  { label: 'Plan',    value: t.plan },
                ].map(m => (
                  <div key={m.label} style={{ background: '#0f172a', borderRadius: 6, padding: '6px 8px' }}>
                    <div style={{ fontSize: 10, color: '#475569' }}>{m.label}</div>
                    <div style={{ fontSize: 12, fontWeight: 600, color: '#94a3b8' }}>{m.value}</div>
                  </div>
                ))}
              </div>
            </div>
          ))}
          {tenants.length === 0 && <div style={{ color: '#475569', fontSize: 13, padding: '16px 0' }}>No tenants found.</div>}
        </div>
      </SectionCard>
    </div>
  );
};

export default WhiteLabelSection;
