/**
 * chart-bot/utils/formatters.ts
 * Number, time, and label formatting utilities for trading data.
 */

// ─── Price Formatting ─────────────────────────────────────────────────────────

export function formatPrice(value: number, decimals = 2): string {
  if (!isFinite(value)) return '—';
  return value.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export function formatPriceDelta(value: number, decimals = 2): string {
  if (!isFinite(value)) return '—';
  const sign = value >= 0 ? '+' : '';
  return `${sign}${formatPrice(value, decimals)}`;
}

export function formatPct(value: number, decimals = 2): string {
  if (!isFinite(value)) return '—';
  const sign = value >= 0 ? '+' : '';
  return `${sign}${value.toFixed(decimals)}%`;
}

export function formatPnl(value: number): string {
  if (!isFinite(value)) return '—';
  const sign = value >= 0 ? '+$' : '-$';
  return `${sign}${Math.abs(value).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function formatVolume(value: number): string {
  if (!isFinite(value)) return '—';
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(2)}M`;
  if (value >= 1_000)     return `${(value / 1_000).toFixed(1)}K`;
  return value.toFixed(0);
}

export function formatSpread(spread: number): string {
  if (!isFinite(spread)) return '—';
  // Gold spread in pips (1 pip = 0.01 for XAUUSD)
  return `${(spread * 100).toFixed(1)} pts`;
}

// ─── Confidence ───────────────────────────────────────────────────────────────

export function formatConfidence(value: number): string {
  return `${(value * 100).toFixed(0)}%`;
}

export function confidenceLabel(value: number): string {
  if (value >= 0.85) return 'VERY HIGH';
  if (value >= 0.70) return 'HIGH';
  if (value >= 0.55) return 'MODERATE';
  if (value >= 0.40) return 'LOW';
  return 'VERY LOW';
}

// ─── Time ─────────────────────────────────────────────────────────────────────

export function formatTime(ts: number): string {
  // ts can be unix seconds or ms — normalise
  const ms = ts > 1e10 ? ts : ts * 1000;
  return new Date(ms).toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

export function formatDateTime(ts: number): string {
  const ms = ts > 1e10 ? ts : ts * 1000;
  return new Date(ms).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

export function formatRelativeTime(ts: number): string {
  const ms = ts > 1e10 ? ts : ts * 1000;
  const diff = Date.now() - ms;
  if (diff < 60_000)  return `${Math.floor(diff / 1000)}s ago`;
  if (diff < 3600_000)return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86400_000)return `${Math.floor(diff / 3600_000)}h ago`;
  return `${Math.floor(diff / 86400_000)}d ago`;
}

// ─── Regime Labels ────────────────────────────────────────────────────────────

export function regimeLabel(regime: string): string {
  const map: Record<string, string> = {
    trending_bull: 'TRENDING ↑',
    trending_bear: 'TRENDING ↓',
    ranging:       'RANGING',
    volatile:      'VOLATILE',
    breakout:      'BREAKOUT',
    reversal:      'REVERSAL',
  };
  return map[regime] ?? regime.toUpperCase();
}

export function regimeColor(regime: string): string {
  const map: Record<string, string> = {
    trending_bull: '#00ff88',
    trending_bear: '#ff3366',
    ranging:       '#f59e0b',
    volatile:      '#a855f7',
    breakout:      '#00d4ff',
    reversal:      '#fbbf24',
  };
  return map[regime] ?? '#64748b';
}

// ─── Impact Labels ────────────────────────────────────────────────────────────

export function impactColor(label: string): string {
  const map: Record<string, string> = {
    high:   '#ff3366',
    medium: '#f59e0b',
    low:    '#64748b',
  };
  return map[label] ?? '#64748b';
}

// ─── Misc ─────────────────────────────────────────────────────────────────────

export function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

export function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

export function normalise(value: number, min: number, max: number): number {
  if (max === min) return 0;
  return clamp((value - min) / (max - min), 0, 1);
}
