/**
 * Strategy Marketplace — browse, purchase, review, and manage your listings.
 * Tabs: Browse · My Listings
 */
import { PageShell } from '../components/system/PageShell';
import { Store, Bot } from 'lucide-react';
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { marketplaceApi } from '../hooks/useApi';
import { useStore, selectUser } from '../store';
import { extractApiError, fmtPctRaw } from '../lib/utils';

interface Strategy {
  strategy_id: string; name: string; description: string; creator_id: string;
  category: string; price: number; license_type: string; rating: number;
  review_count: number; subscriber_count: number; status: string; tags: string[];
  performance?: { total_return_pct?: number; sharpe_ratio?: number; max_drawdown_pct?: number; win_rate_pct?: number; };
}
interface Review { review_id: string; user_id: string; rating: number; title: string; content: string; created_at: string; }
type SortOption = 'popular'|'rating'|'newest'|'price_low'|'price_high';
type MainTab = 'browse'|'my-listings';
const CATEGORIES = ['all','trend_following','mean_reversion','smart_money','macro','breakout','swing'];


const fmt = (n: number, d = 1) => (Number.isFinite(n) ? n.toFixed(d) : '—');
const Stars: React.FC<{rating: number; size?: number}> = ({rating, size=14}) => {
  const r = Number.isFinite(rating) ? Math.max(0, Math.min(5, rating)) : 0;
  const full = Math.floor(r); const half = r - full >= 0.5;
  return <span style={{fontSize:size,lineHeight:1}}>{'★'.repeat(full)}{half ? '½' : ''}{'☆'.repeat(Math.max(0, 5-full-(half?1:0)))}</span>;
};
/**
 * `positive` defaults to true, so a caller that forgets it renders green. Every
 * return figure therefore passes it explicitly, derived from the number.
 * A strategy returning -15% used to display a green `+-15.0%`: the sign was
 * hardcoded into the string and the colour never consulted the value.
 */
const PerfBadge: React.FC<{label:string;value:string;positive?:boolean}> = ({label,value,positive}) => (
  <div style={st.perfBadge}><div style={{...st.perfValue,color:positive===false?'var(--loss)':'var(--gain)'}}>{value}</div><div style={st.perfLabel}>{label}</div></div>
);

const StrategyCard: React.FC<{strategy:Strategy;onSelect:(s:Strategy)=>void}> = ({strategy,onSelect}) => {
  const p = strategy.performance;
  return (
    <div style={st.card} onClick={()=>onSelect(strategy)}>
      <div style={st.cardTop}>
        <div style={st.cardMeta}><span style={st.categoryTag}>{strategy.category.replace('_',' ')}</span>{strategy.tags.slice(0,2).map(t=><span key={t} style={st.tag}>{t}</span>)}</div>
        <div style={st.priceTag}>{strategy.price===0?<span style={{color:'var(--gain)',fontWeight:700}}>Free</span>:<span style={{color:'var(--text-strong)',fontWeight:700}}>${strategy.price}<span style={{color:'var(--text-muted)',fontWeight:400,fontSize: 'var(--fs-body)'}}>/mo</span></span>}</div>
      </div>
      <h3 style={st.cardTitle}>{strategy.name}</h3>
      <p style={st.cardDesc}>{strategy.description}</p>
      {p&&<div style={st.perfRow}>{p.total_return_pct!=null&&<PerfBadge label="Return" value={fmtPctRaw(p.total_return_pct, 1)} positive={p.total_return_pct>=0}/>}{p.sharpe_ratio!=null&&<PerfBadge label="Sharpe" value={fmt(p.sharpe_ratio)} positive={p.sharpe_ratio>=0}/>}{p.max_drawdown_pct!=null&&<PerfBadge label="Max DD" value={`-${fmt(Math.abs(p.max_drawdown_pct))}%`} positive={false}/>}{p.win_rate_pct!=null&&<PerfBadge label="Win rate" value={`${fmt(p.win_rate_pct,0)}%`}/>}</div>}
      <div style={st.cardFooter}><div style={{display:'flex',alignItems:'center',gap:6}}><Stars rating={strategy.rating}/><span style={{fontSize: 'var(--fs-body)',color:'var(--text-dim)'}}>{fmt(strategy.rating)} ({strategy.review_count})</span></div><span style={{fontSize: 'var(--fs-body)',color:'var(--text-muted)'}}>{strategy.subscriber_count} subscribers</span></div>
    </div>
  );
};

const ReviewModal: React.FC<{strategyId:string;onClose:()=>void;onSubmitted:()=>void}> = ({strategyId,onClose,onSubmitted}) => {
  const [rating,setRating]=useState(5); const [title,setTitle]=useState(''); const [content,setContent]=useState(''); const [submitting,setSubmitting]=useState(false); const [err,setErr]=useState('');
  const submit=async()=>{
    if(!title.trim()||!content.trim()){setErr('Title and content are required.');return;}
    setSubmitting(true);
    try{ await marketplaceApi.review(strategyId,{rating,title,content}); onSubmitted(); onClose(); }
    catch(e){setErr(extractApiError(e,'Failed to submit review.'));}
    finally{setSubmitting(false);}
  };
  return(
    <div style={st.overlay} onClick={onClose}>
      <div style={{...st.modal,maxWidth:480}} onClick={e=>e.stopPropagation()}>
        <button onClick={onClose} style={st.closeBtn}>✕</button>
        <h2 style={{fontSize:18,fontWeight:700,color:'var(--text-strong)',marginBottom:16}}>Write a Review</h2>
        <label style={st.label}>Rating</label>
        <div style={{display:'flex',gap:6,marginBottom:12}}>{[1,2,3,4,5].map(n=><button key={n} onClick={()=>setRating(n)} style={{background:'transparent',border:'none',cursor:'pointer',fontSize:24,color:n<=rating?'#f59e0b':'var(--text-faint)'}}>★</button>)}</div>
        <label style={st.label}>Title</label>
        <input aria-label="Summary of your experience" value={title} onChange={e=>setTitle(e.target.value)} style={st.input} placeholder="Summary of your experience"/>
        <label style={{...st.label,marginTop:10}}>Review</label>
        <textarea aria-label="Describe your experience with this strategy" value={content} onChange={e=>setContent(e.target.value)} style={st.textarea} rows={4} placeholder="Describe your experience with this strategy…"/>
        {err&&<div style={st.purchaseError}>{err}</div>}
        <button onClick={submit} disabled={submitting} style={{...st.subscribeBtn,marginTop:12,opacity:submitting?0.6:1}}>{submitting?'Submitting…':'Submit Review'}</button>
      </div>
    </div>
  );
};

const DetailModal: React.FC<{strategy:Strategy;reviews:Review[];onClose:()=>void;onSubscribe:(s:Strategy)=>void;subscribed:boolean;purchaseError:string|null;reviewsErr:string|null;onReview:()=>void}> = ({strategy,reviews,onClose,onSubscribe,subscribed,purchaseError,reviewsErr,onReview}) => {
  const p=strategy.performance;
  return(
    <div style={st.overlay} onClick={onClose}>
      <div style={st.modal} onClick={e=>e.stopPropagation()}>
        <button onClick={onClose} style={st.closeBtn}>✕</button>
        <div style={st.modalHeader}>
          <div><div style={{display:'flex',gap:8,marginBottom:8}}><span style={st.categoryTag}>{strategy.category.replace('_',' ')}</span>{strategy.tags.map(t=><span key={t} style={st.tag}>{t}</span>)}</div><h2 style={st.modalTitle}>{strategy.name}</h2><div style={{display:'flex',alignItems:'center',gap:8,marginTop:6}}><Stars rating={strategy.rating} size={16}/><span style={{color:'var(--text-dim)',fontSize:14}}>{fmt(strategy.rating)} · {strategy.review_count} reviews · {strategy.subscriber_count} subscribers</span></div></div>
          <div style={st.modalPrice}>{strategy.price===0?<span style={{color:'var(--gain)',fontSize: 'var(--fs-hero)',fontWeight:800}}>Free</span>:<><span style={{fontSize:32,fontWeight:800,color:'var(--text-strong)'}}>${strategy.price}</span><span style={{color:'var(--text-muted)',fontSize:14}}>/{strategy.license_type==='one_time'?'one-time':'mo'}</span></>}</div>
        </div>
        <p style={{color:'var(--text-dim)',fontSize: 'var(--fs-value)',lineHeight:1.7,marginBottom:20}}>{strategy.description}</p>
        {p&&<div style={{...st.perfRow,marginBottom:24}}>{p.total_return_pct!=null&&<PerfBadge label="Total return" value={fmtPctRaw(p.total_return_pct, 1)} positive={p.total_return_pct>=0}/>}{p.sharpe_ratio!=null&&<PerfBadge label="Sharpe ratio" value={fmt(p.sharpe_ratio)} positive={p.sharpe_ratio>=0}/>}{p.max_drawdown_pct!=null&&<PerfBadge label="Max drawdown" value={`-${fmt(Math.abs(p.max_drawdown_pct))}%`} positive={false}/>}{p.win_rate_pct!=null&&<PerfBadge label="Win rate" value={`${fmt(p.win_rate_pct,0)}%`}/>}</div>}
        <div style={{display:'flex',gap:10,marginBottom:16}}>
          <button onClick={()=>onSubscribe(strategy)} disabled={subscribed} style={{...st.subscribeBtn,flex:1,opacity:subscribed?0.6:1}}>{subscribed?'✅ Subscribed':strategy.price===0?'Add to my strategies':`Subscribe — $${strategy.price}/${strategy.license_type==='one_time'?'one-time':'mo'}`}</button>
          {subscribed&&<button onClick={onReview} style={{...st.subscribeBtn,background:'var(--surface-hover)',flex:'0 0 auto',padding:'14px 16px'}}>✍ Review</button>}
        </div>
        {purchaseError&&<div style={st.purchaseError}>{purchaseError}</div>}
        {reviewsErr&&<div style={{...st.purchaseError,marginTop:12}}>{reviewsErr}</div>}
        {reviews.length>0&&<div style={{marginTop:28}}><h3 style={st.reviewsTitle}>Reviews</h3>{reviews.map(r=><div key={r.review_id} style={st.reviewCard}><div style={st.reviewHeader}><Stars rating={r.rating}/><strong style={{color:'var(--text)',marginLeft:8}}>{r.title}</strong><span style={{color:'var(--text-faint)',fontSize: 'var(--fs-body)',marginLeft:'auto'}}>{new Date(r.created_at).toLocaleDateString()}</span></div><p style={{color:'var(--text-dim)',fontSize:14,margin:'6px 0 0'}}>{r.content}</p></div>)}</div>}
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
      const res = await marketplaceApi.strategies(params) as {data:{strategies:Strategy[];total:number}};
      if (!mountedRef.current) return;
      setStrategies(res.data.strategies ?? []);
    } catch (err) {
      if (!mountedRef.current) return;
      if ((err as {name?:string}).name === 'CanceledError') return;
      setStrategies([]); setLoadErr(extractApiError(err,'Failed to load strategies.'));
    } finally { if (mountedRef.current) setLoading(false); }
  }, [category, sortBy, search]);

  const loadMyListings = useCallback(async () => {
    if (!currentUser?.id) return;
    try {
      const res = await marketplaceApi.myStrategies(currentUser.id) as {data:{strategies?:Strategy[]}|Strategy[]};
      if (!mountedRef.current) return;
      const d = res.data;
      setMyListings(Array.isArray(d) ? d : (d.strategies ?? []));
    } catch {
      if (!mountedRef.current) return;
      setMyListings([]);
    }
  }, [currentUser?.id]);

  useEffect(() => { loadStrategies(); }, [loadStrategies]);
  useEffect(() => { if (mainTab === 'my-listings') loadMyListings(); }, [mainTab, loadMyListings]);
  // Hydrate the "✅ Subscribed" markers from the user's existing subscriptions
  // so they reflect server state on load rather than resetting each refresh.
  useEffect(() => {
    let mounted = true;
    marketplaceApi.mySubscriptions().then(r => {
      if (!mounted) return;
      const d = (r as { data: unknown }).data;
      const rows: Array<Record<string, unknown>> = Array.isArray(d)
        ? d as Array<Record<string, unknown>>
        : ((d as { subscriptions?: Array<Record<string, unknown>> })?.subscriptions ?? []);
      const ids = rows
        .map(row => String(row.strategy_id ?? row.id ?? ''))
        .filter(Boolean);
      if (ids.length) setSubscribed(prev => new Set([...prev, ...ids]));
    }).catch(() => {});
    return () => { mounted = false; };
  }, []);
  useEffect(() => {
    let mounted = true;
    marketplaceApi.stats().then(r => {
      if (!mounted) return;
      const d = (r as {data:{total_strategies:number;total_subscribers:number}}).data;
      if (d?.total_strategies != null) setStats(d);
    }).catch(() => {});
    return () => { mounted = false; };
  }, []);

  const handleSelect = async (s: Strategy) => {
    setSelected(s); setReviewsErr(null);
    try {
      const res = await marketplaceApi.strategy(s.strategy_id) as {data:{strategy:Strategy;reviews:Review[]}};
      setSelectedReviews(res.data.reviews ?? []);
    } catch (err) { setSelectedReviews([]); setReviewsErr(extractApiError(err,'Failed to load reviews.')); }
  };

  const handleSubscribe = async (s: Strategy) => {
    setPurchaseError(null);
    try {
      // The server takes the buyer from the session; sending an id here was an IDOR.
      await marketplaceApi.purchase({ strategy_id: s.strategy_id });
      setSubscribed(prev => new Set([...prev, s.strategy_id]));
    } catch (err) { setPurchaseError(extractApiError(err,'Purchase failed. Check your payment method.')); }
  };

  const visible = strategies.filter(s => {
    const q = search.toLowerCase();
    if (q && !s.name.toLowerCase().includes(q) && !s.description.toLowerCase().includes(q) && !s.tags.some(t=>t.includes(q))) return false;
    if (category !== 'all' && s.category !== category) return false;
    return true;
  });

  return (
    <PageShell
      width="wide"
      title="Strategy Marketplace"
      icon={Store}
      /* Conditional, so it stays a node rather than becoming a string: the
         counts are absent until the stats request returns, and "0 strategies"
         before it lands is a measurement nobody made. */
      badge={stats ? (
        <span style={st.statsLine}>
          {stats.total_strategies ?? 0} strategies · {(stats.total_subscribers ?? 0).toLocaleString()} subscribers
        </span>
      ) : undefined}
      actions={
        <button
          onClick={() => navigate('/ai-strategy')}
          style={{ background:'rgba(167,139,250,0.12)', border:'1px solid rgba(167,139,250,0.35)', borderRadius:8, color:'var(--ai-model)', fontSize: 'var(--fs-body)', fontWeight:700, padding:'8px 18px', cursor:'pointer', display:'inline-flex', alignItems:'center', gap:6 }}
        >
          <Bot size={14} aria-hidden />
          Build Your Own Strategy
        </button>
      }
    >

      <div style={{display:'flex',gap:4,marginBottom:20,borderBottom:'1px solid var(--border)'}}>
        {(['browse','my-listings'] as MainTab[]).map(tab=>(
          <button key={tab} onClick={()=>setMainTab(tab)} style={{padding:'10px 20px',background:'transparent',border:'none',color:mainTab===tab?'#3b82f6':'var(--text-muted)',fontSize:14,cursor:'pointer',borderBottom:`2px solid ${mainTab===tab?'#3b82f6':'transparent'}`,fontWeight:500}}>
            {tab==='browse'?'Browse':'My Listings'}
          </button>
        ))}
      </div>

      {mainTab==='browse'&&(
        <>
          <div style={st.filterBar}>
            <input aria-label="Search strategies" type="search" placeholder="Search strategies…" value={search} onChange={e=>setSearch(e.target.value)} style={st.searchInput}/>
            <select aria-label="Sort strategies" value={sortBy} onChange={e=>setSortBy(e.target.value as SortOption)} style={st.select}><option value="popular">Most popular</option><option value="rating">Highest rated</option><option value="newest">Newest</option><option value="price_low">Price: low → high</option><option value="price_high">Price: high → low</option></select>
          </div>
          <div style={st.categoryRow}>{CATEGORIES.map(c=><button key={c} onClick={()=>setCategory(c)} style={{...st.categoryPill,background:category===c?'#3b82f6':'var(--raised)',color:category===c?'#fff':'var(--text-dim)',border:`1px solid ${category===c?'#3b82f6':'#334155'}`}}>{c==='all'?'All':c.replace('_',' ')}</button>)}</div>
          {loadErr&&<div style={st.errorBox}>{loadErr}</div>}
          {loading?<p style={{color:'var(--text-muted)',padding:'40px 0'}}>Loading strategies…</p>:!loadErr&&visible.length===0?(<div style={{padding:'40px 0',textAlign:'center',display:'flex',flexDirection:'column',alignItems:'center',gap:12}}><div style={{fontSize:36}}>🛒</div><p style={{color:'var(--text-dim)',fontSize: 'var(--fs-value)',fontWeight:600,margin:0}}>No strategies match your filters.</p><p style={{color:'var(--text-muted)',fontSize: 'var(--fs-body)',margin:0}}>Try clearing your filters or browse all categories.</p><button onClick={()=>{setSearch('');setCategory('all');}} style={{padding:'7px 18px',background:'rgba(59,130,246,0.15)',border:'1px solid rgba(59,130,246,0.4)',borderRadius:8,color:'var(--link)',fontSize: 'var(--fs-body)',fontWeight:700,cursor:'pointer',marginTop:4}}>Clear Filters</button></div>):(
            <div style={st.grid}>{visible.map(s=><StrategyCard key={s.strategy_id} strategy={s} onSelect={handleSelect}/>)}</div>
          )}
        </>
      )}

      {mainTab==='my-listings'&&(
        <div>
          {myListings.length===0?<p style={{color:'var(--text-muted)',padding:'40px 0'}}>You haven't listed any strategies yet.</p>:(
            <div style={st.grid}>{myListings.map(s=><StrategyCard key={s.strategy_id} strategy={s} onSelect={handleSelect}/>)}</div>
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
    </PageShell>
  );
};

const st: Record<string,React.CSSProperties> = {
  page:{maxWidth:1100,margin:'0 auto',padding:'32px 16px',fontFamily:'system-ui,-apple-system,sans-serif',color:'var(--text-strong)',background:'var(--surface)',minHeight:'100vh'},
  pageHeader:{marginBottom:24,display:'flex',justifyContent:'space-between',alignItems:'flex-start'},heading:{fontSize: 'var(--fs-hero)',fontWeight:700,color:'var(--text-strong)',marginBottom:4},
  statsLine:{color:'var(--text-muted)',fontSize:14,margin:0},
  filterBar:{display:'flex',gap:12,marginBottom:16},
  searchInput:{flex:1,padding:'10px 14px',background:'var(--raised)',border:'1px solid var(--border-strong)',borderRadius:8,color:'var(--text-strong)',fontSize:14,outline:'none'},
  select:{padding:'10px 14px',background:'var(--raised)',border:'1px solid var(--border-strong)',borderRadius:8,color:'var(--text-strong)',fontSize:14,cursor:'pointer'},
  categoryRow:{display:'flex',gap:8,flexWrap:'wrap',marginBottom:24},
  categoryPill:{padding:'6px 14px',borderRadius:20,fontSize: 'var(--fs-body)',cursor:'pointer',fontWeight:500,textTransform:'capitalize'},
  grid:{display:'grid',gridTemplateColumns:'repeat(auto-fill,minmax(320px,1fr))',gap:16},
  card:{background:'var(--raised)',border:'1px solid var(--border-strong)',borderRadius:12,padding:20,cursor:'pointer'},
  cardTop:{display:'flex',justifyContent:'space-between',alignItems:'flex-start',marginBottom:10},
  cardMeta:{display:'flex',gap:6,flexWrap:'wrap'},
  categoryTag:{fontSize: 'var(--fs-label)',fontWeight:600,padding:'2px 8px',borderRadius:4,background:'#1e3a5f',color:'var(--link)',textTransform:'capitalize'},
  tag:{fontSize: 'var(--fs-label)',padding:'2px 8px',borderRadius:4,background:'var(--raised)',color:'var(--text-muted)',border:'1px solid var(--border-strong)'},
  priceTag:{fontSize: 'var(--fs-value)',whiteSpace:'nowrap'},
  cardTitle:{fontSize:16,fontWeight:700,color:'var(--text-strong)',margin:'0 0 8px'},
  cardDesc:{fontSize: 'var(--fs-body)',color:'var(--text-dim)',lineHeight:1.6,margin:'0 0 14px',display:'-webkit-box',WebkitLineClamp:2,WebkitBoxOrient:'vertical',overflow:'hidden'},
  perfRow:{display:'flex',gap:8,flexWrap:'wrap',marginBottom:14},
  perfBadge:{background:'var(--surface)',border:'1px solid var(--border-strong)',borderRadius:6,padding:'6px 10px',textAlign:'center',minWidth:64},
  perfValue:{fontSize:14,fontWeight:700},perfLabel:{fontSize: 'var(--fs-micro)',color:'var(--text-muted)',textTransform:'uppercase',letterSpacing:0.3},
  cardFooter:{display:'flex',justifyContent:'space-between',alignItems:'center'},
  overlay:{position:'fixed',inset:0,background:'rgba(0,0,0,0.7)',display:'flex',alignItems:'center',justifyContent:'center',zIndex:1000,padding:16},
  modal:{background:'var(--raised)',border:'1px solid var(--border-strong)',borderRadius:14,padding:'28px',maxWidth:680,width:'100%',maxHeight:'90vh',overflowY:'auto',position:'relative'},
  closeBtn:{position:'absolute',top:16,right:16,background:'transparent',border:'none',color:'var(--text-muted)',fontSize:18,cursor:'pointer'},
  modalHeader:{display:'flex',justifyContent:'space-between',alignItems:'flex-start',marginBottom:16},
  modalTitle:{fontSize:22,fontWeight:700,color:'var(--text-strong)',margin:0},
  modalPrice:{textAlign:'right',flexShrink:0,marginLeft:16},
  subscribeBtn:{width:'100%',padding:14,background:'#3b82f6',color:'#fff',border:'none',borderRadius:8,fontSize: 'var(--fs-value)',fontWeight:600,cursor:'pointer'},
  purchaseError:{background:'rgba(248,113,113,0.1)',border:'1px solid var(--loss)',borderRadius:6,padding:'8px 12px',marginTop:10,fontSize: 'var(--fs-body)',color:'var(--loss)'},
  errorBox:{background:'rgba(248,113,113,0.1)',border:'1px solid var(--loss)',borderRadius:8,padding:'10px 14px',marginBottom:16,fontSize: 'var(--fs-body)',color:'var(--loss)'},
  reviewsTitle:{fontSize:16,fontWeight:600,color:'var(--text)',marginBottom:12},
  reviewCard:{background:'var(--surface)',border:'1px solid var(--border)',borderRadius:8,padding:'12px 14px',marginBottom:10},
  reviewHeader:{display:'flex',alignItems:'center'},
  label:{display:'block',fontSize: 'var(--fs-body)',color:'var(--text-dim)',marginBottom:6},
  input:{width:'100%',background:'var(--surface)',border:'1px solid var(--border-strong)',borderRadius:8,color:'var(--text-strong)',padding:'9px 12px',fontSize:14,outline:'none',boxSizing:'border-box'},
  textarea:{width:'100%',background:'var(--surface)',border:'1px solid var(--border-strong)',borderRadius:8,color:'var(--text-strong)',padding:'9px 12px',fontSize:14,outline:'none',boxSizing:'border-box',resize:'vertical',fontFamily:'inherit'},
};

export default Marketplace;
