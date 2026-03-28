/**
 * useWebSocket
 * ============
 * Manages a persistent WebSocket connection to the HopeFX backend.
 *
 * Features:
 * - Auto-reconnect with exponential back-off (max 30 s)
 * - Heartbeat / ping-pong (30 s interval)
 * - Message routing: price | position | signal | account | heartbeat
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
    | 'price_tick'
    | 'position_update'
    | 'position_close'
    | 'signal'
    | 'account_update'
    | 'heartbeat'
    | 'error';
  data?: unknown;
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function useWebSocket(enabled = true) {
  const wsRef            = useRef<WebSocket | null>(null);
  const reconnectDelay   = useRef(INITIAL_RECONNECT_MS);
  const reconnectTimer   = useRef<ReturnType<typeof setTimeout> | null>(null);
  const heartbeatTimer   = useRef<ReturnType<typeof setInterval> | null>(null);
  const unmounted        = useRef(false);

  const { setWsStatus, setHeartbeat, setPrice, upsertPosition, removePosition, addSignal, setAccount } =
    useStore.getState();

  const handleMessage = useCallback((raw: string) => {
    let msg: WsMessage;
    try {
      msg = JSON.parse(raw) as WsMessage;
    } catch {
      return;
    }

    switch (msg.type) {
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
        break;

      default:
        break;
    }
  }, [setPrice, upsertPosition, removePosition, addSignal, setAccount, setHeartbeat]);

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

    setWsStatus('connecting');

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      if (unmounted.current) { ws.close(); return; }
      setWsStatus('connected');
      reconnectDelay.current = INITIAL_RECONNECT_MS;
      startHeartbeat(ws);

      // Subscribe to all channels
      ws.send(JSON.stringify({
        type: 'subscribe',
        channels: ['prices', 'positions', 'signals', 'account'],
      }));
    };

    ws.onmessage = (event) => handleMessage(event.data as string);

    ws.onerror = () => {
      setWsStatus('error');
    };

    ws.onclose = () => {
      if (heartbeatTimer.current) clearInterval(heartbeatTimer.current);
      if (unmounted.current) return;

      setWsStatus('disconnected');

      // Exponential back-off reconnect
      const delay = reconnectDelay.current;
      reconnectDelay.current = Math.min(delay * 2, MAX_RECONNECT_MS);
      reconnectTimer.current = setTimeout(connect, delay);
    };
  }, [handleMessage, setWsStatus, startHeartbeat]);

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
