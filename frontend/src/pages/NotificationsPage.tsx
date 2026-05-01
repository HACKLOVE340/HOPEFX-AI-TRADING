/**
 * Notifications — real-time notification centre.
 *
 * Wires to:
 *   GET  /api/notifications          — paginated list
 *   POST /api/notifications/:id/read — mark single read
 *   POST /api/notifications/read-all — mark all read
 *   DELETE /api/notifications/:id    — delete single
 *   WS   /ws/notifications           — real-time push
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { notificationsApi } from '../hooks/useApi';
import { useStore } from '../store';
import { getWsBase } from '../lib/utils';

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

const PAGE_SIZE = 20;

const NotificationsPage: React.FC = () => {
  const [items, setItems]         = useState<Notification[]>([]);
  const [loading, setLoading]     = useState(true);
  const [page, setPage]           = useState(1);
  const [hasMore, setHasMore]     = useState(false);
  const [filter, setFilter]       = useState<'all' | 'unread'>('all');
  const [markingAll, setMarkingAll] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const mountedRef = useRef(true);
  const token = useStore(s => s.token);

  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

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
    <div style={{ maxWidth: 760, margin: '0 auto', padding: '24px 16px' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 800, color: '#f1f5f9', margin: 0 }}>
            Notifications {unreadCount > 0 && (
              <span style={{ fontSize: 14, background: '#3b82f6', color: '#fff', borderRadius: 12, padding: '2px 8px', marginLeft: 8 }}>
                {unreadCount}
              </span>
            )}
          </h1>
          <p style={{ fontSize: 13, color: '#64748b', margin: '4px 0 0' }}>Real-time alerts and updates</p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {(['all', 'unread'] as const).map(f => (
            <button key={f} onClick={() => setFilter(f)} style={{
              background: filter === f ? '#1e3a5f' : '#1e293b',
              border: `1px solid ${filter === f ? '#3b82f6' : '#334155'}`,
              borderRadius: 8, color: filter === f ? '#60a5fa' : '#64748b',
              cursor: 'pointer', fontSize: 13, fontWeight: 600, padding: '6px 14px',
            }}>
              {f === 'all' ? 'All' : `Unread (${unreadCount})`}
            </button>
          ))}
          <button onClick={markAllRead} disabled={markingAll || unreadCount === 0} style={{
            background: '#1e293b', border: '1px solid #334155', borderRadius: 8,
            color: '#94a3b8', cursor: 'pointer', fontSize: 13, padding: '6px 14px',
          }}>
            {markingAll ? '…' : '✓ Mark all read'}
          </button>
        </div>
      </div>

      {/* List */}
      {loading && page === 1 && (
        <div style={{ textAlign: 'center', color: '#64748b', padding: 48 }}>Loading…</div>
      )}
      {!loading && items.length === 0 && (
        <div style={{ textAlign: 'center', color: '#475569', padding: 64 }}>
          <div style={{ fontSize: 40, marginBottom: 12 }}>🔔</div>
          <div style={{ fontSize: 16, fontWeight: 600, color: '#64748b' }}>No notifications</div>
          <div style={{ fontSize: 13, color: '#475569', marginTop: 4 }}>You're all caught up!</div>
        </div>
      )}
      {items.map(n => (
        <div
          key={n.id}
          onClick={() => { if (!n.read) markRead(n.id); }}
          style={{
            background: n.read ? '#0d1421' : '#0f1e35',
            border: `1px solid ${n.read ? '#1e293b' : '#1e3a5f'}`,
            borderRadius: 10, padding: '14px 16px', marginBottom: 10,
            cursor: n.read ? 'default' : 'pointer',
            display: 'flex', gap: 14, alignItems: 'flex-start',
            transition: 'background 0.2s',
          }}
        >
          <div style={{ fontSize: 22, flexShrink: 0, marginTop: 2 }}>
            {TYPE_ICON[n.type] ?? '🔔'}
          </div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
              <div style={{ fontWeight: n.read ? 500 : 700, color: '#f1f5f9', fontSize: 14 }}>{n.title}</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
                {!n.read && <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#3b82f6', display: 'inline-block' }} />}
                <span style={{ fontSize: 11, color: '#64748b' }}>{new Date(n.created_at).toLocaleString()}</span>
                <button
                  onClick={e => { e.stopPropagation(); deleteNotif(n.id); }}
                  style={{ background: 'transparent', border: 'none', color: '#475569', cursor: 'pointer', fontSize: 16, lineHeight: 1, padding: 0 }}
                  title="Delete"
                >×</button>
              </div>
            </div>
            <div style={{ fontSize: 13, color: '#94a3b8', marginTop: 4, lineHeight: 1.5 }}>{n.message}</div>
            {n.link && (
              <a href={n.link} style={{ fontSize: 12, color: '#3b82f6', marginTop: 6, display: 'inline-block' }}>
                View details →
              </a>
            )}
          </div>
        </div>
      ))}

      {hasMore && (
        <div style={{ textAlign: 'center', marginTop: 16 }}>
          <button
            onClick={() => load(page + 1, filter)}
            disabled={loading}
            style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, color: '#94a3b8', cursor: 'pointer', fontSize: 13, padding: '8px 24px' }}
          >
            {loading ? 'Loading…' : 'Load more'}
          </button>
        </div>
      )}
    </div>
  );
};

export default NotificationsPage;
