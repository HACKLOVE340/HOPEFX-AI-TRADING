/**
 * store/index.ts
 * Global Zustand store — single source of truth for all real-time state.
 *
 * Slices:
 *   auth          – JWT token, user profile, role
 *   prices        – live bid/ask/mid per symbol + tick history
 *   positions     – open positions
 *   signals       – latest ML signals (capped at 50)
 *   account       – balance, equity, margin, risk metrics
 *   orchestrator  – health, quality, microstructure, sentiment, macro
 *   ws            – WebSocket connection status
 */

import { create } from 'zustand';
import { devtools, persist } from 'zustand/middleware';
import type {
  User,
  PriceTick,
  Position,
  Signal,
  AccountMetrics,
  WsStatus,
  OrchestratorHealth,
  QualityReport,
  MicrostructureSnapshot,
  SentimentResponse,
  MacroResponse,
  EquityPoint,
  PerformanceSummary,
} from '../types';

// Re-export types for backward compat
export type { User, PriceTick, Position, Signal, AccountMetrics, WsStatus };
export type { UserRole } from '../types';

// ─── Auth slice ───────────────────────────────────────────────────────────────

interface AuthSlice {
  token:           string | null;
  user:            User | null;
  isAuthenticated: boolean;
  plan:            import('../lib/subscription').Plan;
  setPlan:         (plan: import('../lib/subscription').Plan) => void;
  setAuth:         (token: string, user: User) => void;
  clearAuth:       () => void;
}

// ─── Price slice ──────────────────────────────────────────────────────────────

interface PriceSlice {
  prices:       Record<string, PriceTick>;
  priceHistory: Record<string, PriceTick[]>;
  setPrice:     (tick: PriceTick) => void;
}

// ─── Position slice ───────────────────────────────────────────────────────────

interface PositionSlice {
  positions:      Position[];
  setPositions:   (positions: Position[]) => void;
  upsertPosition: (position: Position) => void;
  removePosition: (id: string) => void;
}

// ─── Signal slice ─────────────────────────────────────────────────────────────

interface SignalSlice {
  signals:    Signal[];
  setSignals: (signals: Signal[]) => void;
  addSignal:  (signal: Signal) => void;
}

// ─── Account slice ────────────────────────────────────────────────────────────

interface AccountSlice {
  account:    AccountMetrics | null;
  setAccount: (metrics: AccountMetrics) => void;
}

// ─── Orchestrator slice ───────────────────────────────────────────────────────

interface OrchestratorSlice {
  orchestratorHealth:    OrchestratorHealth | null;
  qualityReport:         QualityReport | null;
  microstructure:        MicrostructureSnapshot | null;
  sentiment:             SentimentResponse | null;
  macro:                 MacroResponse | null;
  equityCurve:           EquityPoint[];
  performanceSummary:    PerformanceSummary | null;
  setOrchestratorHealth: (h: OrchestratorHealth) => void;
  setQualityReport:      (r: QualityReport) => void;
  setMicrostructure:     (s: MicrostructureSnapshot) => void;
  setSentiment:          (s: SentimentResponse) => void;
  setMacro:              (m: MacroResponse) => void;
  setEquityCurve:        (curve: EquityPoint[]) => void;
  setPerformanceSummary: (s: PerformanceSummary) => void;
}

// ─── Alerts slice ─────────────────────────────────────────────────────────────

export interface TriggeredAlert {
  id:           string;
  symbol:       string;
  condition:    string;
  target_price: number;
  triggered_at: string;
  message?:     string;
}

interface AlertsSlice {
  triggeredAlerts:  TriggeredAlert[];
  addTriggeredAlert: (alert: TriggeredAlert) => void;
  clearTriggeredAlerts: () => void;
}

// ─── WebSocket slice ──────────────────────────────────────────────────────────

interface WsSlice {
  wsStatus:      WsStatus;
  lastHeartbeat: number | null;
  setWsStatus:   (status: WsStatus) => void;
  setHeartbeat:  (ts: number) => void;
}

// ─── Combined store type ──────────────────────────────────────────────────────

export type AppStore =
  AuthSlice &
  PriceSlice &
  PositionSlice &
  SignalSlice &
  AccountSlice &
  OrchestratorSlice &
  AlertsSlice &
  WsSlice;

// ─── Constants ────────────────────────────────────────────────────────────────

const MAX_TICK_HISTORY = 200;
const MAX_SIGNALS      = 50;

// ─── Store implementation ─────────────────────────────────────────────────────

export const useStore = create<AppStore>()(
  devtools(
    persist(
      (set) => ({
        // ── Auth ──────────────────────────────────────────────────────────────
        token:           null,
        user:            null,
        isAuthenticated: false,
        plan:            'free' as import('../lib/subscription').Plan,

        setAuth: (token, user) =>
          set({ token, user, isAuthenticated: true }, false, 'auth/setAuth'),

        clearAuth: () =>
          set({ token: null, user: null, isAuthenticated: false, plan: 'free' }, false, 'auth/clearAuth'),

        setPlan: (plan) =>
          set({ plan }, false, 'auth/setPlan'),

        // ── Prices ────────────────────────────────────────────────────────────
        prices:       {},
        priceHistory: {},

        setPrice: (tick) =>
          set(
            (state) => {
              const history = state.priceHistory[tick.symbol] ?? [];
              const updated = [...history, tick].slice(-MAX_TICK_HISTORY);
              return {
                prices:       { ...state.prices, [tick.symbol]: tick },
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
              signals: [signal, ...state.signals].slice(0, MAX_SIGNALS),
            }),
            false,
            'signals/add',
          ),

        // ── Account ───────────────────────────────────────────────────────────
        account: null,

        setAccount: (account) =>
          set({ account }, false, 'account/setAccount'),

        // ── Orchestrator ──────────────────────────────────────────────────────
        orchestratorHealth: null,
        qualityReport:      null,
        microstructure:     null,
        sentiment:          null,
        macro:              null,
        equityCurve:        [],
        performanceSummary: null,

        setOrchestratorHealth: (orchestratorHealth) =>
          set({ orchestratorHealth }, false, 'orchestrator/health'),

        setQualityReport: (qualityReport) =>
          set({ qualityReport }, false, 'orchestrator/quality'),

        setMicrostructure: (microstructure) =>
          set({ microstructure }, false, 'orchestrator/microstructure'),

        setSentiment: (sentiment) =>
          set({ sentiment }, false, 'orchestrator/sentiment'),

        setMacro: (macro) =>
          set({ macro }, false, 'orchestrator/macro'),

        setEquityCurve: (equityCurve) =>
          set({ equityCurve }, false, 'performance/equityCurve'),

        setPerformanceSummary: (performanceSummary) =>
          set({ performanceSummary }, false, 'performance/summary'),

        // ── Alerts ────────────────────────────────────────────────────────────
        triggeredAlerts: [],

        addTriggeredAlert: (alert) =>
          set(
            (state) => ({
              triggeredAlerts: [alert, ...state.triggeredAlerts].slice(0, 100),
            }),
            false,
            'alerts/add',
          ),

        clearTriggeredAlerts: () =>
          set({ triggeredAlerts: [] }, false, 'alerts/clear'),

        // ── WebSocket ─────────────────────────────────────────────────────────
        wsStatus:      'disconnected',
        lastHeartbeat: null,

        setWsStatus: (wsStatus) =>
          set({ wsStatus }, false, 'ws/setStatus'),

        setHeartbeat: (ts) =>
          set({ lastHeartbeat: ts }, false, 'ws/heartbeat'),
      }),
      {
        name: 'hopefx-store',
        partialize: (state) => ({
          token:           state.token,
          user:            state.user,
          isAuthenticated: state.isAuthenticated,
        }),
      },
    ),
    { name: 'HopeFX' },
  ),
);

// ─── Selectors ────────────────────────────────────────────────────────────────

export const selectToken              = (s: AppStore) => s.token;
export const selectUser               = (s: AppStore) => s.user;
export const selectIsAuth             = (s: AppStore) => s.isAuthenticated;
export const selectPrice              = (symbol: string) => (s: AppStore) => s.prices[symbol];
export const selectPriceHistory       = (symbol: string) => (s: AppStore) => s.priceHistory[symbol] ?? [];
export const selectPositions          = (s: AppStore) => s.positions;
export const selectSignals            = (s: AppStore) => s.signals;
export const selectAccount            = (s: AppStore) => s.account;
export const selectWsStatus           = (s: AppStore) => s.wsStatus;
export const selectOrchestratorHealth = (s: AppStore) => s.orchestratorHealth;
export const selectQualityReport      = (s: AppStore) => s.qualityReport;
export const selectMicrostructure     = (s: AppStore) => s.microstructure;
export const selectSentiment          = (s: AppStore) => s.sentiment;
export const selectMacro              = (s: AppStore) => s.macro;
export const selectEquityCurve        = (s: AppStore) => s.equityCurve;
export const selectPerformanceSummary = (s: AppStore) => s.performanceSummary;
export const selectTriggeredAlerts    = (s: AppStore) => s.triggeredAlerts;
export const selectKillSwitch         = (s: AppStore) => s.account?.kill_switch ?? false;
export const selectDataQualityScore   = (s: AppStore) =>
  s.orchestratorHealth?.quality_score ?? null;
export const selectPlan               = (s: AppStore) => s.plan;
