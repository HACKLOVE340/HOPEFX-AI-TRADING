/**
 * Notifications — real-time notification centre.
 * Mobile-first: full-width cards, touch-friendly dismiss/action buttons.
 *
 * Wires to:
 *   GET    /api/notifications          — paginated list
 *   POST   /api/notifications/:id/read — mark single read
 *   POST   /api/notifications/read-all — mark all read
 *   DELETE /api/notifications/:id      — delete single
 *   WS     /ws/notifications           — real-time push
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { notificationsApi } from '../hooks/useApi';
import { useStore } from '../store';
import { getWsBase } from '../lib/utils';
import { PageHeader } from '../components/PageHeader';
import { CrossLinkBar } from '../components/CrossLinkBar';
import { EmptyState } from '../components/EmptyState';
import { Spinner } from '../components/Spinner';

interface Notification {
  id: string;
  type: string;
  title: string;
  message: string;
  read: boolean;
  created_at: string;
  link?: string;
}

const TYPE_ICON: Record<string, string> = {
  trade:    '📈',
  alert:    '🚨',
  system:   '⚙️',
  social:   '👥',
  billing:  '💳',
  security: '🔒',
  ai:       '🤖',
};

const TYPE_COLOR: Record<string, string> = {
  trade:    '#4ade80',
  alert:    '#f87171',
  system:   '#94a3b8',
  social:   '#a78bfa',
  billing:  '#fbbf24',
  security: '#f97316',
  ai:       '#06b6d4',
};

const PAGE_SIZE = 20;

const NotificationsPage: React.FC = () => {
  const navigate = useNavigate();
  const [items, setItems]           = useState<Notification[]>([]);
  const [loading, setLoading]       = useState(true);
  const [page, setPage]             = useState(1);
  const [hasMore, setHasMore]       = useState(false);
  const [filter, setFilter]         = useState<'all' | 'unread'>('all');
  const [markingAll, setMarkingAll] = useState(false);
  const wsRef      = useRef<WebSocket | null>(null);
  const mountedRef = useRef(true);
  const token      = useStore(s => s.token);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const load = useCallback(async (pg: number, flt: 'all' | 'unread') => {
    setLoading(true);
    try {
      const res = await notificationsApi.list({ page: pg, limit: PAGE_SIZE, unread_only: flt === 'unread' });
      if (!mountedRef.current) return;
      const d = res.data as { notifications?: Notification[]; has_more?: boolean } | Notification[];
      const notifs = Array.isArray(d) ? d : (d.notifications ?? []);
      const more   = Array.isArray(d) ? notifs.length === PAGE_SIZE : (d.has_more ?? false);
      setItems(pg === 1 ? notifs : prev => [...prev, ...notifs]);
      setHasMore(more);
      setPage(pg);
    } catch { /* non-fatal */ }
    finally { if (mountedRef.current) setLoading(false); }
  }, []);

  useEffect(() => { load(1, filter); }, [load, filter]);

  // Real-time WS push
  useEffect(() => {
    if (!token) return;
    let ws: WebSocket | null = null;
    try {
      ws = new WebSocket(`${getWsBase()}/ws/notifications?token=${token}`);
      wsRef.current = ws;
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data as string) as { type?: string; notification?: Notification };
          if (msg.type === 'notification' && msg.notification) {
            setItems(prev => [msg.notification!, ...prev]);
          }
        } catch { /* ignore */ }
      };
    } catch { /* WS unavailable */ }
    return () => { ws?.close(); wsRef.current = null; };
  }, [token]);

  const markRead = async (id: string) => {
    try {
      await notificationsApi.markRead(id);
      setItems(prev => prev.map(n => n.id === id ? { ...n, read: true } : n));
    } catch { /* non-fatal */ }
  };

  const markAllRead = async () => {
    setMarkingAll(true);
    try {
      await notificationsApi.markAllRead();
      setItems(prev => prev.map(n => ({ ...n, read: true })));
    } catch { /* non-fatal */ }
    finally { setMarkingAll(false); }
  };

  const deleteNotif = async (id: string) => {
    try {
      await notificationsApi.delete(id);
      setItems(prev => prev.filter(n => n.id !== id));
    } catch { /* non-fatal */ }
  };

  const unreadCount = items.filter(n => !n.read).length;

  return (
    <div className="max-w-2xl mx-auto px-3 sm:px-6 py-4 sm:py-8">
      <PageHeader
        title="Notifications"
        subtitle="Real-time alerts and platform updates"
        breadcrumbs={[
          { label: 'Dashboard', href: '/dashboard' },
          { label: 'Notifications' },
        ]}
        badge={
          unreadCount > 0
            ? <span className="text-xs bg-blue-600 text-white rounded-full px-2 py-0.5 font-bold">
                {unreadCount}
              </span>
            : undefined
        }
        actions={
          <div className="flex gap-2 flex-wrap">
            {(['all', 'unread'] as const).map(f => (
              <button key={f} onClick={() => setFilter(f)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold border cursor-pointer transition-colors ${
                  filter === f
                    ? 'bg-blue-500/15 border-blue-500 text-blue-400'
                    : 'bg-terminal-raised border-terminal-border text-slate-500 hover:text-slate-300'
                }`}>
                {f === 'all' ? 'All' : `Unread (${unreadCount})`}
              </button>
            ))}
            <button
              onClick={markAllRead}
              disabled={markingAll || unreadCount === 0}
              className="px-3 py-1.5 bg-terminal-raised border border-terminal-border rounded-lg text-slate-400 text-xs cursor-pointer hover:text-slate-200 transition-colors disabled:opacity-40"
            >
              {markingAll ? '…' : '✓ Mark all read'}
            </button>
          </div>
        }
      />

      <CrossLinkBar links={[
        { label: 'Price Alerts',          href: '/alerts',   icon: '🚨', color: '#f87171' },
        { label: 'Notification Settings', href: '/settings', icon: '⚙️', color: '#94a3b8' },
        { label: 'Chat',                  href: '/chat',     icon: '💬', color: '#06b6d4' },
        { label: 'Dashboard',             href: '/dashboard',icon: '📊', color: '#4ade80' },
      ]} className="mb-5" />

      {/* Loading state */}
      {loading && page === 1 && (
        <div className="flex justify-center py-12">
          <Spinner size="lg" />
        </div>
      )}

      {/* Empty state */}
      {!loading && items.length === 0 && (
        <EmptyState
          icon="🔔"
          title="No notifications"
          description={
            filter === 'unread'
              ? "No unread notifications — you're all caught up!"
              : 'Notifications for trades, alerts, and system events will appear here.'
          }
          action={
            filter === 'unread'
              ? <button onClick={() => setFilter('all')}
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm font-semibold cursor-pointer border-0 transition-colors">
                  View all
                </button>
              : undefined
          }
        />
      )}

      {/* Notification list */}
      <div className="flex flex-col gap-2">
        {items.map(n => {
          const typeColor = TYPE_COLOR[n.type] ?? '#94a3b8';
          return (
            <div
              key={n.id}
              onClick={() => { if (!n.read) markRead(n.id); }}
              className={`rounded-xl border transition-colors ${
                n.read
                  ? 'bg-terminal-bg border-terminal-border'
                  : 'bg-blue-950/20 border-blue-900/50 cursor-pointer'
              }`}
            >
              <div className="flex gap-3 p-3 sm:p-4">
                {/* Type icon */}
                <div
                  className="w-9 h-9 sm:w-10 sm:h-10 rounded-xl flex items-center justify-center text-lg flex-shrink-0 mt-0.5"
                  style={{ background: `${typeColor}18`, color: typeColor }}
                >
                  {TYPE_ICON[n.type] ?? '🔔'}
                </div>

                {/* Content */}
                <div className="flex-1 min-w-0">
                  {/* Title row */}
                  <div className="flex items-start justify-between gap-2">
                    <div className={`text-sm leading-snug ${n.read ? 'font-medium text-slate-300' : 'font-bold text-slate-100'}`}>
                      {n.title}
                    </div>
                    {/* Actions: unread dot + timestamp + delete */}
                    <div className="flex items-center gap-2 flex-shrink-0">
                      {!n.read && (
                        <span className="w-2 h-2 rounded-full bg-blue-500 flex-shrink-0" />
                      )}
                      <span className="text-slate-600 text-2xs hidden sm:block">
                        {new Date(n.created_at).toLocaleString()}
                      </span>
                      <button
                        onClick={e => { e.stopPropagation(); deleteNotif(n.id); }}
                        className="text-slate-600 hover:text-slate-400 bg-transparent border-0 cursor-pointer text-lg leading-none p-0.5 min-w-[24px] min-h-[24px] flex items-center justify-center rounded transition-colors"
                        title="Delete"
                        aria-label="Delete notification"
                      >
                        ×
                      </button>
                    </div>
                  </div>

                  {/* Timestamp on mobile */}
                  <div className="text-slate-600 text-2xs mt-0.5 sm:hidden">
                    {new Date(n.created_at).toLocaleString()}
                  </div>

                  {/* Message */}
                  <div className="text-slate-400 text-xs sm:text-sm mt-1 leading-relaxed">
                    {n.message}
                  </div>

                  {/* Action links */}
                  <div className="flex gap-2 mt-2 flex-wrap">
                    {n.link && (
                      <button
                        onClick={e => {
                          e.stopPropagation();
                          if (n.link!.startsWith('http')) {
                            window.open(n.link, '_blank', 'noopener,noreferrer');
                          } else {
                            navigate(n.link!);
                          }
                        }}
                        className="text-blue-400 text-xs bg-transparent border-0 cursor-pointer p-0 hover:text-blue-300 transition-colors"
                      >
                        View details →
                      </button>
                    )}
                    {(n.type === 'trade' || n.type === 'alert' || n.type === 'ai') && (
                      <button
                        onClick={e => { e.stopPropagation(); navigate('/trade'); }}
                        className="bg-blue-500/10 border border-blue-500/30 rounded-md text-blue-400 text-2xs font-bold px-2 py-0.5 cursor-pointer hover:bg-blue-500/20 transition-colors"
                      >
                        ⚡ Trade
                      </button>
                    )}
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Load more */}
      {hasMore && (
        <div className="text-center mt-4">
          <button
            onClick={() => load(page + 1, filter)}
            disabled={loading}
            className="px-6 py-2.5 bg-terminal-raised border border-terminal-border rounded-lg text-slate-400 text-sm cursor-pointer hover:border-slate-500 hover:text-slate-200 transition-colors disabled:opacity-50"
          >
            {loading ? 'Loading…' : 'Load more'}
          </button>
        </div>
      )}
    </div>
  );
};

export default NotificationsPage;
