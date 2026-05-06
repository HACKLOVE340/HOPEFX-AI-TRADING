/**
 * Teams page — collaborative trading teams with shared strategies and P&L.
 *
 * Wires to:
 *   GET  /api/teams                     — list user's teams
 *   POST /api/teams                     — create team
 *   GET  /api/teams/{id}                — team detail
 *   POST /api/teams/{id}/members        — invite member
 *   DELETE /api/teams/{id}/members/{uid} — remove member
 *   GET  /api/teams/{id}/performance    — team P&L
 *
 * Requires: enterprise plan
 */

import React, { useState, useCallback } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { teamsApi } from '../hooks/useApi';
import { useStore } from '../store';
import { PageHeader } from '../components/PageHeader';
import { EmptyState } from '../components/EmptyState';
import { Spinner } from '../components/Spinner';

// ── Types ─────────────────────────────────────────────────────────────────────

interface TeamMember {
  user_id: string;
  username: string;
  email: string;
  role: 'owner' | 'manager' | 'trader' | 'viewer';
  joined_at: string;
  pnl_contribution: number;
}

interface Team {
  team_id: string;
  name: string;
  description: string;
  owner_id: string;
  member_count: number;
  status: 'active' | 'suspended' | 'archived';
  created_at: string;
  members?: TeamMember[];
  performance?: TeamPerformance;
}

interface TeamPerformance {
  total_pnl:        number;
  win_rate:         number;   // fraction 0–1 (e.g. 0.62 = 62%) — multiply by 100 to display
  total_trades:     number;
  sharpe:           number;
  max_drawdown_pct: number;   // already a percentage (e.g. 8.3)
  period:           string;
}

// teamsApi is imported from hooks/useApi

// ── Role badge ────────────────────────────────────────────────────────────────

const ROLE_COLORS: Record<string, { bg: string; color: string }> = {
  owner:   { bg: '#f59e0b22', color: '#f59e0b' },
  manager: { bg: '#8b5cf622', color: '#8b5cf6' },
  trader:  { bg: '#3b82f622', color: '#3b82f6' },
  viewer:  { bg: '#64748b22', color: '#94a3b8' },
};

function RoleBadge({ role }: { role: string }) {
  const c = ROLE_COLORS[role] ?? ROLE_COLORS.viewer;
  return (
    <span style={{ padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 600,
      background: c.bg, color: c.color, textTransform: 'capitalize' }}>
      {role}
    </span>
  );
}

// ── Stat card ─────────────────────────────────────────────────────────────────

function StatCard({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: '12px 16px' }}>
      <div style={{ fontSize: 11, color: '#64748b', marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 700, color: color ?? '#e2e8f0' }}>{value}</div>
    </div>
  );
}

// ── Team detail panel ─────────────────────────────────────────────────────────

function TeamDetail({ team, onClose }: { team: Team; onClose: () => void }) {
  const qc = useQueryClient();
  const currentUser = useStore(s => s.user);
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteRole, setInviteRole]   = useState('trader');
  const [tab, setTab]                 = useState<'members' | 'performance'>('members');

  const { data: perfData } = useQuery({
    queryKey: ['team-perf', team.team_id],
    queryFn: () => teamsApi.getPerformance(team.team_id).then(r => r.data as TeamPerformance),
  });

  const { data: detailData } = useQuery({
    queryKey: ['team-detail', team.team_id],
    queryFn: () => teamsApi.get(team.team_id).then(r => r.data as Team),
    initialData: team,
  });

  const inviteMut = useMutation({
    mutationFn: () => teamsApi.invite(team.team_id, { email: inviteEmail, role: inviteRole }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['team-detail', team.team_id] });
      setInviteEmail('');
    },
    onError: (err: unknown) => {
      console.error('[TeamsPage] invite error:', err);
    },
  });

  const removeMut = useMutation({
    mutationFn: (uid: string) => teamsApi.removeMember(team.team_id, uid),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['team-detail', team.team_id] }),
    onError: (err: unknown) => {
      console.error('[TeamsPage] removeMember error:', err);
    },
  });

  const members = detailData?.members ?? [];
  const perf    = perfData;
  const isOwner = detailData?.owner_id === currentUser?.id;

  return (
    <div style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 12, padding: 24 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
        <div>
          <h2 style={{ margin: '0 0 4px', fontSize: 18, fontWeight: 700, color: '#e2e8f0' }}>{detailData?.name}</h2>
          <p style={{ margin: 0, fontSize: 12, color: '#64748b' }}>{detailData?.description}</p>
        </div>
        <button onClick={onClose}
          style={{ padding: '6px 10px', background: '#334155', color: '#94a3b8', border: 'none',
            borderRadius: 6, fontSize: 12, cursor: 'pointer' }}>✕</button>
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 20, borderBottom: '1px solid #334155', paddingBottom: 0 }}>
        {(['members', 'performance'] as const).map(t => (
          <button key={t} onClick={() => setTab(t)}
            style={{ padding: '8px 16px', background: 'none', border: 'none', cursor: 'pointer',
              fontSize: 13, fontWeight: tab === t ? 600 : 400,
              color: tab === t ? '#8b5cf6' : '#64748b',
              borderBottom: tab === t ? '2px solid #8b5cf6' : '2px solid transparent',
              textTransform: 'capitalize' }}>
            {t}
          </button>
        ))}
      </div>

      {tab === 'members' && (
        <div>
          {/* Invite form (owner/manager only) */}
          {isOwner && (
            <div style={{ marginBottom: 16 }}>
              <div style={{ display: 'flex', gap: 8 }}>
                <input value={inviteEmail} onChange={e => setInviteEmail(e.target.value)}
                  placeholder="Email address"
                  style={{ flex: 1, background: '#0f172a', border: '1px solid #334155', borderRadius: 6,
                    padding: '8px 10px', color: '#e2e8f0', fontSize: 13 }} />
                <select value={inviteRole} onChange={e => setInviteRole(e.target.value)}
                  style={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 6,
                    padding: '8px 10px', color: '#e2e8f0', fontSize: 13 }}>
                  <option value="trader">Trader</option>
                  <option value="manager">Manager</option>
                  <option value="viewer">Viewer</option>
                </select>
                <button onClick={() => inviteMut.mutate()} disabled={!inviteEmail.trim() || inviteMut.isPending}
                  style={{ padding: '8px 14px', background: '#8b5cf6', color: '#fff', border: 'none',
                    borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: 'pointer',
                    opacity: (!inviteEmail.trim() || inviteMut.isPending) ? 0.5 : 1 }}>
                  Invite
                </button>
              </div>
              {inviteMut.isError && (
                <div style={{ marginTop: 6, fontSize: 12, color: '#f87171' }}>
                  ⚠ {(inviteMut.error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
                    ?? (inviteMut.error instanceof Error ? inviteMut.error.message : 'Invite failed')}
                </div>
              )}
              {inviteMut.isSuccess && (
                <div style={{ marginTop: 6, fontSize: 12, color: '#4ade80' }}>Invitation sent.</div>
              )}
            </div>
          )}

          {/* Member list */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {members.length === 0 && (
              <div style={{ color: '#64748b', fontSize: 13, textAlign: 'center', padding: 20 }}>No members yet</div>
            )}
            {members.map(m => (
              <div key={m.user_id} style={{
                display: 'flex', alignItems: 'center', gap: 12,
                background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: '10px 14px',
              }}>
                <div style={{ width: 32, height: 32, borderRadius: '50%', background: '#334155',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 13, fontWeight: 700, color: '#94a3b8', flexShrink: 0 }}>
                  {m.username?.[0]?.toUpperCase() ?? '?'}
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0' }}>{m.username}</div>
                  <div style={{ fontSize: 11, color: '#64748b' }}>{m.email}</div>
                </div>
                <RoleBadge role={m.role} />
                <div style={{ fontSize: 12, color: m.pnl_contribution >= 0 ? '#22c55e' : '#ef4444', fontWeight: 600 }}>
                  {m.pnl_contribution >= 0 ? '+' : ''}{m.pnl_contribution.toFixed(2)}
                </div>
                {isOwner && m.role !== 'owner' && (
                  <button onClick={() => removeMut.mutate(m.user_id)}
                    style={{ padding: '4px 8px', background: '#ef444422', color: '#ef4444',
                      border: '1px solid #ef444444', borderRadius: 4, fontSize: 11, cursor: 'pointer' }}>
                    Remove
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {tab === 'performance' && perf && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 10 }}>
            <StatCard label="Total P&L" value={`$${perf.total_pnl.toFixed(2)}`}
              color={perf.total_pnl >= 0 ? '#22c55e' : '#ef4444'} />
            <StatCard label="Win Rate" value={`${(perf.win_rate * 100).toFixed(1)}%`} />
            <StatCard label="Total Trades" value={perf.total_trades.toString()} />
            <StatCard label="Sharpe" value={perf.sharpe.toFixed(2)} />
            <StatCard label="Max Drawdown" value={`${perf.max_drawdown_pct.toFixed(1)}%`}
              color="#ef4444" />
          </div>
          <div style={{ fontSize: 11, color: '#475569', textAlign: 'right' }}>Period: {perf.period}</div>
        </div>
      )}

      {tab === 'performance' && !perf && (
        <div style={{ color: '#64748b', fontSize: 13, textAlign: 'center', padding: 30 }}>
          No performance data available yet
        </div>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

const TeamsPage: React.FC = () => {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [selected, setSelected]   = useState<Team | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName]       = useState('');
  const [newDesc, setNewDesc]       = useState('');

  const { data, isLoading } = useQuery({
    queryKey: ['teams'],
    queryFn: () => teamsApi.list().then(r => r.data as { teams: Team[]; total: number }),
    refetchInterval: 15_000,
  });

  const createMut = useMutation({
    mutationFn: () => teamsApi.create({ name: newName, description: newDesc }),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ['teams'] });
      setShowCreate(false);
      setNewName('');
      setNewDesc('');
      setSelected(res.data as Team);
    },
    onError: (err: unknown) => {
      console.error('[TeamsPage] createTeam error:', err);
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => teamsApi.delete(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['teams'] }); setSelected(null); },
    onError: (err: unknown) => {
      console.error('[TeamsPage] deleteTeam error:', err);
    },
  });

  const teams = data?.teams ?? [];

  return (
    <div style={{ padding: '24px 28px', maxWidth: 1200, margin: '0 auto' }}>
      <PageHeader
        title="Teams"
        subtitle="Collaborative trading with shared strategies and P&L — enterprise tier"
        breadcrumbs={[
          { label: 'Dashboard', href: '/dashboard' },
          { label: 'Teams' },
        ]}
        badge={<span style={{ fontSize: 11, fontWeight: 700, padding: '2px 8px', borderRadius: 20, background: 'rgba(6,182,212,0.15)', color: '#06b6d4', border: '1px solid rgba(6,182,212,0.3)' }}>ENTERPRISE</span>}
        actions={
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={() => navigate('/leaderboard')}
              style={{ padding: '7px 14px', background: 'rgba(245,158,11,0.12)', border: '1px solid rgba(245,158,11,0.35)', borderRadius: 8, color: '#f59e0b', fontSize: 12, fontWeight: 600, cursor: 'pointer' }}>
              🏆 Leaderboard
            </button>
            <button onClick={() => navigate('/copy-trading')}
              style={{ padding: '7px 14px', background: 'rgba(52,211,153,0.12)', border: '1px solid rgba(52,211,153,0.35)', borderRadius: 8, color: '#34d399', fontSize: 12, fontWeight: 600, cursor: 'pointer' }}>
              🔁 Copy Trading
            </button>
            <button onClick={() => setShowCreate(s => !s)}
              style={{ padding: '8px 18px', background: '#06b6d4', color: '#fff', border: 'none', borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>
              + New Team
            </button>
          </div>
        }
      />

      {/* Cross-links */}
      <div style={{ display: 'flex', gap: 16, marginBottom: 24, flexWrap: 'wrap', fontSize: 13 }}>
        {[
          { to: '/sub-accounts', label: '🗂 Sub-Accounts' },
          { to: '/performance', label: '📊 Performance' },
          { to: '/signals', label: '📡 Signals' },
          { to: '/affiliate', label: '💰 Affiliate' },
          { to: '/chat', label: '💬 Team Chat' },
        ].map(({ to, label }) => (
          <Link key={to} to={to} style={{ color: '#64748b', textDecoration: 'none' }}
            onMouseEnter={e => (e.currentTarget.style.color = '#94a3b8')}
            onMouseLeave={e => (e.currentTarget.style.color = '#64748b')}>
            {label}
          </Link>
        ))}
      </div>

      {/* Create form */}
      {showCreate && (
        <div style={{ background: '#1e293b', border: '1px solid #06b6d444', borderRadius: 12,
          padding: 20, marginBottom: 20 }}>
          <h3 style={{ margin: '0 0 14px', fontSize: 14, fontWeight: 600, color: '#e2e8f0' }}>Create Team</h3>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12 }}>
            <input value={newName} onChange={e => setNewName(e.target.value)} placeholder="Team name"
              style={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 6,
                padding: '8px 10px', color: '#e2e8f0', fontSize: 13 }} />
            <input value={newDesc} onChange={e => setNewDesc(e.target.value)} placeholder="Description (optional)"
              style={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 6,
                padding: '8px 10px', color: '#e2e8f0', fontSize: 13 }} />
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <button onClick={() => createMut.mutate()} disabled={!newName.trim() || createMut.isPending}
              style={{ padding: '8px 16px', background: '#06b6d4', color: '#fff', border: 'none',
                borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: 'pointer',
                opacity: (!newName.trim() || createMut.isPending) ? 0.5 : 1 }}>
              {createMut.isPending ? 'Creating…' : 'Create'}
            </button>
            <button onClick={() => setShowCreate(false)}
              style={{ padding: '8px 14px', background: '#334155', color: '#94a3b8', border: 'none',
                borderRadius: 6, fontSize: 13, cursor: 'pointer' }}>
              Cancel
            </button>
            {createMut.isError && (
              <span style={{ fontSize: 12, color: '#f87171' }}>
                ⚠ {(createMut.error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
                  ?? (createMut.error instanceof Error ? createMut.error.message : 'Failed to create team')}
              </span>
            )}
          </div>
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: selected ? '280px 1fr' : '1fr', gap: 20 }}>
        {/* Team list */}
        <div>
          {isLoading && (
            <div style={{ display: 'flex', justifyContent: 'center', padding: 40 }}>
              <Spinner size="md" />
            </div>
          )}
          {!isLoading && teams.length === 0 && (
            <EmptyState
              icon="👥"
              title="No teams yet"
              description="Create a team to collaborate with other traders on shared strategies and P&L."
              action={{ label: '+ New Team', onClick: () => setShowCreate(true) }}
            />
          )}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {teams.map(t => (
              <div key={t.team_id} onClick={() => setSelected(t)}
                style={{
                  background: selected?.team_id === t.team_id ? '#0c2340' : '#1e293b',
                  border: `1px solid ${selected?.team_id === t.team_id ? '#06b6d4' : '#334155'}`,
                  borderRadius: 10, padding: '14px 16px', cursor: 'pointer',
                }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                  <span style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0' }}>{t.name}</span>
                  <span style={{ fontSize: 11, color: t.status === 'active' ? '#22c55e' : '#ef4444',
                    background: t.status === 'active' ? '#22c55e22' : '#ef444422',
                    padding: '2px 6px', borderRadius: 4, fontWeight: 600 }}>
                    {t.status}
                  </span>
                </div>
                <div style={{ fontSize: 11, color: '#64748b' }}>
                  {t.member_count} member{t.member_count !== 1 ? 's' : ''}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Team detail */}
        {selected && (
          <TeamDetail
            team={selected}
            onClose={() => setSelected(null)}
          />
        )}
      </div>
    </div>
  );
};

export default TeamsPage;
