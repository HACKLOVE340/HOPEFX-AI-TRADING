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
import { tradingApi } from './useApi';
import type { PriceTick, Position, Signal, AccountMetrics, MicrostructureSnapshot } from '../types';
import type { EquitySnapshot, RiskSnapshot, VolumeDeltaBar, WsNewsItem, SystemAlert } from '../store';

// Module-level map: symbol → last known mid price, used to compute change_pct
// when the server sends 0 or omits the field.
const _lastMid: Record<string, number> = {};

const _envWsUrl = import.meta.env.VITE_WS_URL as string | undefined;
const WS_URL: string = _envWsUrl ?? (() => {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}/ws/live`;
})();

const HEARTBEAT_INTERVAL_MS  = 30_000;
const INITIAL_RECONNECT_MS   = 1_000;
const MAX_RECONNECT_MS       = 30_000;
// Poll REST prices when WS is not connected so the UI shows live-ish data.
const REST_POLL_INTERVAL_MS  = 5_000;

interface WsMessage {
  type:
    // Connection lifecycle
    | 'connected'
    | 'auth_ok'
    | 'heartbeat'
    | 'pong'
    | 'subscribed'
    | 'unsubscribed'
    | 'no_live_feed'
    | 'error'
    // Market data
    | 'price_tick'
    | 'microstructure'
    | 'volume_delta'
    | 'equity_update'
    // Trading
    | 'position_update'
    | 'position_close'
    | 'signal'
    | 'alert_triggered'
    | 'account_update'
    // Intelligence
    | 'sentiment_update'
    | 'risk_update'
    | 'news_item'
    // System events (nuclear halt, circuit breaker)
    | 'system_event'
    | 'nuclear_halt';
  data?:          unknown;
  auth_required?: boolean;
  code?:          string;
  message?:       string;
  channels?:      string[];
  user_id?:       string;
  role?:          string;
}

export function useWebSocket(enabled = true) {
  const wsRef          = useRef<WebSocket | null>(null);
  const reconnectDelay = useRef(INITIAL_RECONNECT_MS);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const heartbeatTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const restPollTimer  = useRef<ReturnType<typeof setInterval> | null>(null);
  const unmounted      = useRef(false);
  const authedRef      = useRef(false);

  // Stable ref to useStore.getState — never changes, so it's safe in
  // useCallback deps without causing reconnect loops on every render.
  const getState = useStore.getState;

  const handleMessage = useCallback((raw: string) => {
    let msg: WsMessage;
    try { msg = JSON.parse(raw) as WsMessage; }
    catch { return; }

    const {
      setWsStatus, setHeartbeat, setPrice,
      upsertPosition, removePosition, addSignal, setAccount,
      setMicrostructure, setVolumeDelta, setSentiment,
      setRiskSnapshot, setEquitySnapshot, addNewsItem, setSystemAlert,
      setNoLiveFeed,
    } = getState();

    switch (msg.type) {
      case 'connected':
        if (msg.auth_required) {
          // Async: refresh token if it's null (happens after page reload because
          // the JWT lives in memory only and isn't persisted to localStorage).
          const sendAuth = async () => {
            let token = getState().token;
            if (!token) {
              try {
                const res = await fetch('/api/auth/refresh', {
                  method: 'POST',
                  credentials: 'include',
                  headers: { 'Content-Type': 'application/json' },
                  body: '{}',
                });
                if (res.ok) {
                  const data = await res.json() as { access_token?: string; user?: import('../types').User };
                  if (data.access_token) {
                    // Refresh response may not include user — use persisted user from store.
                    const existingUser = getState().user;
                    const user = data.user ?? existingUser;
                    if (user) {
                      getState().setAuth(data.access_token, user);
                    }
                    token = data.access_token;
                  }
                }
              } catch { /* refresh failed — WS will retry */ }
            }
            if (token && wsRef.current?.readyState === WebSocket.OPEN) {
              wsRef.current.send(JSON.stringify({ type: 'auth', token: `Bearer ${token}` }));
            }
          };
          void sendAuth();
        } else {
          authedRef.current = true;
          setWsStatus('connected');
          wsRef.current?.send(JSON.stringify({
            type: 'subscribe',
            channels: ['prices', 'positions', 'signals', 'account', 'alerts',
                       'microstructure', 'volume_delta', 'sentiment', 'risk', 'equity', 'news', 'system'],
          }));
        }
        break;

      case 'auth_ok':
        authedRef.current = true;
        setWsStatus('connected');
        // Clear stale no-live-feed banner on successful reconnect.
        setNoLiveFeed(false);
        wsRef.current?.send(JSON.stringify({
          type: 'subscribe',
          channels: ['prices', 'positions', 'signals', 'account', 'alerts',
                     'microstructure', 'volume_delta', 'sentiment', 'risk', 'equity', 'news'],
        }));
        break;

      case 'price_tick': {
        const raw = msg.data as PriceTick;
        // Compute change_pct from previous mid if server sends 0 or omits it.
        // _lastMid is a module-level map so it persists across reconnects.
        const mid = raw.mid ?? ((raw.bid + raw.ask) / 2);
        const prev = _lastMid[raw.symbol];
        const computed_change_pct = raw.change_pct
          ? raw.change_pct
          : prev != null && prev !== 0
            ? ((mid - prev) / prev) * 100
            : 0;
        _lastMid[raw.symbol] = mid;
        const tick: PriceTick = { ...raw, change_pct: computed_change_pct };
        setPrice(tick);
        // Clear the no-live-feed banner once real ticks arrive.
        if (getState().noLiveFeed) setNoLiveFeed(false);
        break;
      }

      case 'position_update': {
        const raw = msg.data as Record<string, unknown>;
        const pos: Position = {
          ...raw,
          size: (raw.size as number) ?? (raw.quantity as number) ?? 0,
          realized_pnl: (raw.realized_pnl as number) ?? 0,
        } as Position;
        upsertPosition(pos);
        break;
      }

      case 'position_close':
        removePosition((msg.data as { id: string }).id);
        break;

      case 'signal':
        addSignal(msg.data as Signal);
        break;

      case 'alert_triggered':
        getState().addTriggeredAlert(msg.data as import('../store').TriggeredAlert);
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

      // ── chart-bot channel ─────────────────────────────────────────────────

      case 'microstructure':
        setMicrostructure(msg.data as MicrostructureSnapshot);
        break;

      case 'volume_delta':
        setVolumeDelta(msg.data as VolumeDeltaBar);
        break;

      case 'sentiment_update': {
        // Server sends { signal: SentimentSignal, recent_articles: NewsArticle[] }
        const rawSentiment = msg.data as { signal: unknown; recent_articles: unknown[] };
        setSentiment({
          signal: rawSentiment?.signal as import('../types').SentimentSignal,
          recent_articles: (rawSentiment?.recent_articles ?? []) as import('../types').NewsArticle[],
        });
        break;
      }

      case 'risk_update':
        setRiskSnapshot(msg.data as RiskSnapshot);
        break;

      case 'equity_update':
        setEquitySnapshot(msg.data as EquitySnapshot);
        break;

      case 'news_item':
        addNewsItem(msg.data as WsNewsItem);
        break;

      case 'system_event':
      case 'nuclear_halt': {
        const alert = msg.data as SystemAlert;
        setSystemAlert(alert);
        break;
      }

      // ── server acknowledgements ───────────────────────────────────────────

      case 'subscribed':
        // Server confirmed channel subscription — no state change needed.
        break;

      case 'unsubscribed':
        // Server confirmed channel unsubscription — no state change needed.
        break;

      case 'pong':
        // Server pong in response to our ping — liveness confirmed.
        setHeartbeat(Date.now());
        break;

      case 'no_live_feed':
        getState().setNoLiveFeed(true, msg.message ?? 'No live broker feed — prices may be delayed.');
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
  }, [getState]);

  const startHeartbeat = useCallback((ws: WebSocket) => {
    if (heartbeatTimer.current) clearInterval(heartbeatTimer.current);
    heartbeatTimer.current = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'ping' }));
      }
    }, HEARTBEAT_INTERVAL_MS);
  }, []);

  /**
   * Normalise a symbol key from the REST /trading/prices response to the
   * slash format used by the WebSocket price_tick messages (e.g. "XAU/USD").
   *
   * The REST endpoint may return:
   *   "XAUUSD"   (broker path — no separator, 6 chars)
   *   "XAU/USD"  (price-engine path — already correct)
   *   "XAU_USD"  (legacy — underscore)
   *   "BTCUSDT"  (7-char crypto: BTC/USDT)
   *   "BTCUSD"   (6-char crypto: BTC/USD)
   *
   * We convert all forms to "BASE/QUOTE" so store keys are consistent.
   * Standard FX and metals use 3-char codes on each side (6 total).
   * Crypto pairs with USDT/BUSD quote use 3+4 = 7 chars.
   */
  const normaliseSymbol = useCallback((raw: string): string => {
    // Already slash format — return as-is
    if (raw.includes('/')) return raw;
    // Underscore separator → slash
    if (raw.includes('_')) return raw.replace('_', '/');
    // 7-char: 3-char base + 4-char quote (e.g. BTCUSDT → BTC/USDT)
    if (raw.length === 7) return `${raw.slice(0, 3)}/${raw.slice(3)}`;
    // 6-char: 3-char base + 3-char quote (e.g. XAUUSD → XAU/USD, EURUSD → EUR/USD)
    if (raw.length === 6) return `${raw.slice(0, 3)}/${raw.slice(3)}`;
    // Fallback — return unchanged; server may already use a non-standard format
    return raw;
  }, []);

  /** Poll REST prices when WS is unavailable so the UI shows recent data. */
  const pollRestPrices = useCallback(async () => {
    const token = getState().token;
    if (!token) return; // not authenticated — skip silently
    try {
      const res = await tradingApi.prices();
      const { setPrice } = getState();
      const now = Date.now();
      for (const [rawSymbol, raw] of Object.entries(res.data)) {
        const symbol = normaliseSymbol(rawSymbol);
        const mid    = (raw.bid + raw.ask) / 2;
        const prev   = _lastMid[symbol];
        const rawAny = raw as Record<string, unknown>;
        const change_pct = prev != null && prev !== 0
          ? ((mid - prev) / prev) * 100
          : (typeof rawAny['change_pct'] === 'number' ? (rawAny['change_pct'] as number) : 0);
        _lastMid[symbol] = mid;
        setPrice({
          symbol,
          bid:        raw.bid,
          ask:        raw.ask,
          mid,
          spread:     raw.ask - raw.bid,
          timestamp:  raw.timestamp ? raw.timestamp * 1000 : now,
          change_pct,
        });
      }
    } catch {
      // Non-fatal — WS reconnect will restore live data
    }
  }, [getState, normaliseSymbol]);

  const startRestPoll = useCallback(() => {
    if (restPollTimer.current) return; // already running
    void pollRestPrices(); // immediate fetch
    restPollTimer.current = setInterval(pollRestPrices, REST_POLL_INTERVAL_MS);
  }, [pollRestPrices]);

  const stopRestPoll = useCallback(() => {
    if (restPollTimer.current) {
      clearInterval(restPollTimer.current);
      restPollTimer.current = null;
    }
  }, []);

  const connect = useCallback(() => {
    if (unmounted.current) return;
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    getState().setWsStatus('connecting');
    authedRef.current = false;

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      if (unmounted.current) { ws.close(); return; }
      reconnectDelay.current = INITIAL_RECONNECT_MS;
      stopRestPoll(); // WS is up — stop REST polling
      startHeartbeat(ws);
    };

    ws.onmessage = (event) => handleMessage(event.data as string);
    ws.onerror = () => {
      getState().setWsStatus('error');
      startRestPoll(); // WS errored — start REST fallback
    };

    ws.onclose = () => {
      if (heartbeatTimer.current) clearInterval(heartbeatTimer.current);
      if (unmounted.current) return;
      getState().setWsStatus('disconnected');
      authedRef.current = false;
      startRestPoll(); // WS closed — start REST fallback
      const delay = reconnectDelay.current;
      // Add ±10% jitter to prevent thundering herd when many clients reconnect
      const jitter = delay * (0.9 + Math.random() * 0.2);
      reconnectDelay.current = Math.min(delay * 2, MAX_RECONNECT_MS);
      reconnectTimer.current = setTimeout(connect, jitter);
    };
  }, [handleMessage, getState, startHeartbeat, startRestPoll, stopRestPoll]);

  useEffect(() => {
    if (!enabled) return;
    unmounted.current = false;
    connect();
    return () => {
      unmounted.current = true;
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      if (heartbeatTimer.current) clearInterval(heartbeatTimer.current);
      stopRestPoll();
      wsRef.current?.close();
    };
  }, [enabled, connect, stopRestPoll]);

  const send = useCallback((msg: object) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg));
    }
  }, []);

  return { send };
}
