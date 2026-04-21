/**
 * Social Signal Feed
 *
 * Community feed of high-confidence AI signals (>= 70%).
 * Users can react (👍/👎), comment, and see copy counts.
 * Opt-in/out toggle controls whether your own signals appear.
 */

import React, { useEffect, useState, useCallback } from 'react';
import { api } from '../hooks/useApi';

// ─── Types ────────────────────────────────────────────────────────────────────

interface FeedItem {
  signal_id:    string;
  symbol:       string;
  direction:    'BUY' | 'SELL';
  confidence:   number;
  entry_price:  number;
  pnl:          number;
  copies:       number;
  username:     string;
  trader_id:    string;
  thumbs_up:    number;
  thumbs_down:  number;
  comment_count: number;
  created_at:   string;
  your_reaction?: 'up' | 'down' | null;
}

interface Comment {
  comment_id: string;
  username:   string;
  text:       string;
  created_at: string;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const fmtPnl = (n: number) =>
  (n >= 0 ? '+$' : '-$') + Math.abs(n).toFixed(2);

const timeAgo = (iso: string) => {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1)  return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
};

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

// ─── Comment panel ────────────────────────────────────────────────────────────

const CommentPanel: React.FC<{ signalId: string; onClose: () => void }> = ({
  signalId, onClose,
}) => {
  const [comments, setComments] = useState<Comment[]>([]);
  const [text, setText]         = useState('');
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    api.get(`/feed/${signalId}/comments`)
      .then((r) => setComments(r.data.comments || []))
      .catch((err) => setError(extractErrorMessage(err, 'Failed to load comments.')))
      .finally(() => setLoading(false));
  }, [signalId]);

  const submit = async () => {
    if (!text.trim()) return;
    setSubmitError(null);
    try {
      const res = await api.post(`/feed/${signalId}/comment`, { text });
      setComments((prev) => [...prev, res.data]);
      setText('');
    } catch (err) {
      setSubmitError(extractErrorMessage(err, 'Failed to post comment.'));
    }
  };

  return (
    <div style={s.commentPanel}>
      <div style={s.commentHeader}>
        <span style={{ fontWeight: 600 }}>Comments</span>
        <button style={s.closeBtn} onClick={onClose}>✕</button>
      </div>
      <div style={s.commentList}>
        {loading && <div style={s.dim}>Loading…</div>}
        {!loading && error && <div style={{ ...s.dim, color: '#f87171' }}>{error}</div>}
        {!loading && !error && comments.length === 0 && <div style={s.dim}>No comments yet. Be first!</div>}
        {comments.map((c) => (
          <div key={c.comment_id} style={s.commentItem}>
            <span style={s.commentUser}>{c.username}</span>
            <span style={s.commentText}>{c.text}</span>
            <span style={s.commentTime}>{timeAgo(c.created_at)}</span>
          </div>
        ))}
      </div>
      {submitError && (
        <div style={{ padding: '4px 16px', fontSize: 12, color: '#f87171' }}>{submitError}</div>
      )}
      <div style={s.commentInput}>
        <input
          style={s.textInput}
          placeholder="Add a comment…"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submit()}
          maxLength={500}
        />
        <button style={s.sendBtn} onClick={submit}>Send</button>
      </div>
    </div>
  );
};

// ─── Feed card ────────────────────────────────────────────────────────────────

const FeedCard: React.FC<{
  item: FeedItem;
  onReact: (id: string, r: 'up' | 'down') => void;
  onComment: (id: string) => void;
  onCopyTrade: (item: FeedItem) => void;
}> = ({ item, onReact, onComment, onCopyTrade }) => {
  const isBuy = item.direction === 'BUY';
  const pnlPos = item.pnl >= 0;

  return (
    <div style={s.card}>
      {/* Header */}
      <div style={s.cardHeader}>
        <div style={s.userInfo}>
          <div style={s.avatar}>{item.username.slice(0, 2).toUpperCase()}</div>
          <div>
            <div style={s.username}>{item.username}</div>
            <div style={s.timeAgo}>{timeAgo(item.created_at)}</div>
          </div>
        </div>
        <div style={{
          ...s.dirBadge,
          background: isBuy ? 'rgba(74,222,128,0.15)' : 'rgba(248,113,113,0.15)',
          color: isBuy ? '#4ade80' : '#f87171',
          border: `1px solid ${isBuy ? '#4ade80' : '#f87171'}`,
        }}>
          {item.direction}
        </div>
      </div>

      {/* Signal info */}
      <div style={s.signalInfo}>
        <div style={s.symbol}>{item.symbol}</div>
        <div style={s.confBar}>
          <div style={s.confLabel}>Confidence</div>
          <div style={s.confTrack}>
            <div style={{
              ...s.confFill,
              width: `${item.confidence}%`,
              background: item.confidence >= 80 ? '#4ade80' : item.confidence >= 70 ? '#facc15' : '#f87171',
            }} />
          </div>
          <div style={s.confPct}>{item.confidence.toFixed(0)}%</div>
        </div>
      </div>

      {/* Metrics row */}
      <div style={s.metricsRow}>
        <div style={s.metric}>
          <div style={s.metricLabel}>Entry</div>
          <div style={s.metricValue}>{item.entry_price.toFixed(item.symbol.includes('JPY') ? 3 : item.symbol.includes('XAU') ? 2 : 5)}</div>
        </div>
        <div style={s.metric}>
          <div style={s.metricLabel}>P&L</div>
          <div style={{ ...s.metricValue, color: pnlPos ? '#4ade80' : '#f87171' }}>
            {fmtPnl(item.pnl)}
          </div>
        </div>
        <div style={s.metric}>
          <div style={s.metricLabel}>Copied</div>
          <div style={s.metricValue}>{item.copies}×</div>
        </div>
      </div>

      {/* Actions */}
      <div style={s.actions}>
        <button
          style={{
            ...s.actionBtn,
            ...(item.your_reaction === 'up' ? s.actionActive : {}),
          }}
          onClick={() => onReact(item.signal_id, 'up')}
        >
          👍 {item.thumbs_up}
        </button>
        <button
          style={{
            ...s.actionBtn,
            ...(item.your_reaction === 'down' ? s.actionActiveDown : {}),
          }}
          onClick={() => onReact(item.signal_id, 'down')}
        >
          👎 {item.thumbs_down}
        </button>
        <button style={s.actionBtn} onClick={() => onComment(item.signal_id)}>
          💬 {item.comment_count}
        </button>
        <button style={s.copyTradeBtn} onClick={() => onCopyTrade(item)}>
          Copy Trade
        </button>
      </div>
    </div>
  );
};

// ─── Main component ───────────────────────────────────────────────────────────

const SYMBOLS = ['All', 'XAU/USD', 'EUR/USD', 'GBP/USD', 'USD/JPY', 'BTC/USD'];

const SocialFeed: React.FC = () => {
  const [items, setItems]         = useState<FeedItem[]>([]);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState<string | null>(null);
  const [page, setPage]           = useState(1);
  const [totalPages, setTotal]    = useState(1);
  const [filter, setFilter]       = useState('All');
  const [optedIn, setOptedIn]     = useState(false);
  const [optInError, setOptInError]   = useState<string | null>(null);
  const [reactError, setReactError]   = useState<string | null>(null);
  const [copyError, setCopyError]     = useState<string | null>(null);
  const [commentFor, setCommentFor]   = useState<string | null>(null);

  const load = useCallback(async (p = 1, sym = filter) => {
    setLoading(true);
    setError(null);
    try {
      const params: Record<string, string | number> = { page: p, limit: 10 };
      if (sym !== 'All') params.symbol = sym;
      const res = await api.get('/feed', { params });
      setItems(res.data.items || []);
      setTotal(res.data.pages || 1);
      setPage(p);
    } catch (err) {
      setItems([]);
      setError(extractErrorMessage(err, 'Unable to load feed. Check your connection.'));
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => { load(1, filter); }, [filter]);

  // Check opt-in status — non-critical, default to false on failure
  useEffect(() => {
    api.get('/feed/status/me')
      .then((r) => setOptedIn(r.data.opted_in))
      .catch(() => { /* opt-in status unavailable; default to false */ });
  }, []);

  const handleReact = async (signalId: string, reaction: 'up' | 'down') => {
    setReactError(null);
    try {
      const res = await api.post(`/feed/${signalId}/react`, { reaction });
      setItems((prev) => prev.map((item) =>
        item.signal_id === signalId
          ? { ...item, thumbs_up: res.data.thumbs_up, thumbs_down: res.data.thumbs_down, your_reaction: res.data.your_reaction }
          : item
      ));
    } catch (err) {
      setReactError(extractErrorMessage(err, 'Failed to record reaction. Please try again.'));
    }
  };

  const handleCopyTrade = async (item: FeedItem) => {
    setCopyError(null);
    try {
      await api.post(`/social/copy/${item.trader_id}`, { signal_id: item.signal_id });
    } catch (err) {
      setCopyError(extractErrorMessage(err, 'Copy trade failed. Ensure you are logged in and have a paper account.'));
    }
  };

  const toggleOptIn = async () => {
    setOptInError(null);
    try {
      if (optedIn) {
        await api.post('/feed/opt-out');
        setOptedIn(false);
      } else {
        await api.post('/feed/opt-in');
        setOptedIn(true);
      }
    } catch (err) {
      setOptInError(extractErrorMessage(err, 'Failed to update signal sharing preference.'));
    }
  };

  return (
    <div style={s.page}>
      {/* Header */}
      <div style={s.header}>
        <div>
          <h1 style={s.title}>Community Signal Feed</h1>
          <p style={s.subtitle}>High-confidence AI signals shared by the community. React, comment, and copy.</p>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4 }}>
          <button
            style={{ ...s.optBtn, ...(optedIn ? s.optBtnActive : {}) }}
            onClick={toggleOptIn}
          >
            {optedIn ? '✓ Sharing My Signals' : 'Share My Signals'}
          </button>
          {optInError && <div style={{ fontSize: 12, color: '#f87171' }}>{optInError}</div>}
        </div>
      </div>

      {/* Symbol filter */}
      <div style={s.filterRow}>
        {SYMBOLS.map((sym) => (
          <button
            key={sym}
            style={{ ...s.filterBtn, ...(filter === sym ? s.filterBtnActive : {}) }}
            onClick={() => setFilter(sym)}
          >
            {sym}
          </button>
        ))}
      </div>

      {/* Inline action errors */}
      {reactError && (
        <div style={s.actionError}>
          {reactError}
          <button style={s.dismissBtn} onClick={() => setReactError(null)}>✕</button>
        </div>
      )}
      {copyError && (
        <div style={s.actionError}>
          {copyError}
          <button style={s.dismissBtn} onClick={() => setCopyError(null)}>✕</button>
        </div>
      )}

      {/* Feed */}
      <div style={s.feedGrid}>
        <div style={s.feedCol}>
          {loading && <div style={s.dim}>Loading feed…</div>}
          {!loading && error && (
            <div style={{ ...s.empty, color: '#f87171' }}>{error}</div>
          )}
          {!loading && !error && items.length === 0 && (
            <div style={s.empty}>No signals yet for this filter.</div>
          )}
          {items.map((item) => (
            <FeedCard
              key={item.signal_id}
              item={item}
              onReact={handleReact}
              onComment={(id) => setCommentFor(commentFor === id ? null : id)}
              onCopyTrade={handleCopyTrade}
            />
          ))}

          {/* Pagination */}
          {totalPages > 1 && (
            <div style={s.pagination}>
              <button style={s.pageBtn} disabled={page <= 1} onClick={() => load(page - 1)}>← Prev</button>
              <span style={s.pageInfo}>{page} / {totalPages}</span>
              <button style={s.pageBtn} disabled={page >= totalPages} onClick={() => load(page + 1)}>Next →</button>
            </div>
          )}
        </div>

        {/* Comment panel */}
        {commentFor && (
          <div style={s.commentCol}>
            <CommentPanel signalId={commentFor} onClose={() => setCommentFor(null)} />
          </div>
        )}
      </div>

      {/* Info banner */}
      <div style={s.infoBanner}>
        <span style={{ color: '#60a5fa', fontWeight: 600 }}>ℹ How it works:</span>
        {' '}Only signals with ≥70% confidence appear here. Toggle "Share My Signals" to contribute.
        Copy-trading executes the same trade on your paper account automatically.
      </div>
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
  },
  header: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
    marginBottom: 20, flexWrap: 'wrap', gap: 12,
  },
  title:    { fontSize: 28, fontWeight: 700, margin: 0 },
  subtitle: { fontSize: 14, color: '#94a3b8', marginTop: 4 },
  optBtn: {
    background: '#1e293b', border: '1px solid #334155', borderRadius: 8,
    color: '#94a3b8', padding: '8px 16px', fontSize: 13, cursor: 'pointer',
  },
  optBtnActive: {
    background: 'rgba(74,222,128,0.15)', border: '1px solid #4ade80', color: '#4ade80',
  },
  filterRow: { display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 20 },
  filterBtn: {
    background: '#1e293b', border: '1px solid #334155', borderRadius: 20,
    color: '#64748b', padding: '6px 14px', fontSize: 12, cursor: 'pointer',
  },
  filterBtnActive: {
    background: '#3b82f6', border: '1px solid #3b82f6', color: '#fff',
  },
  actionError: {
    background: 'rgba(248,113,113,0.1)', border: '1px solid #f87171', borderRadius: 8,
    padding: '8px 14px', marginBottom: 12, fontSize: 13, color: '#f87171',
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
  },
  dismissBtn: {
    background: 'transparent', border: 'none', color: '#f87171',
    fontSize: 14, cursor: 'pointer', marginLeft: 8,
  },
  feedGrid: { display: 'flex', gap: 20, alignItems: 'flex-start' },
  feedCol:  { flex: 1, minWidth: 0 },
  commentCol: { width: 340, flexShrink: 0 },
  card: {
    background: '#1e293b', borderRadius: 12, padding: 20,
    border: '1px solid #334155', marginBottom: 16,
  },
  cardHeader: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14,
  },
  userInfo: { display: 'flex', alignItems: 'center', gap: 10 },
  avatar: {
    width: 36, height: 36, borderRadius: '50%', background: '#3b82f6',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    fontSize: 13, fontWeight: 700, color: '#fff', flexShrink: 0,
  },
  username: { fontSize: 14, fontWeight: 600 },
  timeAgo:  { fontSize: 11, color: '#64748b' },
  dirBadge: {
    fontSize: 11, fontWeight: 700, padding: '3px 10px',
    borderRadius: 4, letterSpacing: '0.05em',
  },
  signalInfo: { marginBottom: 14 },
  symbol: { fontSize: 20, fontWeight: 800, marginBottom: 8 },
  confBar: { display: 'flex', alignItems: 'center', gap: 8 },
  confLabel: { fontSize: 11, color: '#64748b', width: 70 },
  confTrack: {
    flex: 1, height: 6, background: '#0f172a', borderRadius: 3, overflow: 'hidden',
  },
  confFill: { height: '100%', borderRadius: 3, transition: 'width 0.3s' },
  confPct: { fontSize: 12, color: '#94a3b8', width: 32, textAlign: 'right' },
  metricsRow: {
    display: 'flex', gap: 16, marginBottom: 14,
    paddingTop: 12, borderTop: '1px solid #0f172a',
  },
  metric: {},
  metricLabel: { fontSize: 11, color: '#64748b', marginBottom: 2 },
  metricValue: { fontSize: 15, fontWeight: 700 },
  actions: { display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' },
  actionBtn: {
    background: '#0f172a', border: '1px solid #334155', borderRadius: 6,
    color: '#94a3b8', padding: '5px 12px', fontSize: 13, cursor: 'pointer',
  },
  actionActive:     { background: 'rgba(74,222,128,0.15)', border: '1px solid #4ade80', color: '#4ade80' },
  actionActiveDown: { background: 'rgba(248,113,113,0.15)', border: '1px solid #f87171', color: '#f87171' },
  copyTradeBtn: {
    marginLeft: 'auto', background: 'rgba(59,130,246,0.15)', border: '1px solid #3b82f6',
    borderRadius: 6, color: '#60a5fa', padding: '5px 14px', fontSize: 12,
    cursor: 'pointer', fontWeight: 600,
  },
  pagination: {
    display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 16, marginTop: 8,
  },
  pageBtn: {
    background: '#1e293b', border: '1px solid #334155', borderRadius: 6,
    color: '#94a3b8', padding: '6px 14px', fontSize: 13, cursor: 'pointer',
  },
  pageInfo: { fontSize: 13, color: '#64748b' },
  commentPanel: {
    background: '#1e293b', borderRadius: 12, border: '1px solid #334155',
    display: 'flex', flexDirection: 'column', height: 480,
    position: 'sticky', top: 24,
  },
  commentHeader: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    padding: '14px 16px', borderBottom: '1px solid #334155',
  },
  closeBtn: {
    background: 'transparent', border: 'none', color: '#64748b',
    fontSize: 16, cursor: 'pointer',
  },
  commentList: { flex: 1, overflowY: 'auto', padding: '12px 16px' },
  commentItem: {
    marginBottom: 12, paddingBottom: 12, borderBottom: '1px solid #0f172a',
  },
  commentUser: { fontSize: 12, fontWeight: 600, color: '#60a5fa', display: 'block', marginBottom: 2 },
  commentText: { fontSize: 13, color: '#cbd5e1', display: 'block', lineHeight: 1.4 },
  commentTime: { fontSize: 11, color: '#475569', display: 'block', marginTop: 2 },
  commentInput: {
    display: 'flex', gap: 8, padding: '12px 16px',
    borderTop: '1px solid #334155',
  },
  textInput: {
    flex: 1, background: '#0f172a', border: '1px solid #334155', borderRadius: 6,
    color: '#f8fafc', padding: '8px 10px', fontSize: 13, outline: 'none',
  },
  sendBtn: {
    background: '#3b82f6', border: 'none', borderRadius: 6,
    color: '#fff', padding: '8px 14px', fontSize: 13, cursor: 'pointer',
  },
  dim:   { color: '#475569', fontSize: 13, textAlign: 'center', padding: 24 },
  empty: { color: '#475569', fontSize: 14, textAlign: 'center', padding: 48 },
  infoBanner: {
    marginTop: 24, background: '#1e293b', borderRadius: 8, padding: '12px 16px',
    fontSize: 13, color: '#94a3b8', border: '1px solid #334155',
  },
};

export default SocialFeed;
