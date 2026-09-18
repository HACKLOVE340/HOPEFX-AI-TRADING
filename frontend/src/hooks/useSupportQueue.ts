/**
 * The operator queue's live channel — and, more importantly, which source is
 * actually feeding the page.
 *
 * `support_queue` is a PRIVILEGED channel: the server checks the connection's
 * role on subscribe and returns what it refused rather than dropping it
 * silently (see `LiveConnectionManager._PRIVILEGED_CHANNELS`). That refusal has
 * to reach the operator, because the failure mode this whole feature guards
 * against is a console that stopped updating looking exactly like a quiet
 * queue.
 *
 * So this hook reports one of three sources and never guesses:
 *
 *   live     — a frame arrived on the socket within STALE_AFTER_MS
 *   poll     — the socket is not delivering; React Query's interval is
 *   refused  — the server said this role may not join the channel
 *
 * It owns its own socket rather than joining the app-wide one. The app-wide
 * connection subscribes for every signed-in user, and asking it to add a
 * channel only admins may join would make the server refuse on every ordinary
 * session — noise that trains people to ignore the refusal that matters.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

export type LiveSource = 'live' | 'poll' | 'refused';

export interface QueueLive {
  source: LiveSource;
  /** Epoch ms of the last frame, or 0 when none has ever arrived. */
  lastEventAt: number;
}

/** No frame for this long and the socket is no longer what is feeding the page. */
const STALE_AFTER_MS = 25_000;
const CHANNEL = 'support_queue';

function wsUrl(): string {
  const base = import.meta.env.VITE_WS_URL as string | undefined;
  if (base) return base;
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}/ws/live`;
}

export function useSupportQueue(onEvent: (e: Record<string, unknown>) => void): QueueLive {
  const [source, setSource] = useState<LiveSource>('poll');
  const [lastEventAt, setLastEventAt] = useState(0);
  const wsRef = useRef<WebSocket | null>(null);
  // The callback changes on every render of the page; keeping it in a ref stops
  // the socket being torn down and rebuilt each time.
  const cb = useRef(onEvent);
  cb.current = onEvent;

  const markLive = useCallback(() => {
    setLastEventAt(Date.now());
    setSource((s) => (s === 'refused' ? s : 'live'));
  }, []);

  useEffect(() => {
    let closed = false;
    let ws: WebSocket;
    try {
      ws = new WebSocket(wsUrl());
    } catch {
      // No socket at all is the poll case, not an error state: React Query
      // keeps the queue current either way.
      setSource('poll');
      return;
    }
    wsRef.current = ws;

    ws.onopen = () => {
      const token = localStorage.getItem('access_token');
      if (token) ws.send(JSON.stringify({ type: 'auth', token: `Bearer ${token}` }));
      ws.send(JSON.stringify({ type: 'subscribe', channels: [CHANNEL] }));
    };

    ws.onmessage = (ev) => {
      let msg: Record<string, unknown>;
      try { msg = JSON.parse(String(ev.data)) as Record<string, unknown>; }
      catch { return; }

      if (msg.type === 'subscribed') {
        const refused = Array.isArray(msg.refused) ? (msg.refused as string[]) : [];
        const granted = Array.isArray(msg.channels) ? (msg.channels as string[]) : [];
        // The server tells us what it granted, not what we asked for.
        if (refused.includes(CHANNEL)) { setSource('refused'); return; }
        if (granted.includes(CHANNEL)) { setSource('live'); setLastEventAt(Date.now()); }
        return;
      }
      if (msg.type === CHANNEL) {
        markLive();
        const data = msg.data;
        if (data && typeof data === 'object') cb.current(data as Record<string, unknown>);
      }
    };

    ws.onclose = () => { if (!closed) setSource((s) => (s === 'refused' ? s : 'poll')); };
    ws.onerror = () => { setSource((s) => (s === 'refused' ? s : 'poll')); };

    return () => { closed = true; try { ws.close(); } catch { /* already gone */ } };
  }, [markLive]);

  // A socket that is open but silent is not feeding the page. Without this the
  // pill would read "live" for as long as the connection object survived.
  useEffect(() => {
    const t = setInterval(() => {
      setSource((s) => {
        if (s !== 'live') return s;
        return Date.now() - lastEventAt > STALE_AFTER_MS ? 'poll' : s;
      });
    }, 5_000);
    return () => clearInterval(t);
  }, [lastEventAt]);

  return { source, lastEventAt };
}
