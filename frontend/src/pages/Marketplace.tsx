import React, { useState, useEffect, useCallback } from 'react';
import { marketplaceApi } from '../hooks/useApi';
import { useStore, selectUser } from '../store';

// ── Types ─────────────────────────────────────────────────────────────────────

interface Strategy {
  strategy_id: string;
  name: string;
  description: string;
  creator_id: string;
  category: string;
  price: number;
  license_type: string;
  rating: number;
  review_count: number;
  subscriber_count: number;
  status: string;
  tags: string[];
  performance?: {
    total_return_pct?: number;
    sharpe_ratio?: number;
    max_drawdown_pct?: number;
    win_rate_pct?: number;
  };
}

interface Review {
  review_id: string;
  user_id: string;
  rating: number;
  title: string;
  content: string;
  created_at: string;
}

type SortOption = 'popular' | 'rating' | 'newest' | 'price_low' | 'price_high';

const CATEGORIES = ['all', 'trend_following', 'mean_reversion', 'smart_money', 'macro', 'breakout', 'swing'];

// ── Helpers ───────────────────────────────────────────────────────────────────

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

const fmt = (n: number, d = 1) => n.toFixed(d);

const Stars: React.FC<{ rating: number; size?: number }> = ({ rating, size = 14 }) => {
  const full = Math.floor(rating);
  const half = rating - full >= 0.5;
  return (
    <span style={{ fontSize: size, lineHeight: 1 }}>
      {'★'.repeat(full)}
      {half ? '½' : ''}
      {'☆'.repeat(5 - full - (half ? 1 : 0))}
    </span>
  );
};

const PerfBadge: React.FC<{ label: string; value: string; positive?: boolean }> = ({ label, value, positive }) => (
  <div style={styles.perfBadge}>
    <div style={{ ...styles.perfValue, color: positive === false ? '#f87171' : '#4ade80' }}>{value}</div>
    <div style={styles.perfLabel}>{label}</div>
  </div>
);

// ── Strategy Card ─────────────────────────────────────────────────────────────

const StrategyCard: React.FC<{ strategy: Strategy; onSelect: (s: Strategy) => void }> = ({ strategy, onSelect }) => {
  const p = strategy.performance;
  return (
    <div style={styles.card} onClick={() => onSelect(strategy)}>
      <div style={styles.cardTop}>
        <div style={styles.cardMeta}>
          <span style={styles.categoryTag}>{strategy.category.replace('_', ' ')}</span>
          {strategy.tags.slice(0, 2).map(t => (
            <span key={t} style={styles.tag}>{t}</span>
          ))}
        </div>
        <div style={styles.priceTag}>
          {strategy.price === 0 ? (
            <span style={{ color: '#4ade80', fontWeight: 700 }}>Free</span>
          ) : (
            <span style={{ color: '#f8fafc', fontWeight: 700 }}>${strategy.price}<span style={{ color: '#64748b', fontWeight: 400, fontSize: 12 }}>/mo</span></span>
          )}
        </div>
      </div>

      <h3 style={styles.cardTitle}>{strategy.name}</h3>
      <p style={styles.cardDesc}>{strategy.description}</p>

      {p && (
        <div style={styles.perfRow}>
          {p.total_return_pct != null && <PerfBadge label="Return" value={`+${fmt(p.total_return_pct)}%`} />}
          {p.sharpe_ratio != null && <PerfBadge label="Sharpe" value={fmt(p.sharpe_ratio)} />}
          {p.max_drawdown_pct != null && <PerfBadge label="Max DD" value={`-${fmt(p.max_drawdown_pct)}%`} positive={false} />}
          {p.win_rate_pct != null && <PerfBadge label="Win rate" value={`${fmt(p.win_rate_pct, 0)}%`} />}
        </div>
      )}

      <div style={styles.cardFooter}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <Stars rating={strategy.rating} />
          <span style={{ fontSize: 13, color: '#94a3b8' }}>{fmt(strategy.rating)} ({strategy.review_count})</span>
        </div>
        <span style={{ fontSize: 12, color: '#64748b' }}>{strategy.subscriber_count} subscribers</span>
      </div>
    </div>
  );
};

// ── Detail Modal ──────────────────────────────────────────────────────────────

const StrategyDetail: React.FC<{
  strategy: Strategy;
  reviews: Review[];
  onClose: () => void;
  onSubscribe: (s: Strategy) => void;
  subscribed: boolean;
  purchaseError: string | null;
  reviewsErr: string | null;
}> = ({ strategy, reviews, onClose, onSubscribe, subscribed, purchaseError, reviewsErr }) => {
  const p = strategy.performance;
  return (
    <div style={styles.overlay} onClick={onClose}>
      <div style={styles.modal} onClick={e => e.stopPropagation()}>
        <button onClick={onClose} style={styles.closeBtn}>✕</button>

        <div style={styles.modalHeader}>
          <div>
            <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
              <span style={styles.categoryTag}>{strategy.category.replace('_', ' ')}</span>
              {strategy.tags.map(t => <span key={t} style={styles.tag}>{t}</span>)}
            </div>
            <h2 style={styles.modalTitle}>{strategy.name}</h2>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 6 }}>
              <Stars rating={strategy.rating} size={16} />
              <span style={{ color: '#94a3b8', fontSize: 14 }}>{fmt(strategy.rating)} · {strategy.review_count} reviews · {strategy.subscriber_count} subscribers</span>
            </div>
          </div>
          <div style={styles.modalPrice}>
            {strategy.price === 0 ? (
              <span style={{ color: '#4ade80', fontSize: 28, fontWeight: 800 }}>Free</span>
            ) : (
              <>
                <span style={{ fontSize: 32, fontWeight: 800, color: '#f8fafc' }}>${strategy.price}</span>
                <span style={{ color: '#64748b', fontSize: 14 }}>/{strategy.license_type === 'one_time' ? 'one-time' : 'mo'}</span>
              </>
            )}
          </div>
        </div>

        <p style={{ color: '#94a3b8', fontSize: 15, lineHeight: 1.7, marginBottom: 20 }}>{strategy.description}</p>

        {p && (
          <div style={{ ...styles.perfRow, marginBottom: 24 }}>
            {p.total_return_pct != null && <PerfBadge label="Total return" value={`+${fmt(p.total_return_pct)}%`} />}
            {p.sharpe_ratio != null && <PerfBadge label="Sharpe ratio" value={fmt(p.sharpe_ratio)} />}
            {p.max_drawdown_pct != null && <PerfBadge label="Max drawdown" value={`-${fmt(p.max_drawdown_pct)}%`} positive={false} />}
            {p.win_rate_pct != null && <PerfBadge label="Win rate" value={`${fmt(p.win_rate_pct, 0)}%`} />}
          </div>
        )}

        <button
          onClick={() => onSubscribe(strategy)}
          disabled={subscribed}
          style={{ ...styles.subscribeBtn, opacity: subscribed ? 0.6 : 1 }}
        >
          {subscribed ? '✅ Subscribed' : strategy.price === 0 ? 'Add to my strategies' : `Subscribe — $${strategy.price}/${strategy.license_type === 'one_time' ? 'one-time' : 'mo'}`}
        </button>
        {purchaseError && (
          <div style={styles.purchaseError}>{purchaseError}</div>
        )}

        {reviewsErr && <div style={{ ...styles.purchaseError, marginTop: 12 }}>{reviewsErr}</div>}
        {reviews.length > 0 && (
          <div style={{ marginTop: 28 }}>
            <h3 style={styles.reviewsTitle}>Reviews</h3>
            {reviews.map(r => (
              <div key={r.review_id} style={styles.reviewCard}>
                <div style={styles.reviewHeader}>
                  <Stars rating={r.rating} />
                  <strong style={{ color: '#e2e8f0', marginLeft: 8 }}>{r.title}</strong>
                  <span style={{ color: '#475569', fontSize: 12, marginLeft: 'auto' }}>
                    {new Date(r.created_at).toLocaleDateString()}
                  </span>
                </div>
                <p style={{ color: '#94a3b8', fontSize: 14, margin: '6px 0 0' }}>{r.content}</p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

// ── Main component ────────────────────────────────────────────────────────────

const Marketplace: React.FC = () => {
  const currentUser = useStore(selectUser);
  const [strategies, setStrategies]   = useState<Strategy[]>([]);
  const [loading, setLoading]         = useState(true);
  const [loadErr, setLoadErr]         = useState<string | null>(null);
  const [reviewsErr, setReviewsErr]   = useState<string | null>(null);
  const [search, setSearch]           = useState('');
  const [category, setCategory]       = useState('all');
  const [sortBy, setSortBy]           = useState<SortOption>('popular');
  const [selected, setSelected]       = useState<Strategy | null>(null);
  const [selectedReviews, setSelectedReviews] = useState<Review[]>([]);
  const [subscribed, setSubscribed] = useState<Set<string>>(new Set());
  const [purchaseError, setPurchaseError] = useState<string | null>(null);
  const [stats, setStats] = useState<{ total_strategies: number; total_subscribers: number } | null>(null);

  const loadStrategies = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string> = { sort_by: sortBy, limit: '50' };
      if (category !== 'all') params.category = category;
      if (search) params.query = search;
      const res = await marketplaceApi.strategies(params) as { data: { strategies: Strategy[]; total: number } };
      setStrategies(res.data.strategies ?? []);
    } catch (err) {
      setStrategies([]);
      setLoadErr(extractErrorMessage(err, 'Failed to load strategies. Check your connection.'));
    } finally {
      setLoading(false);
    }
  }, [category, sortBy, search]);

  useEffect(() => { loadStrategies(); }, [loadStrategies]);

  useEffect(() => {
    marketplaceApi.stats()
      .then((r) => {
        const d = (r as { data: { total_strategies: number; total_subscribers: number } }).data;
        if (d && typeof d.total_strategies === 'number' && typeof d.total_subscribers === 'number') {
          setStats(d);
        }
      })
      .catch((err: unknown) => {
        console.warn('[Marketplace] Failed to load marketplace stats:', err);
        setStats(null);
      });
  }, []);

  const handleSelect = async (s: Strategy) => {
    setSelected(s);
    setReviewsErr(null);
    try {
      const res = await marketplaceApi.strategy(s.strategy_id) as { data: { strategy: Strategy; reviews: Review[] } };
      setSelectedReviews(res.data.reviews ?? []);
    } catch (err) {
      setSelectedReviews([]);
      setReviewsErr(extractErrorMessage(err, 'Failed to load reviews.'));
    }
  };

  const handleSubscribe = async (s: Strategy) => {
    setPurchaseError(null);
    try {
      await marketplaceApi.purchase({
        buyer_id: currentUser?.id ?? '',
        strategy_id: s.strategy_id,
      });
      setSubscribed(prev => new Set([...prev, s.strategy_id]));
    } catch (err) {
      setPurchaseError(extractErrorMessage(err, 'Purchase failed. Check your payment method and try again.'));
    }
  };

  // Client-side filter for instant search feedback
  const visible = strategies.filter(s => {
    const q = search.toLowerCase();
    if (q && !s.name.toLowerCase().includes(q) && !s.description.toLowerCase().includes(q) && !s.tags.some(t => t.includes(q))) return false;
    if (category !== 'all' && s.category !== category) return false;
    return true;
  });

  return (
    <div style={styles.page}>
      {/* Header */}
      <div style={styles.pageHeader}>
        <div>
          <h1 style={styles.heading}>Strategy Marketplace</h1>
          {stats && (
            <p style={styles.statsLine}>
              {stats.total_strategies} strategies · {stats.total_subscribers.toLocaleString()} subscribers
            </p>
          )}
        </div>
      </div>

      {/* Search + filters */}
      <div style={styles.filterBar}>
        <input
          type="search"
          placeholder="Search strategies…"
          value={search}
          onChange={e => setSearch(e.target.value)}
          style={styles.searchInput}
        />
        <select value={sortBy} onChange={e => setSortBy(e.target.value as SortOption)} style={styles.select}>
          <option value="popular">Most popular</option>
          <option value="rating">Highest rated</option>
          <option value="newest">Newest</option>
          <option value="price_low">Price: low → high</option>
          <option value="price_high">Price: high → low</option>
        </select>
      </div>

      {/* Category pills */}
      <div style={styles.categoryRow}>
        {CATEGORIES.map(c => (
          <button
            key={c}
            onClick={() => setCategory(c)}
            style={{
              ...styles.categoryPill,
              background: category === c ? '#3b82f6' : '#1e293b',
              color: category === c ? '#fff' : '#94a3b8',
              border: `1px solid ${category === c ? '#3b82f6' : '#334155'}`,
            }}
          >
            {c === 'all' ? 'All' : c.replace('_', ' ')}
          </button>
        ))}
      </div>

      {/* Grid */}
      {loadErr && <div style={styles.errorBox}>{loadErr}</div>}
      {loading ? (
        <p style={{ color: '#64748b', padding: '40px 0' }}>Loading strategies…</p>
      ) : !loadErr && visible.length === 0 ? (
        <p style={{ color: '#64748b', padding: '40px 0' }}>No strategies match your filters.</p>
      ) : (
        <div style={styles.grid}>
          {visible.map(s => (
            <StrategyCard key={s.strategy_id} strategy={s} onSelect={handleSelect} />
          ))}
        </div>
      )}

      {/* Detail modal */}
      {selected && (
        <StrategyDetail
          strategy={selected}
          reviews={selectedReviews}
          onClose={() => { setSelected(null); setPurchaseError(null); setReviewsErr(null); }}
          onSubscribe={handleSubscribe}
          subscribed={subscribed.has(selected.strategy_id)}
          purchaseError={purchaseError}
          reviewsErr={reviewsErr}
        />
      )}
    </div>
  );
};

// ── Styles ────────────────────────────────────────────────────────────────────

const styles: Record<string, React.CSSProperties> = {
  page: {
    maxWidth: 1100,
    margin: '0 auto',
    padding: '32px 16px',
    fontFamily: 'system-ui, -apple-system, sans-serif',
    color: '#f1f5f9',
    background: '#0f172a',
    minHeight: '100vh',
  },
  pageHeader: { marginBottom: 24 },
  heading: { fontSize: 28, fontWeight: 700, color: '#f8fafc', marginBottom: 4 },
  statsLine: { color: '#64748b', fontSize: 14, margin: 0 },
  filterBar: { display: 'flex', gap: 12, marginBottom: 16 },
  searchInput: {
    flex: 1, padding: '10px 14px', background: '#1e293b',
    border: '1px solid #334155', borderRadius: 8, color: '#f1f5f9', fontSize: 14, outline: 'none',
  },
  select: {
    padding: '10px 14px', background: '#1e293b', border: '1px solid #334155',
    borderRadius: 8, color: '#f1f5f9', fontSize: 14, cursor: 'pointer',
  },
  categoryRow: { display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 24 },
  categoryPill: {
    padding: '6px 14px', border: '1px solid #334155', borderRadius: 20,
    fontSize: 13, cursor: 'pointer', fontWeight: 500, textTransform: 'capitalize',
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
    gap: 16,
  },
  card: {
    background: '#1e293b', border: '1px solid #334155', borderRadius: 12,
    padding: '20px', cursor: 'pointer', transition: 'border-color 0.15s',
  },
  cardTop: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 },
  cardMeta: { display: 'flex', gap: 6, flexWrap: 'wrap' },
  categoryTag: {
    fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 4,
    background: '#1e3a5f', color: '#60a5fa', textTransform: 'capitalize',
  },
  tag: {
    fontSize: 11, padding: '2px 8px', borderRadius: 4,
    background: '#1e293b', color: '#64748b', border: '1px solid #334155',
  },
  priceTag: { fontSize: 15, whiteSpace: 'nowrap' },
  cardTitle: { fontSize: 16, fontWeight: 700, color: '#f8fafc', margin: '0 0 8px' },
  cardDesc: { fontSize: 13, color: '#94a3b8', lineHeight: 1.6, margin: '0 0 14px', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' },
  perfRow: { display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14 },
  perfBadge: {
    background: '#0f172a', border: '1px solid #334155', borderRadius: 6,
    padding: '6px 10px', textAlign: 'center', minWidth: 64,
  },
  perfValue: { fontSize: 14, fontWeight: 700 },
  perfLabel: { fontSize: 10, color: '#64748b', textTransform: 'uppercase', letterSpacing: 0.3 },
  cardFooter: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' },
  overlay: {
    position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    zIndex: 1000, padding: 16,
  },
  modal: {
    background: '#1e293b', border: '1px solid #334155', borderRadius: 14,
    padding: '28px 28px', maxWidth: 680, width: '100%',
    maxHeight: '90vh', overflowY: 'auto', position: 'relative',
  },
  closeBtn: {
    position: 'absolute', top: 16, right: 16,
    background: 'transparent', border: 'none', color: '#64748b',
    fontSize: 18, cursor: 'pointer',
  },
  modalHeader: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 },
  modalTitle: { fontSize: 22, fontWeight: 700, color: '#f8fafc', margin: 0 },
  modalPrice: { textAlign: 'right', flexShrink: 0, marginLeft: 16 },
  subscribeBtn: {
    width: '100%', padding: '14px', background: '#3b82f6', color: '#fff',
    border: 'none', borderRadius: 8, fontSize: 15, fontWeight: 600, cursor: 'pointer',
  },
  purchaseError: {
    background: 'rgba(248,113,113,0.1)', border: '1px solid #f87171', borderRadius: 6,
    padding: '8px 12px', marginTop: 10, fontSize: 13, color: '#f87171',
  },
  errorBox: {
    background: 'rgba(248,113,113,0.1)', border: '1px solid #f87171', borderRadius: 8,
    padding: '10px 14px', marginBottom: 16, fontSize: 13, color: '#f87171',
  },
  reviewsTitle: { fontSize: 16, fontWeight: 600, color: '#e2e8f0', marginBottom: 12 },
  reviewCard: {
    background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8,
    padding: '12px 14px', marginBottom: 10,
  },
  reviewHeader: { display: 'flex', alignItems: 'center' },
};

export default Marketplace;
