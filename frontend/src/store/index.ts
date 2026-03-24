/**
 * Global Zustand store — single source of truth for all real-time state.
 *
 * Slices:
 *   auth      – JWT token, user profile, role
 *   prices    – live bid/ask/mid per symbol
 *   positions – open positions
 *   signals   – latest ML signals
 *   account   – balance, equity, margin
 *   ws        – WebSocket connection status
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
  opened_at: string;
}

export interface Signal {
  id: string;
  symbol: string;
  direction: 'long' | 'short' | 'neutral';
  confidence: number;       // 0–1
  model: string;
  entry_price: number;
  stop_loss: number;
  take_profit: number;
  generated_at: string;
  status: 'active' | 'triggered' | 'expired';
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
  priceHistory: Record<string, PriceTick[]>; // last 200 ticks per symbol
  setPrice: (tick: PriceTick) => void;
}

interface PositionSlice {
  positions: Position[];
  setPositions: (positions: Position[]) => void;
  upsertPosition: (position: Position) => void;
  removePosition: (id: string) => void;
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

interface WsSlice {
  wsStatus: WsStatus;
  lastHeartbeat: number | null;
  setWsStatus: (status: WsStatus) => void;
  setHeartbeat: (ts: number) => void;
}

type AppStore = AuthSlice & PriceSlice & PositionSlice & SignalSlice & AccountSlice & WsSlice;

// ─── Store implementation ─────────────────────────────────────────────────────

const MAX_HISTORY = 200;

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
        // Only persist auth — everything else is live data
        partialize: (state) => ({
          token: state.token,
          user: state.user,
          isAuthenticated: state.isAuthenticated,
        }),
      },
    ),
    { name: 'HopeFX' },
  ),
);

// ─── Selectors (memoised) ─────────────────────────────────────────────────────

export const selectToken          = (s: AppStore) => s.token;
export const selectUser           = (s: AppStore) => s.user;
export const selectIsAuth         = (s: AppStore) => s.isAuthenticated;
export const selectPrice          = (symbol: string) => (s: AppStore) => s.prices[symbol];
export const selectPriceHistory   = (symbol: string) => (s: AppStore) => s.priceHistory[symbol] ?? [];
export const selectPositions      = (s: AppStore) => s.positions;
export const selectSignals        = (s: AppStore) => s.signals;
export const selectAccount        = (s: AppStore) => s.account;
export const selectWsStatus       = (s: AppStore) => s.wsStatus;
