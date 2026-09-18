/**
 * Trader Profile — own profile (/profile/me) and public view (/profile/:id).
 * Features: edit form, avatar upload, follow/unfollow, stats, signals, strategies.
 */
import React, { useEffect, useState, useCallback, useRef } from 'react';
import { useParams, useNavigate, Navigate } from 'react-router-dom';
import { UserRound } from 'lucide-react';
import { PageShell } from '../components/system/PageShell';
import { profileApi } from '../hooks/useApi';
import { useStore } from '../store';
import { extractApiError, fmtPct, fmtPctRaw } from '../lib/utils';

interface TraderProfile {
  user_id: string; username: string; display_name: string; bio: string;
  avatar_url: string | null; country: string | null; joined_at: string;
  followers_count: number; following_count: number; is_following: boolean;
  /**
   * Optional (audit #37). This file already wrote `profile.stats ?? {zeros}`
   * below while declaring the field required — the author knew the type was
   * wrong and worked around it instead of correcting it, then did not apply the
   * same care to `sig.confidence` and `sig.pnl` forty lines later.
   */
  stats?: { total_trades?: number; win_rate?: number; avg_pnl?: number; sharpe_ratio?: number; total_return_pct?: number; };
  strategies?: { strategy_id: string; name: string; subscribers?: number; rating?: number; }[];
  recent_signals?: { signal_id: string; symbol: string; direction?: string; confidence?: number; pnl?: number; created_at?: string; }[];
}

interface EditForm extends Record<string, unknown> { display_name: string; bio: string; country: string; }

const Profile: React.FC = () => {
  const navigate = useNavigate();
  const { id } = useParams<{ id?: string }>();
  const currentUser = useStore(s => s.user);

  /**
   * F4-01 — the own-profile view is reachable only from the guarded route.
   *
   * `/profile` is declared as `gated('profile', <Profile />)`; `/profile/:id`
   * carries no guard at all, deliberately, so one trader can view another's
   * public profile the way `Leaderboard` and `Marketplace` are public previews.
   *
   * But `isOwn` used to be `!id || id === 'me' || id === currentUser?.id`, so
   * `/profile/me` resolved to the *own*-profile view — edit controls included,
   * calling `profileApi.get(undefined)` exactly as the gated route does — at a
   * URL with neither `AuthGuard` nor the subscription gate. The gate is
   * client-side only, so that is a complete bypass of it: six extra characters.
   *
   * A self-referencing id now redirects to `/profile`, which is guarded. Only
   * the guarded route can produce `isOwn`.
   */
  const selfAlias = id != null && (id === 'me' || id === currentUser?.id);
  const isOwn = !id;

  const [profile, setProfile]       = useState<TraderProfile | null>(null);
  const [loading, setLoading]       = useState(true);
  const [error, setError]           = useState<string | null>(null);
  const [editing, setEditing]       = useState(false);
  const [editForm, setEditForm]     = useState<EditForm>({ display_name: '', bio: '', country: '' });
  const [saving, setSaving]         = useState(false);
  const [saveErr, setSaveErr]       = useState<string | null>(null);
  const [saveOk, setSaveOk]         = useState(false);
  const [following, setFollowing]   = useState(false);
  const [followLoading, setFollowLoading] = useState(false);
  const [avatarUploading, setAvatarUploading] = useState(false);
  const [avatarErr, setAvatarErr]   = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const mountedRef = useRef(true);
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

  const loadProfile = useCallback(async () => {
    // Redirecting to the guarded route — don't spend a request on a view that
    // is about to be replaced (F4-01).
    if (selfAlias) return;
    setLoading(true); setError(null);
    try {
      const res = await profileApi.get(isOwn ? undefined : id);
      if (!mountedRef.current) return;
      const d = res.data as { profile?: TraderProfile } | TraderProfile;
      const p: TraderProfile = ('profile' in d && d.profile) ? d.profile : d as TraderProfile;
      setProfile(p);
      setFollowing(p.is_following);
      if (isOwn) setEditForm({ display_name: p.display_name, bio: p.bio, country: p.country ?? '' });
    } catch (err) {
      if (!mountedRef.current) return;
      if ((err as {name?:string}).name === 'CanceledError') return;
      setError(extractApiError(err, 'Failed to load profile.'));
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, [id, isOwn, selfAlias]);

  useEffect(() => { loadProfile(); }, [loadProfile]);

  const handleSave = async () => {
    setSaving(true); setSaveErr(null); setSaveOk(false);
    try {
      await profileApi.update(editForm);
      setSaveOk(true); setEditing(false);
      await loadProfile();
    } catch (err) {
      setSaveErr(extractApiError(err, 'Failed to save profile.'));
    } finally {
      setSaving(false);
    }
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
      setAvatarErr(extractApiError(err, 'Avatar upload failed.'));
    } finally {
      setAvatarUploading(false);
    }
  };

  const handleFollow = async () => {
    if (!profile) return;
    setFollowLoading(true);
    try {
      if (following) { await profileApi.unfollow(profile.user_id); setFollowing(false); setProfile(p => p ? { ...p, followers_count: p.followers_count - 1 } : p); }
      else           { await profileApi.follow(profile.user_id);   setFollowing(true);  setProfile(p => p ? { ...p, followers_count: p.followers_count + 1 } : p); }
    } catch { /* ignore */ }
    finally { setFollowLoading(false); }
  };

  // All four states use the app shell's `page-content` (audit #26). Loading,
  // error and not-found each used to render inside `s.page` — its own 100vh
  // box with its own background and padding — while only the success path used
  // the shell, so the layout jumped on every visit as the profile resolved.
  // Before anything renders or fetches: an id that means "me" belongs on the
  // guarded route (F4-01).
  if (selfAlias) return <Navigate to="/profile" replace />;

  /*
   * One shell, outliving the branches.
   *
   * The comment above records that all four states were moved onto the app
   * shell's `page-content` so the layout stopped jumping. They still each
   * returned their OWN root, so loading, error and not-found rendered a
   * sentence with no heading and no way onward — the state where an operator
   * most needs both. The shell is now a property of the page rather than of
   * its request having succeeded.
   *
   * The title is the PERSON once they have loaded, and "Profile" before that.
   *
   * An earlier attempt used "Profile" in every state and demoted the person's
   * name to an h2. `renders profile username after load` failed, and it was
   * right to: that assertion was deliberately strengthened under audit F11
   * from "an h1 exists" — which passes on an error page — to "the h1 is the
   * username". A profile page's heading is the person, and the test was
   * describing behaviour someone wanted rather than an accident.
   *
   * So the name moves UP into the shell's heading rather than being duplicated
   * there. The identity card keeps the avatar, the @handle, the bio and the
   * follow counts; it loses only a second, smaller copy of a name that is now
   * the page's title two lines above it. Nothing an operator can read is gone.
   */
  const shell = {
    title: profile?.display_name || profile?.username || 'Profile',
    icon: UserRound,
    width: 'standard' as const,
  };

  if (loading) {
    return <PageShell {...shell}><p style={{color:'var(--text-dim)'}}>Loading profile…</p></PageShell>;
  }
  if (error) {
    return (
      <PageShell {...shell}>
        <div style={s.errorBox}>{error}<button onClick={loadProfile} style={s.retryBtn}>Retry</button></div>
      </PageShell>
    );
  }
  if (!profile) return (
    <PageShell {...shell}>
      <div style={{ textAlign: 'center', padding: '60px 24px', color: 'var(--text-muted)' }}>
        <div style={{ fontSize: 48, marginBottom: 16 }}>👤</div>
        <div style={{ fontSize: 18, fontWeight: 600, color: 'var(--text-strong)', marginBottom: 8 }}>
          Profile not found
        </div>
        <div style={{ fontSize: 14, marginBottom: 24 }}>
          This profile does not exist or has been removed.
        </div>
        <button onClick={() => navigate(-1)} style={s.retryBtn}>← Go back</button>
      </div>
    </PageShell>
  );

  // stats may be absent for a brand-new profile — fall back to zeros so the
  // stats grid renders instead of crashing the whole page.
  const st = profile.stats ?? {
    total_trades: 0, win_rate: 0, avg_pnl: 0, sharpe_ratio: 0, total_return_pct: 0,
  };

  return (
    <PageShell
      {...shell}
      subtitle={`@${profile.username}${profile.country ? ` · ${profile.country}` : ''}`}
    >
      {/* Header */}
      <div style={s.header}>
        <div style={s.avatarWrap}>
          {profile.avatar_url
            ? <img src={profile.avatar_url} alt="avatar" style={s.avatar}/>
            : <div style={s.avatarPlaceholder}>{((profile.display_name || profile.username) ?? '?').charAt(0).toUpperCase()}</div>
          }
          {isOwn && (
            <>
              <button onClick={()=>fileRef.current?.click()} style={s.avatarEditBtn} title="Change avatar" aria-label="Change avatar">
                {avatarUploading ? '…' : '📷'}
              </button>
              <input ref={fileRef} type="file" accept="image/*" aria-label="Upload a new avatar image" style={{display:'none'}} onChange={handleAvatarChange}/>
            </>
          )}
        </div>
        <div style={s.headerInfo}>
          <p style={s.username}>@{profile.username}{profile.country ? ` · ${profile.country}` : ''}</p>
          {profile.bio && <p style={s.bio}>{profile.bio}</p>}
          <div style={s.followRow}>
            <span style={s.followStat}><strong>{profile.followers_count}</strong> followers</span>
            <span style={s.followStat}><strong>{profile.following_count}</strong> following</span>
            <span style={s.followStat}>Joined {new Date(profile.joined_at).toLocaleDateString()}</span>
          </div>
          {avatarErr && <div style={s.inlineError}>{avatarErr}</div>}
        </div>
        <div style={s.headerActions}>
          <button onClick={() => navigate('/trade')}
            style={{ padding: '7px 14px', background: 'rgba(59,130,246,0.12)', border: '1px solid rgba(59,130,246,0.35)', borderRadius: 7, color: 'var(--link)', fontSize: 'var(--fs-body)', fontWeight: 700, cursor: 'pointer' }}>
            ⚡ Trade
          </button>
          <button onClick={() => navigate('/leaderboard')}
            style={{ padding: '7px 14px', background: 'rgba(245,158,11,0.12)', border: '1px solid rgba(245,158,11,0.35)', borderRadius: 7, color: '#f59e0b', fontSize: 'var(--fs-body)', fontWeight: 700, cursor: 'pointer' }}>
            🏆 Leaderboard
          </button>
          {isOwn ? (
            <>
              <a
                href={`/profile/${profile.user_id}`}
                target="_blank"
                rel="noopener noreferrer"
                style={{ ...s.editBtn, textDecoration: 'none', background: 'rgba(59,130,246,0.1)', border: '1px solid #1e3a5f', color: 'var(--link)', display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 'var(--fs-body)'}}
                title="See how your profile looks to other traders"
              >
                👁 View Public Profile
              </a>
              <button onClick={()=>setEditing(!editing)} style={s.editBtn}>{editing ? 'Cancel' : 'Edit Profile'}</button>
            </>
          ) : (
            <button onClick={handleFollow} disabled={followLoading} style={{...s.followBtn, background: following ? 'var(--surface-hover)' : '#3b82f6'}}>
              {followLoading ? '…' : following ? 'Unfollow' : 'Follow'}
            </button>
          )}
        </div>
      </div>

      {/* Edit form */}
      {editing && isOwn && (
        <div style={s.editCard}>
          <h3 style={s.cardTitle}>Edit Profile</h3>
          <label style={s.label} id="profile-display-name-label" htmlFor="profile-display-name">Display Name</label>
          <input id="profile-display-name" aria-labelledby="profile-display-name-label" value={editForm.display_name} onChange={e=>setEditForm(f=>({...f,display_name:e.target.value}))} style={s.input} placeholder="Your display name"/>
          <label style={{...s.label,marginTop:12}} id="profile-bio-label" htmlFor="profile-bio">Bio</label>
          <textarea id="profile-bio" aria-labelledby="profile-bio-label" value={editForm.bio} onChange={e=>setEditForm(f=>({...f,bio:e.target.value}))} style={s.textarea} rows={3} placeholder="Tell the community about yourself…"/>
          <label style={{...s.label,marginTop:12}} id="profile-country-label" htmlFor="profile-country">Country</label>
          <input id="profile-country" aria-labelledby="profile-country-label" value={editForm.country} onChange={e=>setEditForm(f=>({...f,country:e.target.value}))} style={s.input} placeholder="e.g. United States"/>
          {saveErr && <div style={s.inlineError}>{saveErr}</div>}
          {saveOk  && <div style={s.successMsg}>Profile saved successfully.</div>}
          <div style={{display:'flex',gap:10,marginTop:16}}>
            <button onClick={handleSave} disabled={saving} style={{...s.saveBtn,opacity:saving?0.6:1}}>{saving?'Saving…':'Save Changes'}</button>
            <button onClick={()=>setEditing(false)} style={s.cancelBtn}>Cancel</button>
          </div>
        </div>
      )}

      {/* Stats grid */}
      <div style={s.statsGrid}>
        {[
          {label:'Total Trades', value:String(st.total_trades)},
          {label:'Win Rate',     value:`${st.win_rate?.toFixed(1) ?? '—'}%`, positive: (st.win_rate ?? 0) >= 50},
          {label:'Avg P&L',      value:`$${st.avg_pnl?.toFixed(2) ?? '—'}`, positive: (st.avg_pnl ?? 0) >= 0},
          {label:'Sharpe Ratio', value:st.sharpe_ratio?.toFixed(2) ?? '—', positive: (st.sharpe_ratio ?? 0) >= 1},
          {label:'Total P&L',    value:fmtPctRaw(st.total_return_pct, 1), positive: (st.total_return_pct ?? 0) >= 0},
        ].map(({label,value,positive})=>(
          <div key={label} style={s.statCard}>
            <div style={{fontSize: 'var(--fs-body)',color:'var(--text-muted)',marginBottom:4}}>{label}</div>
            <div style={{fontSize:20,fontWeight:700,color:positive===undefined?'var(--text-strong)':positive?'var(--gain)':'var(--loss)'}}>{value}</div>
          </div>
        ))}
      </div>

      {/* Strategies */}
      {(profile.strategies?.length ?? 0) > 0 && (
        <div style={s.card}>
          <h3 style={s.cardTitle}>Strategies ({profile.strategies?.length ?? 0})</h3>
          <div style={{display:'flex',flexDirection:'column',gap:8}}>
            {profile.strategies?.map(str=>(
              <div key={str.strategy_id} style={s.stratRow}>
                <span style={{fontWeight:600,color:'var(--text-strong)'}}>{str.name}</span>
                <span style={{fontSize: 'var(--fs-body)',color:'var(--text-muted)'}}>{str.subscribers ?? 0} subscribers</span>
                <span style={{fontSize: 'var(--fs-body)',color:'#f59e0b'}}>{'★'.repeat(str.rating != null && Number.isFinite(str.rating) ? Math.max(0, Math.min(5, Math.round(str.rating))) : 0)} {str.rating != null && Number.isFinite(str.rating) ? str.rating.toFixed(1) : '—'}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Recent signals */}
      {(profile.recent_signals?.length ?? 0) > 0 && (
        <div style={s.card}>
          <h3 style={s.cardTitle}>Recent Signals</h3>
          <table style={s.table}>
            <thead><tr><th style={s.th}>Symbol</th><th style={s.th}>Direction</th><th style={s.th}>Confidence</th><th style={s.th}>P&L</th><th style={s.th}>Date</th></tr></thead>
            <tbody>
              {(profile.recent_signals ?? []).map(sig=>(
                <tr key={sig.signal_id} style={s.tr}>
                  <td style={s.td}>{sig.symbol}</td>
                  <td style={s.td}><span style={{color:sig.direction==='BUY'?'var(--gain)':'var(--loss)',fontWeight:600}}>{sig.direction}</span></td>
                  <td style={s.td}>{fmtPct(sig.confidence, 0)}</td>
                  <td style={{...s.td,color:sig.pnl==null?'var(--text-dim)':sig.pnl>=0?'var(--gain)':'var(--loss)',fontWeight:600}}>{fmtPctRaw(sig.pnl, 2)}</td>
                  <td style={s.td}>{sig.created_at ? new Date(sig.created_at).toLocaleDateString() : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PageShell>
  );
};

const s: Record<string,React.CSSProperties> = {
  header:{display:'flex',gap:20,alignItems:'flex-start',marginBottom:28,background:'var(--raised)',border:'1px solid var(--border-strong)',borderRadius:12,padding:'24px'},
  avatarWrap:{position:'relative',flexShrink:0},
  avatar:{width:80,height:80,borderRadius:'50%',objectFit:'cover',border:'2px solid var(--border-strong)'},
  avatarPlaceholder:{width:80,height:80,borderRadius:'50%',background:'#1e3a5f',border:'2px solid var(--border-strong)',display:'flex',alignItems:'center',justifyContent:'center',fontSize:'var(--fs-display-sm)',fontWeight:700,color:'var(--link)'},
  avatarEditBtn:{position:'absolute',bottom:0,right:0,background:'var(--surface-hover)',border:'none',borderRadius:'50%',width:26,height:26,cursor:'pointer',fontSize:14,display:'flex',alignItems:'center',justifyContent:'center'},
  headerInfo:{flex:1},
  name:{fontSize:22,fontWeight:700,color:'var(--text-strong)',margin:'0 0 4px'},
  username:{fontSize:14,color:'var(--text-muted)',margin:'0 0 8px'},
  bio:{fontSize:14,color:'var(--text-dim)',margin:'0 0 10px',lineHeight:1.5},
  followRow:{display:'flex',gap:16},
  followStat:{fontSize: 'var(--fs-body)',color:'var(--text-muted)'},
  headerActions:{flexShrink:0},
  editBtn:{background:'var(--surface-hover)',border:'1px solid var(--border-strong)',borderRadius:8,color:'var(--text-strong)',cursor:'pointer',fontSize: 'var(--fs-body)',fontWeight:600,padding:'8px 16px'},
  followBtn:{border:'none',borderRadius:8,color:'#fff',cursor:'pointer',fontSize: 'var(--fs-body)',fontWeight:600,padding:'8px 20px'},
  editCard:{background:'var(--raised)',border:'1px solid var(--border-strong)',borderRadius:10,padding:'20px 24px',marginBottom:20},
  cardTitle:{fontSize:16,fontWeight:600,color:'var(--text)',marginBottom:14,marginTop:0},
  label:{display:'block',fontSize: 'var(--fs-body)',color:'var(--text-dim)',marginBottom:6},
  input:{width:'100%',background:'var(--surface)',border:'1px solid var(--border-strong)',borderRadius:8,color:'var(--text-strong)',padding:'9px 12px',fontSize:14,outline:'none',boxSizing:'border-box'},
  textarea:{width:'100%',background:'var(--surface)',border:'1px solid var(--border-strong)',borderRadius:8,color:'var(--text-strong)',padding:'9px 12px',fontSize:14,outline:'none',boxSizing:'border-box',resize:'vertical',fontFamily:'inherit'},
  inlineError:{background:'rgba(248,113,113,0.1)',border:'1px solid var(--loss)',borderRadius:6,padding:'6px 10px',fontSize: 'var(--fs-body)',color:'var(--loss)',marginTop:8},
  successMsg:{background:'rgba(74,222,128,0.1)',border:'1px solid var(--gain)',borderRadius:6,padding:'6px 10px',fontSize: 'var(--fs-body)',color:'var(--gain)',marginTop:8},
  saveBtn:{background:'#3b82f6',border:'none',borderRadius:8,color:'#fff',cursor:'pointer',fontSize: 'var(--fs-body)',fontWeight:600,padding:'9px 20px'},
  cancelBtn:{background:'transparent',border:'1px solid var(--border-strong)',borderRadius:8,color:'var(--text-dim)',cursor:'pointer',fontSize: 'var(--fs-body)',padding:'9px 16px'},
  statsGrid:{display:'grid',gridTemplateColumns:'repeat(auto-fill,minmax(140px,1fr))',gap:12,marginBottom:20},
  statCard:{background:'var(--raised)',border:'1px solid var(--border-strong)',borderRadius:8,padding:'12px 16px'},
  card:{background:'var(--raised)',border:'1px solid var(--border-strong)',borderRadius:10,padding:'20px 24px',marginBottom:16},
  stratRow:{display:'flex',justifyContent:'space-between',alignItems:'center',padding:'8px 0',borderBottom:'1px solid var(--hairline)'},
  table:{width:'100%',borderCollapse:'collapse'},
  th:{textAlign:'left',fontSize: 'var(--fs-body)',color:'var(--text-muted)',textTransform:'uppercase',letterSpacing:0.5,padding:'8px 12px',borderBottom:'1px solid var(--border-strong)'},
  tr:{borderBottom:'1px solid var(--border)'},
  td:{padding:'10px 12px',fontSize:14,color:'var(--text-dim)'},
  errorBox:{background:'#450a0a',border:'1px solid #dc2626',borderRadius:10,padding:'20px 24px',color:'#fca5a5'},
  retryBtn:{marginLeft:16,background:'transparent',border:'1px solid #dc2626',color:'#fca5a5',borderRadius:6,padding:'4px 12px',cursor:'pointer'},
};

export default Profile;
