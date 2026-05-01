/**
 * Affiliate Program — full 4-tab dashboard.
 * Tabs: Overview · Referrals · Commissions · Leaderboard
 */
import React, { useState, useEffect, useCallback } from 'react';
import { affiliateApi } from '../hooks/useApi';
import { useStore } from '../store';

interface AffiliateMetrics { total_referrals: number; converted_referrals: number; total_revenue: number; total_commissions: number; pending_commissions: number; conversion_rate: number; }
interface AffiliateAccount { affiliate_id: string; code: string; level: 'bronze'|'silver'|'gold'|'platinum'; commission_rate: number; status: string; }
interface Referral { referral_id: string; referred_user_id: string; status: 'pending'|'converted'|'paid'|'expired'; created_at: string; converted_at?: string; commission_amount?: number; }
interface Commission { commission_id: string; referral_id: string; amount: number; status: 'pending'|'paid'|'cancelled'; period: string; paid_at?: string; }
interface LeaderboardEntry { rank: number; affiliate_id: string; code: string; level: string; total_commissions: number; converted_referrals: number; }
type Tab = 'overview'|'referrals'|'commissions'|'leaderboard';

const LEVEL_COLORS: Record<string,string> = { bronze:'#cd7f32', silver:'#94a3b8', gold:'#f59e0b', platinum:'#a78bfa' };
const LEVEL_RATES: Record<string,string>  = { bronze:'10%', silver:'15%', gold:'20%', platinum:'25%' };
const fmt = (n:number,d=2) => n.toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});
const fmtUSD = (n:number) => '$'+fmt(n);
function extractErr(err:unknown,fb:string):string { const d=(err as {response?:{data?:{detail?:string}}})?.response?.data?.detail; return d??(err instanceof Error?err.message:fb); }
const statusBadge=(s:string)=>{ const m:Record<string,{bg:string;color:string}>={pending:{bg:'#1e3a5f',color:'#60a5fa'},converted:{bg:'#14532d',color:'#4ade80'},paid:{bg:'#1a2e1a',color:'#22c55e'},expired:{bg:'#2d1b1b',color:'#f87171'},cancelled:{bg:'#2d1b1b',color:'#f87171'},active:{bg:'#14532d',color:'#4ade80'}}; const c=m[s]??{bg:'#1e293b',color:'#94a3b8'}; return <span style={{...st.badge,background:c.bg,color:c.color}}>{s}</span>; };
const MetricCard:React.FC<{label:string;value:string;sub?:string}>=({label,value,sub})=>(<div style={st.metricCard}><div style={st.metricValue}>{value}</div><div style={st.metricLabel}>{label}</div>{sub&&<div style={st.metricSub}>{sub}</div>}</div>);

const Affiliate:React.FC=()=>{
  const user=useStore(s=>s.user); const userId=user?.id;
  const [account,setAccount]=useState<AffiliateAccount|null>(null);
  const [metrics,setMetrics]=useState<AffiliateMetrics|null>(null);
  const [referrals,setReferrals]=useState<Referral[]>([]);
  const [commissions,setCommissions]=useState<Commission[]>([]);
  const [leaderboard,setLeaderboard]=useState<LeaderboardEntry[]>([]);
  const [loading,setLoading]=useState(true);
  const [apiError,setApiError]=useState<string|null>(null);
  const [subErrors,setSubErrors]=useState<Record<string,string>>({});
  const [copied,setCopied]=useState(false);
  const [signupLoading,setSignupLoading]=useState(false);
  const [activeTab,setActiveTab]=useState<Tab>('overview');
  const [withdrawAmt,setWithdrawAmt]=useState('');
  const [withdrawing,setWithdrawing]=useState(false);
  const [withdrawMsg,setWithdrawMsg]=useState('');

  const loadData=useCallback(async()=>{
    if(!userId)return; setLoading(true); setApiError(null); setSubErrors({});
    try{
      const res=await affiliateApi.account(userId);
      const data=res.data as {has_affiliate_account:boolean;affiliate:AffiliateAccount;metrics:AffiliateMetrics};
      if(data.has_affiliate_account){
        setAccount(data.affiliate); setMetrics(data.metrics);
        const affId=data.affiliate.affiliate_id;
        const [rRes,cRes,lRes]=await Promise.allSettled([affiliateApi.referrals(affId),affiliateApi.commissions(affId),affiliateApi.leaderboard({limit:10})]);
        if(rRes.status==='fulfilled'){const rd=rRes.value.data as {referrals?:Referral[]}|Referral[];setReferrals(Array.isArray(rd)?rd:(rd.referrals??[]));}
        else setSubErrors(p=>({...p,referrals:extractErr(rRes.reason,'Failed to load referrals')}));
        if(cRes.status==='fulfilled'){const cd=cRes.value.data as {commissions?:Commission[]}|Commission[];setCommissions(Array.isArray(cd)?cd:(cd.commissions??[]));}
        else setSubErrors(p=>({...p,commissions:extractErr(cRes.reason,'Failed to load commissions')}));
        if(lRes.status==='fulfilled'){const ld=lRes.value.data as {leaderboard?:LeaderboardEntry[]}|LeaderboardEntry[];setLeaderboard(Array.isArray(ld)?ld:(ld.leaderboard??[]));}
        else setSubErrors(p=>({...p,leaderboard:extractErr(lRes.reason,'Failed to load leaderboard')}));
      } else {
        affiliateApi.leaderboard({limit:10}).then(r=>{const ld=r.data as {leaderboard?:LeaderboardEntry[]}|LeaderboardEntry[];setLeaderboard(Array.isArray(ld)?ld:(ld.leaderboard??[]));}).catch(()=>{});
      }
    }catch(err){setApiError(extractErr(err,'Failed to load affiliate data.'));}
    finally{setLoading(false);}
  },[userId]);

  useEffect(()=>{loadData();},[loadData]);

  const handleSignup=async()=>{
    if(!userId)return; setSignupLoading(true);
    try{await affiliateApi.signup({user_id:userId});await loadData();}
    catch(err){setApiError(extractErr(err,'Signup failed.'));}
    finally{setSignupLoading(false);}
  };

  const handleWithdraw=async()=>{
    if(!account||!withdrawAmt)return;
    const amount=parseFloat(withdrawAmt);
    if(isNaN(amount)||amount<=0){setWithdrawMsg('Enter a valid amount.');return;}
    setWithdrawing(true); setWithdrawMsg('');
    try{
      await affiliateApi.withdraw(account.affiliate_id,amount);
      setWithdrawMsg(`Withdrawal of ${fmtUSD(amount)} requested successfully.`);
      setWithdrawAmt(''); await loadData();
    }catch(err){setWithdrawMsg(extractErr(err,'Withdrawal failed.'));}
    finally{setWithdrawing(false);}
  };

  const copyLink=()=>{
    if(!account)return;
    navigator.clipboard.writeText(`${window.location.origin}/?ref=${account.code}`).then(()=>{setCopied(true);setTimeout(()=>setCopied(false),2500);});
  };

  if(!userId)return(<div style={st.page}><p style={{color:'#94a3b8'}}>Please log in to view your affiliate dashboard.</p></div>);
  if(loading)return(<div style={st.page}><p style={{color:'#94a3b8'}}>Loading affiliate data…</p></div>);
  if(apiError)return(<div style={st.page}><h1 style={st.heading}>Affiliate Program</h1><div style={st.errorBox}><strong>Error:</strong> {apiError}<button onClick={loadData} style={st.retryBtn}>Retry</button></div></div>);

  if(!account)return(
    <div style={st.page}>
      <h1 style={st.heading}>Affiliate Program</h1>
      <div style={st.enrollCard}>
        <h2 style={{fontSize:22,marginBottom:12,color:'#f8fafc'}}>Earn by referring traders</h2>
        <p style={{color:'#94a3b8',marginBottom:24,lineHeight:1.6}}>Share your referral link and earn recurring commissions. Commissions range from <strong style={{color:'#f8fafc'}}>10% (Bronze)</strong> to <strong style={{color:'#a78bfa'}}>25% (Platinum)</strong>.</p>
        <div style={st.tierGrid}>{Object.entries(LEVEL_RATES).map(([level,rate])=>(<div key={level} style={{...st.tierCard,border:`1px solid ${LEVEL_COLORS[level]}`}}><div style={{color:LEVEL_COLORS[level],fontWeight:700,textTransform:'capitalize',marginBottom:4}}>{level}</div><div style={{fontSize:24,fontWeight:800,color:'#f8fafc'}}>{rate}</div><div style={{fontSize:12,color:'#64748b'}}>commission</div></div>))}</div>
        <button onClick={handleSignup} disabled={signupLoading} style={{...st.primaryBtn,marginTop:24,opacity:signupLoading?0.6:1}}>{signupLoading?'Joining…':'Join the affiliate program'}</button>
      </div>
    </div>
  );

  const referralLink=`${window.location.origin}/?ref=${account.code}`;
  return(
    <div style={st.page}>
      <div style={st.pageHeader}>
        <div>
          <h1 style={st.heading}>Affiliate Program</h1>
          <div style={{display:'flex',alignItems:'center',gap:10}}>
            <span style={{...st.levelBadge,background:LEVEL_COLORS[account.level]+'22',color:LEVEL_COLORS[account.level],border:`1px solid ${LEVEL_COLORS[account.level]}`}}>{account.level.toUpperCase()}</span>
            <span style={{color:'#64748b',fontSize:14}}>{(account.commission_rate*100).toFixed(0)}% commission · {statusBadge(account.status)}</span>
          </div>
        </div>
        <button onClick={loadData} style={st.refreshBtn}>↻ Refresh</button>
      </div>

      <div style={st.linkCard}>
        <div style={st.linkLabel}>Your referral link</div>
        <div style={st.linkRow}><code style={st.linkCode}>{referralLink}</code><button onClick={copyLink} style={st.copyBtn}>{copied?'✅ Copied':'Copy link'}</button></div>
        <div style={{fontSize:12,color:'#64748b',marginTop:8}}>Code: <strong style={{color:'#94a3b8'}}>{account.code}</strong></div>
      </div>

      <div style={st.tabs}>
        {(['overview','referrals','commissions','leaderboard'] as Tab[]).map(tab=>(
          <button key={tab} onClick={()=>setActiveTab(tab)} style={{...st.tab,...(activeTab===tab?st.tabActive:{})}}>{tab.charAt(0).toUpperCase()+tab.slice(1)}</button>
        ))}
      </div>

      {activeTab==='overview'&&metrics&&(
        <>
          <div style={st.metricsGrid}>
            <MetricCard label="Total referrals" value={String(metrics.total_referrals)}/>
            <MetricCard label="Converted" value={String(metrics.converted_referrals)} sub={`${fmt(metrics.conversion_rate,1)}% rate`}/>
            <MetricCard label="Total earned" value={fmtUSD(metrics.total_commissions)}/>
            <MetricCard label="Pending payout" value={fmtUSD(metrics.pending_commissions)} sub="Next payout: 1st of month"/>
          </div>
          <div style={st.card}>
            <h3 style={st.cardTitle}>Request Commission Withdrawal</h3>
            <p style={{color:'#64748b',fontSize:13,marginBottom:12}}>Minimum withdrawal: <strong style={{color:'#94a3b8'}}>$50.00</strong></p>
            <div style={{display:'flex',gap:10,alignItems:'center'}}>
              <input type="number" min="0" step="0.01" value={withdrawAmt} onChange={e=>setWithdrawAmt(e.target.value)} placeholder="Amount (USD)" style={st.input}/>
              <button onClick={handleWithdraw} disabled={withdrawing||!withdrawAmt} style={{...st.primaryBtn,opacity:withdrawing||!withdrawAmt?0.6:1}}>{withdrawing?'Processing…':'Withdraw'}</button>
            </div>
            {withdrawMsg&&<div style={{marginTop:10,fontSize:13,color:withdrawMsg.includes('success')?'#4ade80':'#f87171'}}>{withdrawMsg}</div>}
          </div>
          <div style={st.card}>
            <h3 style={st.cardTitle}>How commissions work</h3>
            <ul style={st.howList}>
              <li>Share your referral link — anyone who signs up through it is tracked for 30 days.</li>
              <li>When a referral subscribes to any paid plan, you earn a commission on their monthly fee.</li>
              <li>Commissions are paid out on the 1st of each month via your registered payment method.</li>
              <li>Reach higher tiers: Silver (5+ conversions), Gold (15+), Platinum (30+).</li>
            </ul>
          </div>
        </>
      )}

      {activeTab==='referrals'&&(
        <div style={st.card}>
          <h3 style={st.cardTitle}>Referral history</h3>
          {subErrors.referrals&&<div style={st.subError}>{subErrors.referrals}</div>}
          {referrals.length===0&&!subErrors.referrals?(<p style={{color:'#64748b',fontSize:14}}>No referrals yet. Share your link to get started.</p>):(
            <table style={st.table}><thead><tr><th style={st.th}>User ID</th><th style={st.th}>Status</th><th style={st.th}>Referred</th><th style={st.th}>Converted</th><th style={st.th}>Commission</th></tr></thead>
            <tbody>{referrals.map(r=>(<tr key={r.referral_id} style={st.tr}><td style={{...st.td,fontFamily:'monospace',fontSize:12}}>{r.referred_user_id}</td><td style={st.td}>{statusBadge(r.status)}</td><td style={st.td}>{new Date(r.created_at).toLocaleDateString()}</td><td style={st.td}>{r.converted_at?new Date(r.converted_at).toLocaleDateString():'—'}</td><td style={st.td}>{r.commission_amount!=null?fmtUSD(r.commission_amount):'—'}</td></tr>))}</tbody></table>
          )}
        </div>
      )}

      {activeTab==='commissions'&&(
        <div style={st.card}>
          <h3 style={st.cardTitle}>Commission history ({commissions.length})</h3>
          {subErrors.commissions&&<div style={st.subError}>{subErrors.commissions}</div>}
          {commissions.length===0&&!subErrors.commissions?(<p style={{color:'#64748b',fontSize:14}}>No commissions yet.</p>):(
            <table style={st.table}><thead><tr><th style={st.th}>Period</th><th style={st.th}>Amount</th><th style={st.th}>Status</th><th style={st.th}>Paid At</th></tr></thead>
            <tbody>{commissions.map(c=>(<tr key={c.commission_id} style={st.tr}><td style={st.td}>{c.period}</td><td style={{...st.td,color:'#4ade80',fontWeight:600}}>{fmtUSD(c.amount)}</td><td style={st.td}>{statusBadge(c.status)}</td><td style={st.td}>{c.paid_at?new Date(c.paid_at).toLocaleDateString():'—'}</td></tr>))}</tbody></table>
          )}
        </div>
      )}

      {activeTab==='leaderboard'&&(
        <div style={st.card}>
          <h3 style={st.cardTitle}>Top affiliates</h3>
          {subErrors.leaderboard&&<div style={st.subError}>{subErrors.leaderboard}</div>}
          {!subErrors.leaderboard&&(
            <table style={st.table}><thead><tr><th style={st.th}>#</th><th style={st.th}>Code</th><th style={st.th}>Level</th><th style={st.th}>Conversions</th><th style={st.th}>Earned</th></tr></thead>
            <tbody>{leaderboard.map(e=>(<tr key={e.affiliate_id} style={{...st.tr,background:e.affiliate_id===account.affiliate_id?'#1e3a5f':undefined}}><td style={st.td}>{e.rank===1?'🥇':e.rank===2?'🥈':e.rank===3?'🥉':e.rank}</td><td style={{...st.td,fontFamily:'monospace',color:'#e2e8f0'}}>{e.code}</td><td style={{...st.td,color:LEVEL_COLORS[e.level]??'#94a3b8',textTransform:'capitalize'}}>{e.level}</td><td style={st.td}>{e.converted_referrals}</td><td style={{...st.td,color:'#4ade80'}}>{fmtUSD(e.total_commissions)}</td></tr>))}</tbody></table>
          )}
        </div>
      )}
    </div>
  );
};

const st:Record<string,React.CSSProperties>={
  page:{maxWidth:900,margin:'0 auto',padding:'32px 16px',fontFamily:'system-ui,-apple-system,sans-serif',color:'#f1f5f9',background:'#0f172a',minHeight:'100vh'},
  pageHeader:{display:'flex',justifyContent:'space-between',alignItems:'flex-start',marginBottom:28},
  heading:{fontSize:28,fontWeight:700,marginBottom:6,color:'#f8fafc'},
  levelBadge:{fontSize:11,fontWeight:700,padding:'2px 10px',borderRadius:20,letterSpacing:1},
  refreshBtn:{background:'transparent',border:'1px solid #334155',borderRadius:6,color:'#94a3b8',cursor:'pointer',fontSize:13,padding:'6px 12px'},
  enrollCard:{background:'#1e293b',border:'1px solid #334155',borderRadius:12,padding:'32px 28px',maxWidth:600},
  tierGrid:{display:'grid',gridTemplateColumns:'repeat(4,1fr)',gap:12},
  tierCard:{background:'#0f172a',borderRadius:8,padding:'14px 10px',textAlign:'center'},
  primaryBtn:{padding:'10px 24px',background:'#3b82f6',color:'#fff',border:'none',borderRadius:8,fontSize:14,fontWeight:600,cursor:'pointer'},
  linkCard:{background:'#1e293b',border:'1px solid #334155',borderRadius:10,padding:'16px 20px',marginBottom:24},
  linkLabel:{fontSize:12,color:'#64748b',marginBottom:8,textTransform:'uppercase',letterSpacing:0.5},
  linkRow:{display:'flex',alignItems:'center',gap:12},
  linkCode:{flex:1,background:'#0f172a',border:'1px solid #475569',borderRadius:6,padding:'8px 12px',fontSize:13,color:'#93c5fd',wordBreak:'break-all'},
  copyBtn:{padding:'8px 16px',background:'#3b82f6',color:'#fff',border:'none',borderRadius:6,fontSize:13,cursor:'pointer',whiteSpace:'nowrap'},
  tabs:{display:'flex',gap:4,marginBottom:20,borderBottom:'1px solid #1e293b'},
  tab:{padding:'10px 20px',background:'transparent',border:'none',color:'#64748b',fontSize:14,cursor:'pointer',borderBottom:'2px solid transparent',fontWeight:500},
  tabActive:{color:'#3b82f6',borderBottom:'2px solid #3b82f6'},
  metricsGrid:{display:'grid',gridTemplateColumns:'repeat(4,1fr)',gap:12,marginBottom:20},
  metricCard:{background:'#1e293b',border:'1px solid #334155',borderRadius:10,padding:'16px 18px'},
  metricValue:{fontSize:26,fontWeight:700,color:'#f8fafc',marginBottom:4},
  metricLabel:{fontSize:12,color:'#64748b',textTransform:'uppercase',letterSpacing:0.5},
  metricSub:{fontSize:12,color:'#4ade80',marginTop:4},
  card:{background:'#1e293b',border:'1px solid #334155',borderRadius:10,padding:'20px 24px',marginBottom:16},
  cardTitle:{fontSize:16,fontWeight:600,color:'#e2e8f0',marginBottom:16,marginTop:0},
  input:{background:'#0f172a',border:'1px solid #334155',borderRadius:8,color:'#f1f5f9',padding:'9px 12px',fontSize:14,width:180,outline:'none'},
  subError:{background:'rgba(248,113,113,0.1)',border:'1px solid #f87171',borderRadius:6,padding:'8px 12px',fontSize:13,color:'#f87171',marginBottom:12},
  errorBox:{background:'#450a0a',border:'1px solid #dc2626',borderRadius:10,padding:'20px 24px',color:'#fca5a5'},
  retryBtn:{marginLeft:16,background:'transparent',border:'1px solid #dc2626',color:'#fca5a5',borderRadius:6,padding:'4px 12px',cursor:'pointer'},
  howList:{color:'#94a3b8',fontSize:14,lineHeight:2,paddingLeft:20,margin:0},
  table:{width:'100%',borderCollapse:'collapse'},
  th:{textAlign:'left',fontSize:12,color:'#64748b',textTransform:'uppercase',letterSpacing:0.5,padding:'8px 12px',borderBottom:'1px solid #334155'},
  tr:{borderBottom:'1px solid #1e293b'},
  td:{padding:'10px 12px',fontSize:14,color:'#cbd5e1'},
  badge:{fontSize:11,fontWeight:600,padding:'2px 8px',borderRadius:20,textTransform:'capitalize'},
};

export default Affiliate;
