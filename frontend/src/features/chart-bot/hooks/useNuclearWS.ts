/**
 * chart-bot/hooks/useNuclearWS.ts
 * WebSocket hook for the nuclear dashboard — connects to /ws/nuclear,
 * routes messages into the nuclear Zustand store, and exposes typed
 * subscription helpers.
 *
 * Features:
 * - Auto-reconnect with exponential back-off (1s → 30s)
 * - JWT auth handshake on connect
 * - 30s heartbeat with pong tracking
 * - Typed message routing into useNuclearStore
 * - Alert callback for severity ≥ 7 events
 */

import { useEffect, useRef, useCallback, useState } from 'react';
import { useStore } from '../../../store';
import { useNuclearStore } from '../store/nuclear-store';
import type { NuclearWsMessage, NuclearChartState, NuclearAlertMessage } from '../types/nuclear';

// ─── Config ───────────────────────────────────────────────────────────────────

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const _envNuclearWsUrl = import.meta.env.VITE_NUCLEAR_WS_URL as string | undefined;

function getNuclearWsUrl(): string {
  if (_envNuclearWsUrl) return _envNuclearWsUrl;
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}/ws/nuclear`;
}

const HEARTBEAT_INTERVAL_MS  = 30_000;
const INITIAL_RECONNECT_MS   = 1_000;
const MAX_RECONNECT_MS       = 30_000;
const NUCLEAR_ALERT_SEVERITY = 7;

// ─── Hook ─────────────────────────────────────────────────────────────────────

export type NuclearWsStatus = 'connecting' | 'connected' | 'disconnected' | 'error' | 'unavailable';

export interface UseNuclearWSReturn {
  status: NuclearWsStatus;
  lastAlert: NuclearAlertMessage | null;
  injectEvent: (text: string, vol?: number, sentiment?: number) => void;
  requestSnapshot: () => void;
  requestHistory: (n?: number) => void;
}

export function useNuclearWS(enabled = true): UseNuclearWSReturn {
  const token          = useStore((s) => s.token);
  const [status, setStatus] = useState<NuclearWsStatus>('disconnected');
  const [lastAlert, setLastAlert] = useState<NuclearAlertMessage | null>(null);

  const wsRef            = useRef<WebSocket | null>(null);
  const reconnectDelay   = useRef(INITIAL_RECONNECT_MS);
  const reconnectTimer   = useRef<ReturnType<typeof setTimeout> | null>(null);
  const heartbeatTimer   = useRef<ReturnType<typeof setInterval> | null>(null);
  const mountedRef       = useRef(true);
  const tokenRef         = useRef(token);
  tokenRef.current = token;

  const {
    setChartState,
    setNuclearAlert,
    setWsStatus: setStoreStatus,
  } = useNuclearStore();

  // ── Message router ──────────────────────────────────────────────────────────

  const handleMessage = useCallback((raw: string) => {
    let msg: NuclearWsMessage;
    try {
      msg = JSON.parse(raw);
    } catch {
      return;
    }

    switch (msg.type) {
      case 'nuclear_chart_update':
        // Guard against null data — backend sends null when the nuclear
        // supervisor is unavailable, which would crash any component reading
        // msg.data.severity etc.
        if ((msg as NuclearChartState).data != null) {
          setChartState(msg as NuclearChartState);
        }
        break;

      case 'nuclear_alert': {
        const alert = msg as NuclearAlertMessage;
        setNuclearAlert(alert);
        setLastAlert(alert);
        // Flash the page title on critical alerts
        if (alert.severity >= NUCLEAR_ALERT_SEVERITY) {
          _flashTitle(`☢️ NUCLEAR ALERT — Severity ${alert.severity}/10`);
        }
        break;
      }

      case 'nuclear_resume':
        setNuclearAlert(null);
        setLastAlert(null);
        break;

      case 'nuclear_unavailable':
        // Server sent this because the charting engine failed to load at
        // startup. Stop reconnecting — retrying won't help until the server
        // is restarted with the charting module available.
        setStatus('unavailable');
        setStoreStatus('unavailable');
        wsRef.current?.close();
        clearTimeout(reconnectTimer.current!);
        break;

      case 'heartbeat':
        // Pong back
        wsRef.current?.send(JSON.stringify({ type: 'pong', ts: Date.now() }));
        break;

      default:
        break;
    }
  }, [setChartState, setNuclearAlert]);

  // ── Connect ─────────────────────────────────────────────────────────────────

  const connect = useCallback(() => {
    if (!mountedRef.current || !enabled) return;

    const url = getNuclearWsUrl();
    setStatus('connecting');
    setStoreStatus('connecting');

    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
    } catch {
      setStatus('error');
      setStoreStatus('error');
      scheduleReconnect();
      return;
    }

    wsRef.current = ws;

    ws.onopen = () => {
      if (!mountedRef.current) { ws.close(); return; }
      reconnectDelay.current = INITIAL_RECONNECT_MS;
      setStatus('connected');
      setStoreStatus('connected');

      // Auth handshake
      const t = tokenRef.current;
      if (t) {
        ws.send(JSON.stringify({ type: 'auth', token: t }));
      }

      // Subscribe to nuclear channel
      ws.send(JSON.stringify({ type: 'subscribe', channels: ['nuclear', 'price'] }));

      // Start heartbeat
      heartbeatTimer.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'ping', ts: Date.now() }));
        }
      }, HEARTBEAT_INTERVAL_MS);
    };

    ws.onmessage = (ev) => handleMessage(ev.data);

    ws.onerror = () => {
      setStatus('error');
      setStoreStatus('error');
    };

    ws.onclose = () => {
      if (!mountedRef.current) return;
      clearInterval(heartbeatTimer.current!);
      setStatus('disconnected');
      setStoreStatus('disconnected');
      scheduleReconnect();
    };
  }, [enabled, handleMessage, setStoreStatus]);

  const scheduleReconnect = useCallback(() => {
    if (!mountedRef.current) return;
    // Don't reconnect if the server told us the nuclear engine is unavailable.
    // Retrying endlessly would spam the server logs with no benefit.
    if (status === 'unavailable') return;
    reconnectTimer.current = setTimeout(() => {
      reconnectDelay.current = Math.min(reconnectDelay.current * 2, MAX_RECONNECT_MS);
      connect();
    }, reconnectDelay.current);
  }, [connect, status]);

  // ── Lifecycle ───────────────────────────────────────────────────────────────

  useEffect(() => {
    mountedRef.current = true;
    if (enabled) connect();
    return () => {
      mountedRef.current = false;
      clearTimeout(reconnectTimer.current!);
      clearInterval(heartbeatTimer.current!);
      wsRef.current?.close();
    };
  }, [enabled, connect]);

  // ── Public actions ──────────────────────────────────────────────────────────

  const injectEvent = useCallback((text: string, vol = 1.0, sentiment = 0.0) => {
    wsRef.current?.send(JSON.stringify({
      type: 'inject_event',
      text,
      vol,
      sentiment,
    }));
  }, []);

  const requestSnapshot = useCallback(() => {
    wsRef.current?.send(JSON.stringify({ type: 'get_snapshot' }));
  }, []);

  const requestHistory = useCallback((n = 20) => {
    wsRef.current?.send(JSON.stringify({ type: 'get_history', n }));
  }, []);

  return { status, lastAlert, injectEvent, requestSnapshot, requestHistory };
}

// ─── Title flash helper ───────────────────────────────────────────────────────

let _flashInterval: ReturnType<typeof setInterval> | null = null;
let _originalTitle = '';

function _flashTitle(alertTitle: string, durationMs = 10_000) {
  if (_flashInterval) return; // already flashing
  _originalTitle = document.title;
  let toggle = false;
  _flashInterval = setInterval(() => {
    document.title = toggle ? alertTitle : _originalTitle;
    toggle = !toggle;
  }, 800);
  setTimeout(() => {
    clearInterval(_flashInterval!);
    _flashInterval = null;
    document.title = _originalTitle;
  }, durationMs);
}
