/**
 * Affiliate Program — full 4-tab dashboard.
 * Tabs: Overview · Referrals · Commissions · Leaderboard
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { affiliateApi } from '../hooks/useApi';
import { useStore } from '../store';
import { PageHeader } from '../components/PageHeader';
import { EmptyState } from '../components/EmptyState';
import { ErrorBanner } from '../components/ErrorBanner';
import { useToast } from '../components/Toast';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts';

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
  const navigate=useNavigate();
  const toast=useToast();
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
  const copiedTimerRef=React.useRef<ReturnType<typeof setTimeout>|null>(null);
  const mountedRef=useRef(true);
  const [signupLoading,setSignupLoading]=useState(false);
  const [activeTab,setActiveTab]=useState<Tab>('overview');
  const [withdrawAmt,setWithdrawAmt]=useState('');
  const [withdrawing,setWithdrawing]=useState(false);
  const [withdrawMsg,setWithdrawMsg]=useState('');

  // Cleanup copy timer on unmount
  React.useEffect(()=>()=>{if(copiedTimerRef.current)clearTimeout(copiedTimerRef.current);},[]);

  useEffect(()=>{mountedRef.current=true;return()=>{mountedRef.current=false;};},[]);

  const loadData=useCallback(async()=>{
    if(!userId)return; setLoading(true); setApiError(null); setSubErrors({});
    try{
      const res=await affiliateApi.account(userId);
      if(!mountedRef.current)return;
      const data=res.data as {has_affiliate_account:boolean;affiliate:AffiliateAccount;metrics:AffiliateMetrics};
      if(data.has_affiliate_account){
        setAccount(data.affiliate); setMetrics(data.metrics);
        const affId=data.affiliate.affiliate_id;
        const [rRes,cRes,lRes]=await Promise.allSettled([affiliateApi.referrals(affId),affiliateApi.commissions(affId),affiliateApi.leaderboard({limit:10})]);
        if(!mountedRef.current)return;
        if(rRes.status==='fulfilled'){const rd=rRes.value.data as {referrals?:Referral[]}|Referral[];setReferrals(Array.isArray(rd)?rd:(rd.referrals??[]));}
        else setSubErrors(p=>({...p,referrals:extractErr(rRes.reason,'Failed to load referrals')}));
        if(cRes.status==='fulfilled'){const cd=cRes.value.data as {commissions?:Commission[]}|Commission[];setCommissions(Array.isArray(cd)?cd:(cd.commissions??[]));}
        else setSubErrors(p=>({...p,commissions:extractErr(cRes.reason,'Failed to load commissions')}));
        if(lRes.status==='fulfilled'){const ld=lRes.value.data as {leaderboard?:LeaderboardEntry[]}|LeaderboardEntry[];setLeaderboard(Array.isArray(ld)?ld:(ld.leaderboard??[]));}
        else setSubErrors(p=>({...p,leaderboard:extractErr(lRes.reason,'Failed to load leaderboard')}));
      } else {
        affiliateApi.leaderboard({limit:10}).then(r=>{if(!mountedRef.current)return;const ld=r.data as {leaderboard?:LeaderboardEntry[]}|LeaderboardEntry[];setLeaderboard(Array.isArray(ld)?ld:(ld.leaderboard??[]));}).catch(()=>{});
      }
    }catch(err){
      if(!mountedRef.current)return;
      setApiError(extractErr(err,'Failed to load affiliate data.'));
    }
    finally{if(mountedRef.current)setLoading(false);}
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
    const url=`${window.location.origin}/?ref=${account.code}`;
    navigator.clipboard.writeText(url).then(()=>{
      setCopied(true);
      toast.success('Referral link copied to clipboard!');
      if(copiedTimerRef.current)clearTimeout(copiedTimerRef.current);
      copiedTimerRef.current=setTimeout(()=>setCopied(false),2500);
    }).catch(()=>toast.error('Failed to copy link.'));
  };

  if(!userId)return(
    <div style={{maxWidth:900,margin:'0 auto',padding:'32px 16px'}}>
      <PageHeader title="Affiliate Program" breadcrumbs={[{label:'Dashboard',href:'/dashboard'},{label:'Affiliate'}]}/>
      <EmptyState icon="🔒" title="Sign in required" description="Please log in to view your affiliate dashboard."/>
    </div>
  );
  if(loading)return(
    <div style={{maxWidth:900,margin:'0 auto',padding:'32px 16px'}}>
      <PageHeader title="Affiliate Program" breadcrumbs={[{label:'Dashboard',href:'/dashboard'},{label:'Affiliate'}]}/>
      <div style={{color:'#64748b',fontSize:14,padding:'40px 0',textAlign:'center'}}>Loading affiliate data…</div>
    </div>
  );
  if(apiError)return(
    <div style={{maxWidth:900,margin:'0 auto',padding:'32px 16px'}}>
      <PageHeader title="Affiliate Program" breadcrumbs={[{label:'Dashboard',href:'/dashboard'},{label:'Affiliate'}]}/>
      <ErrorBanner message={apiError} onDismiss={()=>loadData()}/>
    </div>
  );

  if(!account)return(
    <div style={{maxWidth:900,margin:'0 auto',padding:'32px 16px',color:'#f1f5f9'}}>
      <PageHeader
        title="Affiliate Program"
        subtitle="Earn recurring commissions by referring traders to HOPEFX"
        breadcrumbs={[{label:'Dashboard',href:'/dashboard'},{label:'Affiliate'}]}
        actions={
          <div style={{display:'flex',gap:8}}>
            <Link to="/leaderboard"  style={{padding:'7px 14px',background:'rgba(245,158,11,0.1)',border:'1px solid rgba(245,158,11,0.3)',borderRadius:8,color:'#f59e0b',fontSize:12,fontWeight:600,textDecoration:'none'}}>🏆 Leaderboard</Link>
            <Link to="/marketplace"  style={{padding:'7px 14px',background:'rgba(167,139,250,0.1)',border:'1px solid rgba(167,139,250,0.3)',borderRadius:8,color:'#a78bfa',fontSize:12,fontWeight:600,textDecoration:'none'}}>🛒 Marketplace</Link>
          </div>
        }
      />
      <div style={{background:'#1e293b',border:'1px solid #334155',borderRadius:12,padding:'32px 28px',maxWidth:600}}>
        <h2 style={{fontSize:20,marginBottom:12,color:'#f8fafc',fontWeight:700}}>Earn by referring traders</h2>
        <p style={{color:'#94a3b8',marginBottom:24,lineHeight:1.6,fontSize:14}}>Share your referral link and earn recurring commissions. Commissions range from <strong style={{color:'#f8fafc'}}>10% (Bronze)</strong> to <strong style={{color:'#a78bfa'}}>25% (Platinum)</strong>.</p>
        <div style={{display:'grid',gridTemplateColumns:'repeat(4,1fr)',gap:12,marginBottom:24}}>
          {Object.entries(LEVEL_RATES).map(([level,rate])=>(
            <div key={level} style={{background:'#0f172a',border:`1px solid ${LEVEL_COLORS[level]}`,borderRadius:8,padding:'14px 10px',textAlign:'center'}}>
              <div style={{color:LEVEL_COLORS[level],fontWeight:700,textTransform:'capitalize',marginBottom:4,fontSize:13}}>{level}</div>
              <div style={{fontSize:22,fontWeight:800,color:'#f8fafc'}}>{rate}</div>
              <div style={{fontSize:11,color:'#64748b'}}>commission</div>
            </div>
          ))}
        </div>
        <button onClick={handleSignup} disabled={signupLoading} style={{padding:'11px 28px',background:'#3b82f6',color:'#fff',border:'none',borderRadius:8,fontSize:14,fontWeight:600,cursor:'pointer',opacity:signupLoading?0.6:1}}>
          {signupLoading?'Joining…':'Join the affiliate program'}
        </button>
      </div>
    </div>
  );

  const referralLink=`${window.location.origin}/?ref=${account.code}`;
  return(
    <div style={{maxWidth:900,margin:'0 auto',padding:'32px 16px',color:'#f1f5f9'}}>
      <PageHeader
        title="Affiliate Program"
        subtitle="Earn recurring commissions by referring traders"
        breadcrumbs={[{label:'Dashboard',href:'/dashboard'},{label:'Affiliate'}]}
        badge={
          <span style={{fontSize:11,fontWeight:700,padding:'2px 10px',borderRadius:20,letterSpacing:1,background:LEVEL_COLORS[account.level]+'22',color:LEVEL_COLORS[account.level],border:`1px solid ${LEVEL_COLORS[account.level]}`}}>
            {account.level.toUpperCase()}
          </span>
        }
        actions={
          <div style={{display:'flex',gap:8}}>
            <Link to="/copy-trading" style={{padding:'7px 12px',background:'transparent',border:'1px solid #334155',borderRadius:6,color:'#94a3b8',fontSize:12,fontWeight:500,textDecoration:'none'}}>🔁 Copy Trading</Link>
            <Link to="/leaderboard"  style={{padding:'7px 12px',background:'transparent',border:'1px solid #334155',borderRadius:6,color:'#94a3b8',fontSize:12,fontWeight:500,textDecoration:'none'}}>🏆 Leaderboard</Link>
            <button onClick={loadData} style={{padding:'7px 12px',background:'transparent',border:'1px solid #334155',borderRadius:6,color:'#94a3b8',cursor:'pointer',fontSize:12}}>↻ Refresh</button>
          </div>
        }
      />

      {/* Cross-links */}
      <div style={{display:'flex',gap:16,marginBottom:24,flexWrap:'wrap',fontSize:13}}>
        {[
          {to:'/marketplace',label:'🛒 Marketplace'},
          {to:'/copy-trading',label:'🔁 Copy Trading'},
          {to:'/leaderboard',label:'🏆 Leaderboard'},
          {to:'/wallet',label:'💳 Wallet'},
          {to:'/performance',label:'📊 Performance'},
        ].map(({to,label})=>(
          <Link key={to} to={to} style={{color:'#64748b',textDecoration:'none'}}
            onMouseEnter={e=>(e.currentTarget.style.color='#94a3b8')}
            onMouseLeave={e=>(e.currentTarget.style.color='#64748b')}>
            {label}
          </Link>
        ))}
      </div>

      {/* Referral link card */}
      <div style={{background:'#1e293b',border:'1px solid #334155',borderRadius:10,padding:'16px 20px',marginBottom:24}}>
        <div style={{fontSize:11,color:'#64748b',marginBottom:8,textTransform:'uppercase',letterSpacing:0.5}}>Your referral link</div>
        <div style={{display:'flex',alignItems:'center',gap:12}}>
          <code style={{flex:1,background:'#0f172a',border:'1px solid #475569',borderRadius:6,padding:'8px 12px',fontSize:13,color:'#93c5fd',wordBreak:'break-all'}}>{referralLink}</code>
          <button onClick={copyLink} style={{padding:'8px 16px',background:'#3b82f6',color:'#fff',border:'none',borderRadius:6,fontSize:13,cursor:'pointer',whiteSpace:'nowrap',fontWeight:600}}>
            {copied?'✅ Copied':'Copy link'}
          </button>
        </div>
        <div style={{fontSize:12,color:'#64748b',marginTop:8}}>
          Code: <strong style={{color:'#94a3b8'}}>{account.code}</strong>
          <span style={{marginLeft:16,color:'#64748b'}}>{(account.commission_rate*100).toFixed(0)}% commission rate</span>
          <span style={{marginLeft:8}}>{statusBadge(account.status)}</span>
        </div>
      </div>

      {/* Tabs */}
      <div style={{display:'flex',gap:4,marginBottom:20,borderBottom:'1px solid #1e293b'}}>
        {(['overview','referrals','commissions','leaderboard'] as Tab[]).map(tab=>(
          <button key={tab} onClick={()=>setActiveTab(tab)} style={{padding:'10px 20px',background:'transparent',border:'none',color:activeTab===tab?'#3b82f6':'#64748b',fontSize:14,cursor:'pointer',borderBottom:`2px solid ${activeTab===tab?'#3b82f6':'transparent'}`,fontWeight:activeTab===tab?600:400,transition:'color 0.15s',textTransform:'capitalize'}}>
            {tab.charAt(0).toUpperCase()+tab.slice(1)}
          </button>
        ))}
      </div>

      {activeTab==='overview'&&metrics&&(
        <>
          <div style={{display:'grid',gridTemplateColumns:'repeat(4,1fr)',gap:12,marginBottom:20}}>
            <div style={{background:'#1e293b',border:'1px solid #334155',borderRadius:10,padding:'16px 18px'}}>
              <div style={{fontSize:24,fontWeight:700,color:'#f8fafc',marginBottom:4}}>{metrics.total_referrals}</div>
              <div style={{fontSize:11,color:'#64748b',textTransform:'uppercase',letterSpacing:0.5}}>Total referrals</div>
            </div>
            <div style={{background:'#1e293b',border:'1px solid #334155',borderRadius:10,padding:'16px 18px'}}>
              <div style={{fontSize:24,fontWeight:700,color:'#f8fafc',marginBottom:4}}>{metrics.converted_referrals}</div>
              <div style={{fontSize:11,color:'#64748b',textTransform:'uppercase',letterSpacing:0.5}}>Converted</div>
              <div style={{fontSize:12,color:'#4ade80',marginTop:4}}>{fmt(metrics.conversion_rate,1)}% rate</div>
            </div>
            <div style={{background:'#1e293b',border:'1px solid #334155',borderRadius:10,padding:'16px 18px'}}>
              <div style={{fontSize:24,fontWeight:700,color:'#f8fafc',marginBottom:4}}>{fmtUSD(metrics.total_commissions)}</div>
              <div style={{fontSize:11,color:'#64748b',textTransform:'uppercase',letterSpacing:0.5}}>Total earned</div>
            </div>
            <div style={{background:'#1e293b',border:'1px solid #334155',borderRadius:10,padding:'16px 18px'}}>
              <div style={{fontSize:24,fontWeight:700,color:'#f8fafc',marginBottom:4}}>{fmtUSD(metrics.pending_commissions)}</div>
              <div style={{fontSize:11,color:'#64748b',textTransform:'uppercase',letterSpacing:0.5}}>Pending payout</div>
              <div style={{fontSize:12,color:'#94a3b8',marginTop:4}}>Next: 1st of month</div>
            </div>
          </div>
          <div style={{background:'#1e293b',border:'1px solid #334155',borderRadius:10,padding:'20px 24px',marginBottom:16}}>
            <h3 style={{fontSize:15,fontWeight:600,color:'#e2e8f0',marginBottom:4,marginTop:0}}>Request Commission Withdrawal</h3>
            <p style={{color:'#64748b',fontSize:13,marginBottom:12}}>Minimum withdrawal: <strong style={{color:'#94a3b8'}}>$50.00</strong></p>
            <div style={{display:'flex',gap:10,alignItems:'center'}}>
              <input type="number" min="0" step="0.01" value={withdrawAmt} onChange={e=>setWithdrawAmt(e.target.value)} placeholder="Amount (USD)"
                style={{background:'#0f172a',border:'1px solid #334155',borderRadius:8,color:'#f1f5f9',padding:'9px 12px',fontSize:14,width:180,outline:'none'}}/>
              <button onClick={handleWithdraw} disabled={withdrawing||!withdrawAmt}
                style={{padding:'10px 24px',background:'#3b82f6',color:'#fff',border:'none',borderRadius:8,fontSize:14,fontWeight:600,cursor:'pointer',opacity:withdrawing||!withdrawAmt?0.6:1}}>
                {withdrawing?'Processing…':'Withdraw'}
              </button>
            </div>
            {withdrawMsg&&<div style={{marginTop:10,fontSize:13,color:withdrawMsg.includes('success')?'#4ade80':'#f87171'}}>{withdrawMsg}</div>}
          </div>
          <div style={{background:'#1e293b',border:'1px solid #334155',borderRadius:10,padding:'20px 24px',marginBottom:16}}>
            <h3 style={{fontSize:15,fontWeight:600,color:'#e2e8f0',marginBottom:12,marginTop:0}}>How commissions work</h3>
            <ul style={{color:'#94a3b8',fontSize:14,lineHeight:2,paddingLeft:20,margin:0}}>
              <li>Share your referral link — anyone who signs up through it is tracked for 30 days.</li>
              <li>When a referral subscribes to any paid plan, you earn a commission on their monthly fee.</li>
              <li>Commissions are paid out on the 1st of each month via your registered payment method.</li>
              <li>Reach higher tiers: Silver (5+ conversions), Gold (15+), Platinum (30+).</li>
            </ul>
          </div>
        </>
      )}

      {activeTab==='referrals'&&(
        <div style={{background:'#1e293b',border:'1px solid #334155',borderRadius:10,padding:'20px 24px',marginBottom:16}}>
          <h3 style={{fontSize:15,fontWeight:600,color:'#e2e8f0',marginBottom:16,marginTop:0}}>Referral history</h3>
          {subErrors.referrals&&<div style={{background:'rgba(248,113,113,0.1)',border:'1px solid #f87171',borderRadius:6,padding:'8px 12px',fontSize:13,color:'#f87171',marginBottom:12}}>{subErrors.referrals}</div>}
          {referrals.length===0&&!subErrors.referrals ? (
            <EmptyState icon="🔗" title="No referrals yet" description="Share your referral link to start earning commissions."/>
          ) : (
            <table style={{width:'100%',borderCollapse:'collapse'}}>
              <thead><tr>
                {['User ID','Status','Referred','Converted','Commission'].map(h=>(
                  <th key={h} style={{textAlign:'left',fontSize:11,color:'#64748b',textTransform:'uppercase',letterSpacing:0.5,padding:'8px 12px',borderBottom:'1px solid #334155'}}>{h}</th>
                ))}
              </tr></thead>
              <tbody>{referrals.map(r=>(
                <tr key={r.referral_id} style={{borderBottom:'1px solid #1e293b'}}>
                  <td style={{padding:'10px 12px',fontSize:12,color:'#cbd5e1',fontFamily:'monospace'}}>{r.referred_user_id}</td>
                  <td style={{padding:'10px 12px'}}>{statusBadge(r.status)}</td>
                  <td style={{padding:'10px 12px',fontSize:13,color:'#cbd5e1'}}>{new Date(r.created_at).toLocaleDateString()}</td>
                  <td style={{padding:'10px 12px',fontSize:13,color:'#cbd5e1'}}>{r.converted_at?new Date(r.converted_at).toLocaleDateString():'—'}</td>
                  <td style={{padding:'10px 12px',fontSize:13,color:'#4ade80',fontWeight:600}}>{r.commission_amount!=null?fmtUSD(r.commission_amount):'—'}</td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </div>
      )}

      {activeTab==='commissions'&&(
        <div style={{background:'#1e293b',border:'1px solid #334155',borderRadius:10,padding:'20px 24px',marginBottom:16}}>
          <h3 style={{fontSize:15,fontWeight:600,color:'#e2e8f0',marginBottom:16,marginTop:0}}>Commission history ({commissions.length})</h3>
          {subErrors.commissions&&<div style={{background:'rgba(248,113,113,0.1)',border:'1px solid #f87171',borderRadius:6,padding:'8px 12px',fontSize:13,color:'#f87171',marginBottom:12}}>{subErrors.commissions}</div>}
          {commissions.length===0&&!subErrors.commissions ? (
            <EmptyState icon="💰" title="No commissions yet" description="Commissions appear here once your referrals subscribe to a paid plan."/>
          ) : (
            <>
              {/* Commission bar chart */}
              {commissions.length>1&&(
                <div style={{marginBottom:20}}>
                  <div style={{fontSize:11,color:'#64748b',textTransform:'uppercase',letterSpacing:'0.05em',marginBottom:8}}>Monthly Commission Chart</div>
                  <ResponsiveContainer width="100%" height={140}>
                    <BarChart data={commissions.slice().reverse().map(c=>({period:c.period,amount:c.amount,fill:c.status==='paid'?'#4ade80':'#60a5fa'}))} margin={{top:4,right:4,left:-20,bottom:0}}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#0f172a"/>
                      <XAxis dataKey="period" tick={{fontSize:9,fill:'#64748b'}} tickLine={false} axisLine={false}/>
                      <YAxis tick={{fontSize:9,fill:'#64748b'}} tickLine={false} axisLine={false} tickFormatter={(v:number)=>`$${v}`}/>
                      <Tooltip contentStyle={{background:'#0f172a',border:'1px solid #334155',borderRadius:6,fontSize:11}} formatter={(v:number)=>[fmtUSD(v),'Commission']} labelStyle={{color:'#94a3b8'}}/>
                      <Bar dataKey="amount" radius={[3,3,0,0]} fill="#4ade80"/>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
              <table style={{width:'100%',borderCollapse:'collapse'}}>
                <thead><tr>
                  {['Period','Amount','Status','Paid At'].map(h=>(
                    <th key={h} style={{textAlign:'left',fontSize:11,color:'#64748b',textTransform:'uppercase',letterSpacing:0.5,padding:'8px 12px',borderBottom:'1px solid #334155'}}>{h}</th>
                  ))}
                </tr></thead>
                <tbody>{commissions.map(c=>(
                  <tr key={c.commission_id} style={{borderBottom:'1px solid #1e293b'}}>
                    <td style={{padding:'10px 12px',fontSize:13,color:'#cbd5e1'}}>{c.period}</td>
                    <td style={{padding:'10px 12px',fontSize:13,color:'#4ade80',fontWeight:600}}>{fmtUSD(c.amount)}</td>
                    <td style={{padding:'10px 12px'}}>{statusBadge(c.status)}</td>
                    <td style={{padding:'10px 12px',fontSize:13,color:'#cbd5e1'}}>{c.paid_at?new Date(c.paid_at).toLocaleDateString():'—'}</td>
                  </tr>
                ))}</tbody>
              </table>
            </>
          )}
        </div>
      )}

      {activeTab==='leaderboard'&&(
        <div style={{background:'#1e293b',border:'1px solid #334155',borderRadius:10,padding:'20px 24px',marginBottom:16}}>
          <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:16}}>
            <h3 style={{fontSize:15,fontWeight:600,color:'#e2e8f0',margin:0}}>Top affiliates</h3>
            <Link to="/leaderboard" style={{background:'rgba(96,165,250,0.1)',border:'1px solid rgba(96,165,250,0.3)',borderRadius:6,color:'#60a5fa',fontSize:12,fontWeight:600,padding:'5px 12px',textDecoration:'none'}}>
              View full leaderboard →
            </Link>
          </div>
          {subErrors.leaderboard&&<div style={{background:'rgba(248,113,113,0.1)',border:'1px solid #f87171',borderRadius:6,padding:'8px 12px',fontSize:13,color:'#f87171',marginBottom:12}}>{subErrors.leaderboard}</div>}
          {!subErrors.leaderboard&&(
            <table style={{width:'100%',borderCollapse:'collapse'}}>
              <thead><tr>
                {['#','Code','Level','Conversions','Earned'].map(h=>(
                  <th key={h} style={{textAlign:'left',fontSize:11,color:'#64748b',textTransform:'uppercase',letterSpacing:0.5,padding:'8px 12px',borderBottom:'1px solid #334155'}}>{h}</th>
                ))}
              </tr></thead>
              <tbody>{leaderboard.map(e=>(
                <tr key={e.affiliate_id} style={{borderBottom:'1px solid #1e293b',background:e.affiliate_id===account.affiliate_id?'rgba(30,58,95,0.5)':undefined}}>
                  <td style={{padding:'10px 12px',fontSize:14,color:'#cbd5e1'}}>{e.rank===1?'🥇':e.rank===2?'🥈':e.rank===3?'🥉':e.rank}</td>
                  <td style={{padding:'10px 12px',fontSize:13,color:'#e2e8f0',fontFamily:'monospace'}}>{e.code}</td>
                  <td style={{padding:'10px 12px',fontSize:13,color:LEVEL_COLORS[e.level]??'#94a3b8',textTransform:'capitalize',fontWeight:600}}>{e.level}</td>
                  <td style={{padding:'10px 12px',fontSize:13,color:'#cbd5e1'}}>{e.converted_referrals}</td>
                  <td style={{padding:'10px 12px',fontSize:13,color:'#4ade80',fontWeight:600}}>{fmtUSD(e.total_commissions)}</td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
};



export default Affiliate;
