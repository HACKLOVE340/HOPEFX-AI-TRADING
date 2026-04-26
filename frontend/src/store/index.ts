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
// Static import avoids the Rolldown INEFFECTIVE_DYNAMIC_IMPORT warning.
// resetCsrfCache is a pure synchronous function with no circular-dependency
// risk at module evaluation time — the store is initialised after useApi.
import { resetCsrfCache } from '../hooks/useApi';
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

// ─── Live WS snapshot types (chart-bot channel) ───────────────────────────────

export interface EquitySnapshot {
  balance:        number;
  equity:         number;
  unrealized_pnl: number;
  margin_used:    number;
  timestamp:      string;
}

export interface RiskSnapshot {
  daily_loss_pct?:     number;
  max_drawdown_pct?:   number;
  open_risk_pct?:      number;
  kill_switch_active?: boolean;
}

export interface VolumeDeltaBar {
  volume_delta:     number;
  cumulative_delta: number;
  timestamp:        string;
}

export interface WsNewsItem {
  title:           string;
  source:          string;
  sentiment_score: number;
  sentiment_label: 'bullish' | 'bearish' | 'neutral';
  published_at:    string | null;
  url?:            string | null;
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
  // Live WS chart-bot channel snapshots
  equitySnapshot:        EquitySnapshot | null;
  riskSnapshot:          RiskSnapshot | null;
  volumeDelta:           VolumeDeltaBar | null;
  newsItems:             WsNewsItem[];
  setOrchestratorHealth: (h: OrchestratorHealth) => void;
  setQualityReport:      (r: QualityReport) => void;
  setMicrostructure:     (s: MicrostructureSnapshot) => void;
  setSentiment:          (s: SentimentResponse) => void;
  setMacro:              (m: MacroResponse) => void;
  setEquityCurve:        (curve: EquityPoint[]) => void;
  setPerformanceSummary: (s: PerformanceSummary) => void;
  setEquitySnapshot:     (s: EquitySnapshot) => void;
  setRiskSnapshot:       (s: RiskSnapshot) => void;
  setVolumeDelta:        (v: VolumeDeltaBar) => void;
  addNewsItem:           (item: WsNewsItem) => void;
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

// ─── System Event slice ───────────────────────────────────────────────────────

export interface SystemAlert {
  type: string;
  reason: string;
  ts: number;
}

interface SystemEventSlice {
  systemAlert:      SystemAlert | null;
  setSystemAlert:   (alert: SystemAlert) => void;
  clearSystemAlert: () => void;
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
  WsSlice &
  SystemEventSlice;

// ─── Constants ────────────────────────────────────────────────────────────────

const MAX_TICK_HISTORY = 200;
const MAX_SIGNALS      = 50;

// ─── Store implementation ─────────────────────────────────────────────────────

// ─── Hydration gate ───────────────────────────────────────────────────────────
// Zustand persist rehydrates asynchronously from localStorage. Any hook that
// reads `token` before rehydration completes will see null and fire unauthenticated
// requests. This flag is set to true inside onRehydrateStorage so consumers can
// wait before firing authenticated queries.

let _hasHydrated = false;

export function getHasHydrated(): boolean {
  return _hasHydrated;
}

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

        clearAuth: () => {
          // Invalidate the in-memory CSRF cache so the next request fetches a
          // fresh token rather than sending a stale one the server has expired.
          resetCsrfCache();
          set({ token: null, user: null, isAuthenticated: false, plan: 'free' }, false, 'auth/clearAuth');
        },

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
        equitySnapshot:     null,
        riskSnapshot:       null,
        volumeDelta:        null,
        newsItems:          [],

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

        setEquitySnapshot: (equitySnapshot) =>
          set({ equitySnapshot }, false, 'ws/equitySnapshot'),

        setRiskSnapshot: (riskSnapshot) =>
          set({ riskSnapshot }, false, 'ws/riskSnapshot'),

        setVolumeDelta: (volumeDelta) =>
          set({ volumeDelta }, false, 'ws/volumeDelta'),

        addNewsItem: (item) =>
          set(
            (state) => ({ newsItems: [item, ...state.newsItems].slice(0, 50) }),
            false,
            'ws/addNewsItem',
          ),

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

        // ── System Events ──────────────────────────────────────────────────────
        systemAlert: null,

        setSystemAlert: (alert) =>
          set({ systemAlert: alert }, false, 'system/setAlert'),

        clearSystemAlert: () =>
          set({ systemAlert: null }, false, 'system/clear'),
      }),
      {
        name: 'hopefx-store',
        partialize: (state) => ({
          // token is NOT persisted — it lives in memory only.
          // On page refresh the silent-refresh interceptor (useApi.ts) uses
          // the httpOnly refresh-token cookie to obtain a new access token
          // before the first authenticated request fires.
          user:            state.user,
          isAuthenticated: state.isAuthenticated,
          // Persist plan so SubscriptionGate doesn't flash the upgrade wall
          // on every page load while usePlan waits for the billing API.
          // usePlan will overwrite this with the authoritative server value.
          plan:            state.plan,
        }),
        onRehydrateStorage: () => () => {
          // Called once localStorage rehydration is complete.
          // Any hook reading token/isAuthenticated after this point is safe.
          _hasHydrated = true;
        },
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
// Derived from the macro slice — true when a high-impact event blackout is active.
// Used by OrderEntryForm to disable order submission with a clear UI message.
export const selectIsBlackout         = (s: AppStore) => s.macro?.is_blackout ?? false;
export const selectEquitySnapshot     = (s: AppStore) => s.equitySnapshot;
export const selectRiskSnapshot       = (s: AppStore) => s.riskSnapshot;
export const selectVolumeDelta        = (s: AppStore) => s.volumeDelta;
export const selectNewsItems          = (s: AppStore) => s.newsItems;
export const selectDataQualityScore   = (s: AppStore) =>
  s.orchestratorHealth?.quality_score ?? null;
export const selectPlan               = (s: AppStore) => s.plan;
export const selectSystemAlert        = (s: AppStore) => s.systemAlert;

// ─── Hydration hook ───────────────────────────────────────────────────────────
// Use this in any component/hook that must wait for localStorage rehydration
// before firing authenticated API requests.
//
//   const hydrated = useHasHydrated();
//   const query = useQuery({ ..., enabled: hydrated && isAuth });

import { useSyncExternalStore } from 'react';

export function useHasHydrated(): boolean {
  return useSyncExternalStore(
    // subscribe: re-render when the store changes (covers the rehydration moment)
    useStore.subscribe,
    // getSnapshot: return the hydration flag
    () => _hasHydrated,
    // getServerSnapshot: SSR — treat as hydrated
    () => true,
  );
}
