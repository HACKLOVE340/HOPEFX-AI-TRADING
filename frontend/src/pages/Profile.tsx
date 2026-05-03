/**
 * Trader Profile — own profile (/profile/me) and public view (/profile/:id).
 * Features: edit form, avatar upload, follow/unfollow, stats, signals, strategies.
 */
import React, { useEffect, useState, useCallback, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { profileApi } from '../hooks/useApi';
import { useStore } from '../store';

function extractErr(err: unknown, fb: string): string {
  const d = (err as {response?:{data?:{detail?:string}}})?.response?.data?.detail;
  return d ?? (err instanceof Error ? err.message : fb);
}

interface TraderProfile {
  user_id: string; username: string; display_name: string; bio: string;
  avatar_url: string | null; country: string | null; joined_at: string;
  followers_count: number; following_count: number; is_following: boolean;
  stats: { total_trades: number; win_rate: number; avg_pnl: number; sharpe_ratio: number; total_return_pct: number; };
  strategies: { strategy_id: string; name: string; subscribers: number; rating: number; }[];
  recent_signals: { signal_id: string; symbol: string; direction: string; confidence: number; pnl: number; created_at: string; }[];
}

interface EditForm extends Record<string, unknown> { display_name: string; bio: string; country: string; }

const Profile: React.FC = () => {
  const navigate = useNavigate();
  const { id } = useParams<{ id?: string }>();
  const currentUser = useStore(s => s.user);
  const isOwn = !id || id === 'me' || id === currentUser?.id;

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
      setAvatarErr(extractErr(err, 'Avatar upload failed.'));
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

  if (loading) return <div style={s.page}><p style={{color:'#94a3b8'}}>Loading profile…</p></div>;
  if (error)   return <div style={s.page}><div style={s.errorBox}>{error}<button onClick={loadProfile} style={s.retryBtn}>Retry</button></div></div>;
  if (!profile) return null;

  const st = profile.stats;

  return (
    <div style={s.page}>
      {/* Header */}
      <div style={s.header}>
        <div style={s.avatarWrap}>
          {profile.avatar_url
            ? <img src={profile.avatar_url} alt="avatar" style={s.avatar}/>
            : <div style={s.avatarPlaceholder}>{((profile.display_name || profile.username) ?? '?').charAt(0).toUpperCase()}</div>
          }
          {isOwn && (
            <>
              <button onClick={()=>fileRef.current?.click()} style={s.avatarEditBtn} title="Change avatar">
                {avatarUploading ? '…' : '📷'}
              </button>
              <input ref={fileRef} type="file" accept="image/*" style={{display:'none'}} onChange={handleAvatarChange}/>
            </>
          )}
        </div>
        <div style={s.headerInfo}>
          <h1 style={s.name}>{profile.display_name || profile.username}</h1>
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
            style={{ padding: '7px 14px', background: 'rgba(59,130,246,0.12)', border: '1px solid rgba(59,130,246,0.35)', borderRadius: 7, color: '#60a5fa', fontSize: 12, fontWeight: 700, cursor: 'pointer' }}>
            ⚡ Trade
          </button>
          <button onClick={() => navigate('/leaderboard')}
            style={{ padding: '7px 14px', background: 'rgba(245,158,11,0.12)', border: '1px solid rgba(245,158,11,0.35)', borderRadius: 7, color: '#f59e0b', fontSize: 12, fontWeight: 700, cursor: 'pointer' }}>
            🏆 Leaderboard
          </button>
          {isOwn ? (
            <>
              <a
                href={`/profile/${profile.user_id}`}
                target="_blank"
                rel="noopener noreferrer"
                style={{ ...s.editBtn, textDecoration: 'none', background: 'rgba(59,130,246,0.1)', border: '1px solid #1e3a5f', color: '#60a5fa', display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 13 }}
                title="See how your profile looks to other traders"
              >
                👁 View Public Profile
              </a>
              <button onClick={()=>setEditing(!editing)} style={s.editBtn}>{editing ? 'Cancel' : 'Edit Profile'}</button>
            </>
          ) : (
            <button onClick={handleFollow} disabled={followLoading} style={{...s.followBtn, background: following ? '#334155' : '#3b82f6'}}>
              {followLoading ? '…' : following ? 'Unfollow' : 'Follow'}
            </button>
          )}
        </div>
      </div>

      {/* Edit form */}
      {editing && isOwn && (
        <div style={s.editCard}>
          <h3 style={s.cardTitle}>Edit Profile</h3>
          <label style={s.label}>Display Name</label>
          <input value={editForm.display_name} onChange={e=>setEditForm(f=>({...f,display_name:e.target.value}))} style={s.input} placeholder="Your display name"/>
          <label style={{...s.label,marginTop:12}}>Bio</label>
          <textarea value={editForm.bio} onChange={e=>setEditForm(f=>({...f,bio:e.target.value}))} style={s.textarea} rows={3} placeholder="Tell the community about yourself…"/>
          <label style={{...s.label,marginTop:12}}>Country</label>
          <input value={editForm.country} onChange={e=>setEditForm(f=>({...f,country:e.target.value}))} style={s.input} placeholder="e.g. United States"/>
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
          {label:'Total P&L',    value:`${st.total_return_pct >= 0 ? '+' : ''}${st.total_return_pct?.toFixed(1) ?? '—'}%`, positive: (st.total_return_pct ?? 0) >= 0},
        ].map(({label,value,positive})=>(
          <div key={label} style={s.statCard}>
            <div style={{fontSize:12,color:'#64748b',marginBottom:4}}>{label}</div>
            <div style={{fontSize:20,fontWeight:700,color:positive===undefined?'#f1f5f9':positive?'#4ade80':'#f87171'}}>{value}</div>
          </div>
        ))}
      </div>

      {/* Strategies */}
      {profile.strategies.length > 0 && (
        <div style={s.card}>
          <h3 style={s.cardTitle}>Strategies ({profile.strategies.length})</h3>
          <div style={{display:'flex',flexDirection:'column',gap:8}}>
            {profile.strategies.map(str=>(
              <div key={str.strategy_id} style={s.stratRow}>
                <span style={{fontWeight:600,color:'#f1f5f9'}}>{str.name}</span>
                <span style={{fontSize:13,color:'#64748b'}}>{str.subscribers} subscribers</span>
                <span style={{fontSize:13,color:'#f59e0b'}}>{'★'.repeat(Math.round(str.rating))} {str.rating.toFixed(1)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Recent signals */}
      {profile.recent_signals.length > 0 && (
        <div style={s.card}>
          <h3 style={s.cardTitle}>Recent Signals</h3>
          <table style={s.table}>
            <thead><tr><th style={s.th}>Symbol</th><th style={s.th}>Direction</th><th style={s.th}>Confidence</th><th style={s.th}>P&L</th><th style={s.th}>Date</th></tr></thead>
            <tbody>
              {profile.recent_signals.map(sig=>(
                <tr key={sig.signal_id} style={s.tr}>
                  <td style={s.td}>{sig.symbol}</td>
                  <td style={s.td}><span style={{color:sig.direction==='BUY'?'#4ade80':'#f87171',fontWeight:600}}>{sig.direction}</span></td>
                  <td style={s.td}>{(sig.confidence*100).toFixed(0)}%</td>
                  <td style={{...s.td,color:sig.pnl>=0?'#4ade80':'#f87171',fontWeight:600}}>{sig.pnl>=0?'+':''}{sig.pnl.toFixed(2)}%</td>
                  <td style={s.td}>{new Date(sig.created_at).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

const s: Record<string,React.CSSProperties> = {
  page:{maxWidth:860,margin:'0 auto',padding:'32px 16px',fontFamily:'system-ui,-apple-system,sans-serif',color:'#f1f5f9',background:'#0f172a',minHeight:'100vh'},
  header:{display:'flex',gap:20,alignItems:'flex-start',marginBottom:28,background:'#1e293b',border:'1px solid #334155',borderRadius:12,padding:'24px'},
  avatarWrap:{position:'relative',flexShrink:0},
  avatar:{width:80,height:80,borderRadius:'50%',objectFit:'cover',border:'2px solid #334155'},
  avatarPlaceholder:{width:80,height:80,borderRadius:'50%',background:'#1e3a5f',border:'2px solid #334155',display:'flex',alignItems:'center',justifyContent:'center',fontSize:32,fontWeight:700,color:'#60a5fa'},
  avatarEditBtn:{position:'absolute',bottom:0,right:0,background:'#334155',border:'none',borderRadius:'50%',width:26,height:26,cursor:'pointer',fontSize:14,display:'flex',alignItems:'center',justifyContent:'center'},
  headerInfo:{flex:1},
  name:{fontSize:22,fontWeight:700,color:'#f8fafc',margin:'0 0 4px'},
  username:{fontSize:14,color:'#64748b',margin:'0 0 8px'},
  bio:{fontSize:14,color:'#94a3b8',margin:'0 0 10px',lineHeight:1.5},
  followRow:{display:'flex',gap:16},
  followStat:{fontSize:13,color:'#64748b'},
  headerActions:{flexShrink:0},
  editBtn:{background:'#334155',border:'1px solid #475569',borderRadius:8,color:'#f1f5f9',cursor:'pointer',fontSize:13,fontWeight:600,padding:'8px 16px'},
  followBtn:{border:'none',borderRadius:8,color:'#fff',cursor:'pointer',fontSize:13,fontWeight:600,padding:'8px 20px'},
  editCard:{background:'#1e293b',border:'1px solid #334155',borderRadius:10,padding:'20px 24px',marginBottom:20},
  cardTitle:{fontSize:16,fontWeight:600,color:'#e2e8f0',marginBottom:14,marginTop:0},
  label:{display:'block',fontSize:13,color:'#94a3b8',marginBottom:6},
  input:{width:'100%',background:'#0f172a',border:'1px solid #334155',borderRadius:8,color:'#f1f5f9',padding:'9px 12px',fontSize:14,outline:'none',boxSizing:'border-box'},
  textarea:{width:'100%',background:'#0f172a',border:'1px solid #334155',borderRadius:8,color:'#f1f5f9',padding:'9px 12px',fontSize:14,outline:'none',boxSizing:'border-box',resize:'vertical',fontFamily:'inherit'},
  inlineError:{background:'rgba(248,113,113,0.1)',border:'1px solid #f87171',borderRadius:6,padding:'6px 10px',fontSize:12,color:'#f87171',marginTop:8},
  successMsg:{background:'rgba(74,222,128,0.1)',border:'1px solid #4ade80',borderRadius:6,padding:'6px 10px',fontSize:12,color:'#4ade80',marginTop:8},
  saveBtn:{background:'#3b82f6',border:'none',borderRadius:8,color:'#fff',cursor:'pointer',fontSize:13,fontWeight:600,padding:'9px 20px'},
  cancelBtn:{background:'transparent',border:'1px solid #334155',borderRadius:8,color:'#94a3b8',cursor:'pointer',fontSize:13,padding:'9px 16px'},
  statsGrid:{display:'grid',gridTemplateColumns:'repeat(auto-fill,minmax(140px,1fr))',gap:12,marginBottom:20},
  statCard:{background:'#1e293b',border:'1px solid #334155',borderRadius:8,padding:'12px 16px'},
  card:{background:'#1e293b',border:'1px solid #334155',borderRadius:10,padding:'20px 24px',marginBottom:16},
  stratRow:{display:'flex',justifyContent:'space-between',alignItems:'center',padding:'8px 0',borderBottom:'1px solid #0f172a'},
  table:{width:'100%',borderCollapse:'collapse'},
  th:{textAlign:'left',fontSize:12,color:'#64748b',textTransform:'uppercase',letterSpacing:0.5,padding:'8px 12px',borderBottom:'1px solid #334155'},
  tr:{borderBottom:'1px solid #1e293b'},
  td:{padding:'10px 12px',fontSize:14,color:'#cbd5e1'},
  errorBox:{background:'#450a0a',border:'1px solid #dc2626',borderRadius:10,padding:'20px 24px',color:'#fca5a5'},
  retryBtn:{marginLeft:16,background:'transparent',border:'1px solid #dc2626',color:'#fca5a5',borderRadius:6,padding:'4px 12px',cursor:'pointer'},
};

export default Profile;
