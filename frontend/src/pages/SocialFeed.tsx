/**
 * Social Signal Feed — community feed of high-confidence AI signals.
 * Features: opt-in/out toggle, real-time WS signal injection, pagination,
 * reactions (👍/👎), comments, copy counts.
 */
import React, { useEffect, useState, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { socialApi } from '../hooks/useApi';
import { useStore } from '../store';
import { extractApiError, fmtPrice, fmtPctRaw, fmtTime } from '../lib/utils';
import { openAuthenticatedWebSocket } from '../lib/ws';
import { PageHeader, EmptyState, RelatedPages } from '../components';
import {
  Radio,
  Check,
  ThumbsUp,
  ThumbsDown,
  MessageSquare,
  ChevronUp,
  ChevronDown,
  Zap,
  Trophy,
  Users,
  Sparkles,
  BookOpen,
  LineChart,
  Lightbulb,
} from 'lucide-react';

interface FeedItem {
  signal_id: string; symbol: string; direction: 'BUY'|'SELL'; confidence: number;
  entry_price: number; pnl: number; copies: number; username: string; trader_id: string;
  thumbs_up: number; thumbs_down: number; comment_count: number; created_at: string;
  your_reaction?: 'up'|'down'|null;
}
interface Comment { comment_id: string; username: string; text: string; created_at: string; }

const PAGE_SIZE = 20;

const SocialFeed: React.FC = () => {
  const navigate = useNavigate();
  const user = useStore(s => s.user);
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
      setError(extractApiError(err, 'Failed to load signal feed.'));
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => { loadFeed(1, true); }, [loadFeed]);

  // WebSocket — inject new signals in real-time
  const wsToken = useStore(s => s.token);
  useEffect(() => {
    if (!wsToken) return;
    let ws: WebSocket | null = null;
    try {
      ws = openAuthenticatedWebSocket('/ws/social-feed', wsToken);
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data as string) as { type?: string; signal?: FeedItem };
          if (msg.type === 'new_signal' && msg.signal) {
            setItems(prev => [msg.signal!, ...prev].slice(0, 200));
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
    if (sortBy === 'confidence') return (b.confidence ?? 0) - (a.confidence ?? 0);
    if (sortBy === 'return')     return (b.pnl ?? 0) - (a.pnl ?? 0);
    const at = new Date(a.created_at).getTime();
    const bt = new Date(b.created_at).getTime();
    return (isNaN(bt) ? 0 : bt) - (isNaN(at) ? 0 : at);
  });

  return (
    <div className="page-content">
      <PageHeader
        title="Community signal feed"
        icon={Radio}
        subtitle="High-confidence AI signals shared by the community — 70% confidence and above."
        actions={
          <button
            onClick={handleOptToggle}
            disabled={optLoading || optedIn === null}
            aria-pressed={optedIn === true}
            className={`inline-flex min-h-[44px] items-center gap-1.5 rounded-lg px-4 text-[12.5px]
                        font-semibold cursor-pointer transition-colors duration-150
                        disabled:cursor-not-allowed disabled:opacity-50
                        focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500
                        focus-visible:ring-offset-2 focus-visible:ring-offset-[#080c14]
                        ${optedIn
                          ? 'bg-emerald-500/15 text-emerald-300 ring-1 ring-inset ring-emerald-500/40 hover:bg-emerald-500/25'
                          : 'text-slate-400 ring-1 ring-inset ring-[#1e2d3d] hover:bg-[#141c2b] hover:text-slate-200'}`}
          >
            {optLoading
              ? 'Saving…'
              : optedIn
                ? <><Check size={14} strokeWidth={2.5} aria-hidden /> Sharing my signals</>
                : 'Share my signals'}
          </button>
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
          icon={Radio}
          title={symbolFilter === 'All' ? 'No community signals yet' : `No signals for ${symbolFilter}`}
          description={
            symbolFilter === 'All'
              ? 'Signals appear here when a member shares one at 70% confidence or above. You can generate your own in the meantime.'
              : 'Clear the symbol filter to see the whole feed, or generate a signal for this instrument.'
          }
          links={[
            { label: 'Generate AI signals', href: '/ai-strategy' },
            { label: 'Open the ticket', href: '/trade' },
          ]}
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
                <span style={s.confidence}>{Number.isFinite(item.confidence) ? (item.confidence * 100).toFixed(0) : '—'}% conf</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 13, color: '#64748b' }}>by <strong style={{ color: '#94a3b8' }}>{item.username}</strong></span>
                <span style={{ fontSize: 11, color: '#475569' }}>{fmtTime(item.created_at)}</span>
              </div>
            </div>

            <div style={s.metrics}>
              <span style={s.metric}>Entry: <strong>${fmtPrice(item.entry_price, 4)}</strong></span>
              <span style={{ ...s.metric, color: (item.pnl ?? 0) >= 0 ? '#4ade80' : '#f87171' }}>
                P&L: <strong>{fmtPctRaw(item.pnl, 2)}</strong>
              </span>
              <span style={s.metric}>Copies: <strong>{item.copies}</strong></span>
            </div>

            <div style={s.actions}>
              <button
                onClick={() => handleReact(item.signal_id, 'up')}
                aria-pressed={item.your_reaction === 'up'}
                aria-label={`Agree with this ${item.symbol} signal (${item.thumbs_up} so far)`}
                className={`inline-flex min-h-[44px] items-center gap-1.5 rounded-lg px-2.5 text-[12.5px]
                            cursor-pointer transition-colors duration-150 hover:bg-emerald-500/10
                            focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500
                            ${item.your_reaction === 'up' ? 'text-emerald-400' : 'text-slate-500'}`}
              >
                <ThumbsUp size={14} strokeWidth={1.75} aria-hidden /> {item.thumbs_up}
              </button>
              <button
                onClick={() => handleReact(item.signal_id, 'down')}
                aria-pressed={item.your_reaction === 'down'}
                aria-label={`Disagree with this ${item.symbol} signal (${item.thumbs_down} so far)`}
                className={`inline-flex min-h-[44px] items-center gap-1.5 rounded-lg px-2.5 text-[12.5px]
                            cursor-pointer transition-colors duration-150 hover:bg-red-500/10
                            focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-500
                            ${item.your_reaction === 'down' ? 'text-red-400' : 'text-slate-500'}`}
              >
                <ThumbsDown size={14} strokeWidth={1.75} aria-hidden /> {item.thumbs_down}
              </button>
              <button
                onClick={() => toggleExpand(item.signal_id)}
                aria-expanded={expanded === item.signal_id}
                aria-label={`${expanded === item.signal_id ? 'Hide' : 'Show'} ${item.comment_count} comments`}
                className="inline-flex min-h-[44px] items-center gap-1.5 rounded-lg px-2.5 text-[12.5px]
                           text-slate-500 cursor-pointer transition-colors duration-150
                           hover:bg-[#141c2b] hover:text-slate-300 focus-visible:outline-none
                           focus-visible:ring-2 focus-visible:ring-sky-500"
              >
                <MessageSquare size={14} strokeWidth={1.75} aria-hidden /> {item.comment_count}
                {expanded === item.signal_id
                  ? <ChevronUp size={12} strokeWidth={2.5} aria-hidden />
                  : <ChevronDown size={12} strokeWidth={2.5} aria-hidden />}
              </button>
              <button
                onClick={() => navigate('/trade', { state: { signal: { symbol: item.symbol, direction: item.direction } } })}
                aria-label={`Open a ${item.direction} ticket for ${item.symbol}`}
                className={`ml-auto inline-flex min-h-[44px] items-center gap-1.5 rounded-lg px-3.5
                            text-[12.5px] font-bold cursor-pointer transition-colors duration-150
                            focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2
                            focus-visible:ring-offset-[#0d1421]
                            ${item.direction === 'BUY'
                              ? 'bg-emerald-500/12 text-emerald-400 ring-1 ring-inset ring-emerald-500/40 hover:bg-emerald-500/22 focus-visible:ring-emerald-500'
                              : 'bg-red-500/12 text-red-400 ring-1 ring-inset ring-red-500/40 hover:bg-red-500/22 focus-visible:ring-red-500'}`}
              >
                <Zap size={13} strokeWidth={2} aria-hidden /> Trade {item.direction}
              </button>
            </div>

            {expanded === item.signal_id && (
              <div style={s.commentsSection}>
                {(comments[item.signal_id] ?? []).map(c => (
                  <div key={c.comment_id} style={s.comment}>
                    <strong style={{ color: '#94a3b8', fontSize: 12 }}>{c.username}</strong>
                    <span style={{ color: '#64748b', fontSize: 11, marginLeft: 8 }}>{fmtTime(c.created_at)}</span>
                    <p style={{ margin: '4px 0 0', fontSize: 13, color: '#cbd5e1' }}>{c.text}</p>
                  </div>
                ))}
                {user && (
                  <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                    <input
                      value={commentText}
                      onChange={e => setCommentText(e.target.value)}
                      onKeyDown={e => e.key === 'Enter' && !e.shiftKey && submitComment(item.signal_id)}
                      placeholder="Add a comment…"
                      style={s.commentInput}
                    />
                    <button onClick={() => submitComment(item.signal_id)} disabled={submitting || !commentText.trim()} style={s.commentBtn}>
                      {submitting ? '…' : 'Post'}
                    </button>
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

      <RelatedPages
        links={[
          { to: '/leaderboard',  label: 'Leaderboard',   hint: 'Who is performing best right now', icon: Trophy },
          { to: '/copy-trading', label: 'Copy trading',  hint: 'Follow a trader automatically',    icon: Users },
          { to: '/ai-strategy',  label: 'AI strategy',   hint: 'Generate your own signals',        icon: Sparkles },
          { to: '/journal',      label: 'Trade journal', hint: 'How signals worked out for you',   icon: BookOpen },
          { to: '/ai-chart',     label: 'Charts',        hint: 'Study a symbol before you act',    icon: LineChart },
        ]}
      />

      {optedIn !== null && (
        <div style={s.infoBanner}>
          {optedIn
            ? <><Check size={13} strokeWidth={2.5} aria-hidden className="inline mr-1.5 align-[-2px] text-emerald-400" />
                Your high-confidence signals are visible to the community. Turn sharing off to stop.</>
            : <><Lightbulb size={13} strokeWidth={1.75} aria-hidden className="inline mr-1.5 align-[-2px] text-amber-400" />
                Share your AI signals with the community to build your reputation.</>}
        </div>
      )}
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
