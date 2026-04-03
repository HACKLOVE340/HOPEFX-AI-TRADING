// superadmin/WhiteLabelSection.tsx
// Tenant management, branding, per-tenant feature flags, usage/billing
import React, { useEffect, useState, useCallback } from 'react';
import { superadminApi } from '../../hooks/useApi';
import {
  SectionCard, StatusBadge, ActionBtn, Input, Select, Toggle,
  KpiTile, ErrorState, LoadingRows, ConfirmDialog, SAStyles,
} from './ui';
import type { Tenant } from './types';

const fmtMoney = (n: number) =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(n);
const fmtDate = (iso: string) =>
  new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });

interface TenantDrawerProps { tenant: Tenant; onClose: () => void; onRefresh: () => void }

const TenantDrawer: React.FC<TenantDrawerProps> = ({ tenant, onClose, onRefresh }) => {
  const [form, setForm]   = useState({ ...tenant.branding, status: tenant.status, plan: tenant.plan });
  const [saving, setSaving] = useState(false);
  const [msg, setMsg]     = useState('');
  const [confirm, setConfirm] = useState(false);

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

  const suspend = async () => {
    setSaving(true);
    try {
      await superadminApi.suspendTenant(tenant.tenant_id);
      setMsg('Tenant suspended');
      setConfirm(false);
      onRefresh();
    } catch (e: unknown) {
      setMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Suspend failed');
    } finally { setSaving(false); }
  };

  return (
    <>
      {confirm && (
        <ConfirmDialog
          title={`Suspend Tenant: ${tenant.name}`}
          message="This will immediately disable all users under this tenant. Their data is preserved."
          confirmLabel="Suspend Tenant"
          variant="danger"
          onConfirm={suspend}
          onCancel={() => setConfirm(false)}
        />
      )}
      <div style={{ position: 'fixed', inset: 0, zIndex: 800, background: 'rgba(0,0,0,0.5)', backdropFilter: 'blur(3px)' }} onClick={onClose} />
      <div style={{ position: 'fixed', right: 0, top: 0, bottom: 0, zIndex: 801, width: 440, background: '#0a1628', borderLeft: '1px solid #1e293b', overflowY: 'auto', padding: 24, animation: 'sa-fadein 0.2s ease' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: '#f8fafc' }}>{tenant.name}</h3>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#64748b', cursor: 'pointer', fontSize: 20 }}>×</button>
        </div>

        {/* Stats */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 16 }}>
          {[
            { label: 'Users',    value: tenant.user_count },
            { label: 'Revenue',  value: fmtMoney(tenant.monthly_revenue) },
            { label: 'Domain',   value: tenant.domain },
            { label: 'Created',  value: fmtDate(tenant.created_at) },
          ].map(m => (
            <div key={m.label} style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: '10px 12px' }}>
              <div style={{ fontSize: 10, color: '#475569', marginBottom: 3 }}>{m.label}</div>
              <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0' }}>{m.value}</div>
            </div>
          ))}
        </div>

        {/* Status + Plan */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 }}>
          <Select label="Status" value={form.status} onChange={e => setForm(f => ({ ...f, status: e.target.value }))}
            options={[{ value: 'active', label: 'Active' }, { value: 'trial', label: 'Trial' }, { value: 'suspended', label: 'Suspended' }]} />
          <Select label="Plan" value={form.plan} onChange={e => setForm(f => ({ ...f, plan: e.target.value }))}
            options={[{ value: 'starter', label: 'Starter' }, { value: 'pro', label: 'Pro' }, { value: 'enterprise', label: 'Enterprise' }]} />
        </div>

        {/* Branding */}
        <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 10, padding: 16, marginBottom: 16 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: '#94a3b8', marginBottom: 10 }}>Branding</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <Input label="Company Name" value={form.company_name} onChange={e => setForm(f => ({ ...f, company_name: e.target.value }))} />
            <Input label="Logo URL"     value={form.logo_url}     onChange={e => setForm(f => ({ ...f, logo_url: e.target.value }))} />
            <div>
              <label style={{ fontSize: 12, color: '#94a3b8', fontWeight: 500, display: 'block', marginBottom: 5 }}>Primary Color</label>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <input type="color" value={form.primary_color} onChange={e => setForm(f => ({ ...f, primary_color: e.target.value }))}
                  style={{ width: 40, height: 32, border: '1px solid #334155', borderRadius: 6, cursor: 'pointer', background: 'none' }} />
                <Input value={form.primary_color} onChange={e => setForm(f => ({ ...f, primary_color: e.target.value }))} style={{ flex: 1 }} />
              </div>
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <ActionBtn label={saving ? 'Saving…' : 'Save Changes'} onClick={save} variant="primary" loading={saving} />
          {tenant.status !== 'suspended' && (
            <ActionBtn label="Suspend Tenant" onClick={() => setConfirm(true)} variant="danger" icon="🚫" />
          )}
        </div>

        {msg && (
          <div style={{ marginTop: 14, padding: '10px 14px', borderRadius: 8, background: msg.includes('failed') ? '#450a0a' : '#052e16', color: msg.includes('failed') ? '#f87171' : '#4ade80', fontSize: 12, fontWeight: 600 }}>
            {msg}
          </div>
        )}
      </div>
    </>
  );
};

const WhiteLabelSection: React.FC = () => {
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState('');
  const [selected, setSelected] = useState<Tenant | null>(null);
  const [search, setSearch]   = useState('');
  const [msg, setMsg]         = useState('');

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

  const activeCount    = tenants.filter(t => t.status === 'active').length;
  const trialCount     = tenants.filter(t => t.status === 'trial').length;
  const totalRevenue   = tenants.reduce((s, t) => s + t.monthly_revenue, 0);
  const totalUsers     = tenants.reduce((s, t) => s + t.user_count, 0);

  if (loading) return <><SAStyles /><LoadingRows rows={6} /></>;
  if (error)   return <><SAStyles /><ErrorState message={error} onRetry={load} /></>;

  return (
    <div style={{ animation: 'sa-fadein 0.2s ease' }}>
      <SAStyles />
      {selected && <TenantDrawer tenant={selected} onClose={() => setSelected(null)} onRefresh={load} />}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12, marginBottom: 20 }}>
        <KpiTile label="Active Tenants"  value={activeCount}          icon="🏢" accent="#22c55e" />
        <KpiTile label="Trial"           value={trialCount}           icon="🔬" accent="#f59e0b" />
        <KpiTile label="Total Users"     value={totalUsers}           icon="👥" accent="#3b82f6" />
        <KpiTile label="Monthly Revenue" value={fmtMoney(totalRevenue)} icon="💰" accent="#8b5cf6" />
      </div>

      <SectionCard title="White-Label Tenants" icon="🏷️" accent="#8b5cf6"
        subtitle="Manage all white-label deployments"
        actions={
          <div style={{ display: 'flex', gap: 8 }}>
            <Input placeholder="Search tenants…" value={search} onChange={e => setSearch(e.target.value)} style={{ width: 200 }} />
            <ActionBtn label="Refresh" onClick={load} icon="🔄" size="sm" />
          </div>
        }>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 14 }}>
          {tenants.map(t => (
            <div key={t.tenant_id}
              className="sa-row"
              onClick={() => setSelected(t)}
              style={{ background: '#1e293b', borderRadius: 12, padding: '16px 18px', border: '1px solid #334155', cursor: 'pointer', transition: 'border-color 0.15s' }}
            >
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

      {msg && (
        <div style={{ padding: '12px 16px', borderRadius: 8, marginTop: 4, background: msg.includes('failed') ? '#450a0a' : '#052e16', color: msg.includes('failed') ? '#f87171' : '#4ade80', fontSize: 13, fontWeight: 600 }}>
          {msg}
        </div>
      )}
    </div>
  );
};

export default WhiteLabelSection;
