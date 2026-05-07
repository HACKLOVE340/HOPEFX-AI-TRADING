/**
 * Strategy Marketplace — browse, purchase, review, and manage your listings.
 * Tabs: Browse · My Listings
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { marketplaceApi } from '../hooks/useApi';
import { useStore, selectUser } from '../store';
import { PageHeader } from '../components/PageHeader';
import { CrossLinkBar } from '../components/CrossLinkBar';
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
  const sparkData: number[] = (strategy as unknown as { equity_curve?: number[] }).equity_curve
    ?? (p ? Array.from({ length: 12 }, (_, i) => 10000 * (1 + ((p.total_return_pct ?? 0) / 100) * (i / 11))) : []);
  return (
    <div
      onClick={()=>onSelect(strategy)}
      className="bg-terminal-surface border border-terminal-border rounded-xl p-4 sm:p-5 cursor-pointer transition-colors hover:border-blue-500/60 flex flex-col gap-3"
    >
      {/* Top row: category chips + price */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex gap-1.5 flex-wrap">
          <span className="text-2xs font-semibold px-2 py-0.5 rounded bg-blue-500/15 text-blue-400 capitalize">
            {strategy.category.replace(/_/g,' ')}
          </span>
          {strategy.tags.slice(0,2).map(t=>(
            <span key={t} className="text-2xs px-2 py-0.5 rounded bg-terminal-raised text-slate-500 border border-terminal-border">{t}</span>
          ))}
        </div>
        <div className="text-sm whitespace-nowrap flex-shrink-0">
          {strategy.price===0
            ? <span className="text-green-400 font-bold">Free</span>
            : <span className="text-slate-100 font-bold">${strategy.price}<span className="text-slate-500 font-normal text-xs">/mo</span></span>
          }
        </div>
      </div>
      {/* Name + sparkline */}
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-slate-100 text-sm sm:text-base font-bold m-0 flex-1 leading-snug">{strategy.name}</h3>
        {sparkData.length>1&&<Sparkline data={sparkData} width={64} height={24}/>}
      </div>
      {/* Description */}
      <p className="text-slate-400 text-xs sm:text-sm leading-relaxed m-0 line-clamp-2">{strategy.description}</p>
      {/* Performance badges */}
      {p&&<div className="flex gap-2 flex-wrap">
        {p.total_return_pct!=null&&<PerfBadge label="Return" value={`+${fmt(p.total_return_pct)}%`}/>}
        {p.sharpe_ratio!=null&&<PerfBadge label="Sharpe" value={fmt(p.sharpe_ratio)}/>}
        {p.max_drawdown_pct!=null&&<PerfBadge label="Max DD" value={`-${fmt(p.max_drawdown_pct)}%`} positive={false}/>}
        {p.win_rate_pct!=null&&<PerfBadge label="Win rate" value={`${fmt(p.win_rate_pct,0)}%`}/>}
      </div>}
      {/* Footer */}
      <div className="flex items-center justify-between pt-2 border-t border-terminal-border mt-auto">
        <div className="flex items-center gap-1.5">
          <Stars rating={strategy.rating}/>
          <span className="text-slate-400 text-xs">{fmt(strategy.rating)} ({strategy.review_count})</span>
        </div>
        <span className="text-slate-500 text-xs">{strategy.subscriber_count.toLocaleString()} subs</span>
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
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-modal flex items-end sm:items-center justify-center p-0 sm:p-4" onClick={onClose}>
      <div className="bg-terminal-bg border border-terminal-border rounded-t-2xl sm:rounded-xl p-5 sm:p-6 w-full sm:max-w-lg shadow-2xl" onClick={e=>e.stopPropagation()}>
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-slate-100 text-base font-bold m-0">Write a Review</h2>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-300 bg-transparent border-0 cursor-pointer text-xl leading-none p-1">✕</button>
        </div>
        <label className="block text-slate-500 text-2xs font-semibold uppercase tracking-wider mb-2">Rating</label>
        <div className="flex gap-1 mb-4">
          {[1,2,3,4,5].map(n=><button key={n} onClick={()=>setRating(n)} className="bg-transparent border-0 cursor-pointer text-2xl leading-none transition-colors p-0.5" style={{color:n<=rating?'#f59e0b':'#334155'}}>★</button>)}
        </div>
        <label className="block text-slate-500 text-2xs font-semibold uppercase tracking-wider mb-1.5">Title</label>
        <input value={title} onChange={e=>setTitle(e.target.value)}
          className="w-full bg-terminal-raised border border-terminal-border rounded-lg px-3 py-2.5 text-slate-200 text-sm outline-none focus:border-blue-500 transition-colors mb-3"
          placeholder="Summary of your experience"/>
        <label className="block text-slate-500 text-2xs font-semibold uppercase tracking-wider mb-1.5">Review</label>
        <textarea value={content} onChange={e=>setContent(e.target.value)}
          className="w-full bg-terminal-raised border border-terminal-border rounded-lg px-3 py-2.5 text-slate-200 text-sm outline-none focus:border-blue-500 transition-colors resize-y font-sans"
          rows={4} placeholder="Describe your experience with this strategy…"/>
        {err&&<div className="mt-2 text-red-400 text-xs">{err}</div>}
        <button onClick={submit} disabled={submitting}
          className="mt-4 w-full bg-blue-600 hover:bg-blue-500 text-white border-0 rounded-xl py-3 text-sm font-bold cursor-pointer transition-colors disabled:opacity-60">
          {submitting?'Submitting…':'Submit Review'}
        </button>
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
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-modal flex items-end sm:items-center justify-center p-0 sm:p-4" onClick={onClose}>
      <div className="bg-terminal-bg border border-terminal-border rounded-t-2xl sm:rounded-xl p-4 sm:p-6 w-full sm:max-w-2xl max-h-[92vh] sm:max-h-[90vh] overflow-y-auto shadow-2xl" onClick={e=>e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-start justify-between gap-3 mb-4">
          <div className="flex-1 min-w-0">
            <div className="flex gap-1.5 flex-wrap mb-2">
              <span className="text-2xs font-semibold px-2 py-0.5 rounded bg-blue-500/15 text-blue-400 capitalize">{strategy.category.replace(/_/g,' ')}</span>
              {strategy.tags.map(t=><span key={t} className="text-2xs px-2 py-0.5 rounded bg-terminal-raised text-slate-500 border border-terminal-border">{t}</span>)}
            </div>
            <h2 className="text-slate-100 text-lg sm:text-xl font-bold m-0 mb-1 leading-tight">{strategy.name}</h2>
            <div className="flex items-center gap-2 flex-wrap">
              <Stars rating={strategy.rating} size={14}/>
              <span className="text-slate-400 text-xs">{fmt(strategy.rating)} · {strategy.review_count} reviews · {strategy.subscriber_count.toLocaleString()} subs</span>
            </div>
          </div>
          <div className="text-right flex-shrink-0">
            {strategy.price===0
              ? <div className="text-green-400 text-2xl font-black">Free</div>
              : <><div className="text-slate-100 text-2xl font-black">${strategy.price}</div><div className="text-slate-500 text-xs">/{strategy.license_type==='one_time'?'one-time':'mo'}</div></>
            }
          </div>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-300 bg-transparent border-0 cursor-pointer text-xl leading-none p-1 flex-shrink-0">✕</button>
        </div>
        <p className="text-slate-400 text-sm leading-relaxed mb-4">{strategy.description}</p>
        {sparkData.length>1&&<div className="mb-4"><Sparkline data={sparkData} width={280} height={44}/></div>}
        {p&&<div className="flex gap-2 flex-wrap mb-5">
          {p.total_return_pct!=null&&<PerfBadge label="Total return" value={`+${fmt(p.total_return_pct)}%`}/>}
          {p.sharpe_ratio!=null&&<PerfBadge label="Sharpe ratio" value={fmt(p.sharpe_ratio)}/>}
          {p.max_drawdown_pct!=null&&<PerfBadge label="Max drawdown" value={`-${fmt(p.max_drawdown_pct)}%`} positive={false}/>}
          {p.win_rate_pct!=null&&<PerfBadge label="Win rate" value={`${fmt(p.win_rate_pct,0)}%`}/>}
        </div>}
        {/* Purchase confirmation */}
        {confirmOpen&&!subscribed?(
          <div className="bg-blue-500/8 border border-blue-500/35 rounded-xl p-4 mb-3">
            <div className="text-slate-100 text-sm font-semibold mb-1.5">Confirm Purchase</div>
            <div className="text-slate-400 text-xs mb-3">
              Subscribe to <strong className="text-slate-200">{strategy.name}</strong> for{' '}
              <strong className="text-blue-400">{strategy.price===0?'Free':`$${strategy.price}/${strategy.license_type==='one_time'?'one-time':'mo'}`}</strong>?
            </div>
            <div className="flex gap-2">
              <button onClick={()=>{setConfirmOpen(false);onSubscribe(strategy);}} className="flex-1 bg-blue-600 hover:bg-blue-500 text-white border-0 rounded-lg py-2.5 text-sm font-bold cursor-pointer transition-colors">✅ Confirm</button>
              <button onClick={()=>setConfirmOpen(false)} className="flex-1 bg-terminal-raised border border-terminal-border text-slate-400 rounded-lg py-2.5 text-sm cursor-pointer hover:border-slate-500 transition-colors">Cancel</button>
            </div>
          </div>
        ):(
          <div className="flex gap-2 mb-4">
            <button onClick={()=>subscribed?undefined:setConfirmOpen(true)} disabled={subscribed}
              className="flex-1 bg-blue-600 hover:bg-blue-500 text-white border-0 rounded-xl py-3 text-sm font-bold cursor-pointer transition-colors disabled:opacity-60">
              {subscribed?'✅ Subscribed':strategy.price===0?'Add to my strategies':`Subscribe — $${strategy.price}/${strategy.license_type==='one_time'?'one-time':'mo'}`}
            </button>
            {subscribed&&<button onClick={onReview} className="bg-terminal-raised border border-terminal-border text-slate-200 rounded-xl px-4 py-3 text-sm font-bold cursor-pointer hover:border-slate-500 transition-colors">✍ Review</button>}
          </div>
        )}
        {purchaseError&&<div className="bg-red-950/40 border border-red-800 rounded-lg px-4 py-3 text-red-400 text-xs mb-3">{purchaseError}</div>}
        {reviewsErr&&<div className="bg-red-950/40 border border-red-800 rounded-lg px-4 py-3 text-red-400 text-xs mb-3">{reviewsErr}</div>}
        {reviews.length>0&&(
          <div className="mt-5 pt-5 border-t border-terminal-border">
            <h3 className="text-slate-500 text-2xs font-semibold uppercase tracking-wider mb-4">Reviews</h3>
            <div className="flex flex-col gap-3">
              {reviews.map(r=>(
                <div key={r.review_id} className="bg-terminal-raised border border-terminal-border rounded-xl p-4">
                  <div className="flex items-center gap-2 flex-wrap mb-2">
                    <Stars rating={r.rating}/>
                    <strong className="text-slate-200 text-sm">{r.title}</strong>
                    <span className="text-slate-600 text-xs ml-auto">{new Date(r.created_at).toLocaleDateString()}</span>
                  </div>
                  <p className="text-slate-400 text-xs leading-relaxed m-0">{r.content}</p>
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
    <div className="max-w-6xl mx-auto px-3 sm:px-6 py-4 sm:py-8 text-slate-100 min-h-screen">
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
        badge={<span className="text-2xs font-bold px-2 py-0.5 rounded-full bg-blue-500/15 text-blue-400 border border-blue-500/30">LIVE</span>}
        actions={
          <div className="flex gap-2 flex-wrap">
            <Link to="/copy-trading" className="px-3 py-1.5 bg-emerald-500/10 border border-emerald-500/30 rounded-lg text-emerald-400 text-xs font-semibold no-underline hover:bg-emerald-500/20 transition-colors">🔁 Copy Trading</Link>
            <Link to="/signals" className="px-3 py-1.5 bg-violet-500/10 border border-violet-500/30 rounded-lg text-violet-400 text-xs font-semibold no-underline hover:bg-violet-500/20 transition-colors hidden sm:inline-flex">📡 Signals</Link>
            <Link to="/ai-strategy" className="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-bold no-underline transition-colors">🤖 Build Strategy</Link>
          </div>
        }
      />

      <CrossLinkBar links={[
        { label: 'Performance',  href: '/performance',  icon: '📊', color: '#4ade80' },
        { label: 'Leaderboard',  href: '/leaderboard',  icon: '🏆', color: '#f59e0b' },
        { label: 'Affiliate',    href: '/affiliate',    icon: '🤝', color: '#f97316' },
        { label: 'Trade Journal',href: '/journal',      icon: '📓', color: '#a78bfa' },
        { label: 'Copy Trading', href: '/copy-trading', icon: '🔁', color: '#60a5fa' },
      ]} className="mb-6" />

      {/* Tabs */}
      <div className="flex gap-0 mb-6 border-b border-terminal-border overflow-x-auto"
        style={{ scrollbarWidth: 'none' } as React.CSSProperties}>
        {(['browse','my-listings'] as MainTab[]).map(tab=>(
          <button key={tab} onClick={()=>setMainTab(tab)}
            className={`px-4 sm:px-5 py-2.5 bg-transparent border-0 text-sm cursor-pointer whitespace-nowrap transition-colors font-medium ${
              mainTab===tab ? 'text-blue-400' : 'text-slate-500 hover:text-slate-300'
            }`}
            style={{ borderBottom: mainTab===tab ? '2px solid #3b82f6' : '2px solid transparent' }}>
            {tab==='browse'?'Browse':'My Listings'}
          </button>
        ))}
      </div>

      {mainTab==='browse'&&(
        <>
          {/* Search + sort row */}
          <div className="flex gap-2 mb-4 flex-wrap sm:flex-nowrap">
            <input type="search" placeholder="Search strategies…" value={search} onChange={e=>setSearch(e.target.value)}
              className="flex-1 min-w-0 px-3 py-2.5 bg-terminal-raised border border-terminal-border rounded-lg text-slate-200 text-sm outline-none focus:border-blue-500 transition-colors placeholder-slate-600"/>
            <select value={sortBy} onChange={e=>setSortBy(e.target.value as SortOption)}
              className="px-3 py-2.5 bg-terminal-raised border border-terminal-border rounded-lg text-slate-200 text-sm cursor-pointer outline-none focus:border-blue-500 transition-colors flex-shrink-0">
              <option value="popular">Most popular</option>
              <option value="rating">Highest rated</option>
              <option value="newest">Newest</option>
              <option value="price_low">Price: low → high</option>
              <option value="price_high">Price: high → low</option>
            </select>
          </div>
          {/* Category chips — horizontal scroll on mobile */}
          <div className="flex gap-2 flex-wrap mb-6 overflow-x-auto pb-1"
            style={{ scrollbarWidth: 'none' } as React.CSSProperties}>
            {CATEGORIES.map(c=>(
              <button key={c} onClick={()=>setCategory(c)}
                className={`px-3 py-1.5 rounded-full text-xs font-medium cursor-pointer capitalize whitespace-nowrap transition-all border ${
                  category===c
                    ? 'bg-blue-600 border-blue-600 text-white'
                    : 'bg-terminal-raised border-terminal-border text-slate-400 hover:border-slate-500'
                }`}>
                {c==='all'?'All':c.replace(/_/g,' ')}
              </button>
            ))}
          </div>
          {loadErr&&<div className="bg-red-950/40 border border-red-800 rounded-lg px-4 py-3 text-red-400 text-sm mb-4">{loadErr}</div>}
          {loading ? (
            <div className="flex justify-center py-16"><Spinner size="lg"/></div>
          ) : !loadErr && visible.length===0 ? (
            <EmptyState icon="🔍" title="No strategies found" description="Try adjusting your search or category filters."
              action={<button onClick={()=>{setSearch('');setCategory('all');}} className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm font-semibold cursor-pointer border-0 transition-colors">Clear filters</button>}/>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {visible.map(s=><StrategyCard key={s.strategy_id} strategy={s} onSelect={handleSelect}/>)}
            </div>
          )}
        </>
      )}

      {mainTab==='my-listings'&&(
        <div>
          {myListings.length===0 ? (
            <EmptyState icon="📦" title="No listings yet" description="Build and publish your own AI trading strategy to the marketplace."
              action={<Link to="/ai-strategy" className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm font-semibold no-underline transition-colors">🤖 Build Strategy</Link>}/>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
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
