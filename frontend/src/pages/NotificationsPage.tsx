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
import { Bell, Settings, Zap } from 'lucide-react';
import { PageShell } from '../components/system/PageShell';
import { useNavigate } from 'react-router-dom';
import { notificationsApi } from '../hooks/useApi';
import { useStore } from '../store';
import { fmtDateTime, extractApiError } from '../lib/utils';
import { openAuthenticatedWebSocket } from '../lib/ws';
import { ActionBanner } from '../components/ActionBanner';
import { useVoice } from '../hooks/useVoice';
import { useVoiceAlerts } from '../lib/voicePrefs';

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
  const navigate = useNavigate();
  const [items, setItems]         = useState<Notification[]>([]);
  const [loading, setLoading]     = useState(true);
  const [page, setPage]           = useState(1);
  const [hasMore, setHasMore]     = useState(false);
  const [filter, setFilter]       = useState<'all' | 'unread'>('all');
  const [markingAll, setMarkingAll] = useState(false);
  // A failed list load must not render as "No notifications", and a failed
  // mark-read/delete must not look like a no-op click.
  const [err, setErr] = useState('');
  const wsRef = useRef<WebSocket | null>(null);
  const mountedRef = useRef(true);
  const token = useStore(s => s.token);
  const voice = useVoice();
  const [voiceAlerts, setVoiceAlerts] = useVoiceAlerts();

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
      setErr('');
    } catch (e) {
      if (mountedRef.current) setErr(extractApiError(e, 'Could not load notifications'));
    }
    finally { if (mountedRef.current) setLoading(false); }
  }, []);

  useEffect(() => { load(1, filter); }, [load, filter]);

  // Real-time WS push
  useEffect(() => {
    if (!token) return;
    let ws: WebSocket | null = null;
    try {
      ws = openAuthenticatedWebSocket('/ws/notifications', token);
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
      setErr('');
    } catch (e) {
      setErr(extractApiError(e, 'Could not mark that notification as read'));
    }
  };

  const markAllRead = async () => {
    setMarkingAll(true);
    try {
      await notificationsApi.markAllRead();
      setItems(prev => prev.map(n => ({ ...n, read: true })));
      setErr('');
    } catch (e) {
      setErr(extractApiError(e, 'Could not mark all notifications as read'));
    }
    finally { setMarkingAll(false); }
  };

  const deleteNotif = async (id: string) => {
    try {
      await notificationsApi.delete(id);
      setItems(prev => prev.filter(n => n.id !== id));
      setErr('');
    } catch (e) {
      setErr(extractApiError(e, 'Could not delete that notification'));
    }
  };

  const unreadCount = items.filter(n => !n.read).length;

  return (
    <PageShell
      title="Notifications"
      icon={Bell}
      subtitle="Real-time alerts and updates"
      width="standard"
      /* The unread count keeps its place beside the title. It was a span inside
         the h1 and PageShell has a slot for exactly this; a count that moved
         into the body would stop answering the question the page is opened to
         answer. The literal blue and white are gone with it — they were the
         last two colour literals in this file. */
      badge={unreadCount > 0 ? (
        <span style={{
          fontSize: 'var(--fs-label)', background: 'var(--link)', color: 'var(--bg)',
          borderRadius: 12, padding: '2px 8px', fontWeight: 700,
        }}>
          {unreadCount}
        </span>
      ) : undefined}
      actions={(
        <div style={{ display: 'flex', gap: 8 }}>
          {voice.ttsSupported && (
            <button
              onClick={() => {
                const next = !voiceAlerts;
                setVoiceAlerts(next);
                if (next) voice.speak('Spoken alerts enabled');
                else voice.cancelSpeak();
              }}
              title={voiceAlerts ? 'Disable spoken alerts' : 'Read risk and fill alerts aloud'}
              aria-pressed={voiceAlerts}
              style={{
                padding: '6px 13px',
                background: voiceAlerts ? 'rgba(96,165,250,0.14)' : 'rgba(100,116,139,0.12)',
                border: `1px solid ${voiceAlerts ? 'rgba(96,165,250,0.5)' : 'rgba(100,116,139,0.35)'}`,
                borderRadius: 7, color: voiceAlerts ? 'var(--link)' : 'var(--text-dim)', fontSize: 'var(--fs-body)', fontWeight: 700, cursor: 'pointer',
              }}>
              {voiceAlerts ? '🔊 Spoken alerts on' : '🔈 Spoken alerts off'}
            </button>
          )}
          <button onClick={() => navigate('/settings')}
            style={{ padding: '6px 13px', background: 'rgba(100,116,139,0.12)', border: '1px solid rgba(100,116,139,0.35)', borderRadius: 7, color: 'var(--text-dim)', fontSize: 'var(--fs-body)', fontWeight: 700, cursor: 'pointer' }}>
            <Settings size="1em" aria-hidden /> Settings
          </button>
          {(['all', 'unread'] as const).map(f => (
            <button key={f} onClick={() => setFilter(f)} style={{
              background: filter === f ? '#1e3a5f' : 'var(--raised)',
              border: `1px solid ${filter === f ? '#3b82f6' : '#334155'}`,
              borderRadius: 8, color: filter === f ? 'var(--link)' : 'var(--text-muted)',
              cursor: 'pointer', fontSize: 'var(--fs-body)', fontWeight: 600, padding: '6px 14px',
            }}>
              {f === 'all' ? 'All' : `Unread (${unreadCount})`}
            </button>
          ))}
          <button onClick={markAllRead} disabled={markingAll || unreadCount === 0} style={{
            background: 'var(--raised)', border: '1px solid var(--border-strong)', borderRadius: 8,
            color: 'var(--text-dim)', cursor: 'pointer', fontSize: 'var(--fs-body)', padding: '6px 14px',
          }}>
            {markingAll ? '…' : '✓ Mark all read'}
          </button>
        </div>
      )}
    >
      <ActionBanner message={err} ok={false} onDismiss={() => setErr('')} />

      {/* List */}
      {loading && page === 1 && (
        <div style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 48 }}>Loading…</div>
      )}
      {!loading && items.length === 0 && !err && (
        <div style={{ textAlign: 'center', color: 'var(--text-faint)', padding: 64 }}>
          <div style={{ fontSize: 40, marginBottom: 12 }}><Bell size="1em" aria-hidden /></div>
          <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--text-muted)' }}>No notifications</div>
          <div style={{ fontSize: 'var(--fs-body)', color: 'var(--text-faint)', marginTop: 4 }}>You're all caught up!</div>
        </div>
      )}
      {items.map(n => (
        <div
          key={n.id}
          onClick={() => { if (!n.read) markRead(n.id); }}
          style={{
            background: n.read ? 'var(--surface)' : '#0f1e35',
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
              <div style={{ fontWeight: n.read ? 500 : 700, color: 'var(--text-strong)', fontSize: 14 }}>{n.title}</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
                {!n.read && <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#3b82f6', display: 'inline-block' }} />}
                <span style={{ fontSize: 'var(--fs-label)', color: 'var(--text-muted)' }}>{fmtDateTime(n.created_at)}</span>
                <button
                  onClick={e => { e.stopPropagation(); deleteNotif(n.id); }}
                  style={{ background: 'transparent', border: 'none', color: 'var(--text-faint)', cursor: 'pointer', fontSize: 16, lineHeight: 1, padding: 0 }}
                  title="Delete"
                >×</button>
              </div>
            </div>
            <div style={{ fontSize: 'var(--fs-body)', color: 'var(--text-dim)', marginTop: 4, lineHeight: 1.5 }}>{n.message}</div>
            <div style={{ display: 'flex', gap: 8, marginTop: 6, alignItems: 'center' }}>
              {n.link && (
                <a href={n.link} style={{ fontSize: 'var(--fs-body)', color: '#3b82f6', display: 'inline-block' }}>
                  View details →
                </a>
              )}
              {(n.type === 'trade' || n.type === 'alert' || n.type === 'ai') && (
                <button
                  onClick={e => { e.stopPropagation(); navigate('/trade'); }}
                  style={{ background: 'rgba(96,165,250,0.1)', border: '1px solid rgba(96,165,250,0.3)', borderRadius: 5, color: 'var(--link)', fontSize: 'var(--fs-label)', fontWeight: 700, padding: '3px 9px', cursor: 'pointer' }}
                >
                  <Zap size="1em" aria-hidden /> Trade
                </button>
              )}
            </div>
          </div>
        </div>
      ))}

      {hasMore && (
        <div style={{ textAlign: 'center', marginTop: 16 }}>
          <button
            onClick={() => load(page + 1, filter)}
            disabled={loading}
            style={{ background: 'var(--raised)', border: '1px solid var(--border-strong)', borderRadius: 8, color: 'var(--text-dim)', cursor: 'pointer', fontSize: 'var(--fs-body)', padding: '8px 24px' }}
          >
            {loading ? 'Loading…' : 'Load more'}
          </button>
        </div>
      )}
    </PageShell>
  );
};

export default NotificationsPage;
