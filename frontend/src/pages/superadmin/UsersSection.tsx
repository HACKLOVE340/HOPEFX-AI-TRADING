// superadmin/UsersSection.tsx — full user management with bulk operations
import React, { useEffect, useState, useCallback } from 'react';
import { superadminApi } from '../../hooks/useApi';
import { usePolling } from '../../hooks/usePolling';
import {
  SectionCard, StatusBadge, ActionBtn, Input, Select,
  ErrorState, LoadingRows, ConfirmDialog, SAStyles,
} from './ui';
import type { SuperAdminUser, BulkUserResult } from './types';
import { ROLE_BADGE_STYLES, ROLE_LABELS, PLAN_COLORS, PLAN_LABELS } from '../../lib/subscription';
import type { UserRole } from '../../store';
import type { Plan } from '../../lib/subscription';

const timeAgo = (iso: string | null) => {
  if (!iso) return 'Never';
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60_000);
  if (m < 1)  return 'Just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
};

const fmtDate = (iso: string) =>
  new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });

// ── User detail drawer ────────────────────────────────────────────────────────

interface UserDetailDrawerProps {
  user: SuperAdminUser;
  onClose: () => void;
  onRefresh: () => void;
}

interface ActivityEntry {
  action: string;
  timestamp: string;
  ip: string;
  details: string;
}

const UserDetailDrawer: React.FC<UserDetailDrawerProps> = ({ user: initialUser, onClose, onRefresh }) => {
  const [user, setUser]     = useState<SuperAdminUser>(initialUser);
  const [tab, setTab]       = useState<'overview' | 'edit' | 'activity'>('overview');
  const [role, setRole]     = useState(initialUser.role);
  const [plan, setPlan]     = useState(initialUser.plan);
  const [editFields, setEditFields] = useState({ username: initialUser.username, email: initialUser.email });
  const [activity, setActivity] = useState<ActivityEntry[]>([]);
  const [activityLoading, setActivityLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [msg, setMsg]       = useState('');
  const [confirm, setConfirm] = useState<{ action: string; label: string } | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState(false);

  // Load full user detail on mount
  useEffect(() => {
    superadminApi.getUser(initialUser.user_id)
      .then(r => { setUser(r.data); setRole(r.data.role); setPlan(r.data.plan); setEditFields({ username: r.data.username, email: r.data.email }); })
      .catch(() => {}); // fall back to initial data passed in
  }, [initialUser.user_id]);

  // Load activity when tab selected
  useEffect(() => {
    if (tab !== 'activity') return;
    setActivityLoading(true);
    superadminApi.userActivity(user.user_id)
      .then(r => setActivity(r.data.activity ?? r.data ?? []))
      .catch(() => setActivity([]))
      .finally(() => setActivityLoading(false));
  }, [tab, user.user_id]);

  const doAction = async (action: string) => {
    setSaving(true); setMsg('');
    try {
      if (action === 'ban')              await superadminApi.banUser(user.user_id, 'Admin action');
      else if (action === 'unban')       await superadminApi.unbanUser(user.user_id);
      else if (action === 'reset-pw')    await superadminApi.resetUserPassword(user.user_id);
      else if (action === 'impersonate') await superadminApi.impersonateUser(user.user_id);
      else if (action === 'set-role')    await superadminApi.setUserRole(user.user_id, role);
      else if (action === 'set-plan')    await superadminApi.setUserPlan(user.user_id, plan);
      setMsg('Done');
      onRefresh();
    } catch (e: unknown) {
      setMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Action failed');
    } finally {
      setSaving(false);
    }
  };

  const saveEdit = async () => {
    setSaving(true); setMsg('');
    try {
      const res = await superadminApi.updateUser(user.user_id, editFields);
      setUser(prev => ({ ...prev, ...res.data }));
      setMsg('Done');
      onRefresh();
    } catch (e: unknown) {
      setMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Update failed');
    } finally { setSaving(false); }
  };

  const deleteUser = async () => {
    setDeleting(true); setMsg('');
    try {
      await superadminApi.deleteUser(user.user_id);
      setMsg('Done');
      onRefresh();
      setTimeout(onClose, 800);
    } catch (e: unknown) {
      setMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Delete failed');
    } finally { setDeleting(false); setDeleteConfirm(false); }
  };

  const roleStyle = ROLE_BADGE_STYLES[user.role as UserRole] ?? ROLE_BADGE_STYLES.user;

  return (
    <>
      {confirm && (
        <ConfirmDialog
          title={`Confirm: ${confirm.label}`}
          message={`Are you sure you want to ${confirm.label.toLowerCase()} for ${user.username}? This action is logged.`}
          confirmLabel={confirm.label}
          variant={confirm.action === 'ban' ? 'danger' : 'warning'}
          onConfirm={() => { setConfirm(null); doAction(confirm.action); }}
          onCancel={() => setConfirm(null)}
        />
      )}
      {deleteConfirm && (
        <ConfirmDialog
          title="Delete User Account"
          message={`Permanently delete account for "${user.username}" (${user.email})? All data will be anonymised. This cannot be undone.`}
          confirmLabel="Delete Account"
          variant="danger"
          onConfirm={deleteUser}
          onCancel={() => setDeleteConfirm(false)}
        />
      )}
      <div style={{ position: 'fixed', inset: 0, zIndex: 800, background: 'rgba(0,0,0,0.5)', backdropFilter: 'blur(3px)' }} onClick={onClose} />
      <div style={{ position: 'fixed', right: 0, top: 0, bottom: 0, zIndex: 801, width: 460, background: '#0a1628', borderLeft: '1px solid #1e293b', overflowY: 'auto', padding: 24, animation: 'sa-fadein 0.2s ease' }}>

        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div style={{ width: 40, height: 40, borderRadius: '50%', background: roleStyle.bg, border: `2px solid ${roleStyle.border}`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 16, fontWeight: 700, color: roleStyle.color }}>
              {user.username[0].toUpperCase()}
            </div>
            <div>
              <div style={{ fontSize: 14, fontWeight: 700, color: '#f1f5f9' }}>{user.username}</div>
              <div style={{ fontSize: 11, color: '#64748b' }}>{user.email}</div>
            </div>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#64748b', cursor: 'pointer', fontSize: 20 }}>×</button>
        </div>

        {/* Tabs */}
        <div style={{ display: 'flex', gap: 4, marginBottom: 18 }}>
          {(['overview', 'edit', 'activity'] as const).map(t => (
            <button key={t} onClick={() => setTab(t)} style={{ background: tab === t ? '#1e293b' : 'transparent', border: `1px solid ${tab === t ? '#475569' : '#1e293b'}`, borderRadius: 7, color: tab === t ? '#f8fafc' : '#64748b', padding: '6px 14px', fontSize: 12, cursor: 'pointer' }}>
              {{ overview: 'Overview', edit: 'Edit', activity: 'Activity' }[t]}
            </button>
          ))}
        </div>

        {/* ── TAB: Overview ── */}
        {tab === 'overview' && (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 16 }}>
              {[
                { label: 'Status',     value: <StatusBadge status={user.status} size="sm" /> },
                { label: 'Role',       value: <span style={{ fontSize: 11, fontWeight: 700, color: roleStyle.color }}>{ROLE_LABELS[user.role as UserRole] ?? user.role}</span> },
                { label: 'Plan',       value: <span style={{ fontSize: 11, fontWeight: 700, color: PLAN_COLORS[user.plan as Plan] ?? '#94a3b8' }}>{PLAN_LABELS[user.plan as Plan] ?? user.plan}</span> },
                { label: '2FA',        value: <span style={{ color: user.two_fa_enabled ? '#4ade80' : '#f87171', fontSize: 11 }}>{user.two_fa_enabled ? 'Enabled' : 'Disabled'}</span> },
                { label: 'Joined',     value: fmtDate(user.created_at) },
                { label: 'Last Login', value: timeAgo(user.last_login) },
                { label: 'Trades',     value: user.total_trades.toLocaleString() },
                { label: 'Revenue',    value: `$${user.revenue_generated.toFixed(2)}` },
              ].map(r => (
                <div key={r.label} style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 6, padding: '8px 10px' }}>
                  <div style={{ fontSize: 10, color: '#475569', marginBottom: 3 }}>{r.label}</div>
                  <div style={{ fontSize: 12, color: '#e2e8f0' }}>{r.value}</div>
                </div>
              ))}
            </div>

            {/* Role + Plan pickers */}
            <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 10, padding: 14, marginBottom: 12 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: '#64748b', marginBottom: 8 }}>Change Role</div>
              <div style={{ display: 'flex', gap: 8 }}>
                <Select value={role} onChange={e => setRole(e.target.value)} options={[
                  { value: 'user', label: 'User' }, { value: 'trader', label: 'Trader' },
                  { value: 'admin', label: 'Admin' }, { value: 'superadmin', label: 'Super Admin' },
                ]} style={{ flex: 1 }} />
                <ActionBtn label="Apply" onClick={() => setConfirm({ action: 'set-role', label: 'Change Role' })} variant="primary" size="sm" loading={saving} />
              </div>
            </div>

            <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 10, padding: 14, marginBottom: 16 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: '#64748b', marginBottom: 8 }}>Change Plan</div>
              <div style={{ display: 'flex', gap: 8 }}>
                <Select value={plan} onChange={e => setPlan(e.target.value)} options={[
                  { value: 'free',         label: 'Free' },
                  { value: 'starter',      label: 'Starter' },
                  { value: 'professional', label: 'Professional' },
                  { value: 'enterprise',   label: 'Enterprise' },
                  { value: 'elite',        label: 'Elite' },
                ]} style={{ flex: 1 }} />
                <ActionBtn label="Apply" onClick={() => setConfirm({ action: 'set-plan', label: 'Change Plan' })} variant="primary" size="sm" loading={saving} />
              </div>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <ActionBtn label="Reset Password"   onClick={() => setConfirm({ action: 'reset-pw',    label: 'Reset Password'   })} variant="warning" icon="🔑" />
              <ActionBtn label="Impersonate User" onClick={() => setConfirm({ action: 'impersonate', label: 'Impersonate User' })} variant="primary" icon="👤" />
              {user.status === 'banned'
                ? <ActionBtn label="Unban User" onClick={() => setConfirm({ action: 'unban', label: 'Unban User' })} variant="success" icon="✅" />
                : <ActionBtn label="Ban User"   onClick={() => setConfirm({ action: 'ban',   label: 'Ban User'   })} variant="danger"  icon="🚫" />
              }
              <div style={{ borderTop: '1px solid #1e293b', paddingTop: 8 }}>
                <ActionBtn label="Delete Account" onClick={() => setDeleteConfirm(true)} loading={deleting} icon="🗑️" variant="danger" />
              </div>
            </div>
          </>
        )}

        {/* ── TAB: Edit ── */}
        {tab === 'edit' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 10, padding: 16 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: '#94a3b8', marginBottom: 12 }}>Edit Profile</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                <Input label="Username" value={editFields.username} onChange={e => setEditFields(f => ({ ...f, username: e.target.value }))} />
                <Input label="Email"    value={editFields.email}    onChange={e => setEditFields(f => ({ ...f, email:    e.target.value }))} />
              </div>
            </div>
            <ActionBtn label={saving ? 'Saving…' : 'Save Changes'} onClick={saveEdit} variant="primary" loading={saving} />
          </div>
        )}

        {/* ── TAB: Activity ── */}
        {tab === 'activity' && (
          <div>
            {activityLoading ? (
              <div style={{ color: '#475569', fontSize: 13, textAlign: 'center', padding: 24 }}>Loading activity…</div>
            ) : activity.length === 0 ? (
              <div style={{ color: '#475569', fontSize: 13, textAlign: 'center', padding: 24 }}>No activity recorded.</div>
            ) : (
              activity.map((a, i) => (
                <div key={i} style={{ display: 'flex', gap: 10, padding: '10px 0', borderBottom: '1px solid #0f172a', alignItems: 'flex-start' }}>
                  <div style={{ width: 7, height: 7, borderRadius: '50%', background: '#3b82f6', marginTop: 5, flexShrink: 0 }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 12, fontWeight: 600, color: '#f1f5f9' }}>{a.action}</div>
                    {a.details && <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>{a.details}</div>}
                    <div style={{ fontSize: 10, color: '#334155', marginTop: 2 }}>IP: {a.ip}</div>
                  </div>
                  <div style={{ fontSize: 11, color: '#475569', whiteSpace: 'nowrap', flexShrink: 0 }}>
                    {new Date(a.timestamp).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {msg && (
          <div style={{ marginTop: 14, padding: '10px 14px', borderRadius: 8, background: msg === 'Done' ? '#052e16' : '#450a0a', color: msg === 'Done' ? '#4ade80' : '#f87171', fontSize: 12, fontWeight: 600 }}>
            {msg === 'Done' ? '✅ Action completed successfully' : `❌ ${msg}`}
          </div>
        )}
      </div>
    </>
  );
};

// ── Bulk result toast ─────────────────────────────────────────────────────────

const BulkResultToast: React.FC<{ result: BulkUserResult; onClose: () => void }> = ({ result, onClose }) => (
  <div style={{
    position: 'fixed', bottom: 24, right: 24, zIndex: 900,
    background: '#0a1628', border: '1px solid #1e293b', borderRadius: 12,
    padding: '16px 20px', minWidth: 280, boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
    animation: 'sa-fadein 0.2s ease',
  }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
      <span style={{ fontSize: 13, fontWeight: 700, color: '#f1f5f9' }}>Bulk Operation Complete</span>
      <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#64748b', cursor: 'pointer', fontSize: 16 }}>x</button>
    </div>
    <div style={{ fontSize: 12, color: '#4ade80' }}>✅ {result.succeeded.length} succeeded</div>
    {result.failed.length > 0 && (
      <div style={{ fontSize: 12, color: '#f87171', marginTop: 4 }}>
        ❌ {result.failed.length} failed
        {result.failed.slice(0, 3).map(f => (
          <div key={f.user_id} style={{ fontSize: 11, color: '#94a3b8', marginTop: 2 }}>
            {f.user_id}: {f.reason}
          </div>
        ))}
      </div>
    )}
  </div>
);

// ── Main section ──────────────────────────────────────────────────────────────

const UsersSection: React.FC = () => {
  const [users, setUsers]           = useState<SuperAdminUser[]>([]);
  const [loading, setLoading]       = useState(true);
  const [error, setError]           = useState('');
  const [search, setSearch]         = useState('');
  const [roleFilter, setRoleFilter] = useState('');
  const [planFilter, setPlanFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [selected, setSelected]     = useState<SuperAdminUser | null>(null);
  const [page, setPage]             = useState(1);
  const PAGE_SIZE = 20;

  const [checkedIds, setCheckedIds]   = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy]       = useState<string | null>(null);
  const [bulkResult, setBulkResult]   = useState<BulkUserResult | null>(null);
  const [bulkConfirm, setBulkConfirm] = useState<{ action: string; label: string } | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const params: Record<string, string> = {};
      if (search)       params.search    = search;
      if (roleFilter)   params.role      = roleFilter;
      if (planFilter)   params.plan      = planFilter;
      if (statusFilter) params.status    = statusFilter;
      params.page      = String(page);
      params.page_size = String(PAGE_SIZE);
      const res = await superadminApi.users(params);
      setUsers(res.data.users ?? res.data);
      setCheckedIds(new Set());
    } catch (e: unknown) {
      setError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to load users');
    } finally {
      setLoading(false);
    }
  }, [search, roleFilter, planFilter, statusFilter, page]);

  useEffect(() => { load(); }, [load]);
  // Refresh every 30 s — configuration and model data changes less frequently.
  usePolling(load, 30_000);

  const allChecked  = users.length > 0 && users.every(u => checkedIds.has(u.user_id));
  const someChecked = !allChecked && users.some(u => checkedIds.has(u.user_id));

  const toggleAll = () => {
    if (allChecked) {
      setCheckedIds(prev => { const n = new Set(prev); users.forEach(u => n.delete(u.user_id)); return n; });
    } else {
      setCheckedIds(prev => { const n = new Set(prev); users.forEach(u => n.add(u.user_id)); return n; });
    }
  };

  const toggleOne = (id: string) =>
    setCheckedIds(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; });

  const doBulkAction = async (action: string) => {
    const ids = Array.from(checkedIds);
    if (!ids.length) return;
    setBulkBusy(action);
    try {
      if (action === 'export') {
        const res = await superadminApi.bulkExportUsers(ids);
        const url = URL.createObjectURL(new Blob([res.data], { type: 'text/csv' }));
        const a = document.createElement('a');
        a.href = url; a.download = 'users_export.csv'; a.click();
        URL.revokeObjectURL(url);
        return;
      }
      const res = action === 'ban'
        ? await superadminApi.bulkBanUsers(ids, 'Bulk admin action')
        : await superadminApi.bulkUnbanUsers(ids);
      setBulkResult(res.data);
      load();
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Bulk action failed';
      setBulkResult({ succeeded: [], failed: ids.map(id => ({ user_id: id, reason: msg })), total: ids.length });
    } finally {
      setBulkBusy(null);
      setBulkConfirm(null);
    }
  };

  const roleStyle = (role: string) => ROLE_BADGE_STYLES[role as UserRole] ?? ROLE_BADGE_STYLES.user;

  return (
    <div style={{ animation: 'sa-fadein 0.2s ease' }}>
      <SAStyles />
      {selected && <UserDetailDrawer user={selected} onClose={() => setSelected(null)} onRefresh={load} />}
      {bulkResult && <BulkResultToast result={bulkResult} onClose={() => setBulkResult(null)} />}

      {bulkConfirm && (
        <ConfirmDialog
          title={`Bulk ${bulkConfirm.label}`}
          message={`Apply "${bulkConfirm.label}" to ${checkedIds.size} selected user${checkedIds.size !== 1 ? 's' : ''}? This action is logged.`}
          confirmLabel={bulkConfirm.label}
          variant={bulkConfirm.action === 'ban' ? 'danger' : 'warning'}
          onConfirm={() => doBulkAction(bulkConfirm.action)}
          onCancel={() => setBulkConfirm(null)}
        />
      )}

      <SectionCard
        title="User Management"
        icon="👥"
        accent="#3b82f6"
        subtitle={`${users.length} users loaded`}
        actions={<ActionBtn label="Refresh" onClick={load} icon="🔄" size="sm" />}
      >
        {/* Filters */}
        <div style={{ display: 'flex', gap: 10, marginBottom: 16, flexWrap: 'wrap' }}>
          <Input
            placeholder="Search username or email…"
            value={search}
            onChange={e => { setSearch(e.target.value); setPage(1); }}
            style={{ flex: 1, minWidth: 200 }}
          />
          <Select value={roleFilter} onChange={e => { setRoleFilter(e.target.value); setPage(1); }}
            options={[
              { value: '', label: 'All Roles' }, { value: 'user', label: 'User' },
              { value: 'trader', label: 'Trader' }, { value: 'admin', label: 'Admin' },
              { value: 'superadmin', label: 'Super Admin' },
            ]} style={{ width: 140 }} />
          <Select value={planFilter} onChange={e => { setPlanFilter(e.target.value); setPage(1); }}
            options={[
              { value: '',             label: 'All Plans' },
              { value: 'free',         label: 'Free' },
              { value: 'starter',      label: 'Starter' },
              { value: 'professional', label: 'Professional' },
              { value: 'enterprise',   label: 'Enterprise' },
              { value: 'elite',        label: 'Elite' },
            ]} style={{ width: 130 }} />
          <Select value={statusFilter} onChange={e => { setStatusFilter(e.target.value); setPage(1); }}
            options={[
              { value: '', label: 'All Status' }, { value: 'active', label: 'Active' },
              { value: 'banned', label: 'Banned' }, { value: 'pending', label: 'Pending' },
              { value: 'inactive', label: 'Inactive' },
            ]} style={{ width: 130 }} />
        </div>

        {/* Bulk toolbar */}
        {checkedIds.size > 0 && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
            background: '#0f1f35', border: '1px solid #1e3a5f',
            borderRadius: 8, padding: '10px 14px', marginBottom: 12,
          }}>
            <span style={{ fontSize: 12, color: '#93c5fd', fontWeight: 600 }}>
              {checkedIds.size} selected
            </span>
            <div style={{ flex: 1 }} />
            <ActionBtn label="Ban Selected"   onClick={() => setBulkConfirm({ action: 'ban',   label: 'Ban Users'   })} variant="danger"  size="sm" icon="🚫" loading={bulkBusy === 'ban'} />
            <ActionBtn label="Unban Selected" onClick={() => setBulkConfirm({ action: 'unban', label: 'Unban Users' })} variant="success" size="sm" icon="✅" loading={bulkBusy === 'unban'} />
            <ActionBtn label="Export CSV"     onClick={() => doBulkAction('export')}                                    variant="ghost"   size="sm" icon="⬇️" loading={bulkBusy === 'export'} />
            <ActionBtn label="Clear"          onClick={() => setCheckedIds(new Set())}                                  variant="ghost"   size="sm" />
          </div>
        )}

        {/* Table */}
        {loading ? <LoadingRows rows={8} /> : error ? <ErrorState message={error} onRetry={load} /> : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid #1e293b' }}>
                  <th style={{ padding: '8px 12px', width: 36 }}>
                    <input
                      type="checkbox"
                      checked={allChecked}
                      ref={el => { if (el) el.indeterminate = someChecked; }}
                      onChange={toggleAll}
                      style={{ cursor: 'pointer', accentColor: '#3b82f6' }}
                    />
                  </th>
                  {['User', 'Role', 'Plan', 'Status', 'Trades', 'Last Login', 'Joined', ''].map(h => (
                    <th key={h} style={{ padding: '8px 12px', textAlign: 'left', fontSize: 11, fontWeight: 600, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em', whiteSpace: 'nowrap' }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {users.map(u => {
                  const rs = roleStyle(u.role);
                  const isChecked = checkedIds.has(u.user_id);
                  return (
                    <tr key={u.user_id} className="sa-row" style={{ borderBottom: '1px solid #0f172a', transition: 'background 0.1s', background: isChecked ? '#0f1f35' : undefined }}>
                      <td style={{ padding: '10px 12px' }} onClick={e => e.stopPropagation()}>
                        <input type="checkbox" checked={isChecked} onChange={() => toggleOne(u.user_id)} style={{ cursor: 'pointer', accentColor: '#3b82f6' }} />
                      </td>
                      <td style={{ padding: '10px 12px', cursor: 'pointer' }} onClick={() => setSelected(u)}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <div style={{ width: 28, height: 28, borderRadius: '50%', background: rs.bg, border: `1px solid ${rs.border}`, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, fontWeight: 700, color: rs.color, flexShrink: 0 }}>
                            {u.username[0].toUpperCase()}
                          </div>
                          <div>
                            <div style={{ fontWeight: 600, color: '#f1f5f9' }}>{u.username}</div>
                            <div style={{ fontSize: 11, color: '#475569' }}>{u.email}</div>
                          </div>
                        </div>
                      </td>
                      <td style={{ padding: '10px 12px', cursor: 'pointer' }} onClick={() => setSelected(u)}>
                        <span style={{ fontSize: 11, fontWeight: 700, color: rs.color, background: rs.bg, border: `1px solid ${rs.border}`, borderRadius: 4, padding: '2px 7px' }}>
                          {ROLE_LABELS[u.role as UserRole] ?? u.role}
                        </span>
                      </td>
                      <td style={{ padding: '10px 12px', cursor: 'pointer' }} onClick={() => setSelected(u)}>
                        <span style={{ fontSize: 11, fontWeight: 700, color: PLAN_COLORS[u.plan as Plan] ?? '#94a3b8' }}>
                          {PLAN_LABELS[u.plan as Plan] ?? u.plan}
                        </span>
                      </td>
                      <td style={{ padding: '10px 12px', cursor: 'pointer' }} onClick={() => setSelected(u)}><StatusBadge status={u.status} size="sm" /></td>
                      <td style={{ padding: '10px 12px', color: '#94a3b8', cursor: 'pointer' }} onClick={() => setSelected(u)}>{u.total_trades.toLocaleString()}</td>
                      <td style={{ padding: '10px 12px', color: '#64748b', fontSize: 12, cursor: 'pointer' }} onClick={() => setSelected(u)}>{timeAgo(u.last_login)}</td>
                      <td style={{ padding: '10px 12px', color: '#64748b', fontSize: 12, cursor: 'pointer' }} onClick={() => setSelected(u)}>{fmtDate(u.created_at)}</td>
                      <td style={{ padding: '10px 12px', cursor: 'pointer' }} onClick={() => setSelected(u)}><span style={{ fontSize: 11, color: '#3b82f6' }}>View →</span></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {users.length === 0 && (
              <div style={{ textAlign: 'center', padding: '32px', color: '#475569', fontSize: 13 }}>
                No users match the current filters.
              </div>
            )}
          </div>
        )}

        {/* Pagination */}
        {!loading && users.length > 0 && (
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 14 }}>
            <ActionBtn label="← Prev" onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1} size="sm" />
            <span style={{ fontSize: 12, color: '#64748b', alignSelf: 'center' }}>Page {page}</span>
            <ActionBtn label="Next →" onClick={() => setPage(p => p + 1)} disabled={users.length < PAGE_SIZE} size="sm" />
          </div>
        )}
      </SectionCard>
    </div>
  );
};

export default UsersSection;
