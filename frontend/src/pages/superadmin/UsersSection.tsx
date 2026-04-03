// superadmin/UsersSection.tsx — full user management
import React, { useEffect, useState, useCallback } from 'react';
import { superadminApi } from '../../hooks/useApi';
import {
  SectionCard, StatusBadge, ActionBtn, Input, Select,
  Spinner, ErrorState, LoadingRows, ConfirmDialog, SAStyles,
} from './ui';
import type { SuperAdminUser } from './types';
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

const fmtDate = (iso: string) => new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });

interface UserDetailDrawerProps {
  user: SuperAdminUser;
  onClose: () => void;
  onRefresh: () => void;
}

const UserDetailDrawer: React.FC<UserDetailDrawerProps> = ({ user, onClose, onRefresh }) => {
  const [role, setRole]   = useState(user.role);
  const [plan, setPlan]   = useState(user.plan);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg]     = useState('');
  const [confirm, setConfirm] = useState<{ action: string; label: string } | null>(null);

  const doAction = async (action: string) => {
    setSaving(true); setMsg('');
    try {
      if (action === 'ban')             await superadminApi.banUser(user.user_id, 'Admin action');
      else if (action === 'unban')      await superadminApi.unbanUser(user.user_id);
      else if (action === 'reset-pw')   await superadminApi.resetUserPassword(user.user_id);
      else if (action === 'impersonate') await superadminApi.impersonateUser(user.user_id);
      else if (action === 'set-role')   await superadminApi.setUserRole(user.user_id, role);
      else if (action === 'set-plan')   await superadminApi.setUserPlan(user.user_id, plan);
      setMsg('Done');
      onRefresh();
    } catch (e: unknown) {
      setMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Action failed');
    } finally {
      setSaving(false);
    }
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
      <div style={{
        position: 'fixed', inset: 0, zIndex: 800,
        background: 'rgba(0,0,0,0.5)', backdropFilter: 'blur(3px)',
      }} onClick={onClose} />
      <div style={{
        position: 'fixed', right: 0, top: 0, bottom: 0, zIndex: 801,
        width: 420, background: '#0a1628',
        borderLeft: '1px solid #1e293b',
        overflowY: 'auto', padding: 24,
        animation: 'sa-fadein 0.2s ease',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: '#f8fafc' }}>User Detail</h3>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#64748b', cursor: 'pointer', fontSize: 20 }}>×</button>
        </div>

        {/* Identity */}
        <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 10, padding: 16, marginBottom: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
            <div style={{
              width: 44, height: 44, borderRadius: '50%',
              background: `${roleStyle.bg}`, border: `2px solid ${roleStyle.border}`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 18, fontWeight: 700, color: roleStyle.color,
            }}>
              {user.username[0].toUpperCase()}
            </div>
            <div>
              <div style={{ fontSize: 15, fontWeight: 700, color: '#f1f5f9' }}>{user.username}</div>
              <div style={{ fontSize: 12, color: '#64748b' }}>{user.email}</div>
            </div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            {[
              { label: 'Status',      value: <StatusBadge status={user.status} size="sm" /> },
              { label: 'Role',        value: <span style={{ fontSize: 11, fontWeight: 700, color: roleStyle.color }}>{ROLE_LABELS[user.role as UserRole] ?? user.role}</span> },
              { label: 'Plan',        value: <span style={{ fontSize: 11, fontWeight: 700, color: PLAN_COLORS[user.plan as Plan] ?? '#94a3b8' }}>{PLAN_LABELS[user.plan as Plan] ?? user.plan}</span> },
              { label: '2FA',         value: <span style={{ color: user.two_fa_enabled ? '#4ade80' : '#f87171', fontSize: 11 }}>{user.two_fa_enabled ? 'Enabled' : 'Disabled'}</span> },
              { label: 'Joined',      value: fmtDate(user.created_at) },
              { label: 'Last Login',  value: timeAgo(user.last_login) },
              { label: 'Trades',      value: user.total_trades.toLocaleString() },
              { label: 'Revenue',     value: `$${user.revenue_generated.toFixed(2)}` },
            ].map(r => (
              <div key={r.label} style={{ background: '#1e293b', borderRadius: 6, padding: '8px 10px' }}>
                <div style={{ fontSize: 10, color: '#475569', marginBottom: 3 }}>{r.label}</div>
                <div style={{ fontSize: 12, color: '#e2e8f0' }}>{r.value}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Change role */}
        <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 10, padding: 16, marginBottom: 16 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: '#94a3b8', marginBottom: 10 }}>Change Role</div>
          <div style={{ display: 'flex', gap: 8 }}>
            <Select
              value={role}
              onChange={e => setRole(e.target.value)}
              options={[
                { value: 'user',       label: 'User' },
                { value: 'trader',     label: 'Trader' },
                { value: 'admin',      label: 'Admin' },
                { value: 'superadmin', label: 'Super Admin' },
              ]}
              style={{ flex: 1 }}
            />
            <ActionBtn label="Apply" onClick={() => setConfirm({ action: 'set-role', label: 'Change Role' })} variant="primary" size="sm" loading={saving} />
          </div>
        </div>

        {/* Change plan */}
        <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 10, padding: 16, marginBottom: 16 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: '#94a3b8', marginBottom: 10 }}>Change Plan</div>
          <div style={{ display: 'flex', gap: 8 }}>
            <Select
              value={plan}
              onChange={e => setPlan(e.target.value)}
              options={[
                { value: 'free',    label: 'Free' },
                { value: 'starter', label: 'Starter' },
                { value: 'pro',     label: 'Pro' },
                { value: 'elite',   label: 'Elite' },
              ]}
              style={{ flex: 1 }}
            />
            <ActionBtn label="Apply" onClick={() => setConfirm({ action: 'set-plan', label: 'Change Plan' })} variant="primary" size="sm" loading={saving} />
          </div>
        </div>

        {/* Actions */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <ActionBtn label="Reset Password" onClick={() => setConfirm({ action: 'reset-pw', label: 'Reset Password' })} variant="warning" icon="🔑" />
          <ActionBtn label="Impersonate User" onClick={() => setConfirm({ action: 'impersonate', label: 'Impersonate User' })} variant="primary" icon="👤" />
          {user.status === 'banned'
            ? <ActionBtn label="Unban User" onClick={() => setConfirm({ action: 'unban', label: 'Unban User' })} variant="success" icon="✅" />
            : <ActionBtn label="Ban User"   onClick={() => setConfirm({ action: 'ban',   label: 'Ban User'   })} variant="danger"  icon="🚫" />
          }
        </div>

        {msg && (
          <div style={{
            marginTop: 14, padding: '10px 14px', borderRadius: 8,
            background: msg === 'Done' ? '#052e16' : '#450a0a',
            color: msg === 'Done' ? '#4ade80' : '#f87171',
            fontSize: 12, fontWeight: 600,
          }}>
            {msg === 'Done' ? '✅ Action completed successfully' : `❌ ${msg}`}
          </div>
        )}
      </div>
    </>
  );
};

const UsersSection: React.FC = () => {
  const [users, setUsers]       = useState<SuperAdminUser[]>([]);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState('');
  const [search, setSearch]     = useState('');
  const [roleFilter, setRoleFilter] = useState('');
  const [planFilter, setPlanFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [selected, setSelected] = useState<SuperAdminUser | null>(null);
  const [page, setPage]         = useState(1);
  const PAGE_SIZE = 20;

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const params: Record<string, string> = {};
      if (search)       params.search = search;
      if (roleFilter)   params.role   = roleFilter;
      if (planFilter)   params.plan   = planFilter;
      if (statusFilter) params.status = statusFilter;
      params.page      = String(page);
      params.page_size = String(PAGE_SIZE);
      const res = await superadminApi.users(params);
      setUsers(res.data.users ?? res.data);
    } catch (e: unknown) {
      setError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to load users');
    } finally {
      setLoading(false);
    }
  }, [search, roleFilter, planFilter, statusFilter, page]);

  useEffect(() => { load(); }, [load]);

  const roleStyle = (role: string) => ROLE_BADGE_STYLES[role as UserRole] ?? ROLE_BADGE_STYLES.user;

  return (
    <div style={{ animation: 'sa-fadein 0.2s ease' }}>
      <SAStyles />
      {selected && <UserDetailDrawer user={selected} onClose={() => setSelected(null)} onRefresh={load} />}

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
          <Select
            value={roleFilter}
            onChange={e => { setRoleFilter(e.target.value); setPage(1); }}
            options={[
              { value: '', label: 'All Roles' },
              { value: 'user',       label: 'User' },
              { value: 'trader',     label: 'Trader' },
              { value: 'admin',      label: 'Admin' },
              { value: 'superadmin', label: 'Super Admin' },
            ]}
            style={{ width: 140 }}
          />
          <Select
            value={planFilter}
            onChange={e => { setPlanFilter(e.target.value); setPage(1); }}
            options={[
              { value: '', label: 'All Plans' },
              { value: 'free',    label: 'Free' },
              { value: 'starter', label: 'Starter' },
              { value: 'pro',     label: 'Pro' },
              { value: 'elite',   label: 'Elite' },
            ]}
            style={{ width: 130 }}
          />
          <Select
            value={statusFilter}
            onChange={e => { setStatusFilter(e.target.value); setPage(1); }}
            options={[
              { value: '', label: 'All Status' },
              { value: 'active',   label: 'Active' },
              { value: 'banned',   label: 'Banned' },
              { value: 'pending',  label: 'Pending' },
              { value: 'inactive', label: 'Inactive' },
            ]}
            style={{ width: 130 }}
          />
        </div>

        {/* Table */}
        {loading ? <LoadingRows rows={8} /> : error ? <ErrorState message={error} onRetry={load} /> : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid #1e293b' }}>
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
                  return (
                    <tr
                      key={u.user_id}
                      className="sa-row"
                      style={{ borderBottom: '1px solid #0f172a', cursor: 'pointer', transition: 'background 0.1s' }}
                      onClick={() => setSelected(u)}
                    >
                      <td style={{ padding: '10px 12px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                          <div style={{
                            width: 28, height: 28, borderRadius: '50%',
                            background: rs.bg, border: `1px solid ${rs.border}`,
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                            fontSize: 12, fontWeight: 700, color: rs.color, flexShrink: 0,
                          }}>
                            {u.username[0].toUpperCase()}
                          </div>
                          <div>
                            <div style={{ fontWeight: 600, color: '#f1f5f9' }}>{u.username}</div>
                            <div style={{ fontSize: 11, color: '#475569' }}>{u.email}</div>
                          </div>
                        </div>
                      </td>
                      <td style={{ padding: '10px 12px' }}>
                        <span style={{ fontSize: 11, fontWeight: 700, color: rs.color, background: rs.bg, border: `1px solid ${rs.border}`, borderRadius: 4, padding: '2px 7px' }}>
                          {ROLE_LABELS[u.role as UserRole] ?? u.role}
                        </span>
                      </td>
                      <td style={{ padding: '10px 12px' }}>
                        <span style={{ fontSize: 11, fontWeight: 700, color: PLAN_COLORS[u.plan as Plan] ?? '#94a3b8' }}>
                          {PLAN_LABELS[u.plan as Plan] ?? u.plan}
                        </span>
                      </td>
                      <td style={{ padding: '10px 12px' }}><StatusBadge status={u.status} size="sm" /></td>
                      <td style={{ padding: '10px 12px', color: '#94a3b8' }}>{u.total_trades.toLocaleString()}</td>
                      <td style={{ padding: '10px 12px', color: '#64748b', fontSize: 12 }}>{timeAgo(u.last_login)}</td>
                      <td style={{ padding: '10px 12px', color: '#64748b', fontSize: 12 }}>{fmtDate(u.created_at)}</td>
                      <td style={{ padding: '10px 12px' }}>
                        <span style={{ fontSize: 11, color: '#3b82f6' }}>View →</span>
                      </td>
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
