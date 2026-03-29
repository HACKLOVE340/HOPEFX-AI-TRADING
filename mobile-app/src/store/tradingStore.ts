// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * store/tradingStore.ts
 * =====================
 * Zustand store for live trading state.
 * Prices, positions, orders, and signals are updated via WebSocket.
 */

import { create } from 'zustand';
import { apiClient } from '../services/apiClient';
import { wsClient } from '../services/wsClient';
import { Account, Order, Position, Quote, Signal, Trade } from '../types';

interface TradingState {
  account: Account | null;
  quotes: Record<string, Quote>;
  positions: Position[];
  orders: Order[];
  trades: Trade[];
  signals: Signal[];
  isLoading: boolean;
  error: string | null;

  // Actions
  fetchAccount: () => Promise<void>;
  fetchPositions: () => Promise<void>;
  fetchOrders: () => Promise<void>;
  fetchTrades: (limit?: number) => Promise<void>;
  fetchSignals: (symbol?: string) => Promise<void>;
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
  subscribeToLive: () => () => void;
  clearError: () => void;
}

export const useTradingStore = create<TradingState>((set, get) => ({
  account: null,
  quotes: {},
  positions: [],
  orders: [],
  trades: [],
  signals: [],
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

  placeOrder: async (order) => {
    set({ isLoading: true, error: null });
    try {
      const placed = await apiClient.placeOrder(order);
      // Optimistically add to orders list
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

  subscribeToLive: () => {
    // ── Price ticks ────────────────────────────────────────────────────────
    // Backend sends { type: "price_tick", data: { symbol: "XAU/USD", bid, ask, ... } }
    // Mobile store keys quotes by no-slash symbol (XAUUSD) for consistency.
    const normalizeSymbol = (s: string) => s.replace('/', '');

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
        // timestamp may be ms epoch (number) or ISO string
        timestamp: typeof raw.timestamp === 'number'
          ? new Date(raw.timestamp).toISOString()
          : String(raw.timestamp ?? new Date().toISOString()),
        change_pct: Number(raw.change_pct ?? 0),
      };
    };

    const unsubPriceTick = wsClient.on<Record<string, unknown>>('price_tick', (raw) => {
      const quote = normalizeTick(raw);
      if (quote.symbol) {
        set((state) => ({ quotes: { ...state.quotes, [quote.symbol]: quote } }));
      }
    });

    // Legacy alias — some deployments may still send price_update
    const unsubPriceUpdate = wsClient.on<Quote>('price_update', (quote) => {
      if (quote?.symbol) {
        set((state) => ({ quotes: { ...state.quotes, [quote.symbol]: quote } }));
      }
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

    // Position closed — remove from list
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
      }
    });

    // Return combined unsubscribe
    return () => {
      unsubPriceTick();
      unsubPriceUpdate();
      unsubPos();
      unsubPosClose();
      unsubAccount();
      unsubSignal();
    };
  },

  clearError: () => set({ error: null }),
}));
