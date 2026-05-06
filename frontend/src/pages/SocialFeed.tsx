/**
 * Social Signal Feed — community feed of high-confidence AI signals.
 * Features: opt-in/out toggle, real-time WS signal injection, pagination,
 * reactions (👍/👎), comments, copy counts.
 */
import React, { useEffect, useState, useCallback, useRef } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { PageHeader, EmptyState } from '../components';
import { socialApi } from '../hooks/useApi';
import { useStore } from '../store';
import { getWsBase } from '../lib/utils';

interface FeedItem {
  signal_id: string; symbol: string; direction: 'BUY'|'SELL'; confidence: number;
  entry_price: number; pnl: number; copies: number; username: string; trader_id: string;
  thumbs_up: number; thumbs_down: number; comment_count: number; created_at: string;
  your_reaction?: 'up'|'down'|null;
}
interface Comment { comment_id: string; username: string; text: string; created_at: string; }

const PAGE_SIZE = 20;
function extractErr(err: unknown, fb: string): string {
  const d = (err as {response?:{data?:{detail?:string}}})?.response?.data?.detail;
  return d ?? (err instanceof Error ? err.message : fb);
}

const SocialFeed: React.FC = () => {
  const navigate = useNavigate();
  const user = useStore(s => s.user);
  const [wsConnected, setWsConnected] = useState(false);
  const [wsFlash, setWsFlash]         = useState(false);
  const [typingSignals, setTypingSignals] = useState<Record<string, boolean>>({});
  const [items, setItems]           = useState<FeedItem[]>([]);
  const [loading, setLoading]       = useState(true);
  const [error, setError]           = useState<string|null>(null);
  const [page, setPage]             = useState(1);
  const [hasMore, setHasMore]       = useState(true);
  const [optedIn, setOptedIn]       = useState<boolean|null>(null);
  const [optLoading, setOptLoading] = useState(false);
  const [expanded, setExpanded]     = useState<string|null>(null);
  const [comments, setComments]     = useState<Record<string, Comment[]>>({});
  const [commentText, setCommentText] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const mountedRef = useRef(true);
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

  // Load opt-in status
  useEffect(() => {
    let mounted = true;
    socialApi.optStatus()
      .then(r => {
        if (!mounted) return;
        const d = r.data as {opted_in?: boolean}; setOptedIn(d.opted_in ?? false);
      })
      .catch(() => { if (mounted) setOptedIn(false); });
    return () => { mounted = false; };
  }, []);

  const loadFeed = useCallback(async (pg: number, replace = false) => {
    setLoading(true); setError(null);
    try {
      const res = await socialApi.feed({ page: pg, limit: PAGE_SIZE });
      if (!mountedRef.current) return;
      const d = res.data as { signals?: FeedItem[]; items?: FeedItem[] } | FeedItem[];
      const fetched: FeedItem[] = Array.isArray(d) ? d : (d.signals ?? d.items ?? []);
      setItems(prev => replace ? fetched : [...prev, ...fetched]);
      setHasMore(fetched.length === PAGE_SIZE);
    } catch (err) {
      if (!mountedRef.current) return;
      if ((err as {name?:string}).name === 'CanceledError') return;
      setError(extractErr(err, 'Failed to load signal feed.'));
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => { loadFeed(1, true); }, [loadFeed]);

  // WebSocket — inject new signals in real-time with animated indicator
  const wsToken = useStore(s => s.token);
  useEffect(() => {
    if (!wsToken) return;
    const wsUrl = `${getWsBase()}/ws/social-feed?token=${wsToken}`;
    let ws: WebSocket | null = null;
    try {
      ws = new WebSocket(wsUrl);
      ws.onopen  = () => { if (mountedRef.current) setWsConnected(true); };
      ws.onclose = () => { if (mountedRef.current) setWsConnected(false); };
      ws.onerror = () => { if (mountedRef.current) setWsConnected(false); };
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data as string) as { type?: string; signal?: FeedItem };
          if (msg.type === 'new_signal' && msg.signal) {
            setItems(prev => [msg.signal!, ...prev].slice(0, 200));
            // Flash the WS indicator on new signal
            setWsFlash(true);
            setTimeout(() => setWsFlash(false), 800);
          }
        } catch { /* ignore malformed frames */ }
      };
    } catch { /* WS unavailable — polling only */ }
    return () => { ws?.close(); };
  }, [wsToken]);

  const handleOptToggle = async () => {
    setOptLoading(true);
    try {
      if (optedIn) { await socialApi.optOut(); setOptedIn(false); }
      else         { await socialApi.optIn();  setOptedIn(true);  }
    } catch { /* keep current state */ }
    finally { setOptLoading(false); }
  };

  const handleReact = async (signalId: string, reaction: 'up'|'down') => {
    try {
      await socialApi.react(signalId, reaction);
      setItems(prev => prev.map(item => {
        if (item.signal_id !== signalId) return item;
        const wasUp   = item.your_reaction === 'up';
        const wasDown = item.your_reaction === 'down';
        return {
          ...item,
          your_reaction: item.your_reaction === reaction ? null : reaction,
          thumbs_up:   reaction === 'up'   ? item.thumbs_up   + (wasUp   ? -1 : 1) : item.thumbs_up   - (wasUp   ? 1 : 0),
          thumbs_down: reaction === 'down' ? item.thumbs_down + (wasDown ? -1 : 1) : item.thumbs_down - (wasDown ? 1 : 0),
        };
      }));
    } catch { /* ignore */ }
  };

  const loadComments = async (signalId: string) => {
    if (comments[signalId]) return;
    try {
      const res = await socialApi.comments(signalId);
      const d = res.data as { comments?: Comment[] } | Comment[];
      setComments(prev => ({ ...prev, [signalId]: Array.isArray(d) ? d : (d.comments ?? []) }));
    } catch { setComments(prev => ({ ...prev, [signalId]: [] })); }
  };

  const toggleExpand = (signalId: string) => {
    if (expanded === signalId) { setExpanded(null); return; }
    setExpanded(signalId);
    loadComments(signalId);
  };

  const submitComment = async (signalId: string) => {
    if (!commentText.trim()) return;
    setSubmitting(true);
    try {
      await socialApi.addComment(signalId, commentText.trim());
      setCommentText('');
      // Reload comments for this signal
      const res = await socialApi.comments(signalId);
      const d = res.data as { comments?: Comment[] } | Comment[];
      setComments(prev => ({ ...prev, [signalId]: Array.isArray(d) ? d : (d.comments ?? []) }));
      setItems(prev => prev.map(i => i.signal_id === signalId ? { ...i, comment_count: i.comment_count + 1 } : i));
    } catch { /* ignore */ }
    finally { setSubmitting(false); }
  };

  const loadMore = () => {
    const next = page + 1;
    setPage(next);
    loadFeed(next, false);
  };

  const SYMBOLS = ['All', 'XAU/USD', 'EUR/USD', 'GBP/USD', 'USD/JPY', 'BTC/USD'];
  const [symbolFilter, setSymbolFilter] = React.useState('All');
  const [sortBy, setSortBy] = React.useState<'confidence'|'return'|'recent'>('confidence');

  const filteredItems = items.filter(item =>
    symbolFilter === 'All' || item.symbol === symbolFilter
  ).sort((a, b) => {
    if (sortBy === 'confidence') return b.confidence - a.confidence;
    if (sortBy === 'return')     return b.pnl - a.pnl;
    return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
  });

  return (
    <div style={s.page}>
      <PageHeader
        title="Community Signal Feed"
        icon="📡"
        subtitle="High-confidence AI signals from the community (≥70% confidence)"
        breadcrumbs={[
          { label: 'Dashboard', href: '/dashboard' },
          { label: 'Community', href: '/leaderboard' },
          { label: 'Signal Feed' },
        ]}
        actions={
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {/* WS live indicator */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '4px 10px', background: wsConnected ? 'rgba(74,222,128,0.08)' : 'rgba(100,116,139,0.08)', border: `1px solid ${wsConnected ? 'rgba(74,222,128,0.3)' : '#334155'}`, borderRadius: 20 }}>
              <div style={{ width: 7, height: 7, borderRadius: '50%', background: wsConnected ? (wsFlash ? '#fff' : '#4ade80') : '#475569', transition: 'background 0.2s', boxShadow: wsConnected && wsFlash ? '0 0 8px #4ade80' : 'none' }} />
              <span style={{ fontSize: 10, fontWeight: 700, color: wsConnected ? '#4ade80' : '#475569' }}>{wsConnected ? 'LIVE' : 'OFFLINE'}</span>
            </div>
            <Link to="/leaderboard"  style={{ padding: '6px 12px', background: 'rgba(251,191,36,0.1)', border: '1px solid rgba(251,191,36,0.3)', borderRadius: 7, color: '#fbbf24', fontSize: 12, fontWeight: 600, textDecoration: 'none' }}>🏆 Leaderboard</Link>
            <Link to="/copy-trading" style={{ padding: '6px 12px', background: 'rgba(52,211,153,0.1)',  border: '1px solid rgba(52,211,153,0.3)',  borderRadius: 7, color: '#34d399', fontSize: 12, fontWeight: 600, textDecoration: 'none' }}>🔁 Copy Trading</Link>
            <div style={{ width: 1, height: 20, background: '#334155' }} />
            <span style={{ fontSize: 12, color: '#64748b' }}>Share signals:</span>
            <button
              onClick={handleOptToggle}
              disabled={optLoading || optedIn === null}
              style={{
                ...s.toggleBtn,
                background: optedIn ? '#059669' : '#334155',
                color: optedIn ? '#fff' : '#94a3b8',
              }}
            >
              {optLoading ? '…' : optedIn ? '✅ Opted In' : 'Opt In'}
            </button>
          </div>
        }
      />

      {/* Symbol filters */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
        {SYMBOLS.map(sym => (
          <button
            key={sym}
            onClick={() => setSymbolFilter(sym)}
            style={{
              padding: '4px 12px', borderRadius: 6, border: 'none', cursor: 'pointer', fontSize: 13,
              background: symbolFilter === sym ? '#3b82f6' : '#1e293b',
              color: symbolFilter === sym ? '#fff' : '#94a3b8',
            }}
          >
            {sym}
          </button>
        ))}
        <select
          value={sortBy}
          onChange={e => setSortBy(e.target.value as typeof sortBy)}
          style={{ marginLeft: 'auto', background: '#1e293b', color: '#94a3b8', border: '1px solid #334155', borderRadius: 6, padding: '4px 8px', fontSize: 13 }}
        >
          <option value="confidence">Sort: Confidence</option>
          <option value="return">Sort: Return</option>
          <option value="recent">Sort: Recent</option>
        </select>
      </div>

      {error && <div style={s.errorBox}>{error}</div>}

      {filteredItems.length === 0 && !loading && !error && (
        <EmptyState
          icon="📡"
          title="No signals yet"
          description="Community signals appear here once traders opt in to share. You can also opt in above to contribute your own."
          action={
            <div style={{ display: 'flex', gap: 8 }}>
              <Link to="/ai-chart-dashboard" style={{ padding: '8px 18px', background: '#3b82f6', border: 'none', borderRadius: 8, color: '#fff', fontSize: 13, fontWeight: 600, textDecoration: 'none' }}>📈 AI Charts</Link>
              <Link to="/leaderboard"        style={{ padding: '8px 18px', background: 'transparent', border: '1px solid #334155', borderRadius: 8, color: '#94a3b8', fontSize: 13, textDecoration: 'none' }}>🏆 Leaderboard</Link>
            </div>
          }
        />
      )}

      <div style={s.feed}>
        {filteredItems.map(item => (
          <div key={item.signal_id} style={s.card}>
            <div style={s.cardTop}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span style={{ ...s.dirBadge, background: item.direction === 'BUY' ? '#14532d' : '#450a0a', color: item.direction === 'BUY' ? '#4ade80' : '#f87171' }}>
                  {item.direction}
                </span>
                <span style={s.symbol}>{item.symbol}</span>
                <span style={s.confidence}>{(item.confidence * 100).toFixed(0)}% conf</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 13, color: '#64748b' }}>by <strong style={{ color: '#94a3b8' }}>{item.username}</strong></span>
                <span style={{ fontSize: 11, color: '#475569' }}>{new Date(item.created_at).toLocaleTimeString()}</span>
              </div>
            </div>

            <div style={s.metrics}>
              <span style={s.metric}>Entry: <strong>${item.entry_price.toFixed(4)}</strong></span>
              <span style={{ ...s.metric, color: item.pnl >= 0 ? '#4ade80' : '#f87171' }}>
                P&L: <strong>{item.pnl >= 0 ? '+' : ''}{item.pnl.toFixed(2)}%</strong>
              </span>
              <span style={s.metric}>Copies: <strong>{item.copies}</strong></span>
            </div>

            <div style={s.actions}>
              <button onClick={() => handleReact(item.signal_id, 'up')}
                style={{ ...s.reactBtn, color: item.your_reaction === 'up' ? '#4ade80' : '#64748b' }}>
                👍 {item.thumbs_up}
              </button>
              <button onClick={() => handleReact(item.signal_id, 'down')}
                style={{ ...s.reactBtn, color: item.your_reaction === 'down' ? '#f87171' : '#64748b' }}>
                👎 {item.thumbs_down}
              </button>
              <button onClick={() => toggleExpand(item.signal_id)} style={s.commentToggle}>
                💬 {item.comment_count} {expanded === item.signal_id ? '▲' : '▼'}
              </button>
              <button
                onClick={() => { window.location.href = '/trade'; }}
                style={{
                  marginLeft: 'auto', padding: '4px 12px', borderRadius: 6, fontWeight: 700, fontSize: 12, cursor: 'pointer',
                  background: item.direction === 'BUY' ? 'rgba(74,222,128,0.12)' : 'rgba(248,113,113,0.12)',
                  border: `1px solid ${item.direction === 'BUY' ? 'rgba(74,222,128,0.4)' : 'rgba(248,113,113,0.4)'}`,
                  color: item.direction === 'BUY' ? '#4ade80' : '#f87171',
                }}
              >
                ⚡ Trade
              </button>
            </div>

            {expanded === item.signal_id && (
              <div style={s.commentsSection}>
                {(comments[item.signal_id] ?? []).map(c => (
                  <div key={c.comment_id} style={s.comment}>
                    <strong style={{ color: '#94a3b8', fontSize: 12 }}>{c.username}</strong>
                    <span style={{ color: '#64748b', fontSize: 11, marginLeft: 8 }}>{new Date(c.created_at).toLocaleTimeString()}</span>
                    <p style={{ margin: '4px 0 0', fontSize: 13, color: '#cbd5e1' }}>{c.text}</p>
                  </div>
                ))}
                {user && (
                  <div style={{ marginTop: 10 }}>
                    {typingSignals[item.signal_id] && (
                      <div style={{ fontSize: 11, color: '#475569', marginBottom: 4, display: 'flex', alignItems: 'center', gap: 4 }}>
                        <span style={{ display: 'inline-flex', gap: 2 }}>
                          {[0,1,2].map(i => (
                            <span key={i} style={{ width: 4, height: 4, borderRadius: '50%', background: '#475569', display: 'inline-block', animation: `bounce 1.2s ${i * 0.2}s infinite` }} />
                          ))}
                        </span>
                        typing…
                      </div>
                    )}
                    <div style={{ display: 'flex', gap: 8 }}>
                      <input
                        value={commentText}
                        onChange={e => {
                          setCommentText(e.target.value);
                          setTypingSignals(prev => ({ ...prev, [item.signal_id]: e.target.value.length > 0 }));
                        }}
                        onBlur={() => setTypingSignals(prev => ({ ...prev, [item.signal_id]: false }))}
                        onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { submitComment(item.signal_id); setTypingSignals(prev => ({ ...prev, [item.signal_id]: false })); } }}
                        placeholder="Add a comment…"
                        style={s.commentInput}
                      />
                      <button onClick={() => { submitComment(item.signal_id); setTypingSignals(prev => ({ ...prev, [item.signal_id]: false })); }} disabled={submitting || !commentText.trim()} style={s.commentBtn}>
                        {submitting ? '…' : 'Post'}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      {loading && <div style={s.dim}>Loading signals…</div>}

      {!loading && hasMore && items.length > 0 && (
        <div style={{ textAlign: 'center', marginTop: 20 }}>
          <button onClick={loadMore} style={s.loadMoreBtn}>Load more</button>
        </div>
      )}

      {optedIn !== null && (
        <div style={s.infoBanner}>
          {optedIn
            ? '✅ Your high-confidence signals are visible to the community. Toggle off to stop sharing.'
            : '💡 Opt in to share your AI signals with the community and build your reputation.'}
        </div>
      )}

      {/* Cross-links */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', padding: '16px 0', borderTop: '1px solid #1e293b', marginTop: 8 }}>
        <Link to="/leaderboard" style={{ padding: '5px 12px', background: 'transparent', border: '1px solid #1e293b', borderRadius: 6, color: '#475569', fontSize: 12, textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 4 }}>🥇 Leaderboard</Link>
        <Link to="/copy-trading" style={{ padding: '5px 12px', background: 'transparent', border: '1px solid #1e293b', borderRadius: 6, color: '#475569', fontSize: 12, textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 4 }}>🔁 Copy Trading</Link>
        <Link to="/chat" style={{ padding: '5px 12px', background: 'transparent', border: '1px solid #1e293b', borderRadius: 6, color: '#475569', fontSize: 12, textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 4 }}>💬 Chat</Link>
        <Link to="/marketplace" style={{ padding: '5px 12px', background: 'transparent', border: '1px solid #1e293b', borderRadius: 6, color: '#475569', fontSize: 12, textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 4 }}>🛒 Marketplace</Link>
        <Link to="/teams" style={{ padding: '5px 12px', background: 'transparent', border: '1px solid #1e293b', borderRadius: 6, color: '#475569', fontSize: 12, textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 4 }}>👥 Teams</Link>
      </div>
    </div>
  );
};

const s: Record<string, React.CSSProperties> = {
  page:           { maxWidth: 800, margin: '0 auto', padding: '24px 16px', fontFamily: 'system-ui,-apple-system,sans-serif', color: '#f1f5f9', background: '#0f172a', minHeight: '100vh' },
  header:         { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24 },
  title:          { fontSize: 24, fontWeight: 700, color: '#f8fafc', margin: '0 0 4px' },
  subtitle:       { fontSize: 13, color: '#64748b', margin: 0 },
  toggleBtn:      { border: 'none', borderRadius: 8, cursor: 'pointer', fontSize: 13, fontWeight: 600, padding: '8px 16px', transition: 'background 0.2s' },
  errorBox:       { background: 'rgba(248,113,113,0.1)', border: '1px solid #f87171', borderRadius: 8, padding: '10px 14px', marginBottom: 16, fontSize: 13, color: '#f87171' },
  empty:          { color: '#475569', fontSize: 14, textAlign: 'center', padding: 48 },
  feed:           { display: 'flex', flexDirection: 'column', gap: 12 },
  card:           { background: '#1e293b', border: '1px solid #334155', borderRadius: 10, padding: '14px 16px' },
  cardTop:        { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 },
  dirBadge:       { fontSize: 11, fontWeight: 700, padding: '2px 8px', borderRadius: 4 },
  symbol:         { fontSize: 15, fontWeight: 700, color: '#f1f5f9' },
  confidence:     { fontSize: 11, background: '#1e3a5f', color: '#60a5fa', padding: '2px 8px', borderRadius: 10 },
  metrics:        { display: 'flex', gap: 20, marginBottom: 10 },
  metric:         { fontSize: 13, color: '#64748b' },
  actions:        { display: 'flex', gap: 8 },
  reactBtn:       { background: 'transparent', border: '1px solid #334155', borderRadius: 6, cursor: 'pointer', fontSize: 13, padding: '4px 10px' },
  commentToggle:  { background: 'transparent', border: '1px solid #334155', borderRadius: 6, color: '#64748b', cursor: 'pointer', fontSize: 13, padding: '4px 10px', marginLeft: 'auto' },
  commentsSection:{ borderTop: '1px solid #334155', marginTop: 12, paddingTop: 12 },
  comment:        { padding: '6px 0', borderBottom: '1px solid #0f172a' },
  commentInput:   { flex: 1, background: '#0f172a', border: '1px solid #334155', borderRadius: 6, color: '#f1f5f9', fontSize: 13, padding: '6px 10px', outline: 'none' },
  commentBtn:     { background: '#3b82f6', border: 'none', borderRadius: 6, color: '#fff', cursor: 'pointer', fontSize: 13, padding: '6px 14px' },
  dim:            { color: '#475569', fontSize: 13, textAlign: 'center', padding: 24 },
  loadMoreBtn:    { background: '#1e293b', border: '1px solid #334155', borderRadius: 8, color: '#94a3b8', cursor: 'pointer', fontSize: 14, padding: '10px 28px' },
  infoBanner:     { marginTop: 24, background: '#1e293b', borderRadius: 8, padding: '12px 16px', fontSize: 13, color: '#94a3b8', border: '1px solid #334155' },
};

export default SocialFeed;
