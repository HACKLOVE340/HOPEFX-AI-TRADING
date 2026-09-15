/**
 * Whitelabel Tenant Management
 *
 * Create and manage prop-firm / reseller tenants:
 * - Create tenant with logo, primary colour, feature flags
 * - Activate / suspend / delete
 * - Generate API key (shown once)
 * - Preview branded dashboard
 */

import { PageShell } from '../components/system/PageShell';
import React, { useEffect, useState, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../hooks/useApi';
import { extractApiError } from '../lib/utils';

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
      setError(extractApiError(e, 'Failed to create tenant.'));
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

        <label id="whitelabeladmin-company-name-label" htmlFor="whitelabeladmin-company-name" style={s.fieldLabel}>Company Name *</label>
        <input id="whitelabeladmin-company-name" aria-labelledby="whitelabeladmin-company-name-label" style={s.textInput} value={name} onChange={(e) => setName(e.target.value)} placeholder="PropFirm Alpha" />

        <label id="whitelabeladmin-owner-email-label" htmlFor="whitelabeladmin-owner-email" style={s.fieldLabel}>Owner Email *</label>
        <input id="whitelabeladmin-owner-email" aria-labelledby="whitelabeladmin-owner-email-label" style={s.textInput} value={email} onChange={(e) => setEmail(e.target.value)} placeholder="admin@propfirm.com" type="email" />

        <label id="whitelabeladmin-trial-days-0-active-immediately-label" htmlFor="whitelabeladmin-trial-days-0-active-immediately" style={s.fieldLabel}>Trial Days (0 = active immediately)</label>
        <input id="whitelabeladmin-trial-days-0-active-immediately" aria-labelledby="whitelabeladmin-trial-days-0-active-immediately-label" style={s.textInput} value={trialDays} onChange={(e) => setTrialDays(e.target.value)} type="number" min="0" max="365" />

        <label id="whitelabel-primary-colour-label" style={s.fieldLabel}>Primary Brand Colour</label>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          {/* Two controls, one visible label. Both reference it rather than
              restating it; the colour well and the text box announce different
              roles, which is what tells them apart. */}
          <input type="color" value={color} onChange={(e) => setColor(e.target.value)}
            aria-labelledby="whitelabel-primary-colour-label"
            style={{ width: 40, height: 36, border: 'none', background: 'none', cursor: 'pointer' }} />
          <input style={{ ...s.textInput, flex: 1 }} value={color} onChange={(e) => setColor(e.target.value)}
            aria-labelledby="whitelabel-primary-colour-label" />
        </div>

        <label id="whitelabeladmin-logo-url-optional-label" htmlFor="whitelabeladmin-logo-url-optional" style={s.fieldLabel}>Logo URL (optional)</label>
        <input id="whitelabeladmin-logo-url-optional" aria-labelledby="whitelabeladmin-logo-url-optional-label" style={s.textInput} value={logoUrl} onChange={(e) => setLogoUrl(e.target.value)} placeholder="https://…" />

        <label style={s.fieldLabel}>Features</label>
        <div style={s.featureGrid}>
          {ALL_FEATURES.map((f) => (
            <label key={f} style={s.featureCheck}>
              {/* The wrapping label already names this at runtime. The id makes
                  that name readable from the control's own props, and it points
                  at the same {f} the user sees, so the two cannot disagree. */}
              <input type="checkbox" checked={features.includes(f)} onChange={() => toggleFeature(f)}
                aria-labelledby={`whitelabel-feature-${f}-label`} />
              <span id={`whitelabel-feature-${f}-label`} style={{ marginLeft: 6, fontSize: 12 }}>{f}</span>
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

// ─── Preview Panel ────────────────────────────────────────────────────────────

const PreviewPanel: React.FC<{ tenant: Tenant; onClose: () => void }> = ({ tenant, onClose }) => {
  const color = tenant.theme.primary_color;
  return (
    <div style={s.overlay}>
      <div style={{ ...s.modal, maxWidth: 560 }}>
        <div style={s.modalHeader}>
          <span style={{ fontWeight: 700, fontSize: 16 }}>Dashboard Preview — {tenant.name}</span>
          <button style={s.closeBtn} onClick={onClose}>✕</button>
        </div>
        {/* Simulated branded dashboard */}
        <div style={{ background: 'var(--surface)', borderRadius: 10, overflow: 'hidden', border: '1px solid var(--border-strong)' }}>
          {/* Nav bar */}
          <div style={{ background: color, padding: '12px 20px', display: 'flex', alignItems: 'center', gap: 12 }}>
            {tenant.theme.logo_url
              ? <img src={tenant.theme.logo_url} alt="logo" style={{ height: 28 }} />
              : <div style={{ width: 28, height: 28, borderRadius: 6, background: 'rgba(255,255,255,0.3)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 800, color: '#fff', fontSize: 14 }}>
                  {tenant.name.slice(0, 2).toUpperCase()}
                </div>
            }
            <span style={{ fontWeight: 700, color: '#fff', fontSize: 16 }}>{tenant.theme.company_name}</span>
            <span style={{ marginLeft: 'auto', fontSize: 12, color: 'rgba(255,255,255,0.7)' }}>Powered by HOPEFX</span>
          </div>
          {/* Theme preview — shows how the tenant's brand colours apply to the dashboard */}
          <div style={{ padding: 20 }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(180px,1fr))', gap: 12, marginBottom: 16 }}>
              {(['Balance', 'P&L', 'Win Rate'] as const).map((label) => (
                <div key={label} style={{ background: 'var(--raised)', borderRadius: 8, padding: '12px 14px', borderTop: `3px solid ${color}` }}>
                  <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>{label}</div>
                  <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text-strong)' }}>—</div>
                </div>
              ))}
            </div>
            <div style={{ background: 'var(--raised)', borderRadius: 8, padding: 16, height: 80, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-faint)', fontSize: 'var(--fs-body)'}}>
              Equity chart — accent colour: <span style={{ color, marginLeft: 6, fontWeight: 700 }}>{color}</span>
            </div>
          </div>
        </div>
        <div style={{ marginTop: 16 }}>
          <div style={s.fieldLabel}>Enabled Features</div>
          <div style={s.featureGrid}>
            {tenant.features.map((f) => (
              <span key={f} style={{ ...s.featurePill, background: `${color}22`, color, border: `1px solid ${color}` }}>
                {f}
              </span>
            ))}
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
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{tenant.owner_email}</div>
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span style={{ ...s.statusBadge, color: statusColor(tenant.status), border: `1px solid ${statusColor(tenant.status)}` }}>
          {tenant.status}
        </span>
        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{tenant.features.length} features</span>
      </div>

      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        <button style={s.actionBtn} onClick={() => onPreview(tenant)}>Preview</button>
        <button style={s.actionBtn} onClick={() => onApiKey(tenant.tenant_id)}>
          {tenant.has_api_key ? 'Regen Key' : 'Gen Key'}
        </button>
        {tenant.status === 'suspended'
          ? <button style={{ ...s.actionBtn, color: 'var(--gain)' }} onClick={() => onAction(tenant.tenant_id, 'activate')}>Activate</button>
          : <button style={{ ...s.actionBtn, color: 'var(--loss)' }} onClick={() => onAction(tenant.tenant_id, 'suspend')}>Suspend</button>
        }
        <button style={{ ...s.actionBtn, color: 'var(--loss)' }} onClick={() => onAction(tenant.tenant_id, 'delete')}>Delete</button>
      </div>
    </div>
  );
};

// ─── Main component ───────────────────────────────────────────────────────────

const WhitelabelAdmin: React.FC = () => {
  const navigate = useNavigate();
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
      setLoadErr(extractApiError(err, 'Failed to load tenants. Ensure the whitelabel API is running.'));
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleAction = async (id: string, action: string) => {
    if (action === 'delete' && !window.confirm('Delete this tenant? This cannot be undone.')) return;
    setActionErr(null);
    try {
      if (action === 'activate') await api.post(`/whitelabel/tenants/${id}/activate`);
      else if (action === 'suspend') await api.post(`/whitelabel/tenants/${id}/suspend`);
      else if (action === 'delete') await api.delete(`/whitelabel/tenants/${id}`);
      await load();
    } catch (err) {
      setActionErr(extractApiError(err, `Action "${action}" failed. Check permissions and try again.`));
    }
  };

  const handleApiKey = async (id: string) => {
    setActionErr(null);
    try {
      const res = await api.post(`/whitelabel/tenants/${id}/api-key`);
      setApiKeyMsg(`API Key (copy now — shown once): ${res.data.api_key}`);
      await load();
    } catch (err) {
      setActionErr(extractApiError(err, 'Failed to generate API key. Check permissions and try again.'));
    }
  };

  const filtered = filter === 'all' ? tenants : tenants.filter((t) => t.status === filter);

  return (
    <PageShell
      width="wide" title="Whitelabel Tenants"
      subtitle="Manage prop-firm and reseller branded deployments."
      actions={<><div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <button onClick={() => navigate('/trade')}
            style={{ padding: '7px 14px', background: 'rgba(59,130,246,0.12)', border: '1px solid rgba(59,130,246,0.35)', borderRadius: 7, color: 'var(--link)', fontSize: 12, fontWeight: 700, cursor: 'pointer' }}>
            ⚡ Trade
          </button>
          <button onClick={() => navigate('/performance')}
            style={{ padding: '7px 14px', background: 'rgba(139,92,246,0.12)', border: '1px solid rgba(139,92,246,0.35)', borderRadius: 7, color: '#8b5cf6', fontSize: 12, fontWeight: 700, cursor: 'pointer' }}>
            📊 Performance
          </button>
          <button style={s.createBtn} onClick={() => setCreating(true)}>+ New Tenant</button>
        </div></>}
    >
      {creating && (
        <CreateModal
          onCreated={(t) => { setTenants((prev) => [t, ...prev]); setCreating(false); }}
          onClose={() => setCreating(false)}
        />
      )}
      {preview && <PreviewPanel tenant={preview} onClose={() => setPreview(null)} />}

      {/* Header */}


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
              <div style={{ fontSize: 24, fontWeight: 800, color: f === 'all' ? 'var(--text-strong)' : statusColor(f) }}>{count}</div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)', textTransform: 'capitalize' }}>{f}</div>
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
        <span style={{ color: 'var(--link)', fontWeight: 600 }}>ℹ Prop firm partnerships:</span>
        {' '}Each tenant gets a branded dashboard, their own API key, and configurable feature flags.
        Email FTMO / The5ers / Funded Next with the preview link to close deals.
      </div>
    </PageShell>
  );
};

// ─── Styles ───────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  page: {
    minHeight: '100vh', background: 'var(--surface)', color: 'var(--text-strong)',
    fontFamily: "'Inter', system-ui, sans-serif", padding: '24px',
  },
  header: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
    marginBottom: 24, flexWrap: 'wrap', gap: 12,
  },
  title:    { fontSize: 'var(--fs-hero)', fontWeight: 700, margin: 0 },
  subtitle: { fontSize: 14, color: 'var(--text-dim)', marginTop: 4 },
  createBtn: {
    background: '#3b82f6', border: 'none', borderRadius: 8,
    color: '#fff', padding: '10px 20px', fontSize: 14, cursor: 'pointer', fontWeight: 600,
  },
  statsRow: { display: 'flex', gap: 12, marginBottom: 20, flexWrap: 'wrap' },
  statCard: {
    background: 'var(--raised)', border: '1px solid var(--border-strong)', borderRadius: 10,
    padding: '14px 20px', cursor: 'pointer', textAlign: 'center', minWidth: 80,
  },
  card: {
    background: 'var(--raised)', borderRadius: 12, border: '1px solid var(--border-strong)',
    overflow: 'hidden', marginBottom: 20,
  },
  tenantRow: {
    display: 'flex', alignItems: 'center', gap: 16, padding: '16px 20px',
    borderBottom: '1px solid var(--hairline)', flexWrap: 'wrap',
  },
  statusBadge: {
    fontSize: 11, fontWeight: 700, padding: '2px 8px',
    borderRadius: 4, textTransform: 'capitalize',
  },
  actionBtn: {
    background: 'var(--surface)', border: '1px solid var(--border-strong)', borderRadius: 6,
    color: 'var(--text-dim)', padding: '5px 10px', fontSize: 12, cursor: 'pointer',
  },
  dim:   { color: 'var(--text-faint)', fontSize: 'var(--fs-body)', textAlign: 'center', padding: 32 },
  empty: { color: 'var(--text-faint)', fontSize: 14, textAlign: 'center', padding: 48 },
  apiKeyBanner: {
    background: 'rgba(74,222,128,0.1)', border: '1px solid var(--gain)', borderRadius: 8,
    padding: '12px 16px', marginBottom: 16, fontSize: 'var(--fs-body)', color: 'var(--gain)',
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    wordBreak: 'break-all',
  },
  errorBanner: {
    background: 'rgba(248,113,113,0.1)', border: '1px solid var(--loss)', borderRadius: 8,
    padding: '12px 16px', marginBottom: 16, fontSize: 'var(--fs-body)', color: 'var(--loss)',
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    wordBreak: 'break-all',
  },
  infoBanner: {
    background: 'var(--raised)', borderRadius: 8, padding: '12px 16px',
    fontSize: 'var(--fs-body)', color: 'var(--text-dim)', border: '1px solid var(--border-strong)',
  },
  overlay: {
    position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)',
    display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
    padding: 16,
  },
  modal: {
    background: 'var(--raised)', borderRadius: 16, padding: 28,
    border: '1px solid var(--border-strong)', width: '100%', maxWidth: 520,
    maxHeight: '90vh', overflowY: 'auto',
  },
  modalHeader: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20,
  },
  closeBtn: {
    background: 'transparent', border: 'none', color: 'var(--text-muted)', fontSize: 18, cursor: 'pointer',
  },
  fieldLabel: {
    fontSize: 12, color: 'var(--text-dim)', display: 'block', marginBottom: 6, marginTop: 14,
  },
  textInput: {
    width: '100%', background: 'var(--surface)', border: '1px solid var(--border-strong)', borderRadius: 8,
    color: 'var(--text-strong)', padding: '10px 12px', fontSize: 14, outline: 'none', boxSizing: 'border-box',
  },
  featureGrid: { display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 4 },
  featureCheck: { display: 'flex', alignItems: 'center', cursor: 'pointer', fontSize: 12, color: 'var(--text-dim)' },
  featurePill: {
    fontSize: 11, padding: '2px 8px', borderRadius: 4,
  },
  saveBtn: {
    flex: 1, background: '#3b82f6', border: 'none', borderRadius: 8,
    color: '#fff', padding: '10px', fontSize: 14, cursor: 'pointer', fontWeight: 600,
  },
  cancelBtn: {
    flex: 1, background: 'var(--surface-hover)', border: 'none', borderRadius: 8,
    color: 'var(--text-dim)', padding: '10px', fontSize: 14, cursor: 'pointer',
  },
};

export default WhitelabelAdmin;
