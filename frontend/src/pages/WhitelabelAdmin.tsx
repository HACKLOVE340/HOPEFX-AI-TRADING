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
        <div style={{ background: '#0f172a', borderRadius: 10, overflow: 'hidden', border: '1px solid #334155' }}>
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
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 12, marginBottom: 16 }}>
              {(['Balance', 'P&L', 'Win Rate'] as const).map((label) => (
                <div key={label} style={{ background: '#1e293b', borderRadius: 8, padding: '12px 14px', borderTop: `3px solid ${color}` }}>
                  <div style={{ fontSize: 12, color: '#94a3b8' }}>{label}</div>
                  <div style={{ fontSize: 18, fontWeight: 700, color: '#f8fafc' }}>—</div>
                </div>
              ))}
            </div>
            <div style={{ background: '#1e293b', borderRadius: 8, padding: 16, height: 80, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#475569', fontSize: 13 }}>
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
      setLoadErr(extractErrorMessage(err, 'Failed to load tenants. Ensure the whitelabel API is running.'));
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
      setActionErr(extractErrorMessage(err, `Action "${action}" failed. Check permissions and try again.`));
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
      {preview && <PreviewPanel tenant={preview} onClose={() => setPreview(null)} />}

      {/* Header */}
      <div style={s.header}>
        <div>
          <h1 style={s.title}>Whitelabel Tenants</h1>
          <p style={s.subtitle}>Manage prop-firm and reseller branded deployments.</p>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <button onClick={() => navigate('/trade')}
            style={{ padding: '7px 14px', background: 'rgba(59,130,246,0.12)', border: '1px solid rgba(59,130,246,0.35)', borderRadius: 7, color: '#60a5fa', fontSize: 12, fontWeight: 700, cursor: 'pointer' }}>
            ⚡ Trade
          </button>
          <button onClick={() => navigate('/performance')}
            style={{ padding: '7px 14px', background: 'rgba(139,92,246,0.12)', border: '1px solid rgba(139,92,246,0.35)', borderRadius: 7, color: '#8b5cf6', fontSize: 12, fontWeight: 700, cursor: 'pointer' }}>
            📊 Performance
          </button>
          <button style={s.createBtn} onClick={() => setCreating(true)}>+ New Tenant</button>
        </div>
      </div>

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
