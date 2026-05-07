/**
 * Global Zustand store — single source of truth for all real-time state.
 *
 * Slices:
 *   auth        – JWT token, user profile, role
 *   prices      – live bid/ask/mid per symbol
 *   positions   – open positions
 *   orders      – pending/open orders
 *   signals     – latest ML signals
 *   account     – balance, equity, margin
 *   depth       – order book depth per symbol
 *   symbol      – active trading symbol + watchlist
 *   ws          – WebSocket connection status
 */

import { create } from 'zustand';
import { devtools, persist } from 'zustand/middleware';

// ─── Types ────────────────────────────────────────────────────────────────────

export type UserRole = 'user' | 'trader' | 'admin' | 'superadmin';

export interface User {
  id: string;
  email: string;
  username: string;
  role: UserRole;
}

export interface PriceTick {
  symbol: string;
  bid: number;
  ask: number;
  mid: number;
  spread: number;
  timestamp: number; // unix ms
  change_pct: number;
  daily_high?: number;
  daily_low?: number;
  volume?: number;
}

export interface Position {
  id: string;
  symbol: string;
  side: 'long' | 'short';
  size: number;
  entry_price: number;
  current_price: number;
  unrealized_pnl: number;
  realized_pnl: number;
  stop_loss?: number | null;
  take_profit?: number | null;
  margin_used?: number;
  leverage?: number;
  opened_at: string;
  swap?: number;
  commission?: number;
}

export type OrderType = 'market' | 'limit' | 'stop' | 'stop_limit' | 'trailing_stop';
export type OrderStatus = 'pending' | 'open' | 'filled' | 'cancelled' | 'rejected' | 'partial';
export type OrderSide = 'buy' | 'sell';

export interface Order {
  id: string;
  symbol: string;
  side: OrderSide;
  order_type: OrderType;
  quantity: number;
  filled_quantity?: number;
  price?: number | null;
  stop_price?: number | null;
  stop_loss?: number | null;
  take_profit?: number | null;
  trailing_distance?: number | null;
  status: OrderStatus;
  created_at: string;
  updated_at?: string;
  fill_price?: number | null;
  commission?: number;
  comment?: string;
}

export interface Signal {
  id: string;
  symbol: string;
  direction: 'long' | 'short' | 'neutral';
  confidence: number;
  model: string;
  entry_price: number;
  stop_loss: number;
  take_profit: number;
  risk_reward: number;
  generated_at: string;
  status: 'active' | 'triggered' | 'expired';
  timeframe?: string;
  regime?: string;
}

export interface AccountMetrics {
  balance: number;
  equity: number;
  margin_used: number;
  margin_free: number;
  margin_level: number;
  daily_pnl: number;
  daily_pnl_pct: number;
  total_pnl: number;
  win_rate: number;
  sharpe_ratio: number;
  max_drawdown: number;
  open_trades: number;
  leverage?: number;
  currency?: string;
}

export interface DepthLevel {
  price: number;
  size: number;
  total?: number;
}

export interface OrderBookDepth {
  symbol: string;
  bids: DepthLevel[];
  asks: DepthLevel[];
  timestamp: number;
  spread: number;
}

export interface SymbolInfo {
  symbol: string;
  description: string;
  category: 'forex' | 'metals' | 'crypto' | 'indices' | 'commodities' | 'stocks';
  pip_size: number;
  lot_size: number;
  min_lot: number;
  max_lot: number;
  margin_rate: number;
  swap_long?: number;
  swap_short?: number;
  trading_hours?: string;
}

export type WsStatus = 'connecting' | 'connected' | 'disconnected' | 'error';

// ─── Store shape ──────────────────────────────────────────────────────────────

interface AuthSlice {
  token: string | null;
  user: User | null;
  isAuthenticated: boolean;
  setAuth: (token: string, user: User) => void;
  clearAuth: () => void;
}

interface PriceSlice {
  prices: Record<string, PriceTick>;
  priceHistory: Record<string, PriceTick[]>;
  setPrice: (tick: PriceTick) => void;
}

interface PositionSlice {
  positions: Position[];
  setPositions: (positions: Position[]) => void;
  upsertPosition: (position: Position) => void;
  removePosition: (id: string) => void;
  updatePositionPrice: (symbol: string, currentPrice: number) => void;
}

interface OrderSlice {
  orders: Order[];
  setOrders: (orders: Order[]) => void;
  upsertOrder: (order: Order) => void;
  removeOrder: (id: string) => void;
  clearFilledOrders: () => void;
}

interface SignalSlice {
  signals: Signal[];
  setSignals: (signals: Signal[]) => void;
  addSignal: (signal: Signal) => void;
}

interface AccountSlice {
  account: AccountMetrics | null;
  setAccount: (metrics: AccountMetrics) => void;
}

interface DepthSlice {
  depth: Record<string, OrderBookDepth>;
  setDepth: (depth: OrderBookDepth) => void;
}

interface SymbolSlice {
  activeSymbol: string;
  activeTimeframe: string;
  watchlist: string[];
  symbolInfo: Record<string, SymbolInfo>;
  setActiveSymbol: (symbol: string) => void;
  setActiveTimeframe: (tf: string) => void;
  addToWatchlist: (symbol: string) => void;
  removeFromWatchlist: (symbol: string) => void;
  setSymbolInfo: (info: SymbolInfo) => void;
}

interface WsSlice {
  wsStatus: WsStatus;
  lastHeartbeat: number | null;
  setWsStatus: (status: WsStatus) => void;
  setHeartbeat: (ts: number) => void;
}

type AppStore = AuthSlice &
  PriceSlice &
  PositionSlice &
  OrderSlice &
  SignalSlice &
  AccountSlice &
  DepthSlice &
  SymbolSlice &
  WsSlice;

// ─── Store implementation ─────────────────────────────────────────────────────

const MAX_HISTORY = 200;
const DEFAULT_WATCHLIST = ['XAUUSD', 'EURUSD', 'GBPUSD', 'USDJPY', 'BTCUSD', 'US30'];

export const useStore = create<AppStore>()(
  devtools(
    persist(
      (set) => ({
        // ── Auth ──────────────────────────────────────────────────────────────
        token: null,
        user: null,
        isAuthenticated: false,
        setAuth: (token, user) =>
          set({ token, user, isAuthenticated: true }, false, 'auth/setAuth'),
        clearAuth: () =>
          set({ token: null, user: null, isAuthenticated: false }, false, 'auth/clearAuth'),

        // ── Prices ────────────────────────────────────────────────────────────
        prices: {},
        priceHistory: {},
        setPrice: (tick) =>
          set(
            (state) => {
              const history = state.priceHistory[tick.symbol] ?? [];
              const updated = [...history, tick].slice(-MAX_HISTORY);
              return {
                prices: { ...state.prices, [tick.symbol]: tick },
                priceHistory: { ...state.priceHistory, [tick.symbol]: updated },
              };
            },
            false,
            'prices/setPrice',
          ),

        // ── Positions ─────────────────────────────────────────────────────────
        positions: [],
        setPositions: (positions) =>
          set({ positions }, false, 'positions/setPositions'),
        upsertPosition: (position) =>
          set(
            (state) => {
              const idx = state.positions.findIndex((p) => p.id === position.id);
              const next =
                idx >= 0
                  ? state.positions.map((p) => (p.id === position.id ? position : p))
                  : [...state.positions, position];
              return { positions: next };
            },
            false,
            'positions/upsert',
          ),
        removePosition: (id) =>
          set(
            (state) => ({ positions: state.positions.filter((p) => p.id !== id) }),
            false,
            'positions/remove',
          ),
        updatePositionPrice: (symbol, currentPrice) =>
          set(
            (state) => ({
              positions: state.positions.map((p) => {
                if (p.symbol !== symbol) return p;
                const pnlPerUnit =
                  p.side === 'long'
                    ? currentPrice - p.entry_price
                    : p.entry_price - currentPrice;
                return {
                  ...p,
                  current_price: currentPrice,
                  unrealized_pnl: pnlPerUnit * p.size,
                };
              }),
            }),
            false,
            'positions/updatePrice',
          ),

        // ── Orders ────────────────────────────────────────────────────────────
        orders: [],
        setOrders: (orders) =>
          set({ orders }, false, 'orders/setOrders'),
        upsertOrder: (order) =>
          set(
            (state) => {
              const idx = state.orders.findIndex((o) => o.id === order.id);
              const next =
                idx >= 0
                  ? state.orders.map((o) => (o.id === order.id ? order : o))
                  : [...state.orders, order];
              return { orders: next };
            },
            false,
            'orders/upsert',
          ),
        removeOrder: (id) =>
          set(
            (state) => ({ orders: state.orders.filter((o) => o.id !== id) }),
            false,
            'orders/remove',
          ),
        clearFilledOrders: () =>
          set(
            (state) => ({
              orders: state.orders.filter(
                (o) =>
                  o.status !== 'filled' &&
                  o.status !== 'cancelled' &&
                  o.status !== 'rejected',
              ),
            }),
            false,
            'orders/clearFilled',
          ),

        // ── Signals ───────────────────────────────────────────────────────────
        signals: [],
        setSignals: (signals) =>
          set({ signals }, false, 'signals/setSignals'),
        addSignal: (signal) =>
          set(
            (state) => ({
              signals: [signal, ...state.signals].slice(0, 50),
            }),
            false,
            'signals/add',
          ),

        // ── Account ───────────────────────────────────────────────────────────
        account: null,
        setAccount: (account) =>
          set({ account }, false, 'account/setAccount'),

        // ── Depth ─────────────────────────────────────────────────────────────
        depth: {},
        setDepth: (depth) =>
          set(
            (state) => ({ depth: { ...state.depth, [depth.symbol]: depth } }),
            false,
            'depth/set',
          ),

        // ── Symbol ────────────────────────────────────────────────────────────
        activeSymbol: 'XAUUSD',
        activeTimeframe: '1h',
        watchlist: DEFAULT_WATCHLIST,
        symbolInfo: {},
        setActiveSymbol: (symbol) =>
          set({ activeSymbol: symbol }, false, 'symbol/setActive'),
        setActiveTimeframe: (tf) =>
          set({ activeTimeframe: tf }, false, 'symbol/setTimeframe'),
        addToWatchlist: (symbol) =>
          set(
            (state) => ({
              watchlist: state.watchlist.includes(symbol)
                ? state.watchlist
                : [...state.watchlist, symbol],
            }),
            false,
            'symbol/addWatchlist',
          ),
        removeFromWatchlist: (symbol) =>
          set(
            (state) => ({ watchlist: state.watchlist.filter((s) => s !== symbol) }),
            false,
            'symbol/removeWatchlist',
          ),
        setSymbolInfo: (info) =>
          set(
            (state) => ({ symbolInfo: { ...state.symbolInfo, [info.symbol]: info } }),
            false,
            'symbol/setInfo',
          ),

        // ── WebSocket ─────────────────────────────────────────────────────────
        wsStatus: 'disconnected',
        lastHeartbeat: null,
        setWsStatus: (wsStatus) =>
          set({ wsStatus }, false, 'ws/setStatus'),
        setHeartbeat: (ts) =>
          set({ lastHeartbeat: ts }, false, 'ws/heartbeat'),
      }),
      {
        name: 'hopefx-store',
        partialize: (state) => ({
          token: state.token,
          user: state.user,
          isAuthenticated: state.isAuthenticated,
          activeSymbol: state.activeSymbol,
          activeTimeframe: state.activeTimeframe,
          watchlist: state.watchlist,
        }),
      },
    ),
    { name: 'HopeFX' },
  ),
);

// ─── Selectors ────────────────────────────────────────────────────────────────

export const selectToken           = (s: AppStore) => s.token;
export const selectUser            = (s: AppStore) => s.user;
export const selectIsAuth          = (s: AppStore) => s.isAuthenticated;
export const selectPrice           = (symbol: string) => (s: AppStore) => s.prices[symbol];
export const selectPriceHistory    = (symbol: string) => (s: AppStore) => s.priceHistory[symbol] ?? [];
export const selectPositions       = (s: AppStore) => s.positions;
export const selectOrders          = (s: AppStore) => s.orders;
export const selectOpenOrders      = (s: AppStore) =>
  s.orders.filter((o) => o.status === 'open' || o.status === 'pending');
export const selectSignals         = (s: AppStore) => s.signals;
export const selectAccount         = (s: AppStore) => s.account;
export const selectDepth           = (symbol: string) => (s: AppStore) => s.depth[symbol];
export const selectActiveSymbol    = (s: AppStore) => s.activeSymbol;
export const selectActiveTimeframe = (s: AppStore) => s.activeTimeframe;
export const selectWatchlist       = (s: AppStore) => s.watchlist;
export const selectWsStatus        = (s: AppStore) => s.wsStatus;
