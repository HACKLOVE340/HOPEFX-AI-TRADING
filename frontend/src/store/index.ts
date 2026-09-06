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
export type { User, PriceTick, Position, Signal, AccountMetrics, WsStatus, OrchestratorHealth };
export type { UserRole } from '../types';

// ─── Auth slice ───────────────────────────────────────────────────────────────

interface AuthSlice {
  token:           string | null;
  user:            User | null;
  isAuthenticated: boolean;
  plan:            import('../lib/subscription').Plan;
  trial:           boolean;
  trialDaysRemaining: number | null;
  setPlan:         (plan: import('../lib/subscription').Plan, trial?: boolean, trialDaysRemaining?: number | null) => void;
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
  wsStatus:        WsStatus;
  /**
   * Timestamp of the last `heartbeat` message specifically.
   *
   * **This is not the freshness signal — nothing reads it.** F3-02: of the
   * store's 33 state fields it is the only one with zero readers outside this
   * file, and the audit playbook already named it as the known example. It is
   * kept because the heartbeat message type exists and dropping the field would
   * make `useWebSocket` discard a message silently.
   *
   * It is a decoy, which is why this comment is here: it carries the name a
   * reader reaches for when they want "is the feed alive?", and answering that
   * from it is wrong — a heartbeat is the transport telling you the socket is
   * open, which is the exact thing S9-01 showed keeps being true while no data
   * arrives.
   *
   * For liveness use `lastDataAt` / `feedStale`, or `selectFeedLive`, which
   * combine them with the connection state.
   */
  lastHeartbeat:   number | null;
  /**
   * Timestamp of the last *data* message (tick, account, position…) received
   * from the server, independent of connection status.
   *
   * `wsStatus` reflects the TCP/WebSocket state, which stays `'connected'`
   * when the server's broadcast loop stalls — the socket is open, nothing is
   * arriving. `lastHeartbeat` was already recorded but read nowhere outside
   * tests, so the client had no way to observe that condition and rendered the
   * last price it received indefinitely under a green indicator.
   * See docs/HARDENING_BACKLOG.md S9-01 / S10-05.
   */
  lastDataAt:      number | null;
  /** True when no data has arrived for longer than the stale threshold. */
  feedStale:       boolean;
  noLiveFeed:      boolean;
  noLiveFeedMsg:   string | null;
  setWsStatus:     (status: WsStatus) => void;
  setHeartbeat:    (ts: number) => void;
  /** Record that a data message arrived; clears `feedStale`. */
  markDataReceived: (ts?: number) => void;
  setFeedStale:    (stale: boolean) => void;
  setNoLiveFeed:   (active: boolean, msg?: string) => void;
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

// ─── AI job slice ─────────────────────────────────────────────────────────────
// State pushed over the private `ai_jobs` WebSocket channel while a generation
// runs. The workbench still polls; this only makes it react sooner.
//
// NOT persisted. A job carries the operator's prompt and the model's answer, so
// writing it to localStorage would leave one person's questions on a shared
// machine after they log out. `partialize` is an allowlist, which is why this
// needs no exclusion — but it is the reason not to add one.

export interface AiJobUpdate {
  id:        string;
  state:     string;
  prompt?:   string;
  progress?: string[];
  /** Monotonic per job. The workbench prefers the higher of push and poll, so
   *  a frame delayed behind a poll cannot revert a finished job to `running`. */
  rev?:      number;
  [key: string]: unknown;
}

interface AiJobSlice {
  aiJobs:      Record<string, AiJobUpdate>;
  upsertAiJob: (job: AiJobUpdate) => void;
}

// ─── UI preferences slice ─────────────────────────────────────────────────────
// Persisted sidebar personalisation: pinned (favorite) nav items, collapsed
// group state, and a short MRU list of recently-visited paths. All three are
// purely cosmetic, so they are safe to persist to localStorage.

interface UiSlice {
  favorites:       string[];   // nav item paths the user has pinned
  collapsedGroups: string[];   // nav group ids the user has collapsed
  recentPaths:     string[];   // most-recently-visited paths (newest first)
  toggleFavorite:  (path: string) => void;
  toggleGroup:     (groupId: string) => void;
  pushRecentPath:  (path: string) => void;
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
  SystemEventSlice &
  AiJobSlice &
  UiSlice;

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
        token:              null,
        user:               null,
        isAuthenticated:    false,
        plan:               'free' as import('../lib/subscription').Plan,
        trial:              false,
        trialDaysRemaining: null,

        setAuth: (token, user) =>
          set({ token, user, isAuthenticated: true }, false, 'auth/setAuth'),

        clearAuth: () => {
          // Invalidate the in-memory CSRF cache so the next request fetches a
          // fresh token rather than sending a stale one the server has expired.
          resetCsrfCache();
          set({ token: null, user: null, isAuthenticated: false, plan: 'free', trial: false, trialDaysRemaining: null }, false, 'auth/clearAuth');
        },

        setPlan: (plan, trial = false, trialDaysRemaining = null) =>
          set({ plan, trial, trialDaysRemaining }, false, 'auth/setPlan'),

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
        lastDataAt:    null,
        feedStale:     false,
        noLiveFeed:    false,
        noLiveFeedMsg: null,

        setWsStatus: (wsStatus) =>
          set({ wsStatus }, false, 'ws/setStatus'),

        // A heartbeat is itself evidence the server is still sending, so it
        // clears staleness too.
        setHeartbeat: (ts) =>
          set({ lastHeartbeat: ts, lastDataAt: ts, feedStale: false }, false, 'ws/heartbeat'),

        markDataReceived: (ts) =>
          set({ lastDataAt: ts ?? Date.now(), feedStale: false }, false, 'ws/data'),

        setFeedStale: (feedStale) =>
          set({ feedStale }, false, 'ws/feedStale'),

        setNoLiveFeed: (active, msg) =>
          set({ noLiveFeed: active, noLiveFeedMsg: msg ?? null }, false, 'ws/noLiveFeed'),

        // ── System Events ──────────────────────────────────────────────────────
        systemAlert: null,

        setSystemAlert: (alert) =>
          set({ systemAlert: alert }, false, 'system/setAlert'),

        clearSystemAlert: () =>
          set({ systemAlert: null }, false, 'system/clear'),

        // ── AI jobs ────────────────────────────────────────────────────────────
        aiJobs: {},

        upsertAiJob: (job) =>
          set(
            (state) => {
              const prev = state.aiJobs[job.id];
              // Drop a frame that is older than what we already hold. Frames
              // can arrive out of order after a reconnect, and applying a stale
              // one would show a finished job as still running.
              if (prev && (prev.rev ?? 0) > (job.rev ?? 0)) return state;
              return { aiJobs: { ...state.aiJobs, [job.id]: job } };
            },
            false,
            'ai/upsertJob',
          ),

        // ── UI preferences ──────────────────────────────────────────────────────
        favorites:       [],
        collapsedGroups: [],
        recentPaths:     [],

        toggleFavorite: (path) =>
          set(
            (state) => ({
              favorites: state.favorites.includes(path)
                ? state.favorites.filter((p) => p !== path)
                : [...state.favorites, path],
            }),
            false,
            'ui/toggleFavorite',
          ),

        toggleGroup: (groupId) =>
          set(
            (state) => ({
              collapsedGroups: state.collapsedGroups.includes(groupId)
                ? state.collapsedGroups.filter((g) => g !== groupId)
                : [...state.collapsedGroups, groupId],
            }),
            false,
            'ui/toggleGroup',
          ),

        pushRecentPath: (path) =>
          set(
            (state) => {
              if (state.recentPaths[0] === path) return state;
              return {
                recentPaths: [path, ...state.recentPaths.filter((p) => p !== path)].slice(0, 6),
              };
            },
            false,
            'ui/pushRecentPath',
          ),
      }),
      {
        name: 'hopefx-store',
        partialize: (state) => ({
          // token is NOT persisted — it lives in memory only.
          // On page refresh the silent-refresh interceptor (useApi.ts) uses
          // the httpOnly refresh-token cookie to obtain a new access token
          // before the first authenticated request fires.
          user:               state.user,
          // isAuthenticated is persisted so AuthGuard knows to attempt a
          // silent refresh rather than immediately redirecting to /login.
          // IMPORTANT: on rehydration isAuthenticated is reset to false in
          // onRehydrateStorage so the value is never trusted without a live
          // token. AuthGuard re-sets it to true after /me succeeds.
          isAuthenticated:    state.isAuthenticated,
          // Persist plan/trial so SubscriptionGate doesn't flash the upgrade
          // wall on every page load while usePlan waits for the billing API.
          // usePlan will overwrite these with the authoritative server values.
          plan:               state.plan,
          trial:              state.trial,
          trialDaysRemaining: state.trialDaysRemaining,
          // Sidebar personalisation — purely cosmetic, safe to persist.
          favorites:          state.favorites,
          collapsedGroups:    state.collapsedGroups,
          recentPaths:        state.recentPaths,
        }),
        onRehydrateStorage: () => (rehydratedState) => {
          // Called once localStorage rehydration is complete.
          // Any hook reading token/isAuthenticated after this point is safe.
          _hasHydrated = true;

          // After rehydration token is always null (not persisted). Reset
          // isAuthenticated to false so no component treats the user as
          // authenticated before the silent-refresh round-trip completes.
          // AuthGuard will set isAuthenticated=true again after /me succeeds.
          // Without this reset, a user whose refresh cookie has expired would
          // see isAuthenticated=true indefinitely (stale localStorage value)
          // until AuthGuard's /me call fails and calls clearAuth().
          if (rehydratedState) {
            rehydratedState.isAuthenticated = false;
          }
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
export const selectNoLiveFeed         = (s: AppStore) => ({ active: s.noLiveFeed, msg: s.noLiveFeedMsg });
export const selectOrchestratorHealth = (s: AppStore) => s.orchestratorHealth;
export const selectQualityReport      = (s: AppStore) => s.qualityReport;
export const selectMicrostructure     = (s: AppStore) => s.microstructure;
export const selectSentiment          = (s: AppStore) => s.sentiment;
export const selectMacro              = (s: AppStore) => s.macro;
export const selectEquityCurve        = (s: AppStore) => s.equityCurve;
export const selectPerformanceSummary = (s: AppStore) => s.performanceSummary;
export const selectTriggeredAlerts    = (s: AppStore) => s.triggeredAlerts;
/**
 * Whether trading is halted, from every source that can say so (S10-02).
 *
 * Three surfaces used to derive this independently — AccountBar from
 * `account.kill_switch`, RiskTransparencyStrip from
 * `risk.kill_switch_active ?? account.kill_switch`, RiskDashboard from
 * `account.kill_switch` — so a backend populating only the risk snapshot made
 * one badge read HALTED while two read nothing, on the same screen, about the
 * same switch. That is the frontend half of the S2-01 split brain.
 *
 * Deliberately an OR, not a precedence chain: a safety indicator may
 * over-report, never under-report. If any source says halted, we say halted.
 */
export const selectKillSwitch         = (s: AppStore): boolean =>
  Boolean(s.riskSnapshot?.kill_switch_active) || Boolean(s.account?.kill_switch);

/**
 * Is the live feed actually delivering — as opposed to merely connected?
 * (audit F1-02)
 *
 * `wsStatus` alone is not the answer: S9-01 is precisely that it stays
 * `'connected'` while the server's broadcast loop stalls. Nothing errors,
 * nothing reconnects, the numbers just stop moving.
 *
 * Three conditions, all required:
 *   - the socket is open,
 *   - the watchdog has not flagged the feed stale,
 *   - and something has actually arrived.
 *
 * The last one is the easy one to leave out. Connected-but-nothing-received-yet
 * is "unknown", not "live", and rendering unknown as live is the S10-01 defect
 * (an empty list shown for "flat" and for "we have no idea" alike). Same
 * asymmetry as `selectKillSwitch`: over-report a problem, never under-report.
 *
 * One copy, because three surfaces each deriving the kill switch their own way
 * was S10-02 and `PositionsTable` had already started the same drift here.
 */
export const selectFeedLive           = (s: AppStore): boolean =>
  s.wsStatus === 'connected' && !s.feedStale && s.lastDataAt != null;
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
export const selectTrial              = (s: AppStore) => s.trial;
export const selectTrialDaysRemaining = (s: AppStore) => s.trialDaysRemaining;
export const selectSystemAlert        = (s: AppStore) => s.systemAlert;
export const selectAiJobs             = (s: AppStore) => s.aiJobs;
export const selectFavorites          = (s: AppStore) => s.favorites;
export const selectCollapsedGroups    = (s: AppStore) => s.collapsedGroups;
export const selectRecentPaths        = (s: AppStore) => s.recentPaths;

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
