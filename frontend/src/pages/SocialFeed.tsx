/**
 * Social Signal Feed — community feed of high-confidence AI signals.
 * Features: opt-in/out toggle, real-time WS signal injection with auto-reconnect,
 * pagination, reactions (👍/👎), comments, copy counts.
 *
 * Routes: /signals (canonical), /social → /signals, /feed → /signals
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

  // WebSocket — inject new signals in real-time with auto-reconnect (exponential backoff)
  const wsToken = useStore(s => s.token);
  const wsRef2  = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectDelay = useRef(1000);

  useEffect(() => {
    if (!wsToken) return;
    let destroyed = false;

    const connect = () => {
      if (destroyed) return;
      const wsUrl = `${getWsBase()}/ws/social-feed?token=${wsToken}`;
      let ws: WebSocket;
      try { ws = new WebSocket(wsUrl); } catch { return; }
      wsRef2.current = ws;

      ws.onopen = () => {
        if (!mountedRef.current || destroyed) return;
        setWsConnected(true);
        reconnectDelay.current = 1000; // reset backoff on successful connect
      };
      ws.onclose = () => {
        if (!mountedRef.current || destroyed) return;
        setWsConnected(false);
        // Exponential backoff: 1s → 2s → 4s → 8s → max 30s
        const delay = Math.min(reconnectDelay.current, 30_000);
        reconnectDelay.current = delay * 2;
        reconnectTimer.current = setTimeout(connect, delay);
      };
      ws.onerror = () => {
        if (!mountedRef.current || destroyed) return;
        setWsConnected(false);
        ws.close();
      };
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data as string) as { type?: string; signal?: FeedItem };
          if (msg.type === 'new_signal' && msg.signal) {
            setItems(prev => [msg.signal!, ...prev].slice(0, 200));
            setWsFlash(true);
            setTimeout(() => setWsFlash(false), 800);
          }
          // heartbeat — no action needed, connection is alive
        } catch { /* ignore malformed frames */ }
      };
    };

    connect();

    return () => {
      destroyed = true;
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      wsRef2.current?.close();
      wsRef2.current = null;
      setWsConnected(false);
    };
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
    <div className="max-w-3xl mx-auto px-3 sm:px-6 py-4 sm:py-8 text-slate-100 min-h-screen">
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
          <div className="flex items-center gap-2 flex-wrap">
            {/* WS live indicator */}
            <div
              title={wsConnected ? 'Real-time connected' : 'Reconnecting…'}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full border cursor-default ${
                wsConnected
                  ? 'bg-green-500/8 border-green-500/30'
                  : 'bg-slate-500/8 border-terminal-border'
              }`}
            >
              <div className={`w-1.5 h-1.5 rounded-full transition-colors ${
                wsConnected ? (wsFlash ? 'bg-white' : 'bg-green-400') : 'bg-slate-500 animate-pulse'
              }`} />
              <span className={`text-2xs font-bold ${wsConnected ? 'text-green-400' : 'text-slate-500'}`}>
                {wsConnected ? 'LIVE' : 'RECONNECTING'}
              </span>
            </div>
            <Link to="/leaderboard"
              className="px-3 py-1.5 bg-amber-500/10 border border-amber-500/30 rounded-lg text-amber-400 text-xs font-semibold no-underline hover:bg-amber-500/20 transition-colors hidden sm:inline-flex">
              🏆 Leaderboard
            </Link>
            <Link to="/copy-trading"
              className="px-3 py-1.5 bg-emerald-500/10 border border-emerald-500/30 rounded-lg text-emerald-400 text-xs font-semibold no-underline hover:bg-emerald-500/20 transition-colors hidden sm:inline-flex">
              🔁 Copy
            </Link>
            <button
              onClick={handleOptToggle}
              disabled={optLoading || optedIn === null}
              className={`px-3 py-1.5 rounded-lg text-xs font-bold border-0 cursor-pointer transition-colors disabled:opacity-50 ${
                optedIn ? 'bg-emerald-700 text-white' : 'bg-terminal-raised text-slate-400 hover:text-slate-200'
              }`}
            >
              {optLoading ? '…' : optedIn ? '✅ Opted In' : 'Opt In'}
            </button>
          </div>
        }
      />

      {/* Symbol filters + sort — scrollable on mobile */}
      <div className="flex items-center gap-2 mb-4 overflow-x-auto pb-1"
        style={{ scrollbarWidth: 'none' } as React.CSSProperties}>
        {SYMBOLS.map(sym => (
          <button
            key={sym}
            onClick={() => setSymbolFilter(sym)}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold border-0 cursor-pointer whitespace-nowrap transition-colors flex-shrink-0 ${
              symbolFilter === sym
                ? 'bg-blue-600 text-white'
                : 'bg-terminal-raised text-slate-400 hover:text-slate-200'
            }`}
          >
            {sym}
          </button>
        ))}
        <select
          value={sortBy}
          onChange={e => setSortBy(e.target.value as typeof sortBy)}
          className="ml-auto bg-terminal-raised border border-terminal-border rounded-lg text-slate-400 text-xs px-2.5 py-1.5 outline-none cursor-pointer flex-shrink-0"
        >
          <option value="confidence">Confidence</option>
          <option value="return">Return</option>
          <option value="recent">Recent</option>
        </select>
      </div>

      {error && (
        <div className="bg-red-950/40 border border-red-800 rounded-lg px-4 py-3 text-red-400 text-sm mb-4">
          {error}
        </div>
      )}

      {/* Opt-in CTA */}
      {optedIn === false && (
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 bg-gradient-to-br from-blue-500/8 to-violet-500/8 border border-blue-500/25 rounded-xl p-4 sm:p-5 mb-5">
          <div className="min-w-0">
            <div className="text-slate-100 text-sm font-bold mb-1">
              📡 Share your AI signals with the community
            </div>
            <div className="text-slate-400 text-xs leading-relaxed max-w-md">
              Opt in to broadcast your high-confidence signals (≥70%) to other traders.
              Build your reputation on the leaderboard and earn copy-trading followers.
            </div>
          </div>
          <button
            onClick={handleOptToggle}
            disabled={optLoading}
            className="flex-shrink-0 px-5 py-2.5 rounded-lg font-bold text-sm cursor-pointer border-0 text-white transition-opacity disabled:opacity-60 whitespace-nowrap"
            style={{ background: 'linear-gradient(135deg, #3b82f6, #8b5cf6)' }}
          >
            {optLoading ? 'Enabling…' : '✅ Enable Signal Sharing'}
          </button>
        </div>
      )}

      {filteredItems.length === 0 && !loading && !error && (
        <EmptyState
          icon="📡"
          title={optedIn === false ? 'No community signals yet' : 'No signals yet'}
          description={
            optedIn === false
              ? 'Be the first to share — opt in above to broadcast your AI signals to the community.'
              : 'Community signals appear here once traders opt in to share.'
          }
          action={
            <div className="flex gap-2">
              <Link to="/ai-chart-dashboard"
                className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm font-semibold no-underline transition-colors">
                📈 AI Charts
              </Link>
              <Link to="/leaderboard"
                className="px-4 py-2 bg-transparent border border-terminal-border text-slate-400 rounded-lg text-sm no-underline hover:border-slate-500 hover:text-slate-300 transition-colors">
                🏆 Leaderboard
              </Link>
            </div>
          }
        />
      )}

      {/* Signal cards */}
      <div className="flex flex-col gap-3">
        {filteredItems.map(item => {
          const isBuy = item.direction === 'BUY';
          return (
            <div key={item.signal_id}
              className="bg-terminal-surface border border-terminal-border rounded-xl p-3 sm:p-4">
              {/* Card top row */}
              <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 mb-3">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className={`text-2xs font-bold px-2 py-0.5 rounded ${
                    isBuy ? 'bg-green-950 text-green-400' : 'bg-red-950 text-red-400'
                  }`}>
                    {item.direction}
                  </span>
                  <span className="text-slate-100 text-sm sm:text-base font-bold">{item.symbol}</span>
                  <span className="text-2xs bg-blue-950 text-blue-400 px-2 py-0.5 rounded-full">
                    {(item.confidence * 100).toFixed(0)}% conf
                  </span>
                </div>
                <div className="flex items-center gap-2 text-xs text-slate-500">
                  <span>by <strong className="text-slate-400">{item.username}</strong></span>
                  <span className="hidden sm:inline">{new Date(item.created_at).toLocaleTimeString()}</span>
                </div>
              </div>

              {/* Metrics row — wraps on mobile */}
              <div className="flex gap-4 sm:gap-6 mb-3 flex-wrap text-xs">
                <span className="text-slate-500">
                  Entry: <strong className="text-slate-200">${item.entry_price.toFixed(4)}</strong>
                </span>
                <span className={item.pnl >= 0 ? 'text-green-400' : 'text-red-400'}>
                  P&L: <strong>{item.pnl >= 0 ? '+' : ''}{item.pnl.toFixed(2)}%</strong>
                </span>
                <span className="text-slate-500">
                  Copies: <strong className="text-slate-300">{item.copies}</strong>
                </span>
                <span className="text-slate-600 sm:hidden">
                  {new Date(item.created_at).toLocaleTimeString()}
                </span>
              </div>

              {/* Actions */}
              <div className="flex items-center gap-2 flex-wrap">
                <button onClick={() => handleReact(item.signal_id, 'up')}
                  className={`flex items-center gap-1 px-2.5 py-1.5 bg-transparent border border-terminal-border rounded-lg text-xs cursor-pointer transition-colors hover:border-slate-500 ${
                    item.your_reaction === 'up' ? 'text-green-400 border-green-800' : 'text-slate-500'
                  }`}>
                  👍 {item.thumbs_up}
                </button>
                <button onClick={() => handleReact(item.signal_id, 'down')}
                  className={`flex items-center gap-1 px-2.5 py-1.5 bg-transparent border border-terminal-border rounded-lg text-xs cursor-pointer transition-colors hover:border-slate-500 ${
                    item.your_reaction === 'down' ? 'text-red-400 border-red-800' : 'text-slate-500'
                  }`}>
                  👎 {item.thumbs_down}
                </button>
                <button onClick={() => toggleExpand(item.signal_id)}
                  className="flex items-center gap-1 px-2.5 py-1.5 bg-transparent border border-terminal-border rounded-lg text-slate-500 text-xs cursor-pointer hover:border-slate-500 hover:text-slate-300 transition-colors">
                  💬 {item.comment_count} {expanded === item.signal_id ? '▲' : '▼'}
                </button>
                <Link
                  to="/trade"
                  state={{ signal: { symbol: item.symbol, direction: item.direction, entry_price: item.entry_price } }}
                  className={`ml-auto flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-bold no-underline transition-colors ${
                    isBuy
                      ? 'bg-green-500/12 border border-green-500/40 text-green-400 hover:bg-green-500/20'
                      : 'bg-red-500/12 border border-red-500/40 text-red-400 hover:bg-red-500/20'
                  }`}
                >
                  ⚡ Trade
                </Link>
              </div>

              {/* Comments section */}
              {expanded === item.signal_id && (
                <div className="mt-3 pt-3 border-t border-terminal-border flex flex-col gap-2">
                  {(comments[item.signal_id] ?? []).map(c => (
                    <div key={c.comment_id} className="bg-terminal-raised rounded-lg px-3 py-2">
                      <div className="flex items-center gap-2 mb-1">
                        <strong className="text-slate-400 text-xs">{c.username}</strong>
                        <span className="text-slate-600 text-2xs">{new Date(c.created_at).toLocaleTimeString()}</span>
                      </div>
                      <p className="text-slate-300 text-xs leading-relaxed m-0">{c.text}</p>
                    </div>
                  ))}
                  {user && (
                    <div className="mt-1">
                      {typingSignals[item.signal_id] && (
                        <div className="flex items-center gap-1.5 text-slate-600 text-2xs mb-1">
                          {[0,1,2].map(i => (
                            <span key={i} className="w-1 h-1 rounded-full bg-slate-600 inline-block animate-bounce"
                              style={{ animationDelay: `${i * 0.2}s` }} />
                          ))}
                          typing…
                        </div>
                      )}
                      <div className="flex gap-2">
                        <input
                          value={commentText}
                          onChange={e => {
                            setCommentText(e.target.value);
                            setTypingSignals(prev => ({ ...prev, [item.signal_id]: e.target.value.length > 0 }));
                          }}
                          onBlur={() => setTypingSignals(prev => ({ ...prev, [item.signal_id]: false }))}
                          onKeyDown={e => {
                            if (e.key === 'Enter' && !e.shiftKey) {
                              submitComment(item.signal_id);
                              setTypingSignals(prev => ({ ...prev, [item.signal_id]: false }));
                            }
                          }}
                          placeholder="Add a comment…"
                          className="flex-1 bg-terminal-raised border border-terminal-border rounded-lg px-3 py-2 text-slate-200 text-xs outline-none focus:border-blue-500 transition-colors placeholder-slate-600"
                        />
                        <button
                          onClick={() => { submitComment(item.signal_id); setTypingSignals(prev => ({ ...prev, [item.signal_id]: false })); }}
                          disabled={submitting || !commentText.trim()}
                          className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-bold cursor-pointer border-0 transition-colors disabled:opacity-50"
                        >
                          {submitting ? '…' : 'Post'}
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {loading && (
        <div className="text-center text-slate-500 text-sm py-6">Loading signals…</div>
      )}

      {!loading && hasMore && items.length > 0 && (
        <div className="text-center mt-5">
          <button onClick={loadMore}
            className="px-6 py-2.5 bg-terminal-raised border border-terminal-border rounded-lg text-slate-400 text-sm cursor-pointer hover:border-slate-500 hover:text-slate-200 transition-colors">
            Load more
          </button>
        </div>
      )}

      {optedIn !== null && (
        <div className={`mt-5 px-4 py-3 rounded-xl text-xs border ${
          optedIn
            ? 'bg-green-950/30 border-green-900 text-green-400'
            : 'bg-terminal-raised border-terminal-border text-slate-500'
        }`}>
          {optedIn
            ? '✅ Your high-confidence signals are visible to the community. Toggle off to stop sharing.'
            : '💡 Opt in to share your AI signals with the community and build your reputation.'}
        </div>
      )}

      <CrossLinkBar title="Related" className="mt-6" links={[
        { label: '🥇 Leaderboard',  href: '/leaderboard',  color: '#f59e0b' },
        { label: '🔁 Copy Trading', href: '/copy-trading', color: '#34d399' },
        { label: '💬 Chat',         href: '/chat',         color: '#06b6d4' },
        { label: '🛒 Marketplace',  href: '/marketplace',  color: '#a78bfa' },
        { label: '👥 Teams',        href: '/teams',        color: '#60a5fa' },
      ]} />
    </div>
  );
};


export default SocialFeed;
