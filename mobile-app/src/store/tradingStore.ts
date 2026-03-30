// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * store/tradingStore.ts
 * =====================
 * Zustand store for live trading state.
 * Handles prices, microstructure, positions, orders, signals, risk, sentiment.
 * All data flows from WebSocket (primary) with REST fallback.
 */

import { create } from 'zustand';
import { apiClient } from '../services/apiClient';
import { wsClient } from '../services/wsClient';
import { pushNotifications } from '../services/pushNotifications';
import {
  Account, Order, Position, Quote, Signal, Trade,
  Microstructure, RiskMetrics, SentimentData, WSConnectionStatus,
} from '../types';

interface TradingState {
  // Market data
  account: Account | null;
  quotes: Record<string, Quote>;
  positions: Position[];
  orders: Order[];
  trades: Trade[];
  signals: Signal[];

  // Extended data from orchestrator
  microstructure: Record<string, Microstructure>;
  riskMetrics: RiskMetrics | null;
  sentiment: SentimentData | null;

  // Connection
  wsStatus: WSConnectionStatus;

  // UI state
  isLoading: boolean;
  error: string | null;

  // Actions
  fetchAccount: () => Promise<void>;
  fetchPositions: () => Promise<void>;
  fetchOrders: () => Promise<void>;
  fetchTrades: (limit?: number) => Promise<void>;
  fetchSignals: (symbol?: string) => Promise<void>;
  fetchRiskMetrics: () => Promise<void>;
  fetchSentiment: (symbol?: string) => Promise<void>;
  placeOrder: (order: {
    symbol: string;
    side: 'buy' | 'sell';
    quantity: number;
    order_type?: 'market' | 'limit' | 'stop';
    price?: number;
    stop_loss?: number;
    take_profit?: number;
  }) => Promise<Order>;
  cancelOrder: (orderId: string) => Promise<void>;
  closePosition: (positionId: string) => Promise<void>;
  approveSignal: (signalId: string) => void;
  subscribeToLive: () => () => void;
  clearError: () => void;
}

const normalizeSymbol = (s: string) => s.replace('/', '').replace('-', '').toUpperCase();

export const useTradingStore = create<TradingState>((set, get) => ({
  account: null,
  quotes: {},
  positions: [],
  orders: [],
  trades: [],
  signals: [],
  microstructure: {},
  riskMetrics: null,
  sentiment: null,
  wsStatus: 'disconnected',
  isLoading: false,
  error: null,

  fetchAccount: async () => {
    try {
      const account = await apiClient.getAccount();
      set({ account });
    } catch (e) {
      set({ error: 'Failed to fetch account' });
    }
  },

  fetchPositions: async () => {
    try {
      const positions = await apiClient.getPositions();
      set({ positions });
    } catch (e) {
      set({ error: 'Failed to fetch positions' });
    }
  },

  fetchOrders: async () => {
    try {
      const orders = await apiClient.getOrders();
      set({ orders });
    } catch (e) {
      set({ error: 'Failed to fetch orders' });
    }
  },

  fetchTrades: async (limit = 50) => {
    try {
      const trades = await apiClient.getTrades(limit);
      set({ trades });
    } catch (e) {
      set({ error: 'Failed to fetch trades' });
    }
  },

  fetchSignals: async (symbol) => {
    try {
      const signals = await apiClient.getSignals(symbol);
      set({ signals });
    } catch (e) {
      set({ error: 'Failed to fetch signals' });
    }
  },

  fetchRiskMetrics: async () => {
    try {
      const riskMetrics = await apiClient.getRiskMetrics();
      set({ riskMetrics });
    } catch (e) {
      set({ error: 'Failed to fetch risk metrics' });
    }
  },

  fetchSentiment: async (symbol = 'XAUUSD') => {
    try {
      const sentiment = await apiClient.getSentiment(symbol);
      set({ sentiment });
    } catch (e) {
      set({ error: 'Failed to fetch sentiment' });
    }
  },

  placeOrder: async (order) => {
    set({ isLoading: true, error: null });
    try {
      const placed = await apiClient.placeOrder(order);
      set((state) => ({ orders: [placed, ...state.orders] }));
      return placed;
    } catch (e: unknown) {
      const msg =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Order placement failed';
      set({ error: msg });
      throw e;
    } finally {
      set({ isLoading: false });
    }
  },

  cancelOrder: async (orderId) => {
    try {
      await apiClient.cancelOrder(orderId);
      set((state) => ({
        orders: state.orders.map((o) =>
          o.id === orderId ? { ...o, status: 'cancelled' as const } : o
        ),
      }));
    } catch (e) {
      set({ error: 'Failed to cancel order' });
    }
  },

  closePosition: async (positionId) => {
    try {
      await apiClient.closePosition(positionId);
      set((state) => ({
        positions: state.positions.filter((p) => p.id !== positionId),
      }));
    } catch (e) {
      set({ error: 'Failed to close position' });
    }
  },

  approveSignal: (signalId) => {
    set((state) => ({
      signals: state.signals.map((s) =>
        s.id === signalId
          ? { ...s, approved: true, approved_at: new Date().toISOString() }
          : s
      ),
    }));
  },

  subscribeToLive: () => {
    // ── WS connection status ───────────────────────────────────────────────
    const unsubStatus = wsClient.onStatus((wsStatus) => {
      set({ wsStatus });
    });

    // ── Price ticks ────────────────────────────────────────────────────────
    const normalizeTick = (raw: Record<string, unknown>): Quote => {
      const bid = Number(raw.bid ?? 0);
      const ask = Number(raw.ask ?? 0);
      const mid = Number(raw.mid ?? (bid + ask) / 2);
      const rawSymbol = String(raw.symbol ?? '');
      return {
        symbol: normalizeSymbol(rawSymbol),
        bid,
        ask,
        mid,
        spread: Number(raw.spread ?? ask - bid),
        spread_pct: Number(raw.spread_pct ?? 0),
        timestamp: typeof raw.timestamp === 'number'
          ? new Date(raw.timestamp).toISOString()
          : String(raw.timestamp ?? new Date().toISOString()),
        change_pct: Number(raw.change_pct ?? 0),
        change_abs: Number(raw.change_abs ?? 0),
        session_high: raw.session_high ? Number(raw.session_high) : undefined,
        session_low:  raw.session_low  ? Number(raw.session_low)  : undefined,
        volume: raw.volume ? Number(raw.volume) : undefined,
      };
    };

    const unsubPriceTick = wsClient.on<Record<string, unknown>>('price_tick', (raw) => {
      const quote = normalizeTick(raw);
      if (quote.symbol) {
        set((state) => ({ quotes: { ...state.quotes, [quote.symbol]: quote } }));
      }
    });

    // Legacy alias
    const unsubPriceUpdate = wsClient.on<Quote>('price_update', (quote) => {
      if (quote?.symbol) {
        const sym = normalizeSymbol(quote.symbol);
        set((state) => ({ quotes: { ...state.quotes, [sym]: { ...quote, symbol: sym } } }));
      }
    });

    // ── Microstructure ─────────────────────────────────────────────────────
    const unsubMicro = wsClient.on<Microstructure>('microstructure_update', (data) => {
      if (data?.symbol) {
        const sym = normalizeSymbol(data.symbol);
        set((state) => ({
          microstructure: { ...state.microstructure, [sym]: { ...data, symbol: sym } },
        }));
      }
    });

    // ── Risk updates ───────────────────────────────────────────────────────
    const unsubRisk = wsClient.on<RiskMetrics>('risk_update', (data) => {
      if (data) set({ riskMetrics: data });
    });

    const unsubKillSwitch = wsClient.on<{ reason: string; triggered_at: string }>(
      'kill_switch_trigger',
      (data) => {
        set((state) => ({
          riskMetrics: state.riskMetrics
            ? {
                ...state.riskMetrics,
                kill_switch_active: true,
                kill_switch_reason: data?.reason,
                kill_switch_triggered_at: data?.triggered_at,
              }
            : null,
        }));
        // Fire local push notification immediately
        pushNotifications.alertKillSwitch(data?.reason ?? 'Risk limit breached').catch(console.warn);
      }
    );

    // ── Sentiment ──────────────────────────────────────────────────────────
    const unsubSentiment = wsClient.on<SentimentData>('sentiment_update', (data) => {
      if (data) set({ sentiment: data });
    });

    // ── Position updates ───────────────────────────────────────────────────
    const unsubPos = wsClient.on<Position | Position[]>('position_update', (data) => {
      if (Array.isArray(data)) {
        set({ positions: data });
      } else if (data?.id) {
        set((state) => ({
          positions: state.positions.map((p) => (p.id === data.id ? data : p)),
        }));
      }
    });

    const unsubPosClose = wsClient.on<{ id: string }>('position_close', ({ id }) => {
      set((state) => ({ positions: state.positions.filter((p) => p.id !== id) }));
    });

    // ── Account updates ────────────────────────────────────────────────────
    const unsubAccount = wsClient.on<Account>('account_update', (account) => {
      if (account) set({ account });
    });

    // ── Signals ────────────────────────────────────────────────────────────
    const unsubSignal = wsClient.on<Signal>('signal', (signal) => {
      if (signal) {
        set((state) => ({ signals: [signal, ...state.signals.slice(0, 49)] }));
        // Push alert for high-confidence signals (≥ 0.75)
        if (signal.confidence >= 0.75 && signal.direction !== 'neutral') {
          pushNotifications
            .alertSignal(signal.symbol, signal.direction, signal.confidence)
            .catch(console.warn);
        }
      }
    });

    return () => {
      unsubStatus();
      unsubPriceTick();
      unsubPriceUpdate();
      unsubMicro();
      unsubRisk();
      unsubKillSwitch();
      unsubSentiment();
      unsubPos();
      unsubPosClose();
      unsubAccount();
      unsubSignal();
    };
  },

  clearError: () => set({ error: null }),
}));
