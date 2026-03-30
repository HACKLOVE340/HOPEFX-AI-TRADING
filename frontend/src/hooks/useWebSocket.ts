/**
 * useWebSocket
 * ============
 * Manages a persistent WebSocket connection to the HopeFX backend /ws/live.
 *
 * Features:
 * - JWT auth handshake on connect (backend requires X-API-Key or Bearer token)
 * - Auto-reconnect with exponential back-off (max 30 s)
 * - Heartbeat / ping-pong (30 s interval)
 * - Message routing: price_tick | position_update | position_close |
 *   signal | account_update | heartbeat | no_live_feed | connected | auth_ok
 * - Dispatches directly into Zustand store
 * - Cleans up on unmount
 */

import { useEffect, useRef, useCallback } from 'react';
import { useStore } from '../store';

// Derive the WebSocket URL from the current page origin so it works through
// the Vite dev-server proxy (/ws → ws://localhost:8000) and in production
// without hardcoding a port.  VITE_WS_URL overrides everything when set.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const _envWsUrl = (import.meta as any).env?.VITE_WS_URL as string | undefined;
const WS_URL: string = _envWsUrl ?? (() => {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}/ws/live`;
})();

const HEARTBEAT_INTERVAL_MS = 30_000;
const INITIAL_RECONNECT_MS  = 1_000;
const MAX_RECONNECT_MS      = 30_000;

// ─── Message types from backend ───────────────────────────────────────────────

interface WsMessage {
  type:
    | 'connected'
    | 'auth_ok'
    | 'price_tick'
    | 'position_update'
    | 'position_close'
    | 'signal'
    | 'account_update'
    | 'heartbeat'
    | 'no_live_feed'
    | 'error';
  data?: unknown;
  auth_required?: boolean;
  user_id?: string;
  code?: string;
  message?: string;
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function useWebSocket(enabled = true) {
  const wsRef            = useRef<WebSocket | null>(null);
  const reconnectDelay   = useRef(INITIAL_RECONNECT_MS);
  const reconnectTimer   = useRef<ReturnType<typeof setTimeout> | null>(null);
  const heartbeatTimer   = useRef<ReturnType<typeof setInterval> | null>(null);
  const unmounted        = useRef(false);
  const authedRef        = useRef(false);

  const store = useStore.getState;

  const handleMessage = useCallback((raw: string) => {
    let msg: WsMessage;
    try {
      msg = JSON.parse(raw) as WsMessage;
    } catch {
      return;
    }

    const { setWsStatus, setHeartbeat, setPrice, upsertPosition,
            removePosition, addSignal, setAccount } = store();

    switch (msg.type) {
      case 'connected':
        // Server sent connected — if auth required, send JWT immediately
        if (msg.auth_required) {
          const token = store().token;
          if (token && wsRef.current?.readyState === WebSocket.OPEN) {
            wsRef.current.send(JSON.stringify({
              type: 'auth',
              token: `Bearer ${token}`,
            }));
          }
        } else {
          // No auth required — mark connected and subscribe immediately
          authedRef.current = true;
          setWsStatus('connected');
          wsRef.current?.send(JSON.stringify({
            type: 'subscribe',
            channels: ['prices', 'positions', 'signals', 'account'],
          }));
        }
        break;

      case 'auth_ok':
        authedRef.current = true;
        setWsStatus('connected');
        // Subscribe to all channels after successful auth
        wsRef.current?.send(JSON.stringify({
          type: 'subscribe',
          channels: ['prices', 'positions', 'signals', 'account'],
        }));
        break;

      case 'price_tick':
        setPrice(msg.data as Parameters<typeof setPrice>[0]);
        break;

      case 'position_update':
        upsertPosition(msg.data as Parameters<typeof upsertPosition>[0]);
        break;

      case 'position_close':
        removePosition((msg.data as { id: string }).id);
        break;

      case 'signal':
        addSignal(msg.data as Parameters<typeof addSignal>[0]);
        break;

      case 'account_update':
        setAccount(msg.data as Parameters<typeof setAccount>[0]);
        break;

      case 'heartbeat':
        setHeartbeat(Date.now());
        // Respond with ping to reset server-side miss counter
        if (wsRef.current?.readyState === WebSocket.OPEN) {
          wsRef.current.send(JSON.stringify({ type: 'ping' }));
        }
        break;

      case 'no_live_feed':
        // Backend has no live broker connected — update status but don't disconnect
        console.info('[WS] No live broker feed:', msg.message);
        break;

      case 'error':
        console.warn('[WS] Server error:', msg.code, msg.message);
        if (msg.code === 'AUTH_FAILED' || msg.code === 'AUTH_REQUIRED') {
          setWsStatus('error');
        }
        break;

      default:
        break;
    }
  }, [store]);

  const startHeartbeat = useCallback((ws: WebSocket) => {
    if (heartbeatTimer.current) clearInterval(heartbeatTimer.current);
    heartbeatTimer.current = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'ping' }));
      }
    }, HEARTBEAT_INTERVAL_MS);
  }, []);

  const connect = useCallback(() => {
    if (unmounted.current) return;
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    store().setWsStatus('connecting');
    authedRef.current = false;

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      if (unmounted.current) { ws.close(); return; }
      reconnectDelay.current = INITIAL_RECONNECT_MS;
      startHeartbeat(ws);
      // Auth handshake is triggered by the 'connected' message from server
    };

    ws.onmessage = (event) => handleMessage(event.data as string);

    ws.onerror = () => {
      store().setWsStatus('error');
    };

    ws.onclose = () => {
      if (heartbeatTimer.current) clearInterval(heartbeatTimer.current);
      if (unmounted.current) return;

      store().setWsStatus('disconnected');
      authedRef.current = false;

      // Exponential back-off reconnect
      const delay = reconnectDelay.current;
      reconnectDelay.current = Math.min(delay * 2, MAX_RECONNECT_MS);
      reconnectTimer.current = setTimeout(connect, delay);
    };
  }, [handleMessage, store, startHeartbeat]);

  useEffect(() => {
    if (!enabled) return;
    unmounted.current = false;
    connect();

    return () => {
      unmounted.current = true;
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      if (heartbeatTimer.current) clearInterval(heartbeatTimer.current);
      wsRef.current?.close();
    };
  }, [enabled, connect]);

  const send = useCallback((msg: object) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg));
    }
  }, []);

  return { send };
}
