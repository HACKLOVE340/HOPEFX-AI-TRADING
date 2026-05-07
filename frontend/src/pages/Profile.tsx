/**
 * Trader Profile — own profile (/profile/me) and public view (/profile/:id).
 * Mobile-first: stacked card layout on xs/sm, side-by-side on md+.
 * Wires to: GET /api/profile, GET /api/profile/:id, POST /api/profile,
 *           POST /api/profile/avatar, POST/DELETE /api/social/follow/:id
 */
import React, { useEffect, useState, useCallback, useRef } from 'react';
import { useParams, Link } from 'react-router-dom';
import { profileApi } from '../hooks/useApi';
import { useStore } from '../store';
import { PageHeader } from '../components/PageHeader';
import { CrossLinkBar } from '../components/CrossLinkBar';
import { EmptyState } from '../components/EmptyState';
import { ErrorBanner } from '../components/ErrorBanner';
import { Spinner } from '../components/Spinner';
import { MetricCard } from '../components/MetricCard';

function extractErr(err: unknown, fb: string): string {
  const d = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
  return d ?? (err instanceof Error ? err.message : fb);
}

interface TraderProfile {
  user_id: string; username: string; display_name: string; bio: string;
  avatar_url: string | null; country: string | null; joined_at: string;
  followers_count: number; following_count: number; is_following: boolean;
  stats: {
    total_trades: number; win_rate: number; avg_pnl: number;
    sharpe_ratio: number; total_return_pct: number;
  } | null;
  strategies: { strategy_id: string; name: string; subscribers: number; rating: number; }[] | null;
  recent_signals: {
    signal_id: string; symbol: string; direction: string;
    confidence: number; pnl: number; created_at: string;
  }[] | null;
}

function normalizeProfile(raw: unknown): TraderProfile {
  const p = (raw ?? {}) as Record<string, unknown>;
  const rs = (p.stats && typeof p.stats === 'object') ? (p.stats as Record<string, unknown>) : {};
  return {
    user_id:         String(p.user_id ?? ''),
    username:        String(p.username ?? ''),
    display_name:    String(p.display_name ?? p.username ?? ''),
    bio:             String(p.bio ?? ''),
    avatar_url:      typeof p.avatar_url === 'string' ? p.avatar_url : null,
    country:         typeof p.country === 'string' ? p.country : null,
    joined_at:       String(p.joined_at ?? new Date().toISOString()),
    followers_count: typeof p.followers_count === 'number' ? p.followers_count : 0,
    following_count: typeof p.following_count === 'number' ? p.following_count : 0,
    is_following:    Boolean(p.is_following),
    stats: {
      total_trades:     typeof rs.total_trades === 'number' ? rs.total_trades : 0,
      win_rate:         typeof rs.win_rate === 'number' ? rs.win_rate : 0,
      avg_pnl:          typeof rs.avg_pnl === 'number' ? rs.avg_pnl : 0,
      sharpe_ratio:     typeof rs.sharpe_ratio === 'number' ? rs.sharpe_ratio : 0,
      total_return_pct: typeof rs.total_return_pct === 'number' ? rs.total_return_pct : 0,
    },
    strategies:     Array.isArray(p.strategies) ? p.strategies as TraderProfile['strategies'] : [],
    recent_signals: Array.isArray(p.recent_signals) ? p.recent_signals as TraderProfile['recent_signals'] : [],
  };
}

interface EditForm { display_name: string; bio: string; country: string; }

const Profile: React.FC = () => {
  const { id } = useParams<{ id?: string }>();
  const currentUser = useStore(s => s.user);
  const isOwn = !id || id === 'me' || id === currentUser?.id;

  const [profile, setProfile]             = useState<TraderProfile | null>(null);
  const [loading, setLoading]             = useState(true);
  const [error, setError]                 = useState<string | null>(null);
  const [editing, setEditing]             = useState(false);
  const [editForm, setEditForm]           = useState<EditForm>({ display_name: '', bio: '', country: '' });
  const [saving, setSaving]               = useState(false);
  const [saveErr, setSaveErr]             = useState<string | null>(null);
  const [saveOk, setSaveOk]               = useState(false);
  const [following, setFollowing]         = useState(false);
  const [followLoading, setFollowLoading] = useState(false);
  const [avatarUploading, setAvatarUploading] = useState(false);
  const [avatarErr, setAvatarErr]         = useState<string | null>(null);
  const fileRef    = useRef<HTMLInputElement>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const loadProfile = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const res = await profileApi.get(isOwn ? undefined : id);
      if (!mountedRef.current) return;
      const d = res.data as { profile?: unknown } | unknown;
      const raw = (d && typeof d === 'object' && 'profile' in (d as object))
        ? (d as { profile: unknown }).profile : d;
      const p = normalizeProfile(raw);
      setProfile(p);
      setFollowing(p.is_following);
      if (isOwn) setEditForm({ display_name: p.display_name, bio: p.bio, country: p.country ?? '' });
    } catch (err) {
      if (!mountedRef.current) return;
      if ((err as { name?: string }).name === 'CanceledError') return;
      setError(extractErr(err, 'Failed to load profile.'));
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, [id, isOwn]);

  useEffect(() => { loadProfile(); }, [loadProfile]);

  const handleSave = async () => {
    setSaving(true); setSaveErr(null); setSaveOk(false);
    try {
      await profileApi.update(editForm);
      setSaveOk(true); setEditing(false);
      await loadProfile();
    } catch (err) {
      setSaveErr(extractErr(err, 'Failed to save profile.'));
    } finally { setSaving(false); }
  };

  const handleAvatarChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setAvatarUploading(true); setAvatarErr(null);
    try {
      const fd = new FormData();
      fd.append('avatar', file);
      await profileApi.uploadAvatar(fd);
      await loadProfile();
    } catch (err) {
      setAvatarErr(extractErr(err, 'Avatar upload failed.'));
    } finally { setAvatarUploading(false); }
  };

  const handleFollow = async () => {
    if (!profile) return;
    setFollowLoading(true);
    try {
      if (following) {
        await profileApi.unfollow(profile.user_id);
        setFollowing(false);
        setProfile(p => p ? { ...p, followers_count: p.followers_count - 1 } : p);
      } else {
        await profileApi.follow(profile.user_id);
        setFollowing(true);
        setProfile(p => p ? { ...p, followers_count: p.followers_count + 1 } : p);
      }
    } catch { /* non-fatal */ }
    finally { setFollowLoading(false); }
  };

  if (loading) return (
    <div className="max-w-3xl mx-auto px-4 py-6">
      <PageHeader title="Profile" icon="👤"
        breadcrumbs={[{ label: 'Dashboard', href: '/dashboard' }, { label: 'Profile' }]} />
      <div className="flex justify-center py-16"><Spinner size="lg" /></div>
    </div>
  );

  if (error) return (
    <div className="max-w-3xl mx-auto px-4 py-6">
      <PageHeader title="Profile"
        breadcrumbs={[{ label: 'Dashboard', href: '/dashboard' }, { label: 'Profile' }]} />
      <ErrorBanner message={error} onDismiss={loadProfile} />
    </div>
  );

  if (!profile) return null;

  const st = profile.stats ?? { total_trades: 0, win_rate: 0, avg_pnl: 0, sharpe_ratio: 0, total_return_pct: 0 };
  const strategies    = profile.strategies ?? [];
  const recentSignals = profile.recent_signals ?? [];
  const displayName   = profile.display_name || profile.username;

  return (
    <div className="max-w-3xl mx-auto px-3 sm:px-6 py-4 sm:py-8">
      <PageHeader
        icon="👤"
        title={isOwn ? 'My Profile' : `${displayName}'s Profile`}
        subtitle={isOwn ? 'Manage your public trading profile' : `@${profile.username}`}
        breadcrumbs={[
          { label: 'Dashboard', href: '/dashboard' },
          ...(isOwn
            ? [{ label: 'Profile' }]
            : [{ label: 'Leaderboard', href: '/leaderboard' }, { label: profile.username }]
          ),
        ]}
        actions={
          <div className="flex gap-2 flex-wrap">
            <Link to="/trade"
              className="px-3 py-1.5 bg-blue-500/10 border border-blue-500/30 rounded-lg text-blue-400 text-xs font-bold no-underline hover:bg-blue-500/20 transition-colors">
              ⚡ Trade
            </Link>
            <Link to="/leaderboard"
              className="px-3 py-1.5 bg-amber-500/10 border border-amber-500/30 rounded-lg text-amber-400 text-xs font-bold no-underline hover:bg-amber-500/20 transition-colors">
              🏆 Leaderboard
            </Link>
          </div>
        }
      />

      {/* Quick links */}
      <div className="flex gap-3 flex-wrap text-xs mb-6">
        {[
          { to: '/performance', label: '📊 Performance' },
          { to: '/journal',     label: '📓 Journal' },
          { to: '/portfolio',   label: '💼 Portfolio' },
          { to: '/settings',    label: '⚙️ Settings' },
          { to: '/kyc',         label: '🪪 KYC' },
        ].map(({ to, label }) => (
          <Link key={to} to={to}
            className="text-slate-500 no-underline hover:text-slate-300 transition-colors">
            {label}
          </Link>
        ))}
      </div>

      {/* Profile header card */}
      <div className="bg-terminal-surface border border-terminal-border rounded-xl p-4 sm:p-6 mb-4">
        <div className="flex flex-col sm:flex-row gap-4 sm:gap-5">
          {/* Avatar */}
          <div className="relative flex-shrink-0 self-start">
            {profile.avatar_url
              ? <img src={profile.avatar_url} alt="avatar"
                  className="w-20 h-20 sm:w-24 sm:h-24 rounded-full object-cover border-2 border-terminal-border" />
              : <div className="w-20 h-20 sm:w-24 sm:h-24 rounded-full bg-blue-950 border-2 border-terminal-border flex items-center justify-center text-3xl font-bold text-blue-400">
                  {displayName.charAt(0).toUpperCase()}
                </div>
            }
            {isOwn && (
              <>
                <button
                  onClick={() => fileRef.current?.click()}
                  className="absolute bottom-0 right-0 w-7 h-7 bg-terminal-raised border border-terminal-border rounded-full flex items-center justify-center text-sm cursor-pointer hover:bg-terminal-surface transition-colors"
                  title="Change avatar"
                >
                  {avatarUploading ? '…' : '📷'}
                </button>
                <input ref={fileRef} type="file" accept="image/*"
                  className="hidden" onChange={handleAvatarChange} />
              </>
            )}
          </div>

          {/* Info */}
          <div className="flex-1 min-w-0">
            <h2 className="text-slate-100 text-xl font-bold m-0 leading-tight">{displayName}</h2>
            <p className="text-slate-500 text-sm mt-0.5 mb-2">
              @{profile.username}{profile.country ? ` · ${profile.country}` : ''}
            </p>
            {profile.bio && (
              <p className="text-slate-400 text-sm leading-relaxed mb-3">{profile.bio}</p>
            )}
            <div className="flex gap-4 text-sm flex-wrap mb-3">
              <span className="text-slate-400">
                <strong className="text-slate-200">{profile.followers_count.toLocaleString()}</strong> followers
              </span>
              <span className="text-slate-400">
                <strong className="text-slate-200">{profile.following_count.toLocaleString()}</strong> following
              </span>
              <span className="text-slate-500 text-xs">
                Joined {new Date(profile.joined_at).toLocaleDateString()}
              </span>
            </div>
            {avatarErr && (
              <div className="text-red-400 text-xs bg-red-950/40 border border-red-900 rounded px-3 py-2 mb-2">
                {avatarErr}
              </div>
            )}
            {/* Action buttons */}
            <div className="flex gap-2 flex-wrap">
              {isOwn ? (
                <>
                  <button
                    onClick={() => setEditing(v => !v)}
                    className="px-4 py-2 bg-terminal-raised border border-terminal-border rounded-lg text-slate-300 text-sm font-semibold cursor-pointer hover:border-slate-500 transition-colors"
                  >
                    {editing ? 'Cancel' : 'Edit Profile'}
                  </button>
                  <Link to={`/profile/${profile.user_id}`}
                    className="px-4 py-2 bg-blue-500/10 border border-blue-500/30 rounded-lg text-blue-400 text-sm font-semibold no-underline hover:bg-blue-500/20 transition-colors">
                    👁 Public View
                  </Link>
                </>
              ) : (
                <button
                  onClick={handleFollow}
                  disabled={followLoading}
                  className={`px-5 py-2 rounded-lg text-sm font-bold cursor-pointer transition-colors border-0 ${
                    following
                      ? 'bg-terminal-raised text-slate-300 hover:bg-red-950/40 hover:text-red-400'
                      : 'bg-blue-600 text-white hover:bg-blue-500'
                  } disabled:opacity-60`}
                >
                  {followLoading ? '…' : following ? 'Unfollow' : 'Follow'}
                </button>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Edit form */}
      {editing && isOwn && (
        <div className="bg-terminal-surface border border-terminal-border rounded-xl p-4 sm:p-6 mb-4">
          <h3 className="text-slate-100 text-base font-semibold mb-4 mt-0">Edit Profile</h3>
          <div className="flex flex-col gap-3">
            <div>
              <label className="block text-slate-400 text-xs font-semibold mb-1.5 uppercase tracking-wider">
                Display Name
              </label>
              <input
                value={editForm.display_name}
                onChange={e => setEditForm(f => ({ ...f, display_name: e.target.value }))}
                className="w-full bg-terminal-raised border border-terminal-border rounded-lg px-3 py-2.5 text-slate-200 text-sm outline-none focus:border-blue-500 transition-colors"
                placeholder="Your display name"
              />
            </div>
            <div>
              <label className="block text-slate-400 text-xs font-semibold mb-1.5 uppercase tracking-wider">Bio</label>
              <textarea
                value={editForm.bio}
                onChange={e => setEditForm(f => ({ ...f, bio: e.target.value }))}
                rows={3}
                className="w-full bg-terminal-raised border border-terminal-border rounded-lg px-3 py-2.5 text-slate-200 text-sm outline-none focus:border-blue-500 transition-colors resize-y"
                placeholder="Tell the community about yourself…"
              />
            </div>
            <div>
              <label className="block text-slate-400 text-xs font-semibold mb-1.5 uppercase tracking-wider">Country</label>
              <input
                value={editForm.country}
                onChange={e => setEditForm(f => ({ ...f, country: e.target.value }))}
                className="w-full bg-terminal-raised border border-terminal-border rounded-lg px-3 py-2.5 text-slate-200 text-sm outline-none focus:border-blue-500 transition-colors"
                placeholder="e.g. United States"
              />
            </div>
            {saveErr && (
              <div className="text-red-400 text-xs bg-red-950/40 border border-red-900 rounded px-3 py-2">{saveErr}</div>
            )}
            {saveOk && (
              <div className="text-green-400 text-xs bg-green-950/40 border border-green-900 rounded px-3 py-2">
                Profile saved successfully.
              </div>
            )}
            <div className="flex gap-2 pt-1">
              <button
                onClick={handleSave}
                disabled={saving}
                className="px-5 py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm font-bold cursor-pointer transition-colors disabled:opacity-60 border-0"
              >
                {saving ? 'Saving…' : 'Save Changes'}
              </button>
              <button
                onClick={() => setEditing(false)}
                className="px-5 py-2.5 bg-terminal-raised border border-terminal-border text-slate-400 rounded-lg text-sm font-semibold cursor-pointer hover:border-slate-500 transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Stats grid — 2 cols on xs, 3 on sm, 5 on md */}
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3 mb-4">
        <MetricCard label="Total Trades"  value={st.total_trades.toLocaleString()} />
        <MetricCard label="Win Rate"      value={`${st.win_rate.toFixed(1)}%`}
          deltaPositive={st.win_rate >= 50} />
        <MetricCard label="Avg P&L"       value={`$${st.avg_pnl.toFixed(2)}`}
          deltaPositive={st.avg_pnl >= 0} />
        <MetricCard label="Sharpe Ratio"  value={st.sharpe_ratio.toFixed(2)}
          deltaPositive={st.sharpe_ratio >= 1} />
        <MetricCard label="Total Return"
          value={`${st.total_return_pct >= 0 ? '+' : ''}${st.total_return_pct.toFixed(1)}%`}
          deltaPositive={st.total_return_pct >= 0}
          className="col-span-2 sm:col-span-1" />
      </div>

      {/* Strategies */}
      <div className="bg-terminal-surface border border-terminal-border rounded-xl p-4 sm:p-6 mb-4">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-slate-100 text-base font-semibold m-0">
            Strategies ({strategies.length})
          </h3>
          <Link to="/marketplace"
            className="text-xs text-blue-400 no-underline px-3 py-1.5 border border-blue-500/30 rounded-lg bg-blue-500/8 hover:bg-blue-500/15 transition-colors">
            Browse →
          </Link>
        </div>
        {strategies.length === 0 ? (
          <EmptyState
            icon="📦"
            title="No strategies yet"
            description={isOwn ? 'Build and publish your first AI trading strategy.' : 'No published strategies.'}
            action={isOwn
              ? <Link to="/ai-strategy"
                  className="px-4 py-2 bg-blue-600 rounded-lg text-white text-sm font-semibold no-underline hover:bg-blue-500 transition-colors">
                  🤖 Build Strategy
                </Link>
              : undefined
            }
          />
        ) : (
          <div className="flex flex-col gap-2">
            {strategies.map(str => (
              <Link key={str.strategy_id} to="/marketplace"
                className="flex items-center justify-between gap-3 px-3 py-2.5 bg-terminal-raised border border-terminal-border rounded-lg no-underline hover:border-slate-600 transition-colors">
                <span className="font-semibold text-slate-200 text-sm truncate">{str.name}</span>
                <span className="text-slate-500 text-xs flex-shrink-0">
                  {str.subscribers.toLocaleString()} subs
                </span>
                <span className="text-amber-400 text-xs flex-shrink-0">
                  ★ {(str.rating ?? 0).toFixed(1)}
                </span>
              </Link>
            ))}
          </div>
        )}
      </div>

      {/* Recent signals */}
      <div className="bg-terminal-surface border border-terminal-border rounded-xl p-4 sm:p-6 mb-4">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-slate-100 text-base font-semibold m-0">Recent Signals</h3>
          <Link to="/signals"
            className="text-xs text-violet-400 no-underline px-3 py-1.5 border border-violet-500/30 rounded-lg bg-violet-500/8 hover:bg-violet-500/15 transition-colors">
            View all →
          </Link>
        </div>
        {recentSignals.length === 0 ? (
          <EmptyState icon="📡" title="No signals yet"
            description={isOwn ? 'Your recent AI signals will appear here.' : 'No recent signals.'} />
        ) : (
          <div className="overflow-x-auto" style={{ WebkitOverflowScrolling: 'touch' } as React.CSSProperties}>
            <table className="w-full border-collapse text-sm" style={{ minWidth: 480 }}>
              <thead>
                <tr>
                  {['Symbol', 'Direction', 'Confidence', 'P&L', 'Date'].map(h => (
                    <th key={h}
                      className="text-left text-slate-500 text-2xs font-semibold uppercase tracking-wider px-3 py-2 border-b border-terminal-border bg-terminal-raised">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {recentSignals.map(sig => (
                  <tr key={sig.signal_id} className="border-b border-terminal-border/60 hover:bg-terminal-raised/40 transition-colors">
                    <td className="px-3 py-2.5 font-semibold text-slate-200">{sig.symbol}</td>
                    <td className="px-3 py-2.5">
                      <span className={`text-xs font-bold px-2 py-0.5 rounded ${
                        sig.direction === 'BUY'
                          ? 'bg-green-500/10 text-green-400'
                          : 'bg-red-500/10 text-red-400'
                      }`}>
                        {sig.direction}
                      </span>
                    </td>
                    <td className="px-3 py-2.5 text-slate-400 tabular-nums">
                      {((sig.confidence ?? 0) * 100).toFixed(0)}%
                    </td>
                    <td className={`px-3 py-2.5 font-semibold tabular-nums ${
                      (sig.pnl ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'
                    }`}>
                      {(sig.pnl ?? 0) >= 0 ? '+' : ''}{(sig.pnl ?? 0).toFixed(2)}%
                    </td>
                    <td className="px-3 py-2.5 text-slate-500 text-xs">
                      {new Date(sig.created_at).toLocaleDateString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <CrossLinkBar title="Related" links={[
        { label: 'Settings',    href: '/settings',              icon: '⚙️', color: '#94a3b8' },
        { label: 'KYC',         href: '/kyc',                   icon: '🪪', color: '#60a5fa' },
        { label: 'Security',    href: '/settings?tab=security', icon: '🔐', color: '#f87171' },
        { label: 'Wallet',      href: '/wallet',                icon: '💳', color: '#4ade80' },
        { label: 'Leaderboard', href: '/leaderboard',           icon: '🏆', color: '#f59e0b' },
        { label: 'Social Feed', href: '/signals',               icon: '📡', color: '#a78bfa' },
      ]} />
    </div>
  );
};

export default Profile;
