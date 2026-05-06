/**
 * Whitelabel Tenant Management
 *
 * Create and manage prop-firm / reseller tenants:
 * - Create tenant with logo, primary colour, feature flags
 * - Activate / suspend / delete
 * - Generate API key (shown once)
 * - Preview branded dashboard
 */

import React, { useEffect, useState, useCallback, useRef } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../hooks/useApi';
import { PageHeader } from '../components/PageHeader';
import { Badge } from '../components/Badge';
import { useConfirm } from '../components/ConfirmDialog';
import { useToast } from '../components/Toast';

// ─── Types ────────────────────────────────────────────────────────────────────

interface Theme {
  primary_color: string;
  logo_url:      string;
  company_name:  string;
}

interface Tenant {
  tenant_id:    string;
  name:         string;
  owner_email:  string;
  status:       'active' | 'trial' | 'suspended' | 'pending' | 'terminated';
  features:     string[];
  theme:        Theme;
  custom_domain: string | null;
  created_at:   string | null;
  expires_at:   string | null;
  has_api_key:  boolean;
}

const ALL_FEATURES = [
  'trading', 'backtesting', 'social_trading', 'analytics',
  'news', 'alerts', 'api_access', 'custom_branding',
  'white_label', 'risk_management', 'portfolio', 'reporting', 'mobile',
];

// ─── Helpers ──────────────────────────────────────────────────────────────────

const statusColor = (s: string) => ({
  active:     '#4ade80',
  trial:      '#facc15',
  suspended:  '#f87171',
  pending:    '#94a3b8',
  terminated: '#475569',
}[s] ?? '#94a3b8');

// ─── Create Tenant Modal ──────────────────────────────────────────────────────

const CreateModal: React.FC<{
  onCreated: (t: Tenant) => void;
  onClose:   () => void;
}> = ({ onCreated, onClose }) => {
  const [name,         setName]         = useState('');
  const [email,        setEmail]        = useState('');
  const [trialDays,    setTrialDays]    = useState('0');
  const [color,        setColor]        = useState('#3b82f6');
  const [logoUrl,      setLogoUrl]      = useState('');
  const [features,     setFeatures]     = useState<string[]>(['trading', 'risk_management']);
  const [saving,       setSaving]       = useState(false);
  const [error,        setError]        = useState('');

  const toggleFeature = (f: string) =>
    setFeatures((prev) => prev.includes(f) ? prev.filter((x) => x !== f) : [...prev, f]);

  const submit = async () => {
    if (!name.trim() || !email.trim()) { setError('Name and email are required.'); return; }
    setSaving(true);
    try {
      const res = await api.post('/whitelabel/tenants', {
        name, owner_email: email,
        trial_days: parseInt(trialDays) || 0,
        features, primary_color: color, logo_url: logoUrl,
      });
      onCreated(res.data);
    } catch (e: unknown) {
      setError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed to create tenant.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={s.overlay}>
      <div style={s.modal}>
        <div style={s.modalHeader}>
          <span style={{ fontWeight: 700, fontSize: 16 }}>New Whitelabel Tenant</span>
          <button style={s.closeBtn} onClick={onClose}>✕</button>
        </div>

        {error && <div style={s.errorBanner}>{error}</div>}

        <label style={s.fieldLabel}>Company Name *</label>
        <input style={s.textInput} value={name} onChange={(e) => setName(e.target.value)} placeholder="PropFirm Alpha" />

        <label style={s.fieldLabel}>Owner Email *</label>
        <input style={s.textInput} value={email} onChange={(e) => setEmail(e.target.value)} placeholder="admin@propfirm.com" type="email" />

        <label style={s.fieldLabel}>Trial Days (0 = active immediately)</label>
        <input style={s.textInput} value={trialDays} onChange={(e) => setTrialDays(e.target.value)} type="number" min="0" max="365" />

        <label style={s.fieldLabel}>Primary Brand Colour</label>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <input type="color" value={color} onChange={(e) => setColor(e.target.value)}
            style={{ width: 40, height: 36, border: 'none', background: 'none', cursor: 'pointer' }} />
          <input style={{ ...s.textInput, flex: 1 }} value={color} onChange={(e) => setColor(e.target.value)} />
        </div>

        <label style={s.fieldLabel}>Logo URL (optional)</label>
        <input style={s.textInput} value={logoUrl} onChange={(e) => setLogoUrl(e.target.value)} placeholder="https://…" />

        <label style={s.fieldLabel}>Features</label>
        <div style={s.featureGrid}>
          {ALL_FEATURES.map((f) => (
            <label key={f} style={s.featureCheck}>
              <input type="checkbox" checked={features.includes(f)} onChange={() => toggleFeature(f)} />
              <span style={{ marginLeft: 6, fontSize: 12 }}>{f}</span>
            </label>
          ))}
        </div>

        <div style={{ display: 'flex', gap: 8, marginTop: 20 }}>
          <button style={s.saveBtn} onClick={submit} disabled={saving}>
            {saving ? 'Creating…' : 'Create Tenant'}
          </button>
          <button style={s.cancelBtn} onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
};

// ─── Live Branding Preview Panel ─────────────────────────────────────────────

const PreviewPanel: React.FC<{
  tenant:    Tenant;
  onClose:   () => void;
  onSaved:   (t: Tenant) => void;
}> = ({ tenant, onClose, onSaved }) => {
  const [color,       setColor]       = useState(tenant.theme.primary_color);
  const [logoUrl,     setLogoUrl]     = useState(tenant.theme.logo_url ?? '');
  const [companyName, setCompanyName] = useState(tenant.theme.company_name ?? tenant.name);
  const [features,    setFeatures]    = useState<string[]>(tenant.features);
  const [saving,      setSaving]      = useState(false);
  const [saveMsg,     setSaveMsg]     = useState('');

  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [onClose]);

  const toggleFeature = (f: string) =>
    setFeatures(prev => prev.includes(f) ? prev.filter(x => x !== f) : [...prev, f]);

  const handleSave = async () => {
    setSaving(true); setSaveMsg('');
    try {
      const res = await api.patch(`/whitelabel/tenants/${tenant.tenant_id}`, {
        primary_color: color, logo_url: logoUrl, company_name: companyName, features,
      });
      setSaveMsg('✓ Saved');
      onSaved(res.data as Tenant);
      setTimeout(() => setSaveMsg(''), 2500);
    } catch { setSaveMsg('⚠ Save failed'); }
    finally { setSaving(false); }
  };

  return (
    <div style={s.overlay} onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div style={{ ...s.modal, maxWidth: 700, display: 'flex', flexDirection: 'column', gap: 0, padding: 0, overflow: 'hidden' }}>
        <div style={{ ...s.modalHeader, padding: '16px 20px', borderBottom: '1px solid #1e293b' }}>
          <span style={{ fontWeight: 700, fontSize: 16 }}>Live Branding Preview — {tenant.name}</span>
          <button style={s.closeBtn} onClick={onClose}>✕</button>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 0, flex: 1, overflow: 'hidden' }}>
          {/* Left: controls */}
          <div style={{ padding: 20, borderRight: '1px solid #1e293b', overflowY: 'auto' }}>
            <div style={s.fieldLabel}>Brand Colour</div>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 12 }}>
              <input type="color" value={color} onChange={e => setColor(e.target.value)}
                style={{ width: 40, height: 36, border: 'none', background: 'none', cursor: 'pointer' }} />
              <input style={{ ...s.textInput, flex: 1, marginBottom: 0 }} value={color} onChange={e => setColor(e.target.value)} />
            </div>

            <div style={s.fieldLabel}>Company Name</div>
            <input style={s.textInput} value={companyName} onChange={e => setCompanyName(e.target.value)} />

            <div style={s.fieldLabel}>Logo URL</div>
            <input style={s.textInput} value={logoUrl} onChange={e => setLogoUrl(e.target.value)} placeholder="https://…" />

            <div style={s.fieldLabel}>Feature Flags</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {ALL_FEATURES.map(f => (
                <label key={f} style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
                  <div
                    onClick={() => toggleFeature(f)}
                    style={{
                      width: 36, height: 20, borderRadius: 10, cursor: 'pointer', transition: 'background 0.2s',
                      background: features.includes(f) ? color : '#334155', position: 'relative', flexShrink: 0,
                    }}
                  >
                    <div style={{
                      position: 'absolute', top: 2, left: features.includes(f) ? 18 : 2,
                      width: 16, height: 16, borderRadius: '50%', background: '#fff',
                      transition: 'left 0.2s',
                    }} />
                  </div>
                  <span style={{ fontSize: 12, color: features.includes(f) ? '#e2e8f0' : '#64748b' }}>{f}</span>
                </label>
              ))}
            </div>

            <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
              <button onClick={() => void handleSave()} disabled={saving}
                style={{ ...s.saveBtn, flex: 'none', padding: '8px 20px', fontSize: 13 }}>
                {saving ? 'Saving…' : '💾 Save Changes'}
              </button>
              {saveMsg && <span style={{ fontSize: 12, color: saveMsg.startsWith('✓') ? '#22c55e' : '#f87171', alignSelf: 'center' }}>{saveMsg}</span>}
            </div>
          </div>

          {/* Right: live preview */}
          <div style={{ padding: 20, overflowY: 'auto', background: '#060d18' }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 12 }}>Live Preview</div>
            <div style={{ background: '#0f172a', borderRadius: 10, overflow: 'hidden', border: '1px solid #1e293b' }}>
              {/* Nav bar */}
              <div style={{ background: color, padding: '10px 16px', display: 'flex', alignItems: 'center', gap: 10 }}>
                {logoUrl
                  ? <img src={logoUrl} alt="logo" style={{ height: 24, borderRadius: 4 }} onError={e => { (e.target as HTMLImageElement).style.display = 'none'; }} />
                  : <div style={{ width: 24, height: 24, borderRadius: 5, background: 'rgba(255,255,255,0.3)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 800, color: '#fff', fontSize: 11 }}>
                      {companyName.slice(0, 2).toUpperCase()}
                    </div>
                }
                <span style={{ fontWeight: 700, color: '#fff', fontSize: 14 }}>{companyName}</span>
                <span style={{ marginLeft: 'auto', fontSize: 10, color: 'rgba(255,255,255,0.6)' }}>Powered by HOPEFX</span>
              </div>
              {/* KPI cards */}
              <div style={{ padding: 14 }}>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 8, marginBottom: 12 }}>
                  {['Balance', 'P&L', 'Win Rate'].map(label => (
                    <div key={label} style={{ background: '#1e293b', borderRadius: 6, padding: '10px 12px', borderTop: `3px solid ${color}` }}>
                      <div style={{ fontSize: 10, color: '#94a3b8' }}>{label}</div>
                      <div style={{ fontSize: 15, fontWeight: 700, color: '#f8fafc' }}>—</div>
                    </div>
                  ))}
                </div>
                {/* Chart placeholder */}
                <div style={{ background: '#1e293b', borderRadius: 6, padding: 12, height: 60, display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 10 }}>
                  <svg width="100%" height="40" viewBox="0 0 200 40" preserveAspectRatio="none">
                    <polyline points="0,35 30,28 60,20 90,25 120,10 150,18 200,5" fill="none" stroke={color} strokeWidth="2" />
                  </svg>
                </div>
                {/* Feature pills */}
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                  {features.slice(0, 6).map(f => (
                    <span key={f} style={{ fontSize: 9, padding: '2px 6px', borderRadius: 4, background: `${color}22`, color, border: `1px solid ${color}50` }}>{f}</span>
                  ))}
                  {features.length > 6 && <span style={{ fontSize: 9, color: '#475569' }}>+{features.length - 6} more</span>}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

// ─── Tenant Row ───────────────────────────────────────────────────────────────

const TenantRow: React.FC<{
  tenant:    Tenant;
  onAction:  (id: string, action: string) => void;
  onPreview: (t: Tenant) => void;
  onApiKey:  (id: string) => void;
}> = ({ tenant, onAction, onPreview, onApiKey }) => {
  const color = tenant.theme.primary_color;
  return (
    <div style={s.tenantRow}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, flex: 1, minWidth: 0 }}>
        <div style={{
          width: 40, height: 40, borderRadius: 8, flexShrink: 0,
          background: color, display: 'flex', alignItems: 'center',
          justifyContent: 'center', fontWeight: 800, color: '#fff', fontSize: 14,
        }}>
          {tenant.name.slice(0, 2).toUpperCase()}
        </div>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontWeight: 600, fontSize: 14, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {tenant.name}
          </div>
          <div style={{ fontSize: 12, color: '#64748b' }}>{tenant.owner_email}</div>
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span style={{ ...s.statusBadge, color: statusColor(tenant.status), border: `1px solid ${statusColor(tenant.status)}` }}>
          {tenant.status}
        </span>
        <span style={{ fontSize: 12, color: '#64748b' }}>{tenant.features.length} features</span>
      </div>

      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        <button style={s.actionBtn} onClick={() => onPreview(tenant)}>Preview</button>
        <button style={s.actionBtn} onClick={() => onApiKey(tenant.tenant_id)}>
          {tenant.has_api_key ? 'Regen Key' : 'Gen Key'}
        </button>
        {tenant.status === 'suspended'
          ? <button style={{ ...s.actionBtn, color: '#4ade80' }} onClick={() => onAction(tenant.tenant_id, 'activate')}>Activate</button>
          : <button style={{ ...s.actionBtn, color: '#f87171' }} onClick={() => onAction(tenant.tenant_id, 'suspend')}>Suspend</button>
        }
        <button style={{ ...s.actionBtn, color: '#f87171' }} onClick={() => onAction(tenant.tenant_id, 'delete')}>Delete</button>
      </div>
    </div>
  );
};

// ─── Main component ───────────────────────────────────────────────────────────

function extractErrorMessage(err: unknown, fallback: string): string {
  if (err && typeof err === 'object') {
    const e = err as Record<string, unknown>;
    const detail = (e['response'] as Record<string, unknown> | undefined)?.['data'];
    if (detail && typeof detail === 'object') {
      const d = detail as Record<string, unknown>;
      if (typeof d['detail'] === 'string') return d['detail'];
      if (typeof d['message'] === 'string') return d['message'];
    }
    if (typeof e['message'] === 'string') return e['message'];
  }
  return fallback;
}

const WhitelabelAdmin: React.FC = () => {
  const confirm  = useConfirm();
  const toast    = useToast();
  const [tenants,    setTenants]    = useState<Tenant[]>([]);
  const [loading,    setLoading]    = useState(true);
  const [loadErr,    setLoadErr]    = useState<string | null>(null);
  const [actionErr,  setActionErr]  = useState<string | null>(null);
  const [creating,   setCreating]   = useState(false);
  const [preview,    setPreview]    = useState<Tenant | null>(null);
  const [apiKeyMsg,  setApiKeyMsg]  = useState('');
  const [filter,     setFilter]     = useState('all');
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadErr(null);
    try {
      const res = await api.get('/whitelabel/tenants');
      if (!mountedRef.current) return;
      setTenants(res.data.tenants || []);
    } catch (err) {
      if (!mountedRef.current) return;
      setTenants([]);
      setLoadErr(extractErrorMessage(err, 'Failed to load tenants. Ensure the whitelabel API is running.'));
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleAction = async (id: string, action: string) => {
    if (action === 'delete') {
      const ok = await confirm({
        title:        'Delete tenant?',
        description:  'This will permanently remove the tenant, their branding, and API key. This cannot be undone.',
        confirmLabel: 'Delete Tenant',
        variant:      'danger',
      });
      if (!ok) return;
    }
    setActionErr(null);
    try {
      if (action === 'activate') await api.post(`/whitelabel/tenants/${id}/activate`);
      else if (action === 'suspend') await api.post(`/whitelabel/tenants/${id}/suspend`);
      else if (action === 'delete') await api.delete(`/whitelabel/tenants/${id}`);
      toast.success(`Tenant ${action}d successfully.`);
      await load();
    } catch (err) {
      const msg = extractErrorMessage(err, `Action "${action}" failed. Check permissions and try again.`);
      setActionErr(msg);
      toast.error(msg);
    }
  };

  const handleApiKey = async (id: string) => {
    setActionErr(null);
    try {
      const res = await api.post(`/whitelabel/tenants/${id}/api-key`);
      setApiKeyMsg(`API Key (copy now — shown once): ${res.data.api_key}`);
      await load();
    } catch (err) {
      setActionErr(extractErrorMessage(err, 'Failed to generate API key. Check permissions and try again.'));
    }
  };

  const filtered = filter === 'all' ? tenants : tenants.filter((t) => t.status === filter);

  return (
    <div style={s.page}>
      {creating && (
        <CreateModal
          onCreated={(t) => { setTenants((prev) => [t, ...prev]); setCreating(false); }}
          onClose={() => setCreating(false)}
        />
      )}
      {preview && (
        <PreviewPanel
          tenant={preview}
          onClose={() => setPreview(null)}
          onSaved={(updated) => {
            setTenants(prev => prev.map(t => t.tenant_id === updated.tenant_id ? updated : t));
            setPreview(updated);
          }}
        />
      )}}

      {/* Header */}
      <PageHeader
        title="Whitelabel Tenants"
        subtitle="Manage prop-firm and reseller branded deployments."
        breadcrumbs={[
          { label: 'Home',        href: '/home' },
          { label: 'Admin Panel', href: '/admin' },
          { label: 'Whitelabel Admin' },
        ]}
        badge={
          <Badge variant="info" style={{ fontSize: 11 }}>
            {tenants.length} Tenant{tenants.length !== 1 ? 's' : ''}
          </Badge>
        }
        actions={
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <Link to="/superadmin"
              style={{ padding: '7px 14px', background: 'rgba(239,68,68,0.12)', border: '1px solid rgba(239,68,68,0.35)', borderRadius: 7, color: '#f87171', fontSize: 12, fontWeight: 700, cursor: 'pointer', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: 4 }}>
              ⚡ Super Admin
            </Link>
            <Link to="/admin"
              style={{ padding: '7px 14px', background: 'rgba(100,116,139,0.12)', border: '1px solid rgba(100,116,139,0.35)', borderRadius: 7, color: '#94a3b8', fontSize: 12, fontWeight: 700, cursor: 'pointer', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: 4 }}>
              🔧 Admin
            </Link>
            <button style={s.createBtn} onClick={() => setCreating(true)}>+ New Tenant</button>
          </div>
        }
      />

      {/* API key message */}
      {apiKeyMsg && (
        <div style={s.apiKeyBanner}>
          <span>{apiKeyMsg}</span>
          <button style={s.closeBtn} onClick={() => setApiKeyMsg('')}>✕</button>
        </div>
      )}

      {/* Action / load errors */}
      {actionErr && (
        <div style={s.errorBanner}>
          <span>{actionErr}</span>
          <button style={s.closeBtn} onClick={() => setActionErr(null)}>✕</button>
        </div>
      )}
      {loadErr && (
        <div style={s.errorBanner}>
          <span>{loadErr}</span>
          <button style={s.closeBtn} onClick={() => setLoadErr(null)}>✕</button>
        </div>
      )}

      {/* Stats */}
      <div style={s.statsRow}>
        {(['all', 'active', 'trial', 'suspended'] as const).map((f) => {
          const count = f === 'all' ? tenants.length : tenants.filter((t) => t.status === f).length;
          return (
            <button
              key={f}
              style={{ ...s.statCard, ...(filter === f ? { border: '1px solid #3b82f6' } : {}) }}
              onClick={() => setFilter(f)}
            >
              <div style={{ fontSize: 24, fontWeight: 800, color: f === 'all' ? '#f8fafc' : statusColor(f) }}>{count}</div>
              <div style={{ fontSize: 12, color: '#64748b', textTransform: 'capitalize' }}>{f}</div>
            </button>
          );
        })}
      </div>

      {/* Tenant list */}
      <div style={s.card}>
        {loading && <div style={s.dim}>Loading tenants…</div>}
        {!loading && filtered.length === 0 && (
          <div style={s.empty}>No tenants yet. Click "+ New Tenant" to create one.</div>
        )}
        {filtered.map((t) => (
          <TenantRow
            key={t.tenant_id}
            tenant={t}
            onAction={handleAction}
            onPreview={setPreview}
            onApiKey={handleApiKey}
          />
        ))}
      </div>

      {/* Info */}
      <div style={s.infoBanner}>
        <span style={{ color: '#60a5fa', fontWeight: 600 }}>ℹ Prop firm partnerships:</span>
        {' '}Each tenant gets a branded dashboard, their own API key, and configurable feature flags.
        Email FTMO / The5ers / Funded Next with the preview link to close deals.
      </div>

      {/* Cross-links */}
      <div style={{ borderTop: '1px solid #1e293b', paddingTop: 20, marginTop: 8 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 12 }}>
          Related
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 10 }}>
          {[
            { icon: '🔧', label: 'Admin Panel',          desc: 'Platform overview & KPIs',         to: '/admin' },
            { icon: '⚡', label: 'Super Admin',          desc: 'Master control panel',             to: '/superadmin' },
            { icon: '🛡️', label: 'Security Dashboard',  desc: 'Threats, IPs, lockdown controls',  to: '/security' },
            { icon: '🔍', label: 'Audit Log',            desc: 'Full event trail with filters',    to: '/audit' },
            { icon: '🟢', label: 'System Status',        desc: 'Component health & uptime',        to: '/status' },
            { icon: '📖', label: 'Docs',                 desc: 'Platform documentation',           to: '/docs' },
          ].map(({ icon, label, desc, to }) => (
            <Link
              key={to}
              to={to}
              style={{ display: 'flex', alignItems: 'center', gap: 12, background: '#0d1421', border: '1px solid #1e293b', borderRadius: 10, padding: '12px 16px', textDecoration: 'none' }}
              onMouseEnter={e => { (e.currentTarget as HTMLAnchorElement).style.borderColor = '#334155'; (e.currentTarget as HTMLAnchorElement).style.background = '#111827'; }}
              onMouseLeave={e => { (e.currentTarget as HTMLAnchorElement).style.borderColor = '#1e293b'; (e.currentTarget as HTMLAnchorElement).style.background = '#0d1421'; }}
            >
              <span style={{ fontSize: 20, flexShrink: 0 }}>{icon}</span>
              <div>
                <div style={{ fontSize: 13, fontWeight: 600, color: '#f1f5f9' }}>{label}</div>
                <div style={{ fontSize: 11, color: '#64748b', marginTop: 1 }}>{desc}</div>
              </div>
              <span style={{ marginLeft: 'auto', color: '#334155', fontSize: 16 }}>›</span>
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
};

// ─── Styles ───────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  page: {
    minHeight: '100vh', background: '#0f172a', color: '#f8fafc',
    fontFamily: "'Inter', system-ui, sans-serif", padding: '24px',
  },
  header: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
    marginBottom: 24, flexWrap: 'wrap', gap: 12,
  },
  title:    { fontSize: 28, fontWeight: 700, margin: 0 },
  subtitle: { fontSize: 14, color: '#94a3b8', marginTop: 4 },
  createBtn: {
    background: '#3b82f6', border: 'none', borderRadius: 8,
    color: '#fff', padding: '10px 20px', fontSize: 14, cursor: 'pointer', fontWeight: 600,
  },
  statsRow: { display: 'flex', gap: 12, marginBottom: 20, flexWrap: 'wrap' },
  statCard: {
    background: '#1e293b', border: '1px solid #334155', borderRadius: 10,
    padding: '14px 20px', cursor: 'pointer', textAlign: 'center', minWidth: 80,
  },
  card: {
    background: '#1e293b', borderRadius: 12, border: '1px solid #334155',
    overflow: 'hidden', marginBottom: 20,
  },
  tenantRow: {
    display: 'flex', alignItems: 'center', gap: 16, padding: '16px 20px',
    borderBottom: '1px solid #0f172a', flexWrap: 'wrap',
  },
  statusBadge: {
    fontSize: 11, fontWeight: 700, padding: '2px 8px',
    borderRadius: 4, textTransform: 'capitalize',
  },
  actionBtn: {
    background: '#0f172a', border: '1px solid #334155', borderRadius: 6,
    color: '#94a3b8', padding: '5px 10px', fontSize: 12, cursor: 'pointer',
  },
  dim:   { color: '#475569', fontSize: 13, textAlign: 'center', padding: 32 },
  empty: { color: '#475569', fontSize: 14, textAlign: 'center', padding: 48 },
  apiKeyBanner: {
    background: 'rgba(74,222,128,0.1)', border: '1px solid #4ade80', borderRadius: 8,
    padding: '12px 16px', marginBottom: 16, fontSize: 13, color: '#4ade80',
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    wordBreak: 'break-all',
  },
  errorBanner: {
    background: 'rgba(248,113,113,0.1)', border: '1px solid #f87171', borderRadius: 8,
    padding: '12px 16px', marginBottom: 16, fontSize: 13, color: '#f87171',
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    wordBreak: 'break-all',
  },
  infoBanner: {
    background: '#1e293b', borderRadius: 8, padding: '12px 16px',
    fontSize: 13, color: '#94a3b8', border: '1px solid #334155',
  },
  overlay: {
    position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)',
    display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
    padding: 16,
  },
  modal: {
    background: '#1e293b', borderRadius: 16, padding: 28,
    border: '1px solid #334155', width: '100%', maxWidth: 520,
    maxHeight: '90vh', overflowY: 'auto',
  },
  modalHeader: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20,
  },
  closeBtn: {
    background: 'transparent', border: 'none', color: '#64748b', fontSize: 18, cursor: 'pointer',
  },
  fieldLabel: {
    fontSize: 12, color: '#94a3b8', display: 'block', marginBottom: 6, marginTop: 14,
  },
  textInput: {
    width: '100%', background: '#0f172a', border: '1px solid #334155', borderRadius: 8,
    color: '#f8fafc', padding: '10px 12px', fontSize: 14, outline: 'none', boxSizing: 'border-box',
  },
  featureGrid: { display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 4 },
  featureCheck: { display: 'flex', alignItems: 'center', cursor: 'pointer', fontSize: 12, color: '#94a3b8' },
  featurePill: {
    fontSize: 11, padding: '2px 8px', borderRadius: 4,
  },
  saveBtn: {
    flex: 1, background: '#3b82f6', border: 'none', borderRadius: 8,
    color: '#fff', padding: '10px', fontSize: 14, cursor: 'pointer', fontWeight: 600,
  },
  cancelBtn: {
    flex: 1, background: '#334155', border: 'none', borderRadius: 8,
    color: '#94a3b8', padding: '10px', fontSize: 14, cursor: 'pointer',
  },
};

export default WhitelabelAdmin;
