// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * services/wsClient.ts
 * ====================
 * Singleton WebSocket client for the HopeFX backend /ws/live endpoint.
 *
 * Channels subscribed:
 *   prices        → price_tick (bid/ask/spread/change_pct)
 *   microstructure → microstructure_update (OFI, volume delta, depth imbalance)
 *   signals       → signal (AI signal with confidence + reasoning)
 *   risk          → risk_update, kill_switch_trigger
 *   sentiment     → sentiment_update (score, momentum, headlines)
 *   positions     → position_update, position_close
 *   account       → account_update
 *
 * Features:
 *   - JWT auth via first message (type: "auth")
 *   - Exponential back-off reconnect (1s → 30s cap)
 *   - Ping/pong keepalive every 20s
 *   - Connection status observable (callbacks)
 *   - Typed event emitter with unsubscribe handles
 *   - Graceful teardown on logout
 *   - Message queue: buffers sends while connecting
 */

import Constants from 'expo-constants';
import { WSMessage, WSMessageType, WSConnectionStatus } from '../types';

const WS_BASE: string =
  (Constants.expoConfig?.extra?.wsBaseUrl as string) ?? 'ws://localhost:8000';

const WS_URL = `${WS_BASE}/ws/live`;
const PING_INTERVAL_MS   = 20_000;
const RECONNECT_BASE_MS  = 1_000;
const RECONNECT_MAX_MS   = 30_000;
const CONNECT_TIMEOUT_MS = 10_000;

type Listener<T = unknown> = (data: T) => void;
type StatusListener = (status: WSConnectionStatus) => void;

// All channels the mobile app subscribes to
const ALL_CHANNELS = [
  'prices',
  'microstructure',
  'signals',
  'risk',
  'sentiment',
  'positions',
  'account',
] as const;

class HopeFXWebSocket {
  private _ws: WebSocket | null = null;
  private _token: string | null = null;
  private _listeners: Map<WSMessageType, Set<Listener>> = new Map();
  private _statusListeners: Set<StatusListener> = new Set();
  private _pingTimer: ReturnType<typeof setInterval> | null = null;
  private _reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private _connectTimeoutTimer: ReturnType<typeof setTimeout> | null = null;
  private _reconnectDelay = RECONNECT_BASE_MS;
  private _intentionalClose = false;
  private _status: WSConnectionStatus = 'disconnected';
  private _sendQueue: string[] = [];
  private _reconnectAttempts = 0;

  // ── Public API ─────────────────────────────────────────────────────────────

  connect(token: string): void {
    this._token = token;
    this._intentionalClose = false;
    this._reconnectDelay = RECONNECT_BASE_MS;
    this._reconnectAttempts = 0;
    this._open();
  }

  disconnect(): void {
    this._intentionalClose = true;
    this._clearTimers();
    this._sendQueue = [];
    if (this._ws) {
      this._ws.close(1000, 'logout');
      this._ws = null;
    }
    this._setStatus('disconnected');
  }

  /**
   * Subscribe to a message type. Returns an unsubscribe function.
   */
  on<T = unknown>(type: WSMessageType, listener: Listener<T>): () => void {
    if (!this._listeners.has(type)) {
      this._listeners.set(type, new Set());
    }
    this._listeners.get(type)!.add(listener as Listener);
    return () => this._listeners.get(type)?.delete(listener as Listener);
  }

  /**
   * Subscribe to connection status changes.
   */
  onStatus(listener: StatusListener): () => void {
    this._statusListeners.add(listener);
    // Immediately emit current status
    listener(this._status);
    return () => this._statusListeners.delete(listener);
  }

  /**
   * Send a message. Queues if not yet connected.
   */
  send(type: string, data: unknown): void {
    const payload = JSON.stringify({ type, data, timestamp: new Date().toISOString() });
    if (this._ws?.readyState === WebSocket.OPEN) {
      this._ws.send(payload);
    } else {
      // Queue for when connection is established
      this._sendQueue.push(payload);
    }
  }

  get isConnected(): boolean {
    return this._ws?.readyState === WebSocket.OPEN;
  }

  get status(): WSConnectionStatus {
    return this._status;
  }

  get reconnectAttempts(): number {
    return this._reconnectAttempts;
  }

  // ── Internal ───────────────────────────────────────────────────────────────

  private _open(): void {
    if (!this._token) return;
    if (this._ws && this._ws.readyState === WebSocket.CONNECTING) return;

    this._setStatus('connecting');

    // Connect timeout — if no open event within 10s, force reconnect
    this._connectTimeoutTimer = setTimeout(() => {
      if (this._status === 'connecting') {
        console.warn('[WS] Connect timeout — forcing reconnect');
        this._ws?.close();
        this._ws = null;
        if (!this._intentionalClose) this._scheduleReconnect();
      }
    }, CONNECT_TIMEOUT_MS);

    this._ws = new WebSocket(WS_URL);

    this._ws.onopen = () => {
      this._clearConnectTimeout();
      this._reconnectDelay = RECONNECT_BASE_MS;
      this._reconnectAttempts = 0;

      // Auth handshake — backend closes with 4001 if not received within timeout
      this._ws!.send(JSON.stringify({
        type: 'auth',
        token: `Bearer ${this._token}`,
      }));

      // Subscribe to all channels
      this._ws!.send(JSON.stringify({
        type: 'subscribe',
        channels: ALL_CHANNELS,
      }));

      // Flush queued messages
      while (this._sendQueue.length > 0) {
        const msg = this._sendQueue.shift();
        if (msg) this._ws!.send(msg);
      }

      this._setStatus('connected');
      this._startPing();
    };

    this._ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data as string) as {
          type: string;
          data?: unknown;
          [k: string]: unknown;
        };

        // Protocol messages — handle silently
        if (msg.type === 'pong' || msg.type === 'auth_ok') return;

        // Server heartbeat → respond with ping
        if (msg.type === 'heartbeat') {
          this.send('ping', {});
          return;
        }

        // Dispatch to listeners
        const listeners = this._listeners.get(msg.type as WSMessageType);
        if (listeners?.size) {
          listeners.forEach((fn) => {
            try {
              fn(msg.data);
            } catch (e) {
              console.warn(`[WS] Listener error for ${msg.type}:`, e);
            }
          });
        }
      } catch (e) {
        console.warn('[WS] Parse error:', e);
      }
    };

    this._ws.onerror = (e) => {
      console.warn('[WS] Socket error:', e);
    };

    this._ws.onclose = (e) => {
      this._clearTimers();
      console.log(`[WS] Closed (code=${e.code}, reason=${e.reason})`);

      if (!this._intentionalClose) {
        this._reconnectAttempts++;
        this._setStatus('reconnecting');
        this._scheduleReconnect();
      }
    };
  }

  private _startPing(): void {
    this._pingTimer = setInterval(() => {
      if (this._ws?.readyState === WebSocket.OPEN) {
        this._ws.send(JSON.stringify({ type: 'ping' }));
      }
    }, PING_INTERVAL_MS);
  }

  private _scheduleReconnect(): void {
    const delay = this._reconnectDelay;
    // Exponential back-off with jitter
    const jitter = Math.random() * 500;
    this._reconnectDelay = Math.min(delay * 2, RECONNECT_MAX_MS);
    console.log(`[WS] Reconnecting in ${Math.round(delay + jitter)}ms (attempt ${this._reconnectAttempts})`);
    this._reconnectTimer = setTimeout(() => this._open(), delay + jitter);
  }

  private _setStatus(status: WSConnectionStatus): void {
    if (this._status === status) return;
    this._status = status;
    this._statusListeners.forEach((fn) => {
      try { fn(status); } catch (e) { /* ignore */ }
    });
  }

  private _clearConnectTimeout(): void {
    if (this._connectTimeoutTimer) {
      clearTimeout(this._connectTimeoutTimer);
      this._connectTimeoutTimer = null;
    }
  }

  private _clearTimers(): void {
    this._clearConnectTimeout();
    if (this._pingTimer) { clearInterval(this._pingTimer); this._pingTimer = null; }
    if (this._reconnectTimer) { clearTimeout(this._reconnectTimer); this._reconnectTimer = null; }
  }
}

// Singleton
export const wsClient = new HopeFXWebSocket();
