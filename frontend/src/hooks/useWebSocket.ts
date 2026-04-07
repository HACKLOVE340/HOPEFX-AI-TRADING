/**
 * hooks/useWebSocket.ts
 * Persistent WebSocket connection to /ws/live with:
 * - JWT auth handshake
 * - Auto-reconnect with exponential back-off (max 30s)
 * - Heartbeat / ping-pong (30s interval)
 * - Full message routing → Zustand store
 */

import { useEffect, useRef, useCallback } from 'react';
import { useStore } from '../store';
import type { PriceTick, Position, Signal, AccountMetrics } from '../types';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const _envWsUrl = (import.meta as any).env?.VITE_WS_URL as string | undefined;
const WS_URL: string = _envWsUrl ?? (() => {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}/ws/live`;
})();

const HEARTBEAT_INTERVAL_MS = 30_000;
const INITIAL_RECONNECT_MS  = 1_000;
const MAX_RECONNECT_MS      = 30_000;

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
  data?:          unknown;
  auth_required?: boolean;
  code?:          string;
  message?:       string;
}

export function useWebSocket(enabled = true) {
  const wsRef          = useRef<WebSocket | null>(null);
  const reconnectDelay = useRef(INITIAL_RECONNECT_MS);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const heartbeatTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const unmounted      = useRef(false);
  const authedRef      = useRef(false);

  const store = useStore.getState;

  const handleMessage = useCallback((raw: string) => {
    let msg: WsMessage;
    try { msg = JSON.parse(raw) as WsMessage; }
    catch { return; }

    const {
      setWsStatus, setHeartbeat, setPrice,
      upsertPosition, removePosition, addSignal, setAccount,
    } = store();

    switch (msg.type) {
      case 'connected':
        if (msg.auth_required) {
          const token = store().token;
          if (token && wsRef.current?.readyState === WebSocket.OPEN) {
            wsRef.current.send(JSON.stringify({ type: 'auth', token: `Bearer ${token}` }));
          }
        } else {
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
        wsRef.current?.send(JSON.stringify({
          type: 'subscribe',
          channels: ['prices', 'positions', 'signals', 'account', 'alerts'],
        }));
        break;

      case 'price_tick':
        setPrice(msg.data as PriceTick);
        break;

      case 'position_update':
        upsertPosition(msg.data as Position);
        break;

      case 'position_close':
        removePosition((msg.data as { id: string }).id);
        break;

      case 'signal':
        addSignal(msg.data as Signal);
        break;

      case 'alert_triggered':
        store.getState().addTriggeredAlert(msg.data as import('../store').TriggeredAlert);
        break;

      case 'account_update':
        setAccount(msg.data as AccountMetrics);
        break;

      case 'heartbeat':
        setHeartbeat(Date.now());
        if (wsRef.current?.readyState === WebSocket.OPEN) {
          wsRef.current.send(JSON.stringify({ type: 'ping' }));
        }
        break;

      case 'no_live_feed':
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
    };

    ws.onmessage = (event) => handleMessage(event.data as string);
    ws.onerror = () => { store().setWsStatus('error'); };

    ws.onclose = () => {
      if (heartbeatTimer.current) clearInterval(heartbeatTimer.current);
      if (unmounted.current) return;
      store().setWsStatus('disconnected');
      authedRef.current = false;
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
