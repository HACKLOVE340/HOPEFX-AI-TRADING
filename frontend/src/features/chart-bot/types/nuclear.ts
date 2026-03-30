/**
 * chart-bot/types/nuclear.ts
 * Nuclear dashboard type definitions — extends the base chart-bot types
 * with geopolitical risk, RL decision, and nuclear alert structures.
 */

// ─── Nuclear Severity ─────────────────────────────────────────────────────────

export type NuclearAction =
  | 'normal'
  | 'pause_new_entries'
  | 'hedge_mode'
  | 'nuclear_mode';

export type RLActionLabel = 'NORMAL' | 'PAUSE' | 'HEDGE' | 'NUCLEAR';

export type GaugeLabel = 'NORMAL' | 'ELEVATED' | 'HIGH' | 'CRITICAL';

// ─── Matched Term (from WORDMAP scorer) ──────────────────────────────────────

export interface MatchedTerm {
  term: string;
  category: string;
  weight: number;
  count: number;
  contribution: number;
}

// ─── Nuclear State ────────────────────────────────────────────────────────────

export interface NuclearState {
  severity: number;           // 0–10
  action: NuclearAction;
  nuclear_level: number;      // 0–3
  trading_paused: boolean;
  rl_action: number;          // 0–3
  rl_action_label: RLActionLabel;
  rl_agent_loaded: boolean;
  confidence: number;         // 0–1
  raw_score: number;
  matched_terms: MatchedTerm[];
  category_scores: Record<string, number>;
  vol_factor: number;
  sentiment_factor: number;
  explanation: string;        // human-readable co-pilot text
  alert_active: boolean;
  historical_analog: string | null;
  cooldown_remaining: number;
  event_count: number;
}

// ─── Geopolitical Gauge ───────────────────────────────────────────────────────

export interface GeopoliticalGauge {
  score: number;    // 0–100
  label: GaugeLabel;
  color: string;    // hex
  flashing: boolean;
  severity: number;
}

// ─── Risk Data ────────────────────────────────────────────────────────────────

export interface NuclearRiskData {
  cvar_95: number;
  cvar_99: number;
  var_95: number;
  exposure: number;
  max_risk: number;
  kill_switch_active: boolean;
  kill_switch_reason: string | null;
  daily_pnl: number;
  drawdown_pct: number;
  equity: number;
  balance: number;
}

// ─── Price Data ───────────────────────────────────────────────────────────────

export interface NuclearPriceData {
  bid: number;
  ask: number;
  mid: number;
  spread: number;
  change_pct: number;
  source: string;
}

// ─── Prediction Path ──────────────────────────────────────────────────────────

export interface PredictionPoint {
  time: number;   // unix seconds
  price: number;
  low: number;
  high: number;
  scenario: 'normal' | 'nuclear';
}

// ─── Nuclear Signal ───────────────────────────────────────────────────────────

export interface NuclearSignal {
  id: string;
  direction: 'long' | 'short' | 'neutral';
  confidence: number;
  model: string;
  entry: number;
  sl: number;
  tp: number;
  reason: string;
  ts: number;
}

// ─── Equity Point ─────────────────────────────────────────────────────────────

export interface NuclearEquityPoint {
  time: number;
  equity: number;
  drawdown: number;
  annotation?: string;
}

// ─── Nuclear Event (history) ──────────────────────────────────────────────────

export interface NuclearEvent {
  ts: number;
  text: string;
  severity: number;
  action: NuclearAction;
  explanation: string;
}

// ─── Full Chart State (from /ws/nuclear) ─────────────────────────────────────

export interface NuclearChartState {
  type: 'nuclear_chart_update';
  ts: number;
  price: NuclearPriceData;
  bars: {
    '1m': OHLCVBar[];
    '5m': OHLCVBar[];
    '1h': OHLCVBar[];
  };
  nuclear: NuclearState;
  risk: NuclearRiskData;
  signals: NuclearSignal[];
  equity_curve: NuclearEquityPoint[];
  prediction_path: PredictionPoint[];
  geopolitical_gauge: GeopoliticalGauge;
  nuclear_events: NuclearEvent[];
}

// ─── WebSocket Messages ───────────────────────────────────────────────────────

export interface NuclearAlertMessage {
  type: 'nuclear_alert';
  ts: number;
  severity: number;
  action: NuclearAction;
  rl_action_label: RLActionLabel;
  explanation: string;
  historical_analog: string | null;
  gauge: GeopoliticalGauge;
}

export interface NuclearResumeMessage {
  type: 'nuclear_resume';
  ts: number;
  message: string;
}

export type NuclearWsMessage =
  | NuclearChartState
  | NuclearAlertMessage
  | NuclearResumeMessage
  | { type: 'heartbeat'; ts: number }
  | { type: 'pong'; ts: number }
  | { type: 'subscribed'; channels: string[]; ts: number }
  | { type: 'event_scored'; result: NuclearState; ts: number }
  | { type: 'nuclear_history'; events: NuclearEvent[]; ts: number }
  | { type: 'error'; message: string };

// ─── Re-export OHLCVBar for convenience ──────────────────────────────────────

export interface OHLCVBar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

// ─── Nuclear color helpers ────────────────────────────────────────────────────

export const NUCLEAR_COLORS = {
  severity: {
    0:  '#00ff88',  // normal
    1:  '#00ff88',
    2:  '#84cc16',
    3:  '#84cc16',
    4:  '#fbbf24',
    5:  '#f59e0b',
    6:  '#f97316',
    7:  '#ef4444',
    8:  '#dc2626',
    9:  '#ff0033',
    10: '#ff0033',
  } as Record<number, string>,

  action: {
    normal:            '#00ff88',
    pause_new_entries: '#fbbf24',
    hedge_mode:        '#f97316',
    nuclear_mode:      '#ff0033',
  } as Record<NuclearAction, string>,

  rl: {
    NORMAL:  '#00ff88',
    PAUSE:   '#fbbf24',
    HEDGE:   '#f97316',
    NUCLEAR: '#ff0033',
  } as Record<RLActionLabel, string>,
} as const;

export function severityColor(severity: number): string {
  return NUCLEAR_COLORS.severity[Math.min(10, Math.max(0, severity))] ?? '#00ff88';
}

export function actionColor(action: NuclearAction): string {
  return NUCLEAR_COLORS.action[action] ?? '#00ff88';
}

export function severityLabel(severity: number): string {
  if (severity >= 9) return 'CRITICAL';
  if (severity >= 7) return 'HIGH';
  if (severity >= 5) return 'ELEVATED';
  if (severity >= 3) return 'MODERATE';
  return 'NORMAL';
}
