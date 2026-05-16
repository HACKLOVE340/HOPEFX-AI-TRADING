/**
 * SubAccounts — manage sub-accounts and trading teams.
 *
 * Backend:
 *   GET/POST/PATCH/DELETE /api/accounts/sub-accounts
 *   GET/POST              /api/accounts/teams
 *   POST/PATCH/DELETE     /api/accounts/teams/{id}/members
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../hooks/useApi';
import { extractApiError } from '../lib/utils';
import { PageHeader } from '../components/PageHeader';
import { DataTable, type Column } from '../components/DataTable';
import { Badge, type BadgeVariant } from '../components/Badge';
import { Modal } from '../components/Modal';
import { Spinner } from '../components/Spinner';
import { ErrorBanner } from '../components/ErrorBanner';
import { EmptyState } from '../components/EmptyState';
import { MetricCard } from '../components/MetricCard';

// ── Types ─────────────────────────────────────────────────────────────────────

interface SubAccount {
  account_id: string;
  label: string;
  broker: string;
  balance: number;
  equity: number;
  daily_pnl: number;
  active: boolean;
  created_at: string;
}

interface TeamMember {
  user_id: string;
  username: string;
  email: string;
  role: string;
  joined_at: string;
}

interface Team {
  team_id: string;
  name: string;
  creator_id: string;
  created_at: string;
  members: TeamMember[];
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const ROLE_VARIANT: Record<string, BadgeVariant> = {
  admin:   'danger',
  manager: 'warning',
  trader:  'info',
  viewer:  'neutral',
};

function fmt(n: number, prefix = '$'): string {
  return `${prefix}${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

// ── Sub-account columns ───────────────────────────────────────────────────────

function buildAccCols(
  onEdit: (a: SubAccount) => void,
  onDelete: (a: SubAccount) => void,
): Column<SubAccount>[] {
  return [
    {
      key: 'label',
      header: 'Label',
      sortKey: 'label',
      sortable: true,
      render: (r) => <span style={{ fontWeight: 600, color: '#f1f5f9' }}>{r.label}</span>,
    },
    {
      key: 'broker',
      header: 'Broker',
      render: (r) => <span style={{ color: '#94a3b8', fontSize: 12 }}>{r.broker}</span>,
    },
    {
      key: 'balance',
      header: 'Balance',
      align: 'right',
      sortKey: 'balance',
      sortable: true,
      render: (r) => <span style={{ fontFamily: 'monospace' }}>{fmt(r.balance)}</span>,
    },
    {
      key: 'equity',
      header: 'Equity',
      align: 'right',
      sortKey: 'equity',
      sortable: true,
      render: (r) => <span style={{ fontFamily: 'monospace' }}>{fmt(r.equity)}</span>,
    },
    {
      key: 'daily_pnl',
      header: 'Daily P&L',
      align: 'right',
      sortKey: 'daily_pnl',
      sortable: true,
      render: (r) => (
        <span style={{ color: r.daily_pnl >= 0 ? '#4ade80' : '#f87171', fontFamily: 'monospace', fontWeight: 600 }}>
          {r.daily_pnl >= 0 ? '+' : ''}{fmt(r.daily_pnl)}
        </span>
      ),
    },
    {
      key: 'active',
      header: 'Status',
      render: (r) => <Badge variant={r.active ? 'success' : 'neutral'}>{r.active ? 'Active' : 'Inactive'}</Badge>,
    },
    {
      key: 'actions',
      header: '',
      width: '100px',
      render: (r) => (
        <div style={{ display: 'flex', gap: 6 }}>
          <button onClick={() => onEdit(r)} style={btnStyle}>Edit</button>
          <button onClick={() => onDelete(r)} style={{ ...btnStyle, color: '#f87171', border: '1px solid rgba(248,113,113,0.3)' }}>Del</button>
        </div>
      ),
    },
  ];
}

// ── Team member columns ───────────────────────────────────────────────────────

function buildMemberCols(
  onRoleChange: (m: TeamMember) => void,
  onRemove: (m: TeamMember) => void,
): Column<TeamMember>[] {
  return [
    {
      key: 'username',
      header: 'Username',
      sortKey: 'username',
      sortable: true,
      render: (r) => <span style={{ color: '#60a5fa', fontWeight: 600 }}>{r.username}</span>,
    },
    {
      key: 'email',
      header: 'Email',
      render: (r) => <span style={{ color: '#94a3b8', fontSize: 12 }}>{r.email}</span>,
    },
    {
      key: 'role',
      header: 'Role',
      render: (r) => <Badge variant={ROLE_VARIANT[r.role] ?? 'neutral'}>{r.role}</Badge>,
    },
    {
      key: 'joined_at',
      header: 'Joined',
      render: (r) => (
        <span style={{ color: '#64748b', fontSize: 12 }}>
          {new Date(r.joined_at).toLocaleDateString()}
        </span>
      ),
    },
    {
      key: 'actions',
      header: '',
      width: '120px',
      render: (r) => (
        <div style={{ display: 'flex', gap: 6 }}>
          <button onClick={() => onRoleChange(r)} style={btnStyle}>Role</button>
          <button onClick={() => onRemove(r)} style={{ ...btnStyle, color: '#f87171', border: '1px solid rgba(248,113,113,0.3)' }}>Remove</button>
        </div>
      ),
    },
  ];
}

// ── Page ──────────────────────────────────────────────────────────────────────

const SubAccounts: React.FC = () => {
  const navigate = useNavigate();
  const [accounts, setAccounts]   = useState<SubAccount[]>([]);
  const [teams, setTeams]         = useState<Team[]>([]);
  const [selectedTeam, setSelectedTeam] = useState<Team | null>(null);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState<string | null>(null);

  // Modals
  const [showCreateAcc, setShowCreateAcc]   = useState(false);
  const [showCreateTeam, setShowCreateTeam] = useState(false);
  const [showInvite, setShowInvite]         = useState(false);
  const [editAcc, setEditAcc]               = useState<SubAccount | null>(null);

  // Form state
  const [newAccLabel, setNewAccLabel]   = useState('');
  const [newAccBroker, setNewAccBroker] = useState('oanda_paper');
  const [newAccBalance, setNewAccBalance] = useState('10000');
  const [newTeamName, setNewTeamName]   = useState('');
  const [inviteUserId, setInviteUserId] = useState('');
  const [inviteUsername, setInviteUsername] = useState('');
  const [inviteEmail, setInviteEmail]   = useState('');
  const [inviteRole, setInviteRole]     = useState('trader');
  const [saving, setSaving]             = useState(false);

  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [accRes, teamRes] = await Promise.all([
        api.get<{ accounts: SubAccount[] }>('/accounts/sub-accounts'),
        api.get<{ teams: Team[] }>('/accounts/teams'),
      ]);
      if (!mountedRef.current) return;
      setAccounts(accRes.data.accounts);
      setTeams(teamRes.data.teams);
      if (teamRes.data.teams.length > 0 && !selectedTeam) {
        setSelectedTeam(teamRes.data.teams[0]!);
      }
    } catch (e: unknown) {
      if (!mountedRef.current) return;
      setError(extractApiError(e, 'Failed to load accounts'));
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, [selectedTeam]);

  useEffect(() => { void load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Sub-account actions ──────────────────────────────────────────────────

  const handleCreateAcc = async () => {
    setSaving(true);
    try {
      await api.post('/accounts/sub-accounts', {
        label: newAccLabel,
        broker: newAccBroker,
        initial_balance: parseFloat(newAccBalance) || 10000,
      });
      setShowCreateAcc(false);
      setNewAccLabel('');
      await load();
    } catch (e: unknown) {
      setError(extractApiError(e, 'Create failed'));
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteAcc = async (acc: SubAccount) => {
    if (!confirm(`Delete sub-account "${acc.label}"?`)) return;
    try {
      await api.delete(`/accounts/sub-accounts/${acc.account_id}`);
      await load();
    } catch (e: unknown) {
      setError(extractApiError(e, 'Delete failed'));
    }
  };

  const handleEditAcc = async () => {
    if (!editAcc) return;
    setSaving(true);
    try {
      await api.patch(`/accounts/sub-accounts/${editAcc.account_id}`, {
        label: editAcc.label,
        active: editAcc.active,
      });
      setEditAcc(null);
      await load();
    } catch (e: unknown) {
      setError(extractApiError(e, 'Update failed'));
    } finally {
      setSaving(false);
    }
  };

  // ── Team actions ─────────────────────────────────────────────────────────

  const handleCreateTeam = async () => {
    setSaving(true);
    try {
      await api.post('/accounts/teams', { name: newTeamName });
      setShowCreateTeam(false);
      setNewTeamName('');
      await load();
    } catch (e: unknown) {
      setError(extractApiError(e, 'Create team failed'));
    } finally {
      setSaving(false);
    }
  };

  const handleInvite = async () => {
    if (!selectedTeam) return;
    setSaving(true);
    try {
      await api.post(`/accounts/teams/${selectedTeam.team_id}/members`, {
        user_id: inviteUserId,
        username: inviteUsername,
        email: inviteEmail,
        role: inviteRole,
      });
      setShowInvite(false);
      setInviteUserId('');
      setInviteUsername('');
      setInviteEmail('');
      await load();
    } catch (e: unknown) {
      setError(extractApiError(e, 'Invite failed'));
    } finally {
      setSaving(false);
    }
  };

  const handleRemoveMember = async (member: TeamMember) => {
    if (!selectedTeam) return;
    if (!confirm(`Remove ${member.username} from team?`)) return;
    try {
      await api.delete(`/accounts/teams/${selectedTeam.team_id}/members/${member.user_id}`);
      await load();
    } catch (e: unknown) {
      setError(extractApiError(e, 'Remove failed'));
    }
  };

  const handleRoleChange = async (member: TeamMember) => {
    if (!selectedTeam) return;
    const newRole = prompt(`New role for ${member.username} (admin/manager/trader/viewer):`, member.role);
    if (!newRole || !['admin', 'manager', 'trader', 'viewer'].includes(newRole)) return;
    try {
      await api.patch(`/accounts/teams/${selectedTeam.team_id}/members/${member.user_id}`, { role: newRole });
      await load();
    } catch (e: unknown) {
      setError(extractApiError(e, 'Role update failed'));
    }
  };

  // ── Derived metrics ───────────────────────────────────────────────────────

  const totalBalance = accounts.reduce((s, a) => s + a.balance, 0);
  const totalEquity  = accounts.reduce((s, a) => s + a.equity, 0);
  const totalPnl     = accounts.reduce((s, a) => s + a.daily_pnl, 0);

  const accCols    = buildAccCols((a) => setEditAcc({ ...a }), handleDeleteAcc);
  const memberCols = buildMemberCols(handleRoleChange, handleRemoveMember);
  const currentMembers = selectedTeam?.members ?? [];

  return (
    <div className="page-content">
      <PageHeader
        title="Sub-Accounts & Teams"
        subtitle="Manage trading accounts and team access"
        actions={
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={() => navigate('/trade')}
              style={{ padding: '7px 14px', background: 'rgba(59,130,246,0.12)', border: '1px solid rgba(59,130,246,0.35)', borderRadius: 7, color: '#60a5fa', fontSize: 12, fontWeight: 700, cursor: 'pointer' }}>
              ⚡ Trade
            </button>
            <button onClick={() => setShowCreateAcc(true)} style={s.primaryBtn}>+ Sub-Account</button>
            <button onClick={() => setShowCreateTeam(true)} style={s.secondaryBtn}>+ Team</button>
          </div>
        }
      />

      {error && <ErrorBanner message={error} onDismiss={() => setError(null)} style={{ marginBottom: 16 }} />}

      {/* Summary metrics */}
      <div style={s.metrics}>
        <MetricCard label="Total Balance"  value={fmt(totalBalance)}  icon="💰" loading={loading} />
        <MetricCard label="Total Equity"   value={fmt(totalEquity)}   icon="📊" loading={loading} />
        <MetricCard
          label="Daily P&L"
          value={fmt(totalPnl)}
          delta={totalPnl >= 0 ? `+${fmt(totalPnl)}` : fmt(totalPnl)}
          deltaPositive={totalPnl >= 0}
          icon="📈"
          loading={loading}
        />
        <MetricCard label="Sub-Accounts"   value={accounts.length}    icon="🗂️" loading={loading} />
      </div>

      {/* Sub-accounts table */}
      <section style={s.section}>
        <h2 style={s.sectionTitle}>Sub-Accounts</h2>
        {!loading && accounts.length === 0 ? (
          <EmptyState
            icon="🗂️"
            title="No sub-accounts yet"
            description="Create a sub-account to track separate P&L, risk limits, or broker connections."
            action={<button onClick={() => setShowCreateAcc(true)} style={s.primaryBtn}>Create Sub-Account</button>}
          />
        ) : (
          <DataTable<SubAccount>
            columns={accCols}
            data={accounts}
            rowKey={(r) => r.account_id}
            loading={loading}
            pageSize={10}
          />
        )}
      </section>

      {/* Teams section */}
      <section style={s.section}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
          <h2 style={s.sectionTitle}>Teams</h2>
          {teams.length > 1 && (
            <select
              value={selectedTeam?.team_id ?? ''}
              onChange={(e) => setSelectedTeam(teams.find((t) => t.team_id === e.target.value) ?? null)}
              style={s.select}
            >
              {teams.map((t) => (
                <option key={t.team_id} value={t.team_id}>{t.name}</option>
              ))}
            </select>
          )}
          {selectedTeam && (
            <button onClick={() => setShowInvite(true)} style={s.secondaryBtn}>+ Invite Member</button>
          )}
        </div>

        {!loading && teams.length === 0 ? (
          <EmptyState
            icon="👥"
            title="No teams yet"
            description="Create a team to collaborate with other traders and share strategies."
            action={<button onClick={() => setShowCreateTeam(true)} style={s.primaryBtn}>Create Team</button>}
          />
        ) : selectedTeam ? (
          <DataTable<TeamMember>
            columns={memberCols}
            data={currentMembers}
            rowKey={(r) => r.user_id}
            loading={loading}
            pageSize={20}
          />
        ) : null}
      </section>

      {/* ── Modals ─────────────────────────────────────────────────────────── */}

      {/* Create sub-account */}
      <Modal
        open={showCreateAcc}
        onClose={() => setShowCreateAcc(false)}
        title="Create Sub-Account"
        footer={
          <>
            <button onClick={() => setShowCreateAcc(false)} style={s.cancelBtn}>Cancel</button>
            <button onClick={handleCreateAcc} disabled={saving || !newAccLabel} style={s.primaryBtn}>
              {saving ? <Spinner size="sm" /> : 'Create'}
            </button>
          </>
        }
      >
        <div style={s.formGrid}>
          <label style={s.label}>Label</label>
          <input
            value={newAccLabel}
            onChange={(e) => setNewAccLabel(e.target.value)}
            placeholder="e.g. Paper Trading"
            style={s.input}
          />
          <label style={s.label}>Broker</label>
          <select value={newAccBroker} onChange={(e) => setNewAccBroker(e.target.value)} style={s.input}>
            <option value="oanda_paper">OANDA Paper</option>
            <option value="oanda_live">OANDA Live</option>
            <option value="ibkr">Interactive Brokers</option>
            <option value="mt5">MetaTrader 5</option>
          </select>
          <label style={s.label}>Initial Balance ($)</label>
          <input
            type="number"
            value={newAccBalance}
            onChange={(e) => setNewAccBalance(e.target.value)}
            min="0"
            style={s.input}
          />
        </div>
      </Modal>

      {/* Edit sub-account */}
      <Modal
        open={!!editAcc}
        onClose={() => setEditAcc(null)}
        title="Edit Sub-Account"
        footer={
          <>
            <button onClick={() => setEditAcc(null)} style={s.cancelBtn}>Cancel</button>
            <button onClick={handleEditAcc} disabled={saving} style={s.primaryBtn}>
              {saving ? <Spinner size="sm" /> : 'Save'}
            </button>
          </>
        }
      >
        {editAcc && (
          <div style={s.formGrid}>
            <label style={s.label}>Label</label>
            <input
              value={editAcc.label}
              onChange={(e) => setEditAcc({ ...editAcc, label: e.target.value })}
              style={s.input}
            />
            <label style={s.label}>Status</label>
            <select
              value={editAcc.active ? 'active' : 'inactive'}
              onChange={(e) => setEditAcc({ ...editAcc, active: e.target.value === 'active' })}
              style={s.input}
            >
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
            </select>
          </div>
        )}
      </Modal>

      {/* Create team */}
      <Modal
        open={showCreateTeam}
        onClose={() => setShowCreateTeam(false)}
        title="Create Team"
        footer={
          <>
            <button onClick={() => setShowCreateTeam(false)} style={s.cancelBtn}>Cancel</button>
            <button onClick={handleCreateTeam} disabled={saving || !newTeamName} style={s.primaryBtn}>
              {saving ? <Spinner size="sm" /> : 'Create'}
            </button>
          </>
        }
      >
        <div style={s.formGrid}>
          <label style={s.label}>Team Name</label>
          <input
            value={newTeamName}
            onChange={(e) => setNewTeamName(e.target.value)}
            placeholder="e.g. Alpha Desk"
            style={s.input}
          />
        </div>
      </Modal>

      {/* Invite member */}
      <Modal
        open={showInvite}
        onClose={() => setShowInvite(false)}
        title={`Invite to ${selectedTeam?.name ?? 'Team'}`}
        footer={
          <>
            <button onClick={() => setShowInvite(false)} style={s.cancelBtn}>Cancel</button>
            <button
              onClick={handleInvite}
              disabled={saving || !inviteUserId || !inviteUsername}
              style={s.primaryBtn}
            >
              {saving ? <Spinner size="sm" /> : 'Invite'}
            </button>
          </>
        }
      >
        <div style={s.formGrid}>
          <label style={s.label}>User ID</label>
          <input value={inviteUserId} onChange={(e) => setInviteUserId(e.target.value)} placeholder="user-xxx" style={s.input} />
          <label style={s.label}>Username</label>
          <input value={inviteUsername} onChange={(e) => setInviteUsername(e.target.value)} placeholder="trader_x" style={s.input} />
          <label style={s.label}>Email</label>
          <input type="email" value={inviteEmail} onChange={(e) => setInviteEmail(e.target.value)} placeholder="trader@example.com" style={s.input} />
          <label style={s.label}>Role</label>
          <select value={inviteRole} onChange={(e) => setInviteRole(e.target.value)} style={s.input}>
            <option value="viewer">Viewer</option>
            <option value="trader">Trader</option>
            <option value="manager">Manager</option>
            <option value="admin">Admin</option>
          </select>
        </div>
      </Modal>
    </div>
  );
};

// ── Styles ────────────────────────────────────────────────────────────────────

const btnStyle: React.CSSProperties = {
  background: 'transparent',
  border: '1px solid var(--border, #334155)',
  borderRadius: 5,
  color: '#94a3b8',
  cursor: 'pointer',
  fontSize: 11,
  padding: '3px 8px',
};

const s: Record<string, React.CSSProperties> = {
  page:    { padding: '24px 28px', maxWidth: 1200 },
  metrics: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12, marginBottom: 28 },
  section: { marginBottom: 32 },
  sectionTitle: { color: 'var(--text, #f1f5f9)', fontSize: 15, fontWeight: 600, marginBottom: 12 },
  primaryBtn: {
    alignItems: 'center', background: '#3b82f6', border: 'none', borderRadius: 6,
    color: '#fff', cursor: 'pointer', display: 'flex', fontSize: 13, fontWeight: 600,
    gap: 6, padding: '7px 16px',
  },
  secondaryBtn: {
    background: 'transparent', border: '1px solid var(--border, #334155)', borderRadius: 6,
    color: 'var(--text-muted, #94a3b8)', cursor: 'pointer', fontSize: 13, padding: '7px 14px',
  },
  cancelBtn: {
    background: 'transparent', border: '1px solid var(--border, #334155)', borderRadius: 6,
    color: 'var(--text-muted, #94a3b8)', cursor: 'pointer', fontSize: 13, padding: '7px 14px',
  },
  formGrid: { display: 'flex', flexDirection: 'column', gap: 10 },
  label:    { color: 'var(--text-muted, #94a3b8)', fontSize: 12, fontWeight: 600 },
  input: {
    background: 'var(--surface-raised, #243044)', border: '1px solid var(--border, #334155)',
    borderRadius: 6, color: 'var(--text, #f1f5f9)', fontSize: 13, outline: 'none', padding: '8px 12px',
  },
  select: {
    background: 'var(--surface, #1e293b)', border: '1px solid var(--border, #334155)',
    borderRadius: 6, color: 'var(--text, #f1f5f9)', fontSize: 13, padding: '6px 10px',
  },
};

export default SubAccounts;
