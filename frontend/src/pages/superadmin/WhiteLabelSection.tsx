// superadmin/WhiteLabelSection.tsx
// Tenant management, branding, per-tenant feature flags, usage/billing
import React, { useEffect, useState, useCallback, useRef } from 'react';
import { superadminApi } from '../../hooks/useApi';
import { usePolling } from '../../hooks/usePolling';
import { EmptyState } from '../../components/EmptyState';
import {
  SectionCard, StatusBadge, ActionBtn, Input, Select,
  KpiTile, ErrorState, LoadingRows, ConfirmDialog,
} from './ui';
import type { Tenant } from './types';
import { asArray, extractApiError } from '../../lib/utils';
import { ActionBanner } from '../../components/ActionBanner';
import { Banknote, BarChart3, Building2, CheckCircle2, KeyRound, Microscope, Plug, Plus, Radio, RefreshCw, Save, Tag, Trash2, Users } from 'lucide-react';

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
  const [msgOk, setMsgOk] = useState(true);
  const [deleteConfirm, setDeleteConfirm] = useState(false);
  const [suspendConfirm, setSuspendConfirm] = useState(false);

  // Load full tenant detail on mount
  useEffect(() => {
    superadminApi.getTenant(initial.tenant_id)
      .then(r => {
        const t = r.data.tenant ?? r.data;
        setTenant(t);
        setForm({ ...t.branding, status: t.status, plan: t.plan });
      })
      .catch(() => {});
  }, [initial.tenant_id]);

  // Load API keys on keys tab
  useEffect(() => {
    if (tab !== 'keys') return;
    setKeysLoading(true);
    superadminApi.tenantApiKeys(tenant.tenant_id)
      .then(r => setKeys(r.data.api_keys ?? r.data.keys ?? r.data ?? []))
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
      setMsgOk(true);
      setMsg('Tenant updated');
      onRefresh();
    } catch (e: unknown) {
      setMsgOk(false);
      setMsg(extractApiError(e, 'Save failed'));
    } finally { setSaving(false); }
  };

  const activate = async () => {
    setBusy('activate'); setMsg('');
    try {
      await superadminApi.activateTenant(tenant.tenant_id);
      setMsgOk(true);
      setMsg('Tenant activated');
      onRefresh();
    } catch (e: unknown) {
      setMsgOk(false);
      setMsg(extractApiError(e, 'Activate failed'));
    } finally { setBusy(null); }
  };

  const suspend = async () => {
    setBusy('suspend'); setMsg('');
    try {
      await superadminApi.suspendTenant(tenant.tenant_id);
      setMsgOk(true);
      setMsg('Tenant suspended');
      setSuspendConfirm(false);
      onRefresh();
    } catch (e: unknown) {
      setMsgOk(false);
      setMsg(extractApiError(e, 'Suspend failed'));
    } finally { setBusy(null); }
  };

  const deleteTenant = async () => {
    setBusy('delete'); setMsg('');
    try {
      await superadminApi.deleteTenant(tenant.tenant_id);
      setMsgOk(true);
      setMsg('Tenant deleted');
      onRefresh();
      setTimeout(onClose, 600);
    } catch (e: unknown) {
      setMsgOk(false);
      setMsg(extractApiError(e, 'Delete failed'));
    } finally { setBusy(null); setDeleteConfirm(false); }
  };

  const rotateKey = async () => {
    setBusy('rotate'); setMsg('');
    try {
      await superadminApi.rotateTenantKey(tenant.tenant_id);
      setMsgOk(true);
      setMsg('API key rotated — new key active');
      // Reload keys
      setKeysLoading(true);
      superadminApi.tenantApiKeys(tenant.tenant_id)
        .then(r => setKeys(r.data.api_keys ?? r.data.keys ?? r.data ?? []))
        .catch(() => {})
        .finally(() => setKeysLoading(false));
    } catch (e: unknown) {
      setMsgOk(false);
      setMsg(extractApiError(e, 'Key rotation failed'));
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
      <div style={{ position: 'fixed', right: 0, top: 0, bottom: 0, zIndex: 801, width: 480, background: '#0a1628', borderLeft: '1px solid var(--border)', overflowY: 'auto', padding: 24, animation: 'sa-fadein 0.2s ease' }}>

        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ width: 36, height: 36, borderRadius: 8, background: `${tenant.branding.primary_color}33`, border: `2px solid ${tenant.branding.primary_color}`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 16, fontWeight: 700, color: tenant.branding.primary_color }}>
              {tenant.name[0]}
            </div>
            <div>
              <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-strong)' }}>{tenant.name}</div>
              <div style={{ fontSize: 'var(--fs-label)', color: 'var(--text-muted)' }}>{tenant.domain}</div>
            </div>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 20 }}>×</button>
        </div>

        {/* Tabs */}
        <div style={{ display: 'flex', gap: 4, marginBottom: 18 }}>
          {(['overview', 'keys', 'usage'] as const).map(t => (
            <button key={t} onClick={() => setTab(t)} style={{ background: tab === t ? 'var(--raised)' : 'transparent', border: `1px solid ${tab === t ? '#475569' : '#1e293b'}`, borderRadius: 7, color: tab === t ? 'var(--text-strong)' : 'var(--text-muted)', padding: '6px 14px', fontSize: 'var(--fs-body)', cursor: 'pointer' }}>
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
                <div key={m.label} style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 12px' }}>
                  <div style={{ fontSize: 'var(--fs-micro)', color: 'var(--text-faint)', marginBottom: 3 }}>{m.label}</div>
                  <div style={{ fontSize: 'var(--fs-body)', fontWeight: 600, color: 'var(--text)' }}>{m.value}</div>
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
            <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, marginBottom: 14 }}>
              <div style={{ fontSize: 'var(--fs-label)', fontWeight: 600, color: 'var(--text-dim)', marginBottom: 10 }}>Branding</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                <Input label="Company Name" value={form.company_name ?? ''} onChange={e => setForm(f => ({ ...f, company_name: e.target.value }))} />
                <Input label="Logo URL"     value={form.logo_url ?? ''}     onChange={e => setForm(f => ({ ...f, logo_url: e.target.value }))} />
                <div>
                  <label id="sa-whitelabel-primary-colour-label" style={{ fontSize: 'var(--fs-body)', color: 'var(--text-dim)', display: 'block', marginBottom: 5 }}>Primary Colour</label>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <input type="color" value={form.primary_color ?? '#3b82f6'} onChange={e => setForm(f => ({ ...f, primary_color: e.target.value }))}
                      aria-labelledby="sa-whitelabel-primary-colour-label"
                      style={{ width: 40, height: 32, border: '1px solid var(--border-strong)', borderRadius: 6, cursor: 'pointer', background: 'none' }} />
                    <Input value={form.primary_color ?? ''} onChange={e => setForm(f => ({ ...f, primary_color: e.target.value }))} style={{ flex: 1 }} />
                  </div>
                </div>
              </div>
            </div>

            <ActionBtn label={saving ? 'Saving…' : 'Save Changes'} onClick={save} variant="primary" loading={saving} />

            {/* Danger zone */}
            <div style={{ borderTop: '1px solid var(--border)', marginTop: 16, paddingTop: 14, display: 'flex', flexDirection: 'column', gap: 8 }}>
              {tenant.status === 'suspended'
                ? <ActionBtn label="Activate Tenant" onClick={activate}                      variant="success" icon={<CheckCircle2 size={18} aria-hidden />} loading={busy === 'activate'} />
                : <ActionBtn label="Suspend Tenant"  onClick={() => setSuspendConfirm(true)} variant="warning" icon="��" loading={busy === 'suspend'} />
              }
              <ActionBtn label="Delete Tenant" onClick={() => setDeleteConfirm(true)} variant="danger" icon={<Trash2 size={18} aria-hidden />} loading={busy === 'delete'} />
            </div>
          </>
        )}

        {/* ── TAB: API Keys ── */}
        {tab === 'keys' && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 12 }}>
              <ActionBtn label="Rotate Key" onClick={rotateKey} loading={busy === 'rotate'} variant="warning" icon={<RefreshCw size={18} aria-hidden />} size="sm" />
            </div>
            {keysLoading ? (
              <div style={{ color: 'var(--text-faint)', fontSize: 'var(--fs-body)', padding: 24 }}>Loading keys…</div>
            ) : keys.length === 0 ? (
              <EmptyState compact icon={KeyRound} title="No API keys found" description="Tenant API keys will appear here once generated." />
            ) : (
              keys.map(k => (
                <div key={k.key_id} style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 8, padding: '12px 14px', marginBottom: 8 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontFamily: 'monospace', fontSize: 'var(--fs-body)', color: 'var(--ai-model)' }}>{k.prefix}…</span>
                    <span style={{ fontSize: 'var(--fs-label)', fontWeight: 700, color: k.active ? 'var(--gain)' : 'var(--loss)' }}>{k.active ? 'Active' : 'Revoked'}</span>
                  </div>
                  <div style={{ fontSize: 'var(--fs-label)', color: 'var(--text-faint)', marginTop: 4 }}>
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
              <div style={{ color: 'var(--text-faint)', fontSize: 'var(--fs-body)', padding: 24 }}>Loading usage…</div>
            ) : !usage ? (
              <div style={{ color: 'var(--text-faint)', fontSize: 'var(--fs-body)', textAlign: 'center', padding: 24 }}>No usage data available.</div>
            ) : (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                {[
                  { label: 'API Calls Today',  value: (usage.api_calls_today ?? 0).toLocaleString(), icon: <Plug size={16} aria-hidden />, color: '#3b82f6' },
                  { label: 'Active Users',     value: usage.active_users ?? 0,                       icon: <Users size={16} aria-hidden />, color: '#22c55e' },
                  { label: 'Storage',          value: `${(usage.storage_mb ?? 0).toFixed(1)} MB`,    icon: <Save size={16} aria-hidden />, color: '#f59e0b' },
                  { label: 'Bandwidth',        value: `${(usage.bandwidth_mb ?? 0).toFixed(1)} MB`,  icon: <Radio size={16} aria-hidden />, color: '#8b5cf6' },
                  { label: 'Trades Today',     value: (usage.trades_today ?? 0).toLocaleString(),    icon: <BarChart3 size={16} aria-hidden />, color: '#06b6d4' },
                ].map(m => (
                  <div key={m.label} style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 10, padding: '14px 16px' }}>
                    <div style={{ fontSize: 'var(--fs-body)', color: 'var(--text-faint)', marginBottom: 6 }}>{m.icon} {m.label}</div>
                    <div style={{ fontSize: 20, fontWeight: 700, color: m.color }}>{m.value}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        <ActionBanner message={msg} ok={msgOk} />
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
      setErr(extractApiError(e, 'Create failed'));
    } finally { setSaving(false); }
  };

  return (
    <>
      <div style={{ position: 'fixed', inset: 0, zIndex: 800, background: 'rgba(0,0,0,0.5)', backdropFilter: 'blur(3px)' }} onClick={onClose} />
      <div style={{ position: 'fixed', left: '50%', top: '50%', transform: 'translate(-50%,-50%)', zIndex: 801, width: 420, background: '#0a1628', border: '1px solid var(--border)', borderRadius: 14, padding: 28, animation: 'sa-fadein 0.2s ease' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: 'var(--text-strong)' }}>Create New Tenant</h3>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 20 }}>×</button>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <Input label="Tenant Name *"   value={form.name}         onChange={e => set('name', e.target.value)}         placeholder="Acme Capital" />
          <Input label="Domain *"        value={form.domain}       onChange={e => set('domain', e.target.value)}       placeholder="app.acmecapital.com" />
          <Input label="Company Name"    value={form.company_name} onChange={e => set('company_name', e.target.value)} placeholder="Acme Capital Ltd" />
          <Select label="Plan" value={form.plan} onChange={e => set('plan', e.target.value)}
            options={[{ value: 'starter', label: 'Starter' }, { value: 'professional', label: 'Professional' }, { value: 'enterprise', label: 'Enterprise' }]} />
          <div>
            <label id="sa-whitelabel-create-colour-label" style={{ fontSize: 'var(--fs-body)', color: 'var(--text-dim)', display: 'block', marginBottom: 5 }}>Primary Colour</label>
            <div style={{ display: 'flex', gap: 8 }}>
              <input type="color" value={form.primary_color} onChange={e => set('primary_color', e.target.value)}
                aria-labelledby="sa-whitelabel-create-colour-label"
                style={{ width: 40, height: 32, border: '1px solid var(--border-strong)', borderRadius: 6, cursor: 'pointer', background: 'none' }} />
              <Input value={form.primary_color} onChange={e => set('primary_color', e.target.value)} style={{ flex: 1 }} />
            </div>
          </div>
        </div>
        {err && <div style={{ marginTop: 12, padding: '8px 12px', borderRadius: 6, background: '#450a0a', color: 'var(--loss)', fontSize: 'var(--fs-body)'}}>{err}</div>}
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

  const mountedRef = useRef(true);
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const res = await superadminApi.tenants({ search });
      if (!mountedRef.current) return;
      setTenants(asArray(res.data, 'tenants'));
    } catch (e: unknown) {
      if (!mountedRef.current) return;
      setError(extractApiError(e, 'Failed to load tenants'));
    } finally { if (mountedRef.current) setLoading(false); }
  }, [search]);

  useEffect(() => { load(); }, [load]);
  // Refresh every 60 s — compliance and financial data is not real-time.
  usePolling(load, 60_000);

  const activeCount  = tenants.filter(t => t.status === 'active').length;
  const trialCount   = tenants.filter(t => t.status === 'trial').length;
  const totalRevenue = tenants.reduce((s, t) => s + t.monthly_revenue, 0);
  const totalUsers   = tenants.reduce((s, t) => s + t.user_count, 0);

  if (loading) return <><LoadingRows rows={6} /></>;
  if (error)   return <><ErrorState message={error} onRetry={load} /></>;

  return (
    <div style={{ animation: 'sa-fadein 0.2s ease' }}>

      {selected  && <TenantDrawer    tenant={selected} onClose={() => setSelected(null)} onRefresh={load} />}
      {creating  && <CreateTenantForm onClose={() => setCreating(false)} onCreated={load} />}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12, marginBottom: 20 }}>
        <KpiTile label="Active Tenants"  value={activeCount}           icon={<Building2 size={18} aria-hidden />} accent="#22c55e" />
        <KpiTile label="Trial"           value={trialCount}            icon={<Microscope size={18} aria-hidden />} accent="#f59e0b" />
        <KpiTile label="Total Users"     value={totalUsers}            icon={<Users size={18} aria-hidden />} accent="#3b82f6" />
        <KpiTile label="Monthly Revenue" value={fmtMoney(totalRevenue)} icon={<Banknote size={18} aria-hidden />} accent="#8b5cf6" />
      </div>

      <SectionCard title="White-Label Tenants" icon={<Tag size={18} aria-hidden />} accent="#8b5cf6"
        subtitle="Manage all white-label deployments"
        actions={
          <div style={{ display: 'flex', gap: 8 }}>
            <Input placeholder="Search tenants…" value={search} onChange={e => setSearch(e.target.value)} style={{ width: 200 }} />
            <ActionBtn label="+ New Tenant" onClick={() => setCreating(true)} variant="primary" size="sm" icon={<Plus size={18} aria-hidden />} />
            <ActionBtn label="Refresh"      onClick={load} icon={<RefreshCw size={18} aria-hidden />} size="sm" />
          </div>
        }>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 14 }}>
          {tenants.map(t => (
            <div key={t.tenant_id} className="sa-row" onClick={() => setSelected(t)}
              style={{ background: 'var(--raised)', borderRadius: 12, padding: '16px 18px', border: '1px solid var(--border-strong)', cursor: 'pointer', transition: 'border-color 0.15s' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <div style={{ width: 36, height: 36, borderRadius: 8, background: t.branding.primary_color + '33', border: `2px solid ${t.branding.primary_color}`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 16, fontWeight: 700, color: t.branding.primary_color }}>
                    {t.name[0]}
                  </div>
                  <div>
                    <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-strong)' }}>{t.name}</div>
                    <div style={{ fontSize: 'var(--fs-label)', color: 'var(--text-faint)' }}>{t.domain}</div>
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
                  <div key={m.label} style={{ background: 'var(--surface)', borderRadius: 6, padding: '6px 8px' }}>
                    <div style={{ fontSize: 'var(--fs-micro)', color: 'var(--text-faint)' }}>{m.label}</div>
                    <div style={{ fontSize: 'var(--fs-body)', fontWeight: 600, color: 'var(--text-dim)' }}>{m.value}</div>
                  </div>
                ))}
              </div>
            </div>
          ))}
          {tenants.length === 0 && <EmptyState compact icon={Tag} title="No tenants found" description="Create a whitelabel tenant to deploy a branded instance." links={[{ label: 'Whitelabel Admin', href: '/whitelabel', icon: <Tag size={16} aria-hidden /> }]} />}
        </div>
      </SectionCard>
    </div>
  );
};

export default WhiteLabelSection;
