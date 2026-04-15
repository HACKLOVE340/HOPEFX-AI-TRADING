/**
 * Trader Profile Page
 *
 * Shows avatar, display name, trading stats, strategy list,
 * follower/following counts, recent signals, and copy-trading button.
 * Works for both /profile/me (own profile) and /profile/:id (public).
 */

import React, { useEffect, useState, useCallback } from 'react';
import { api } from '../hooks/useApi';

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

// ─── Types ────────────────────────────────────────────────────────────────────

interface ProfileData {
  trader_id:       string;
  username:        string;
  bio:             string;
  avatar_url:      string | null;
  website:         string | null;
  verified:        boolean;
  is_public:       boolean;
  total_followers: number;
  total_following: number;
  total_trades:    number;
  win_rate:        number;
  total_pnl:       number;
  avg_win:         number;
  avg_loss:        number;
  sharpe_ratio:    number;
  created_at:      string | null;
}

interface Signal {
  signal_id:  string;
  symbol:     string;
  direction:  'BUY' | 'SELL';
  confidence: number;
  pnl:        number;
  copies:     number;
  created_at: string;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const fmt = (n: number, d = 2) =>
  n.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });

const fmtUSD = (n: number) =>
  (n >= 0 ? '+$' : '-$') + Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function initials(name: string) {
  return name.slice(0, 2).toUpperCase();
}

// ─── Avatar ───────────────────────────────────────────────────────────────────

const Avatar: React.FC<{ url: string | null; name: string; size?: number }> = ({
  url, name, size = 80,
}) => (
  <div style={{
    width: size, height: size, borderRadius: '50%',
    background: url ? 'transparent' : '#3b82f6',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    fontSize: size * 0.35, fontWeight: 700, color: '#fff',
    overflow: 'hidden', flexShrink: 0,
    border: '3px solid #334155',
  }}>
    {url
      ? <img src={url} alt={name} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
      : initials(name)
    }
  </div>
);

// ─── Stat card ────────────────────────────────────────────────────────────────

const StatCard: React.FC<{ label: string; value: string; color?: string }> = ({
  label, value, color = '#f8fafc',
}) => (
  <div style={s.statCard}>
    <div style={s.statLabel}>{label}</div>
    <div style={{ ...s.statValue, color }}>{value}</div>
  </div>
);

// ─── Signal row ───────────────────────────────────────────────────────────────

const SignalRow: React.FC<{ sig: Signal }> = ({ sig }) => (
  <div style={s.signalRow}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <span style={{
        ...s.badge,
        background: sig.direction === 'BUY' ? 'rgba(74,222,128,0.15)' : 'rgba(248,113,113,0.15)',
        color: sig.direction === 'BUY' ? '#4ade80' : '#f87171',
      }}>
        {sig.direction}
      </span>
      <span style={{ fontWeight: 600, fontSize: 14 }}>{sig.symbol}</span>
      <span style={{ fontSize: 12, color: '#64748b' }}>{sig.confidence.toFixed(0)}% conf.</span>
    </div>
    <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
      <span style={{ fontSize: 13, color: sig.pnl >= 0 ? '#4ade80' : '#f87171' }}>
        {fmtUSD(sig.pnl)}
      </span>
      <span style={{ fontSize: 12, color: '#64748b' }}>{sig.copies} copied</span>
    </div>
  </div>
);

// ─── Edit modal ───────────────────────────────────────────────────────────────

const EditModal: React.FC<{
  profile: ProfileData;
  onSave: (data: Partial<ProfileData>) => void;
  onClose: () => void;
  saveErr: string | null;
}> = ({ profile, onSave, onClose, saveErr }) => {
  const [bio, setBio]          = useState(profile.bio);
  const [website, setWebsite]  = useState(profile.website || '');
  const [avatarUrl, setAvatar] = useState(profile.avatar_url || '');

  return (
    <div style={s.overlay}>
      <div style={s.modal}>
        <div style={s.modalHeader}>
          <span style={{ fontWeight: 700, fontSize: 16 }}>Edit Profile</span>
          <button style={s.closeBtn} onClick={onClose}>✕</button>
        </div>
        {saveErr && (
          <div style={s.modalError}>{saveErr}</div>
        )}
        <label style={s.fieldLabel}>Bio</label>
        <textarea
          style={s.textarea}
          value={bio}
          onChange={(e) => setBio(e.target.value)}
          maxLength={500}
          rows={3}
        />
        <label style={s.fieldLabel}>Avatar URL</label>
        <input style={s.textInput} value={avatarUrl} onChange={(e) => setAvatar(e.target.value)} placeholder="https://…" />
        <label style={s.fieldLabel}>Website</label>
        <input style={s.textInput} value={website} onChange={(e) => setWebsite(e.target.value)} placeholder="https://…" />
        <div style={{ display: 'flex', gap: 8, marginTop: 20 }}>
          <button style={s.saveBtn} onClick={() => onSave({ bio, website: website || null, avatar_url: avatarUrl || null })}>
            Save
          </button>
          <button style={s.cancelBtn} onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
};

// ─── Main component ───────────────────────────────────────────────────────────

const Profile: React.FC = () => {
  // Determine trader_id from URL hash: /profile#<id> or /profile (own)
  const traderId = window.location.hash.slice(1) || 'me';
  const isOwnProfile = traderId === 'me';

  const [profile, setProfile]     = useState<ProfileData | null>(null);
  const [signals, setSignals]     = useState<Signal[]>([]);
  const [loading, setLoading]     = useState(true);
  const [following, setFollowing] = useState(false);
  const [followErr, setFollowErr] = useState<string | null>(null);
  const [saveErr, setSaveErr]     = useState<string | null>(null);
  const [editing, setEditing]     = useState(false);
  const [tab, setTab]             = useState<'signals' | 'stats'>('signals');

  const loadProfile = useCallback(async () => {
    setLoading(true);
    try {
      const endpoint = isOwnProfile ? '/profiles/me' : `/profiles/${traderId}`;
      const res = await api.get(endpoint);
      setProfile(res.data);

      const sigRes = await api.get(`/profiles/${res.data.trader_id}/signals`);
      setSignals(sigRes.data.signals || []);
    } catch {
      setProfile(null);
      setSignals([]);
    } finally {
      setLoading(false);
    }
  }, [traderId, isOwnProfile]);

  useEffect(() => { loadProfile(); }, [loadProfile]);

  const handleFollow = async () => {
    if (!profile) return;
    setFollowErr(null);
    try {
      if (following) {
        await api.delete(`/profiles/${profile.trader_id}/follow`);
      } else {
        await api.post(`/profiles/${profile.trader_id}/follow`);
      }
      setFollowing(!following);
      setProfile((p) => p ? {
        ...p,
        total_followers: p.total_followers + (following ? -1 : 1),
      } : p);
    } catch (err) {
      setFollowErr(extractErrorMessage(err, 'Failed to update follow status. Please try again.'));
    }
  };

  const handleSave = async (updates: Partial<ProfileData>) => {
    setSaveErr(null);
    try {
      const res = await api.put('/profiles/me', updates);
      setProfile(res.data);
      setEditing(false);
    } catch (err) {
      setSaveErr(extractErrorMessage(err, 'Failed to save profile. Please try again.'));
      // Keep modal open so user can retry
    }
  };

  if (loading) return <div style={s.loading}>Loading profile…</div>;
  if (!profile) return <div style={s.loading}>Profile not found.</div>;

  const rrRatio = (profile.avg_loss ?? 0) > 0 ? ((profile.avg_win ?? 0) / (profile.avg_loss ?? 1)).toFixed(2) : '—';
  const memberSince = profile.created_at
    ? new Date(profile.created_at).toLocaleDateString('en-US', { month: 'long', year: 'numeric' })
    : '—';

  return (
    <div style={s.page}>
      {editing && (
        <EditModal
          profile={profile}
          onSave={handleSave}
          onClose={() => { setEditing(false); setSaveErr(null); }}
          saveErr={saveErr}
        />
      )}

      {/* ── Header ── */}
      <div style={s.headerCard}>
        <div style={s.headerTop}>
          <Avatar url={profile.avatar_url} name={profile.username} size={88} />
          <div style={s.headerInfo}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <h1 style={s.username}>{profile.username}</h1>
              {profile.verified && (
                <span style={s.verifiedBadge} title="Verified trader">✓</span>
              )}
            </div>
            <div style={s.bio}>{profile.bio || 'No bio yet.'}</div>
            {profile.website && (
              <a href={profile.website} target="_blank" rel="noopener noreferrer" style={s.website}>
                {profile.website}
              </a>
            )}
            <div style={s.memberSince}>Member since {memberSince}</div>
          </div>
          <div style={s.headerActions}>
            {isOwnProfile ? (
              <button style={s.editBtn} onClick={() => setEditing(true)}>Edit Profile</button>
            ) : (
              <>
                <button
                  style={{ ...s.followBtn, ...(following ? s.followingBtn : {}) }}
                  onClick={handleFollow}
                >
                  {following ? 'Following' : 'Follow'}
                </button>
                <button style={s.copyBtn}>Copy Trade</button>
                {followErr && (
                  <div style={s.inlineError}>{followErr}</div>
                )}
              </>
            )}
          </div>
        </div>

        {/* Follower counts */}
        <div style={s.socialRow}>
          <div style={s.socialStat}>
            <span style={s.socialNum}>{(profile.total_followers ?? 0).toLocaleString()}</span>
            <span style={s.socialLabel}>Followers</span>
          </div>
          <div style={s.socialDivider} />
          <div style={s.socialStat}>
            <span style={s.socialNum}>{(profile.total_following ?? 0).toLocaleString()}</span>
            <span style={s.socialLabel}>Following</span>
          </div>
          <div style={s.socialDivider} />
          <div style={s.socialStat}>
            <span style={s.socialNum}>{(profile.total_trades ?? 0).toLocaleString()}</span>
            <span style={s.socialLabel}>Trades</span>
          </div>
        </div>
      </div>

      {/* ── Stats grid ── */}
      <div style={s.statsGrid}>
        <StatCard label="Win Rate"    value={`${(profile.win_rate ?? 0).toFixed(1)}%`}  color={(profile.win_rate ?? 0) >= 50 ? '#4ade80' : '#f87171'} />
        <StatCard label="Total P&L"   value={fmtUSD(profile.total_pnl ?? 0)}          color={(profile.total_pnl ?? 0) >= 0 ? '#4ade80' : '#f87171'} />
        <StatCard label="Avg Win"     value={`$${fmt(profile.avg_win ?? 0)}`}          color="#4ade80" />
        <StatCard label="Avg Loss"    value={`$${fmt(profile.avg_loss ?? 0)}`}         color="#f87171" />
        <StatCard label="R:R Ratio"   value={`1:${rrRatio}`}                           color="#60a5fa" />
        <StatCard label="Sharpe"      value={(profile.sharpe_ratio ?? 0).toFixed(2)}   color={(profile.sharpe_ratio ?? 0) >= 1 ? '#4ade80' : '#facc15'} />
      </div>

      {/* ── Tabs ── */}
      <div style={s.tabs}>
        <button
          style={{ ...s.tab, ...(tab === 'signals' ? s.tabActive : {}) }}
          onClick={() => setTab('signals')}
        >
          Recent Signals
        </button>
        <button
          style={{ ...s.tab, ...(tab === 'stats' ? s.tabActive : {}) }}
          onClick={() => setTab('stats')}
        >
          Performance
        </button>
      </div>

      {tab === 'signals' && (
        <div style={s.card}>
          {signals.length === 0 ? (
            <div style={s.empty}>No public signals yet.</div>
          ) : (
            signals.map((sig) => <SignalRow key={sig.signal_id} sig={sig} />)
          )}
        </div>
      )}

      {tab === 'stats' && (
        <div style={s.card}>
          <div style={s.perfRow}>
            <div style={s.perfLabel}>Total Trades</div>
            <div style={s.perfValue}>{(profile.total_trades ?? 0).toLocaleString()}</div>
          </div>
          <div style={s.perfRow}>
            <div style={s.perfLabel}>Win Rate</div>
            <div style={{ ...s.perfValue, color: (profile.win_rate ?? 0) >= 50 ? '#4ade80' : '#f87171' }}>
              {(profile.win_rate ?? 0).toFixed(1)}%
            </div>
          </div>
          <div style={s.perfRow}>
            <div style={s.perfLabel}>Total P&L</div>
            <div style={{ ...s.perfValue, color: (profile.total_pnl ?? 0) >= 0 ? '#4ade80' : '#f87171' }}>
              {fmtUSD(profile.total_pnl ?? 0)}
            </div>
          </div>
          <div style={s.perfRow}>
            <div style={s.perfLabel}>Average Win</div>
            <div style={{ ...s.perfValue, color: '#4ade80' }}>${fmt(profile.avg_win ?? 0)}</div>
          </div>
          <div style={s.perfRow}>
            <div style={s.perfLabel}>Average Loss</div>
            <div style={{ ...s.perfValue, color: '#f87171' }}>${fmt(profile.avg_loss ?? 0)}</div>
          </div>
          <div style={s.perfRow}>
            <div style={s.perfLabel}>Risk:Reward</div>
            <div style={{ ...s.perfValue, color: '#60a5fa' }}>1:{rrRatio}</div>
          </div>
          <div style={s.perfRow}>
            <div style={s.perfLabel}>Sharpe Ratio</div>
            <div style={{ ...s.perfValue, color: (profile.sharpe_ratio ?? 0) >= 1 ? '#4ade80' : '#facc15' }}>
              {(profile.sharpe_ratio ?? 0).toFixed(2)}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

// ─── Styles ───────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  page: {
    minHeight: '100vh',
    background: '#0f172a',
    color: '#f8fafc',
    fontFamily: "'Inter', system-ui, sans-serif",
    padding: '24px',
    maxWidth: 800,
    margin: '0 auto',
  },
  loading: { color: '#94a3b8', padding: 48, textAlign: 'center' },
  headerCard: {
    background: '#1e293b',
    borderRadius: 16,
    padding: 28,
    border: '1px solid #334155',
    marginBottom: 20,
  },
  headerTop: {
    display: 'flex', gap: 20, alignItems: 'flex-start', flexWrap: 'wrap',
  },
  headerInfo: { flex: 1, minWidth: 200 },
  username: { fontSize: 24, fontWeight: 800, margin: 0 },
  verifiedBadge: {
    background: '#3b82f6', color: '#fff', borderRadius: '50%',
    width: 20, height: 20, display: 'inline-flex', alignItems: 'center',
    justifyContent: 'center', fontSize: 11, fontWeight: 700,
  },
  bio: { fontSize: 14, color: '#94a3b8', marginTop: 6, lineHeight: 1.5 },
  website: { fontSize: 13, color: '#60a5fa', marginTop: 4, display: 'block' },
  memberSince: { fontSize: 12, color: '#475569', marginTop: 6 },
  headerActions: { display: 'flex', flexDirection: 'column', gap: 8 },
  editBtn: {
    background: '#334155', border: 'none', borderRadius: 8,
    color: '#f8fafc', padding: '8px 16px', fontSize: 13, cursor: 'pointer',
  },
  followBtn: {
    background: '#3b82f6', border: 'none', borderRadius: 8,
    color: '#fff', padding: '8px 20px', fontSize: 13, cursor: 'pointer', fontWeight: 600,
  },
  followingBtn: { background: '#334155', color: '#94a3b8' },
  copyBtn: {
    background: 'rgba(74,222,128,0.15)', border: '1px solid #4ade80',
    borderRadius: 8, color: '#4ade80', padding: '8px 16px', fontSize: 13, cursor: 'pointer',
  },
  socialRow: {
    display: 'flex', alignItems: 'center', gap: 24, marginTop: 20,
    paddingTop: 20, borderTop: '1px solid #334155',
  },
  socialStat: { display: 'flex', flexDirection: 'column', alignItems: 'center' },
  socialNum: { fontSize: 20, fontWeight: 700 },
  socialLabel: { fontSize: 12, color: '#64748b' },
  socialDivider: { width: 1, height: 32, background: '#334155' },
  statsGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
    gap: 12, marginBottom: 20,
  },
  statCard: {
    background: '#1e293b', borderRadius: 10, padding: '14px 16px',
    border: '1px solid #334155',
  },
  statLabel: { fontSize: 11, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 },
  statValue: { fontSize: 20, fontWeight: 700 },
  tabs: { display: 'flex', gap: 4, marginBottom: 16 },
  tab: {
    background: 'transparent', border: '1px solid #334155', borderRadius: 8,
    color: '#64748b', padding: '8px 16px', fontSize: 13, cursor: 'pointer',
  },
  tabActive: { background: '#1e293b', color: '#f8fafc', borderColor: '#475569' },
  card: {
    background: '#1e293b', borderRadius: 12, padding: 20,
    border: '1px solid #334155',
  },
  signalRow: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    padding: '12px 0', borderBottom: '1px solid #0f172a',
  },
  badge: {
    fontSize: 11, fontWeight: 700, padding: '2px 8px',
    borderRadius: 4, letterSpacing: '0.05em',
  },
  empty: { color: '#475569', textAlign: 'center', padding: 32 },
  perfRow: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    padding: '10px 0', borderBottom: '1px solid #0f172a',
  },
  perfLabel: { fontSize: 13, color: '#94a3b8' },
  perfValue: { fontSize: 14, fontWeight: 600 },
  overlay: {
    position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
    display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
  },
  modal: {
    background: '#1e293b', borderRadius: 16, padding: 28,
    border: '1px solid #334155', width: '100%', maxWidth: 440,
  },
  modalHeader: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20,
  },
  closeBtn: {
    background: 'transparent', border: 'none', color: '#64748b',
    fontSize: 18, cursor: 'pointer',
  },
  fieldLabel: { fontSize: 12, color: '#94a3b8', display: 'block', marginBottom: 6, marginTop: 14 },
  textarea: {
    width: '100%', background: '#0f172a', border: '1px solid #334155',
    borderRadius: 8, color: '#f8fafc', padding: '10px 12px', fontSize: 14,
    outline: 'none', resize: 'vertical', boxSizing: 'border-box',
  },
  textInput: {
    width: '100%', background: '#0f172a', border: '1px solid #334155',
    borderRadius: 8, color: '#f8fafc', padding: '10px 12px', fontSize: 14,
    outline: 'none', boxSizing: 'border-box',
  },
  saveBtn: {
    flex: 1, background: '#3b82f6', border: 'none', borderRadius: 8,
    color: '#fff', padding: '10px', fontSize: 14, cursor: 'pointer', fontWeight: 600,
  },
  cancelBtn: {
    flex: 1, background: '#334155', border: 'none', borderRadius: 8,
    color: '#94a3b8', padding: '10px', fontSize: 14, cursor: 'pointer',
  },
  inlineError: {
    background: 'rgba(248,113,113,0.1)', border: '1px solid #f87171', borderRadius: 6,
    padding: '6px 10px', fontSize: 12, color: '#f87171', marginTop: 4,
  },
  modalError: {
    background: 'rgba(248,113,113,0.1)', border: '1px solid #f87171', borderRadius: 6,
    padding: '8px 12px', fontSize: 13, color: '#f87171', marginBottom: 12,
  },
};

export default Profile;
