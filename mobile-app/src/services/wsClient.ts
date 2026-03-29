// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * services/wsClient.ts
 * ====================
 * Singleton WebSocket client connected to /ws/live on the HopeFX backend.
 *
 * Features:
 *  - JWT auth via ?token= query param (same as web frontend)
 *  - Automatic reconnect with exponential back-off (max 30 s)
 *  - Ping/pong keepalive every 20 s
 *  - Typed message dispatch via event emitter pattern
 *  - Graceful teardown on logout
 */

import Constants from 'expo-constants';
import { WSMessage, WSMessageType } from '../types';

const WS_BASE: string =
  (Constants.expoConfig?.extra?.wsBaseUrl as string) ?? 'ws://localhost:8000';

const WS_URL = `${WS_BASE}/ws/live`;
const PING_INTERVAL_MS = 20_000;
const RECONNECT_BASE_MS = 1_000;
const RECONNECT_MAX_MS = 30_000;

type Listener<T = unknown> = (data: T) => void;

class HopeFXWebSocket {
  private _ws: WebSocket | null = null;
  private _token: string | null = null;
  private _listeners: Map<WSMessageType, Set<Listener>> = new Map();
  private _pingTimer: ReturnType<typeof setInterval> | null = null;
  private _reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private _reconnectDelay = RECONNECT_BASE_MS;
  private _intentionalClose = false;

  // ── Public API ─────────────────────────────────────────────────────────────

  connect(token: string): void {
    this._token = token;
    this._intentionalClose = false;
    this._reconnectDelay = RECONNECT_BASE_MS;
    this._open();
  }

  disconnect(): void {
    this._intentionalClose = true;
    this._clearTimers();
    if (this._ws) {
      this._ws.close(1000, 'logout');
      this._ws = null;
    }
  }

  on<T = unknown>(type: WSMessageType, listener: Listener<T>): () => void {
    if (!this._listeners.has(type)) {
      this._listeners.set(type, new Set());
    }
    this._listeners.get(type)!.add(listener as Listener);
    // Return unsubscribe function
    return () => this._listeners.get(type)?.delete(listener as Listener);
  }

  send(type: string, data: unknown): void {
    if (this._ws?.readyState === WebSocket.OPEN) {
      this._ws.send(JSON.stringify({ type, data, timestamp: new Date().toISOString() }));
    }
  }

  get isConnected(): boolean {
    return this._ws?.readyState === WebSocket.OPEN;
  }

  // ── Internal ───────────────────────────────────────────────────────────────

  private _open(): void {
    if (!this._token) return;
    const url = `${WS_URL}?token=${encodeURIComponent(this._token)}`;
    this._ws = new WebSocket(url);

    this._ws.onopen = () => {
      console.log('[WS] Connected');
      this._reconnectDelay = RECONNECT_BASE_MS;
      this._startPing();
    };

    this._ws.onmessage = (event) => {
      try {
        const msg: WSMessage = JSON.parse(event.data as string);
        if (msg.type === 'pong') return;
        const listeners = this._listeners.get(msg.type);
        listeners?.forEach((fn) => fn(msg.data));
      } catch (e) {
        console.warn('[WS] Parse error:', e);
      }
    };

    this._ws.onerror = (e) => {
      console.warn('[WS] Error:', e);
    };

    this._ws.onclose = (e) => {
      console.log(`[WS] Closed (code=${e.code})`);
      this._clearTimers();
      if (!this._intentionalClose) {
        this._scheduleReconnect();
      }
    };
  }

  private _startPing(): void {
    this._pingTimer = setInterval(() => {
      this.send('ping', {});
    }, PING_INTERVAL_MS);
  }

  private _scheduleReconnect(): void {
    const delay = this._reconnectDelay;
    this._reconnectDelay = Math.min(delay * 2, RECONNECT_MAX_MS);
    console.log(`[WS] Reconnecting in ${delay}ms…`);
    this._reconnectTimer = setTimeout(() => this._open(), delay);
  }

  private _clearTimers(): void {
    if (this._pingTimer) clearInterval(this._pingTimer);
    if (this._reconnectTimer) clearTimeout(this._reconnectTimer);
    this._pingTimer = null;
    this._reconnectTimer = null;
  }
}

// Singleton
export const wsClient = new HopeFXWebSocket();
