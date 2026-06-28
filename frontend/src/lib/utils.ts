/**
 * lib/utils.ts — shared utility functions for the trading UI.
 */

import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

// ── Tailwind class merger ─────────────────────────────────────────────────────

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// ── Number formatting ─────────────────────────────────────────────────────────

/** Format a price with fixed decimal places, e.g. 2345.67 → "2,345.67" */
export function fmtPrice(value: number | null | undefined, decimals = 2): string {
  if (value == null || !isFinite(value)) return '—';
  return value.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

/** Format a percentage, e.g. 0.0523 → "+5.23%" */
export function fmtPct(value: number | null | undefined, decimals = 2): string {
  if (value == null || !isFinite(value)) return '—';
  const sign = value >= 0 ? '+' : '';
  return `${sign}${(value * 100).toFixed(decimals)}%`;
}

/** Format a raw percentage number, e.g. 5.23 → "+5.23%" */
export function fmtPctRaw(value: number | null | undefined, decimals = 2): string {
  if (value == null || !isFinite(value)) return '—';
  const sign = value >= 0 ? '+' : '';
  return `${sign}${value.toFixed(decimals)}%`;
}

/** Format P&L with sign and currency symbol */
export function fmtPnl(value: number | null | undefined, decimals = 2): string {
  if (value == null || !isFinite(value)) return '—';
  const sign = value >= 0 ? '+' : '';
  return `${sign}$${Math.abs(value).toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })}`;
}

/** Format a large number with K/M/B suffix */
export function fmtCompact(value: number | null | undefined): string {
  if (value == null || !isFinite(value)) return '—';
  if (Math.abs(value) >= 1e9) return `${(value / 1e9).toFixed(2)}B`;
  if (Math.abs(value) >= 1e6) return `${(value / 1e6).toFixed(2)}M`;
  if (Math.abs(value) >= 1e3) return `${(value / 1e3).toFixed(1)}K`;
  return value.toFixed(2);
}

/** Format spread in pips (for gold: 1 pip = $0.01) */
export function fmtSpread(spread: number | null | undefined): string {
  if (spread == null || !isFinite(spread)) return '—';
  return `${(spread * 100).toFixed(1)} pts`;
}

/** Format a ratio (Sharpe, Sortino) */
export function fmtRatio(value: number | null | undefined): string {
  if (value == null || !isFinite(value)) return '—';
  return value.toFixed(2);
}

// ── Color helpers ─────────────────────────────────────────────────────────────

/** Returns Tailwind text class for a P&L value */
export function pnlColor(value: number | null | undefined): string {
  if (value == null) return 'text-slate-400';
  if (value > 0) return 'text-bull';
  if (value < 0) return 'text-bear';
  return 'text-slate-400';
}

/** Returns Tailwind text class for a directional value */
export function dirColor(dir: 'long' | 'short' | 'neutral' | string): string {
  if (dir === 'long')  return 'text-bull';
  if (dir === 'short') return 'text-bear';
  return 'text-slate-400';
}

/** Returns hex color for confidence level */
export function confColor(confidence: number): string {
  if (confidence >= 0.75) return '#00e676';
  if (confidence >= 0.55) return '#ffb800';
  return '#ff6b35';
}

/** Returns hex color for macro impact */
export function impactColor(impact: string): string {
  if (impact === 'high')   return '#ff3b5c';
  if (impact === 'medium') return '#ffb800';
  if (impact === 'low')    return '#00d4ff';
  return '#475569';
}

/** Returns hex color for sentiment score (-1 to +1) */
export function sentimentColor(score: number): string {
  if (score > 0.2)  return '#00e676';
  if (score < -0.2) return '#ff1744';
  return '#ffb800';
}

// ── Time formatting ───────────────────────────────────────────────────────────

/** Format ISO timestamp to HH:MM:SS */
export function fmtTime(iso: string | number | null | undefined): string {
  if (iso == null) return '—';
  const d = typeof iso === 'number' ? new Date(iso) : new Date(iso);
  if (isNaN(d.getTime())) return '—';
  return d.toLocaleTimeString('en-US', {
    hour:   '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

/** Format ISO timestamp to date + time */
export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '—';
  return d.toLocaleString('en-US', {
    month:  'short',
    day:    'numeric',
    hour:   '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

/** Relative time, e.g. "2m ago" */
export function fmtRelative(iso: string | number | null | undefined): string {
  if (iso == null) return '—';
  const d = typeof iso === 'number' ? new Date(iso) : new Date(iso);
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60)   return `${Math.floor(diff)}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

// ── WebSocket ─────────────────────────────────────────────────────────────────

/**
 * Returns the WebSocket base URL for the current environment.
 *
 * Priority:
 *   1. VITE_WS_URL env var (set in .env / docker-compose)
 *   2. Derived from window.location — wss:// on HTTPS, ws:// on HTTP.
 *      This avoids mixed-content errors on production HTTPS deployments
 *      where a hardcoded ws:// fallback would be blocked by the browser.
 *
 * Usage:
 *   const ws = new WebSocket(`${getWsBase()}/ws/notifications?token=${token}`);
 */
export function getWsBase(): string {
  const envUrl = import.meta.env.VITE_WS_URL as string | undefined;
  if (envUrl) return envUrl;
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}`;
}

// ── API response coercion ──────────────────────────────────────────────────────

/**
 * Coerce an API response into an array, tolerating the common shapes a FastAPI
 * endpoint may return: `{ <key>: [...] }`, a bare `[...]`, or anything else
 * (error envelope, partial object) → `[]`.
 *
 * This prevents the frequent "X.map is not a function" / "X.filter is not a
 * function" render crash when a section does `setState(res.data.items ?? res.data)`
 * and the response is a non-array object. Always returns a real array.
 *
 * Usage: `setEvents(asArray(res.data, 'events'))`
 */
export function asArray<T = unknown>(data: unknown, key?: string): T[] {
  if (key && data && typeof data === 'object' && !Array.isArray(data)) {
    const v = (data as Record<string, unknown>)[key];
    if (Array.isArray(v)) return v as T[];
  }
  return Array.isArray(data) ? (data as T[]) : [];
}

// ── Misc ──────────────────────────────────────────────────────────────────────

/** Clamp a value between min and max */
export function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

/** Linear interpolation */
export function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

/** Compute drawdown series from equity curve */
export function computeDrawdown(equity: number[]): number[] {
  let peak = equity[0] ?? 0;
  return equity.map((e) => {
    if (e > peak) peak = e;
    return peak > 0 ? (e - peak) / peak : 0;
  });
}

/**
 * Extract a human-readable error message from an Axios error.
 *
 * FastAPI can return `detail` as either a string or an object
 * ({msg, loc, type} on 422/503). This function handles both shapes
 * so callers never render [object Object].
 *
 * Priority: response.data.detail → response.data.message → err.message → fallback
 */
export function extractApiError(err: unknown, fallback = 'An error occurred'): string {
  if (err == null) return fallback;
  const response = (err as { response?: { status?: number; data?: { detail?: unknown; message?: unknown } } })?.response;
  const data = response?.data;
  const raw = data?.detail ?? data?.message;
  if (typeof raw === 'string' && raw.length > 0) return raw;
  if (raw && typeof raw === 'object') {
    const d = raw as { msg?: string; message?: string };
    const s = d.msg ?? d.message;
    if (typeof s === 'string' && s.length > 0) return s;
    return JSON.stringify(raw);
  }
  // For 404 with no body, return the fallback rather than the raw Axios message
  // ("Request failed with status code 404") which is not user-friendly.
  if (response?.status === 404) return fallback;
  const msg = (err as { message?: unknown })?.message;
  if (typeof msg === 'string' && msg.length > 0) return msg;
  return fallback;
}
