/**
 * Strategy Marketplace — browse, purchase, review, and manage your listings.
 * Tabs: Browse · My Listings
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { marketplaceApi } from '../hooks/useApi';
import { useStore, selectUser } from '../store';
import { PageHeader } from '../components/PageHeader';
import { EmptyState } from '../components/EmptyState';
import { ErrorBanner } from '../components/ErrorBanner';
import { Spinner } from '../components/Spinner';
import { Sparkline } from '../components/ui/Sparkline';

interface Strategy {
  strategy_id: string; name: string; description: string; creator_id: string;
  category: string; price: number; license_type: string; rating: number;
  review_count: number; subscriber_count: number; status: string; tags: string[];
  performance?: { total_return_pct?: number; sharpe_ratio?: number; max_drawdown_pct?: number; win_rate_pct?: number; };
}

/** Normalize a raw API strategy object so arrays/strings are always safe to use. */
function normalizeStrategy(raw: unknown): Strategy {
  const s = (raw ?? {}) as Record<string, unknown>;
  return {
    strategy_id:      String(s.strategy_id ?? ''),
    name:             String(s.name ?? ''),
    description:      String(s.description ?? ''),
    creator_id:       String(s.creator_id ?? ''),
    category:         String(s.category ?? 'other'),
    price:            typeof s.price === 'number' ? s.price : 0,
    license_type:     String(s.license_type ?? 'monthly'),
    rating:           typeof s.rating === 'number' ? s.rating : 0,
    review_count:     typeof s.review_count === 'number' ? s.review_count : 0,
    subscriber_count: typeof s.subscriber_count === 'number' ? s.subscriber_count : 0,
    status:           String(s.status ?? 'active'),
    tags:             Array.isArray(s.tags) ? (s.tags as unknown[]).map(String) : [],
    performance:      s.performance && typeof s.performance === 'object'
                        ? (s.performance as Strategy['performance'])
                        : undefined,
  };
}
interface Review { review_id: string; user_id: string; rating: number; title: string; content: string; created_at: string; }
type SortOption = 'popular'|'rating'|'newest'|'price_low'|'price_high';
type MainTab = 'browse'|'my-listings';
const CATEGORIES = ['all','trend_following','mean_reversion','smart_money','macro','breakout','swing'];

function extractErr(err: unknown, fb: string): string {
  const d = (err as {response?:{data?:{detail?:string;message?:string}}})?.response?.data;
  return d?.detail ?? d?.message ?? (err instanceof Error ? err.message : fb);
}
const fmt = (n: number, d = 1) => n.toFixed(d);
const Stars: React.FC<{rating: number; size?: number}> = ({rating, size=14}) => {
  const full = Math.floor(rating); const half = rating - full >= 0.5;
  return <span style={{fontSize:size,lineHeight:1,color:'#f59e0b'}}>{'★'.repeat(full)}{half ? '½' : ''}{'☆'.repeat(5-full-(half?1:0))}</span>;
};
const PerfBadge: React.FC<{label:string;value:string;positive?:boolean}> = ({label,value,positive}) => (
  <div style={{background:'#0f172a',border:'1px solid #334155',borderRadius:6,padding:'6px 10px',textAlign:'center',minWidth:64}}>
    <div style={{fontSize:14,fontWeight:700,color:positive===false?'#f87171':'#4ade80'}}>{value}</div>
    <div style={{fontSize:10,color:'#64748b',textTransform:'uppercase',letterSpacing:0.3}}>{label}</div>
  </div>
);

const StrategyCard: React.FC<{strategy:Strategy;onSelect:(s:Strategy)=>void}> = ({strategy,onSelect}) => {
  const p = strategy.performance;
  // Build sparkline data from equity_curve if available, else synthesise from return
  const sparkData: number[] = (strategy as unknown as { equity_curve?: number[] }).equity_curve
    ?? (p ? Array.from({ length: 12 }, (_, i) => 10000 * (1 + ((p.total_return_pct ?? 0) / 100) * (i / 11))) : []);
  return (
    <div
      onClick={()=>onSelect(strategy)}
      style={{background:'#1e293b',border:'1px solid #334155',borderRadius:12,padding:20,cursor:'pointer',transition:'border-color 0.15s'}}
      onMouseEnter={e=>(e.currentTarget.style.borderColor='#3b82f6')}
      onMouseLeave={e=>(e.currentTarget.style.borderColor='#334155')}
    >
      <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start',marginBottom:10}}>
        <div style={{display:'flex',gap:6,flexWrap:'wrap'}}>
          <span style={{fontSize:11,fontWeight:600,padding:'2px 8px',borderRadius:4,background:'rgba(59,130,246,0.15)',color:'#60a5fa',textTransform:'capitalize'}}>
            {strategy.category.replace(/_/g,' ')}
          </span>
          {strategy.tags.slice(0,2).map(t=>(
            <span key={t} style={{fontSize:11,padding:'2px 8px',borderRadius:4,background:'#1e293b',color:'#64748b',border:'1px solid #334155'}}>{t}</span>
          ))}
        </div>
        <div style={{fontSize:14,whiteSpace:'nowrap'}}>
          {strategy.price===0
            ? <span style={{color:'#4ade80',fontWeight:700}}>Free</span>
            : <span style={{color:'#f8fafc',fontWeight:700}}>${strategy.price}<span style={{color:'#64748b',fontWeight:400,fontSize:12}}>/mo</span></span>
          }
        </div>
      </div>
      <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start',marginBottom:8}}>
        <h3 style={{fontSize:15,fontWeight:700,color:'#f8fafc',margin:0,flex:1}}>{strategy.name}</h3>
        {sparkData.length>1&&<Sparkline data={sparkData} width={72} height={28}/>}
      </div>
      <p style={{fontSize:13,color:'#94a3b8',lineHeight:1.6,margin:'0 0 12px',display:'-webkit-box',WebkitLineClamp:2,WebkitBoxOrient:'vertical',overflow:'hidden'}}>{strategy.description}</p>
      {p&&<div style={{display:'flex',gap:8,flexWrap:'wrap',marginBottom:12}}>
        {p.total_return_pct!=null&&<PerfBadge label="Return" value={`+${fmt(p.total_return_pct)}%`}/>}
        {p.sharpe_ratio!=null&&<PerfBadge label="Sharpe" value={fmt(p.sharpe_ratio)}/>}
        {p.max_drawdown_pct!=null&&<PerfBadge label="Max DD" value={`-${fmt(p.max_drawdown_pct)}%`} positive={false}/>}
        {p.win_rate_pct!=null&&<PerfBadge label="Win rate" value={`${fmt(p.win_rate_pct,0)}%`}/>}
      </div>}
      <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',paddingTop:10,borderTop:'1px solid #1e293b'}}>
        <div style={{display:'flex',alignItems:'center',gap:6}}>
          <Stars rating={strategy.rating}/>
          <span style={{fontSize:12,color:'#94a3b8'}}>{fmt(strategy.rating)} ({strategy.review_count})</span>
        </div>
        <span style={{fontSize:12,color:'#64748b'}}>{strategy.subscriber_count.toLocaleString()} subscribers</span>
      </div>
    </div>
  );
};

const ReviewModal: React.FC<{strategyId:string;onClose:()=>void;onSubmitted:()=>void}> = ({strategyId,onClose,onSubmitted}) => {
  const [rating,setRating]=useState(5); const [title,setTitle]=useState(''); const [content,setContent]=useState(''); const [submitting,setSubmitting]=useState(false); const [err,setErr]=useState('');
  const submit=async()=>{
    if(!title.trim()||!content.trim()){setErr('Title and content are required.');return;}
    setSubmitting(true);
    try{ await marketplaceApi.review(strategyId,{rating,title,content}); onSubmitted(); onClose(); }
    catch(e){setErr(extractErr(e,'Failed to submit review.'));}
    finally{setSubmitting(false);}
  };
  return(
    <div style={{position:'fixed',inset:0,background:'rgba(0,0,0,0.7)',backdropFilter:'blur(4px)',zIndex:50,display:'flex',alignItems:'center',justifyContent:'center',padding:16}} onClick={onClose}>
      <div style={{background:'#0f172a',border:'1px solid #334155',borderRadius:16,padding:24,width:'100%',maxWidth:480,boxShadow:'0 25px 50px rgba(0,0,0,0.5)'}} onClick={e=>e.stopPropagation()}>
        <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:20}}>
          <h2 style={{fontSize:18,fontWeight:700,color:'#f8fafc',margin:0}}>Write a Review</h2>
          <button onClick={onClose} style={{background:'none',border:'none',color:'#64748b',cursor:'pointer',fontSize:20,lineHeight:1}}>✕</button>
        </div>
        <label style={{display:'block',fontSize:11,color:'#64748b',marginBottom:8,textTransform:'uppercase',letterSpacing:0.5}}>Rating</label>
        <div style={{display:'flex',gap:4,marginBottom:16}}>
          {[1,2,3,4,5].map(n=><button key={n} onClick={()=>setRating(n)} style={{background:'transparent',border:'none',cursor:'pointer',fontSize:24,color:n<=rating?'#f59e0b':'#334155',transition:'color 0.1s'}}>★</button>)}
        </div>
        <label style={{display:'block',fontSize:11,color:'#64748b',marginBottom:6,textTransform:'uppercase',letterSpacing:0.5}}>Title</label>
        <input value={title} onChange={e=>setTitle(e.target.value)} style={{width:'100%',background:'#1e293b',border:'1px solid #334155',borderRadius:8,padding:'9px 12px',color:'#f1f5f9',fontSize:14,outline:'none',boxSizing:'border-box',marginBottom:12}} placeholder="Summary of your experience"/>
        <label style={{display:'block',fontSize:11,color:'#64748b',marginBottom:6,textTransform:'uppercase',letterSpacing:0.5}}>Review</label>
        <textarea value={content} onChange={e=>setContent(e.target.value)} style={{width:'100%',background:'#1e293b',border:'1px solid #334155',borderRadius:8,padding:'9px 12px',color:'#f1f5f9',fontSize:14,outline:'none',boxSizing:'border-box',resize:'vertical',fontFamily:'inherit'}} rows={4} placeholder="Describe your experience with this strategy…"/>
        {err&&<div style={{marginTop:8,fontSize:13,color:'#f87171'}}>{err}</div>}
        <button onClick={submit} disabled={submitting} style={{marginTop:16,width:'100%',background:'#3b82f6',color:'#fff',border:'none',borderRadius:10,padding:'11px 0',fontSize:14,fontWeight:600,cursor:'pointer',opacity:submitting?0.6:1}}>{submitting?'Submitting…':'Submit Review'}</button>
      </div>
    </div>
  );
};

const DetailModal: React.FC<{strategy:Strategy;reviews:Review[];onClose:()=>void;onSubscribe:(s:Strategy)=>void;subscribed:boolean;purchaseError:string|null;reviewsErr:string|null;onReview:()=>void}> = ({strategy,reviews,onClose,onSubscribe,subscribed,purchaseError,reviewsErr,onReview}) => {
  const p=strategy.performance;
  const [confirmOpen,setConfirmOpen]=useState(false);
  const sparkData: number[] = (strategy as unknown as { equity_curve?: number[] }).equity_curve
    ?? (p ? Array.from({length:12},(_,i)=>10000*(1+((p.total_return_pct??0)/100)*(i/11))) : []);
  return(
    <div style={{position:'fixed',inset:0,background:'rgba(0,0,0,0.7)',backdropFilter:'blur(4px)',zIndex:50,display:'flex',alignItems:'center',justifyContent:'center',padding:16}} onClick={onClose}>
      <div style={{background:'#0f172a',border:'1px solid #334155',borderRadius:16,padding:24,width:'100%',maxWidth:680,maxHeight:'90vh',overflowY:'auto',boxShadow:'0 25px 50px rgba(0,0,0,0.5)'}} onClick={e=>e.stopPropagation()}>
        <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start',marginBottom:20}}>
          <div style={{flex:1,paddingRight:16}}>
            <div style={{display:'flex',gap:6,flexWrap:'wrap',marginBottom:8}}>
              <span style={{fontSize:11,fontWeight:600,padding:'2px 8px',borderRadius:4,background:'rgba(59,130,246,0.15)',color:'#60a5fa',textTransform:'capitalize'}}>{strategy.category.replace(/_/g,' ')}</span>
              {strategy.tags.map(t=><span key={t} style={{fontSize:11,padding:'2px 8px',borderRadius:4,background:'#1e293b',color:'#64748b',border:'1px solid #334155'}}>{t}</span>)}
            </div>
            <h2 style={{fontSize:20,fontWeight:700,color:'#f8fafc',margin:'0 0 6px'}}>{strategy.name}</h2>
            <div style={{display:'flex',alignItems:'center',gap:8}}>
              <Stars rating={strategy.rating} size={16}/>
              <span style={{color:'#94a3b8',fontSize:13}}>{fmt(strategy.rating)} · {strategy.review_count} reviews · {strategy.subscriber_count.toLocaleString()} subscribers</span>
            </div>
          </div>
          <div style={{textAlign:'right',flexShrink:0}}>
            {strategy.price===0
              ? <div style={{fontSize:28,fontWeight:800,color:'#4ade80'}}>Free</div>
              : <><div style={{fontSize:28,fontWeight:800,color:'#f8fafc'}}>${strategy.price}</div><div style={{fontSize:13,color:'#64748b'}}>/{strategy.license_type==='one_time'?'one-time':'mo'}</div></>
            }
          </div>
          <button onClick={onClose} style={{marginLeft:16,background:'none',border:'none',color:'#64748b',cursor:'pointer',fontSize:20,lineHeight:1,flexShrink:0}}>✕</button>
        </div>
        <p style={{color:'#94a3b8',fontSize:14,lineHeight:1.7,marginBottom:16}}>{strategy.description}</p>
        {sparkData.length>1&&<div style={{marginBottom:16}}><Sparkline data={sparkData} width={300} height={48}/></div>}
        {p&&<div style={{display:'flex',gap:8,flexWrap:'wrap',marginBottom:24}}>
          {p.total_return_pct!=null&&<PerfBadge label="Total return" value={`+${fmt(p.total_return_pct)}%`}/>}
          {p.sharpe_ratio!=null&&<PerfBadge label="Sharpe ratio" value={fmt(p.sharpe_ratio)}/>}
          {p.max_drawdown_pct!=null&&<PerfBadge label="Max drawdown" value={`-${fmt(p.max_drawdown_pct)}%`} positive={false}/>}
          {p.win_rate_pct!=null&&<PerfBadge label="Win rate" value={`${fmt(p.win_rate_pct,0)}%`}/>}
        </div>}
        {/* Purchase confirmation */}
        {confirmOpen&&!subscribed?(
          <div style={{background:'rgba(59,130,246,0.08)',border:'1px solid rgba(59,130,246,0.35)',borderRadius:10,padding:'14px 16px',marginBottom:12}}>
            <div style={{fontSize:14,fontWeight:600,color:'#f1f5f9',marginBottom:6}}>Confirm Purchase</div>
            <div style={{fontSize:13,color:'#94a3b8',marginBottom:12}}>
              Subscribe to <strong style={{color:'#f1f5f9'}}>{strategy.name}</strong> for{' '}
              <strong style={{color:'#60a5fa'}}>{strategy.price===0?'Free':`$${strategy.price}/${strategy.license_type==='one_time'?'one-time':'mo'}`}</strong>?
            </div>
            <div style={{display:'flex',gap:8}}>
              <button onClick={()=>{setConfirmOpen(false);onSubscribe(strategy);}} style={{flex:1,background:'#3b82f6',color:'#fff',border:'none',borderRadius:8,padding:'10px 0',fontSize:13,fontWeight:700,cursor:'pointer'}}>
                ✅ Confirm
              </button>
              <button onClick={()=>setConfirmOpen(false)} style={{flex:1,background:'#334155',color:'#94a3b8',border:'none',borderRadius:8,padding:'10px 0',fontSize:13,cursor:'pointer'}}>
                Cancel
              </button>
            </div>
          </div>
        ):(
          <div style={{display:'flex',gap:10,marginBottom:16}}>
            <button onClick={()=>subscribed?undefined:setConfirmOpen(true)} disabled={subscribed} style={{flex:1,background:'#3b82f6',color:'#fff',border:'none',borderRadius:10,padding:'13px 0',fontSize:14,fontWeight:600,cursor:subscribed?'default':'pointer',opacity:subscribed?0.6:1}}>
              {subscribed?'✅ Subscribed':strategy.price===0?'Add to my strategies':`Subscribe — $${strategy.price}/${strategy.license_type==='one_time'?'one-time':'mo'}`}
            </button>
            {subscribed&&<button onClick={onReview} style={{background:'#334155',color:'#e2e8f0',border:'none',borderRadius:10,padding:'13px 16px',fontSize:14,fontWeight:600,cursor:'pointer'}}>✍ Review</button>}
          </div>
        )}
        {purchaseError&&<div style={{background:'rgba(248,113,113,0.1)',border:'1px solid #f87171',borderRadius:8,padding:'10px 14px',fontSize:13,color:'#f87171',marginBottom:12}}>{purchaseError}</div>}
        {reviewsErr&&<div style={{background:'rgba(248,113,113,0.1)',border:'1px solid #f87171',borderRadius:8,padding:'10px 14px',fontSize:13,color:'#f87171',marginBottom:12}}>{reviewsErr}</div>}
        {reviews.length>0&&(
          <div style={{marginTop:24,paddingTop:24,borderTop:'1px solid #1e293b'}}>
            <h3 style={{fontSize:13,fontWeight:600,color:'#94a3b8',textTransform:'uppercase',letterSpacing:0.5,marginBottom:16}}>Reviews</h3>
            <div style={{display:'flex',flexDirection:'column',gap:12}}>
              {reviews.map(r=>(
                <div key={r.review_id} style={{background:'#1e293b',border:'1px solid #334155',borderRadius:10,padding:16}}>
                  <div style={{display:'flex',alignItems:'center',gap:8,marginBottom:8}}>
                    <Stars rating={r.rating}/>
                    <strong style={{color:'#e2e8f0',fontSize:14}}>{r.title}</strong>
                    <span style={{color:'#475569',fontSize:12,marginLeft:'auto'}}>{new Date(r.created_at).toLocaleDateString()}</span>
                  </div>
                  <p style={{color:'#94a3b8',fontSize:13,margin:0}}>{r.content}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

const Marketplace: React.FC = () => {
  const navigate = useNavigate();
  const currentUser = useStore(selectUser);
  const [mainTab,setMainTab]         = useState<MainTab>('browse');
  const [strategies,setStrategies]   = useState<Strategy[]>([]);
  const [myListings,setMyListings]   = useState<Strategy[]>([]);
  const [loading,setLoading]         = useState(true);
  const [loadErr,setLoadErr]         = useState<string|null>(null);
  const [reviewsErr,setReviewsErr]   = useState<string|null>(null);
  const [search,setSearch]           = useState('');
  const [category,setCategory]       = useState('all');
  const [sortBy,setSortBy]           = useState<SortOption>('popular');
  const [selected,setSelected]       = useState<Strategy|null>(null);
  const [selectedReviews,setSelectedReviews] = useState<Review[]>([]);
  const [subscribed,setSubscribed]   = useState<Set<string>>(new Set());
  const [purchaseError,setPurchaseError] = useState<string|null>(null);
  const [stats,setStats]             = useState<{total_strategies:number;total_subscribers:number}|null>(null);
  const [showReviewModal,setShowReviewModal] = useState(false);

  const mountedRef = useRef(true);
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

  const loadStrategies = useCallback(async () => {
    setLoading(true); setLoadErr(null);
    try {
      const params: Record<string,string> = { sort_by: sortBy, limit: '50' };
      if (category !== 'all') params.category = category;
      if (search) params.query = search;
      const res = await marketplaceApi.strategies(params) as {data:{strategies?:unknown[];total?:number}|unknown[]};
      if (!mountedRef.current) return;
      const raw = Array.isArray(res.data) ? res.data : ((res.data as {strategies?:unknown[]}).strategies ?? []);
      setStrategies(raw.map(normalizeStrategy));
    } catch (err) {
      if (!mountedRef.current) return;
      if ((err as {name?:string}).name === 'CanceledError') return;
      setStrategies([]); setLoadErr(extractErr(err,'Failed to load strategies.'));
    } finally { if (mountedRef.current) setLoading(false); }
  }, [category, sortBy, search]);

  const loadMyListings = useCallback(async () => {
    if (!currentUser?.id) return;
    try {
      const res = await marketplaceApi.myStrategies(currentUser.id) as {data:{strategies?:unknown[]}|unknown[]};
      if (!mountedRef.current) return;
      const d = res.data;
      const raw = Array.isArray(d) ? d : ((d as {strategies?:unknown[]}).strategies ?? []);
      setMyListings(raw.map(normalizeStrategy));
    } catch {
      if (!mountedRef.current) return;
      setMyListings([]);
    }
  }, [currentUser?.id]);

  useEffect(() => { loadStrategies(); }, [loadStrategies]);
  useEffect(() => { if (mainTab === 'my-listings') loadMyListings(); }, [mainTab, loadMyListings]);
  useEffect(() => {
    let mounted = true;
    marketplaceApi.stats().then(r => {
      if (!mounted) return;
      const d = (r as {data:{total_strategies?:number;total_subscribers?:number}|null}).data;
      if (d && typeof d.total_strategies === 'number' && typeof d.total_subscribers === 'number') {
        setStats({ total_strategies: d.total_strategies, total_subscribers: d.total_subscribers });
      }
    }).catch(() => {});
    return () => { mounted = false; };
  }, []);

  const handleSelect = async (s: Strategy) => {
    setSelected(s); setReviewsErr(null);
    try {
      const res = await marketplaceApi.strategy(s.strategy_id) as {data:{strategy?:unknown;reviews?:Review[]}};
      if (res.data.strategy) setSelected(normalizeStrategy(res.data.strategy));
      setSelectedReviews(Array.isArray(res.data.reviews) ? res.data.reviews : []);
    } catch (err) { setSelectedReviews([]); setReviewsErr(extractErr(err,'Failed to load reviews.')); }
  };

  const handleSubscribe = async (s: Strategy) => {
    setPurchaseError(null);
    try {
      await marketplaceApi.purchase({ buyer_id: currentUser?.id ?? '', strategy_id: s.strategy_id });
      setSubscribed(prev => new Set([...prev, s.strategy_id]));
    } catch (err) { setPurchaseError(extractErr(err,'Purchase failed. Check your payment method.')); }
  };

  const visible = strategies.filter(s => {
    const q = search.toLowerCase();
    if (q && !s.name.toLowerCase().includes(q) && !s.description.toLowerCase().includes(q) && !(s.tags ?? []).some(t => t.toLowerCase().includes(q))) return false;
    if (category !== 'all' && s.category !== category) return false;
    return true;
  });

  return (
    <div style={{maxWidth:1100,margin:'0 auto',padding:'32px 16px',color:'#f1f5f9',minHeight:'100vh'}}>
      <PageHeader
        title="Strategy Marketplace"
        icon="🛒"
        subtitle={
          stats?.total_strategies != null && stats?.total_subscribers != null
            ? `${stats.total_strategies.toLocaleString()} strategies · ${stats.total_subscribers.toLocaleString()} subscribers`
            : 'Browse, purchase, and review AI trading strategies'
        }
        breadcrumbs={[
          { label: 'Dashboard', href: '/dashboard' },
          { label: 'Marketplace' },
        ]}
        badge={<span style={{fontSize:11,fontWeight:700,padding:'2px 8px',borderRadius:20,background:'rgba(59,130,246,0.15)',color:'#60a5fa',border:'1px solid rgba(59,130,246,0.3)'}}>LIVE</span>}
        actions={
          <div style={{display:'flex',gap:8}}>
            <Link to="/copy-trading" style={{padding:'7px 14px',background:'rgba(52,211,153,0.1)',border:'1px solid rgba(52,211,153,0.3)',borderRadius:8,color:'#34d399',fontSize:12,fontWeight:600,textDecoration:'none'}}>🔁 Copy Trading</Link>
            <Link to="/signals" style={{padding:'7px 14px',background:'rgba(167,139,250,0.1)',border:'1px solid rgba(167,139,250,0.3)',borderRadius:8,color:'#a78bfa',fontSize:12,fontWeight:600,textDecoration:'none'}}>📡 Signals</Link>
            <Link to="/ai-strategy" style={{padding:'8px 18px',background:'#3b82f6',color:'#fff',border:'none',borderRadius:8,fontSize:13,fontWeight:700,textDecoration:'none'}}>🤖 Build Strategy</Link>
          </div>
        }
      />

      {/* Cross-links */}
      <div style={{display:'flex',gap:16,marginBottom:24,flexWrap:'wrap',fontSize:13}}>
        {[
          {to:'/performance',label:'📊 Performance'},
          {to:'/leaderboard',label:'🏆 Leaderboard'},
          {to:'/affiliate',label:'💰 Affiliate'},
          {to:'/journal',label:'📓 Journal'},
          {to:'/copy-trading',label:'🔁 Copy Trading'},
        ].map(({to,label})=>(
          <Link key={to} to={to} style={{color:'#64748b',textDecoration:'none',transition:'color 0.15s'}}
            onMouseEnter={e=>(e.currentTarget.style.color='#94a3b8')}
            onMouseLeave={e=>(e.currentTarget.style.color='#64748b')}>
            {label}
          </Link>
        ))}
      </div>

      {/* Tabs */}
      <div style={{display:'flex',gap:4,marginBottom:24,borderBottom:'1px solid #1e293b'}}>
        {(['browse','my-listings'] as MainTab[]).map(tab=>(
          <button key={tab} onClick={()=>setMainTab(tab)} style={{padding:'10px 20px',background:'transparent',border:'none',color:mainTab===tab?'#3b82f6':'#64748b',fontSize:14,cursor:'pointer',borderBottom:`2px solid ${mainTab===tab?'#3b82f6':'transparent'}`,fontWeight:mainTab===tab?600:400,transition:'color 0.15s'}}>
            {tab==='browse'?'Browse':'My Listings'}
          </button>
        ))}
      </div>

      {mainTab==='browse'&&(
        <>
          <div style={{display:'flex',gap:12,marginBottom:16,flexWrap:'wrap'}}>
            <input type="search" placeholder="Search strategies…" value={search} onChange={e=>setSearch(e.target.value)}
              style={{flex:1,minWidth:200,padding:'10px 14px',background:'#1e293b',border:'1px solid #334155',borderRadius:8,color:'#f1f5f9',fontSize:14,outline:'none'}}/>
            <select value={sortBy} onChange={e=>setSortBy(e.target.value as SortOption)}
              style={{padding:'10px 14px',background:'#1e293b',border:'1px solid #334155',borderRadius:8,color:'#f1f5f9',fontSize:14,cursor:'pointer',outline:'none'}}>
              <option value="popular">Most popular</option>
              <option value="rating">Highest rated</option>
              <option value="newest">Newest</option>
              <option value="price_low">Price: low → high</option>
              <option value="price_high">Price: high → low</option>
            </select>
          </div>
          <div style={{display:'flex',gap:8,flexWrap:'wrap',marginBottom:24}}>
            {CATEGORIES.map(c=>(
              <button key={c} onClick={()=>setCategory(c)} style={{padding:'6px 14px',borderRadius:20,fontSize:13,cursor:'pointer',fontWeight:500,textTransform:'capitalize',background:category===c?'#3b82f6':'#1e293b',color:category===c?'#fff':'#94a3b8',border:`1px solid ${category===c?'#3b82f6':'#334155'}`,transition:'all 0.15s'}}>
                {c==='all'?'All':c.replace(/_/g,' ')}
              </button>
            ))}
          </div>
          {loadErr&&<div style={{background:'rgba(248,113,113,0.1)',border:'1px solid #f87171',borderRadius:8,padding:'12px 16px',fontSize:13,color:'#f87171',marginBottom:16}}>{loadErr}</div>}
          {loading ? (
            <div style={{display:'flex',justifyContent:'center',padding:'64px 0'}}><Spinner size="lg"/></div>
          ) : !loadErr && visible.length===0 ? (
            <EmptyState icon="🔍" title="No strategies found" description="Try adjusting your search or category filters."
              action={<button onClick={()=>{setSearch('');setCategory('all');}} style={{padding:'8px 18px',background:'#3b82f6',border:'none',borderRadius:8,color:'#fff',fontSize:13,fontWeight:600,cursor:'pointer'}}>Clear filters</button>}/>
          ) : (
            <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fill,minmax(320px,1fr))',gap:16}}>
              {visible.map(s=><StrategyCard key={s.strategy_id} strategy={s} onSelect={handleSelect}/>)}
            </div>
          )}
        </>
      )}

      {mainTab==='my-listings'&&(
        <div>
          {myListings.length===0 ? (
            <EmptyState icon="📦" title="No listings yet" description="Build and publish your own AI trading strategy to the marketplace."
              action={<Link to="/ai-strategy" style={{padding:'8px 18px',background:'#3b82f6',borderRadius:8,color:'#fff',fontSize:13,fontWeight:600,textDecoration:'none',display:'inline-block'}}>🤖 Build Strategy</Link>}/>
          ) : (
            <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fill,minmax(320px,1fr))',gap:16}}>
              {myListings.map(s=><StrategyCard key={s.strategy_id} strategy={s} onSelect={handleSelect}/>)}
            </div>
          )}
        </div>
      )}

      {selected&&(
        <DetailModal
          strategy={selected} reviews={selectedReviews}
          onClose={()=>{setSelected(null);setPurchaseError(null);setReviewsErr(null);}}
          onSubscribe={handleSubscribe} subscribed={subscribed.has(selected.strategy_id)}
          purchaseError={purchaseError} reviewsErr={reviewsErr}
          onReview={()=>setShowReviewModal(true)}
        />
      )}
      {showReviewModal&&selected&&(
        <ReviewModal strategyId={selected.strategy_id} onClose={()=>setShowReviewModal(false)} onSubmitted={()=>handleSelect(selected)}/>
      )}
    </div>
  );
};

// st kept for any residual references — all new styles are inline above
void (0 as unknown as Record<string,React.CSSProperties>);

export default Marketplace;
