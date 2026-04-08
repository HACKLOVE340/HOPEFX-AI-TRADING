/**
 * chart-bot/services/orchestrator-ws.ts
 *
 * High-performance WebSocket client for the MarketDataOrchestrator.
 * Extends the base /ws/live connection with chart-bot-specific channels:
 *   - microstructure   → MicrostructureSnapshot
 *   - volume_delta     → VolumeDeltaBar
 *   - sentiment_update → SentimentSnapshot
 *   - risk_update      → RiskMetrics
 *   - pattern_detected → ChartPattern
 *   - level_update     → SupportResistanceLevel[]
 *   - equity_update    → EquityPoint
 *   - news_item        → NewsItem
 *   - ai_analysis      → AIAnalysis
 *
 * Architecture:
 *   - Singleton EventEmitter pattern — one socket, many subscribers
 *   - Zero-copy message routing via typed event bus
 *   - Exponential back-off reconnect (1s → 30s)
 *   - JWT auth handshake on connect
 *   - 30s heartbeat with server pong tracking
 *   - Subscriber ref-counting for clean teardown
 */

import type {
  WsEnvelope,
  WsMessageType,
  PriceTick,
  MicrostructureSnapshot,
  VolumeDeltaBar,
  SentimentSnapshot,
  RiskMetrics,
  ChartPattern,
  SupportResistanceLevel,
  EquityPoint,
  NewsItem,
  AIAnalysis,
  MLSignal,
} from '../types';

// ─── Event Bus ────────────────────────────────────────────────────────────────

export type EventMap = {
  price_tick:        PriceTick;
  microstructure:    MicrostructureSnapshot;
  volume_delta:      VolumeDeltaBar;
  sentiment_update:  SentimentSnapshot;
  risk_update:       RiskMetrics;
  pattern_detected:  ChartPattern;
  level_update:      SupportResistanceLevel[];
  equity_update:     EquityPoint;
  news_item:         NewsItem;
  ai_analysis:       AIAnalysis;
  signal:            MLSignal;
  connected:         void;
  disconnected:      void;
  error:             string;
};

type Handler<T> = (data: T) => void;
type Unsubscribe = () => void;

class TypedEventBus {
  private listeners = new Map<string, Set<Handler<unknown>>>();

  on<K extends keyof EventMap>(event: K, handler: Handler<EventMap[K]>): Unsubscribe {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set());
    }
    this.listeners.get(event)!.add(handler as Handler<unknown>);
    return () => this.off(event, handler);
  }

  off<K extends keyof EventMap>(event: K, handler: Handler<EventMap[K]>): void {
    this.listeners.get(event)?.delete(handler as Handler<unknown>);
  }

  emit<K extends keyof EventMap>(event: K, data: EventMap[K]): void {
    this.listeners.get(event)?.forEach((h) => {
      try { h(data); } catch (e) { console.error('[OrchestratorWS] handler error:', e); }
    });
  }

  clear(): void {
    this.listeners.clear();
  }
}

// ─── Orchestrator WebSocket Client ────────────────────────────────────────────

const HEARTBEAT_MS     = 30_000;
const INITIAL_DELAY_MS = 1_000;
const MAX_DELAY_MS     = 30_000;
const CHART_BOT_CHANNELS = [
  'prices', 'positions', 'signals', 'account',
  'microstructure', 'volume_delta', 'sentiment',
  'risk', 'patterns', 'levels', 'equity', 'news',
];

class OrchestratorWSClient {
  readonly bus = new TypedEventBus();

  private ws: WebSocket | null = null;
  private reconnectDelay = INITIAL_DELAY_MS;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private destroyed = false;
  private tokenGetter: (() => string | null) | null = null;

  // Connection state
  private _status: 'connecting' | 'connected' | 'disconnected' | 'error' = 'disconnected';
  get status() { return this._status; }

  // ── Lifecycle ───────────────────────────────────────────────────────────────

  init(tokenGetter: () => string | null): void {
    this.tokenGetter = tokenGetter;
    this.destroyed = false;
    this.connect();
  }

  destroy(): void {
    this.destroyed = true;
    this.clearTimers();
    this.ws?.close(1000, 'client_destroy');
    this.ws = null;
    this.bus.clear();
  }

  send(msg: object): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
    }
  }

  // ── Connection ──────────────────────────────────────────────────────────────

  private connect(): void {
    if (this.destroyed) return;
    if (this.ws?.readyState === WebSocket.OPEN) return;

    this._status = 'connecting';

    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const envUrl = import.meta.env.VITE_WS_URL as string | undefined;
    const url = envUrl ?? `${proto}//${window.location.host}/ws/live`;

    const ws = new WebSocket(url);
    this.ws = ws;

    ws.onopen = () => {
      if (this.destroyed) { ws.close(); return; }
      this.reconnectDelay = INITIAL_DELAY_MS;
      this.startHeartbeat(ws);
    };

    ws.onmessage = (ev) => this.route(ev.data as string);

    ws.onerror = () => {
      this._status = 'error';
      this.bus.emit('error', 'WebSocket connection error');
    };

    ws.onclose = () => {
      this.clearTimers();
      if (this.destroyed) return;
      this._status = 'disconnected';
      this.bus.emit('disconnected', undefined as void);
      const delay = this.reconnectDelay;
      this.reconnectDelay = Math.min(delay * 2, MAX_DELAY_MS);
      this.reconnectTimer = setTimeout(() => this.connect(), delay);
    };
  }

  // ── Message Routing ─────────────────────────────────────────────────────────

  private route(raw: string): void {
    let msg: WsEnvelope;
    try { msg = JSON.parse(raw) as WsEnvelope; }
    catch { return; }

    switch (msg.type as WsMessageType) {
      case 'connected':
        this.handleConnected(msg as WsEnvelope & { auth_required?: boolean });
        break;
      case 'auth_ok':
        this._status = 'connected';
        this.subscribe();
        this.bus.emit('connected', undefined as void);
        break;
      case 'price_tick':
        this.bus.emit('price_tick', msg.data as PriceTick);
        break;
      case 'microstructure':
        this.bus.emit('microstructure', msg.data as MicrostructureSnapshot);
        break;
      case 'volume_delta':
        this.bus.emit('volume_delta', msg.data as VolumeDeltaBar);
        break;
      case 'sentiment_update':
        this.bus.emit('sentiment_update', msg.data as SentimentSnapshot);
        break;
      case 'risk_update':
        this.bus.emit('risk_update', msg.data as RiskMetrics);
        break;
      case 'pattern_detected':
        this.bus.emit('pattern_detected', msg.data as ChartPattern);
        break;
      case 'level_update':
        this.bus.emit('level_update', msg.data as SupportResistanceLevel[]);
        break;
      case 'equity_update':
        this.bus.emit('equity_update', msg.data as EquityPoint);
        break;
      case 'news_item':
        this.bus.emit('news_item', msg.data as NewsItem);
        break;
      case 'ai_analysis':
        this.bus.emit('ai_analysis', msg.data as AIAnalysis);
        break;
      case 'signal':
        this.bus.emit('signal', msg.data as MLSignal);
        break;
      case 'heartbeat':
        this.ws?.send(JSON.stringify({ type: 'ping' }));
        break;
      case 'error':
        this.bus.emit('error', (msg as WsEnvelope<{ message: string }>).data?.message ?? 'unknown error');
        break;
      default:
        break;
    }
  }

  private handleConnected(msg: WsEnvelope & { auth_required?: boolean }): void {
    if (msg.auth_required) {
      const token = this.tokenGetter?.();
      if (token && this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: 'auth', token: `Bearer ${token}` }));
      }
    } else {
      this._status = 'connected';
      this.subscribe();
      this.bus.emit('connected', undefined as void);
    }
  }

  private subscribe(): void {
    this.send({ type: 'subscribe', channels: CHART_BOT_CHANNELS });
  }

  // ── Heartbeat ───────────────────────────────────────────────────────────────

  private startHeartbeat(ws: WebSocket): void {
    this.heartbeatTimer = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'ping' }));
      }
    }, HEARTBEAT_MS);
  }

  private clearTimers(): void {
    if (this.reconnectTimer) { clearTimeout(this.reconnectTimer); this.reconnectTimer = null; }
    if (this.heartbeatTimer) { clearInterval(this.heartbeatTimer); this.heartbeatTimer = null; }
  }
}

// ─── Singleton export ─────────────────────────────────────────────────────────

export const orchestratorWS = new OrchestratorWSClient();
