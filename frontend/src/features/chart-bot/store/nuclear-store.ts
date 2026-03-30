/**
 * chart-bot/store/nuclear-store.ts
 * Zustand store for nuclear dashboard state.
 * Single source of truth for all nuclear/geopolitical risk data.
 */

import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import type {
  NuclearChartState,
  NuclearState,
  NuclearRiskData,
  NuclearPriceData,
  GeopoliticalGauge,
  NuclearSignal,
  NuclearEquityPoint,
  NuclearEvent,
  PredictionPoint,
  NuclearAlertMessage,
  OHLCVBar,
} from '../types/nuclear';
import type { NuclearWsStatus } from '../hooks/useNuclearWS';

// ─── Store shape ──────────────────────────────────────────────────────────────

interface NuclearStoreState {
  // Connection
  wsStatus: NuclearWsStatus;
  lastUpdate: number | null;

  // Price
  price: NuclearPriceData | null;

  // Bars per timeframe
  bars1m: OHLCVBar[];
  bars5m: OHLCVBar[];
  bars1h: OHLCVBar[];
  activeTimeframe: '1m' | '5m' | '1h';

  // Nuclear state
  nuclear: NuclearState | null;
  activeAlert: NuclearAlertMessage | null;

  // Risk
  risk: NuclearRiskData | null;

  // Signals
  signals: NuclearSignal[];

  // Equity curve
  equityCurve: NuclearEquityPoint[];

  // Prediction path
  predictionPath: PredictionPoint[];

  // Geopolitical gauge
  gauge: GeopoliticalGauge | null;

  // Nuclear event history
  nuclearEvents: NuclearEvent[];

  // UI state
  protectedView: boolean;   // true when nuclear_mode active
  showExplainPanel: boolean;
  selectedEventIndex: number | null;

  // Actions
  setChartState: (state: NuclearChartState) => void;
  setNuclearAlert: (alert: NuclearAlertMessage | null) => void;
  setWsStatus: (status: NuclearWsStatus) => void;
  setActiveTimeframe: (tf: '1m' | '5m' | '1h') => void;
  setShowExplainPanel: (show: boolean) => void;
  setSelectedEventIndex: (idx: number | null) => void;
  dismissAlert: () => void;
}

// ─── Store ────────────────────────────────────────────────────────────────────

export const useNuclearStore = create<NuclearStoreState>()(
  devtools(
    (set, get) => ({
      wsStatus: 'disconnected',
      lastUpdate: null,
      price: null,
      bars1m: [],
      bars5m: [],
      bars1h: [],
      activeTimeframe: '1m',
      nuclear: null,
      activeAlert: null,
      risk: null,
      signals: [],
      equityCurve: [],
      predictionPath: [],
      gauge: null,
      nuclearEvents: [],
      protectedView: false,
      showExplainPanel: false,
      selectedEventIndex: null,

      setChartState: (state) => {
        const isNuclearMode = state.nuclear?.action === 'nuclear_mode';
        set(
          {
            lastUpdate: state.ts,
            price: state.price,
            bars1m: state.bars?.['1m'] ?? get().bars1m,
            bars5m: state.bars?.['5m'] ?? get().bars5m,
            bars1h: state.bars?.['1h'] ?? get().bars1h,
            nuclear: state.nuclear,
            risk: state.risk,
            signals: state.signals ?? [],
            equityCurve: state.equity_curve ?? [],
            predictionPath: state.prediction_path ?? [],
            gauge: state.geopolitical_gauge,
            nuclearEvents: state.nuclear_events ?? [],
            protectedView: isNuclearMode,
          },
          false,
          'nuclear/setChartState',
        );
      },

      setNuclearAlert: (alert) =>
        set({ activeAlert: alert }, false, 'nuclear/setAlert'),

      setWsStatus: (wsStatus) =>
        set({ wsStatus }, false, 'nuclear/setWsStatus'),

      setActiveTimeframe: (activeTimeframe) =>
        set({ activeTimeframe }, false, 'nuclear/setTimeframe'),

      setShowExplainPanel: (showExplainPanel) =>
        set({ showExplainPanel }, false, 'nuclear/setExplainPanel'),

      setSelectedEventIndex: (selectedEventIndex) =>
        set({ selectedEventIndex }, false, 'nuclear/setSelectedEvent'),

      dismissAlert: () =>
        set({ activeAlert: null }, false, 'nuclear/dismissAlert'),
    }),
    { name: 'NuclearStore' },
  ),
);

// ─── Selectors ────────────────────────────────────────────────────────────────

export const selectNuclearSeverity  = (s: NuclearStoreState) => s.nuclear?.severity ?? 0;
export const selectNuclearAction    = (s: NuclearStoreState) => s.nuclear?.action ?? 'normal';
export const selectNuclearExplain   = (s: NuclearStoreState) => s.nuclear?.explanation ?? '';
export const selectAlertActive      = (s: NuclearStoreState) => s.nuclear?.alert_active ?? false;
export const selectProtectedView    = (s: NuclearStoreState) => s.protectedView;
export const selectGauge            = (s: NuclearStoreState) => s.gauge;
export const selectActiveBars       = (s: NuclearStoreState) => {
  switch (s.activeTimeframe) {
    case '5m': return s.bars5m;
    case '1h': return s.bars1h;
    default:   return s.bars1m;
  }
};
