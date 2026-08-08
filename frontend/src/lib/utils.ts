/**
 * lib/utils.ts — shared utility functions for the trading UI.
 */

import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

// ── Tailwind class merger ─────────────────────────────────────────────────────

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// ── Symbol normalisation ──────────────────────────────────────────────────────
// The UI shows instruments as "XAU/USD" but the backend validates every order
// to canonical MT5 form ("XAUUSD"), and the WS/price feeds sometimes use
// "XAU_USD". Comparing these with === silently fails: a position stored as
// "XAUUSD" never matches a panel filtering on "XAU/USD", so the user's own
// open trades and signals disappear from symbol-scoped views. Always compare
// through these helpers, never with raw ===.

/** Canonical, comparison-safe form of a symbol: uppercase, no separators. */
export function canonicalSymbol(s: string | null | undefined): string {
  if (!s) return '';
  return s.replace(/[/_\-\s]/g, '').toUpperCase();
}

/** True when two symbols refer to the same instrument regardless of formatting. */
export function sameSymbol(a: string | null | undefined, b: string | null | undefined): boolean {
  return canonicalSymbol(a) === canonicalSymbol(b);
}
/**
 * Normalise a position's direction to 'long' | 'short' | null.
 *
 * The API is inconsistent: some endpoints return `side`, others `direction`, and
 * either may be absent — which is why `pos.direction.toLowerCase()` crashed
 * PnLDashboard (audit #37/#40) while three other call sites each wrote their own
 * slightly different comparison. `null` means "not reported", which callers must
 * render as unknown rather than defaulting to short.
 */
export function positionSide(
  pos: { side?: string | null; direction?: string | null } | null | undefined,
): 'long' | 'short' | null {
  const raw = (pos?.side ?? pos?.direction ?? '').toString().trim().toLowerCase();
  if (!raw) return null;
  if (raw === 'long' || raw === 'buy' || raw === 'b') return 'long';
  if (raw === 'short' || raw === 'sell' || raw === 's') return 'short';
  return null;
}

/**
 * Convert a compact pair symbol to the slash form the price feed keys on:
 * `XAUUSD` → `XAU/USD`. Already-slashed input is returned unchanged.
 *
 * Watchlist previously did this with a hardcoded chain of five .replace() calls
 * while offering ten symbols, so ETHUSD, USDCAD, AUDUSD, USDCHF and NZDUSD never
 * matched a feed key and showed no live price at all. Three other sites did it
 * with `sym.slice(0,3) + '/' + sym.slice(3)`, which is the same rule written a
 * fourth time and silently wrong for anything that is not six characters.
 */
export function toSlashSymbol(symbol: string): string {
  if (!symbol || symbol.includes('/')) return symbol;
  if (symbol.length !== 6) return symbol;
  return `${symbol.slice(0, 3)}/${symbol.slice(3)}`;
}


// ── Safe redirect validation ──────────────────────────────────────────────────
/**
 * True only for a same-origin, root-relative path safe to pass to navigate().
 *
 * The login page reads its post-auth destination from a user-controlled `?next=`
 * param. Without this guard, `?next=//evil.com` (protocol-relative) or the
 * backslash variants `/\evil.com` / `\\evil.com` are an open redirect — and the
 * installed react-router has an unpatched advisory (GHSA open-redirect via
 * backslash, CVE-2025-68470 bypass) that its own internal check does not stop.
 * Validating here closes it regardless of the router version.
 */
export function isSafeRedirectPath(path: string | null | undefined): boolean {
  if (!path || typeof path !== 'string') return false;
  if (!path.startsWith('/')) return false;          // must be root-relative
  if (path.startsWith('//')) return false;          // protocol-relative → external
  if (path.includes('\\')) return false;            // backslash bypass tricks
  if (/^\/[a-z][a-z0-9+.-]*:/i.test(path)) return false; // /javascript:, /data:, …
  return true;
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

/**
 * Format P&L with sign and currency symbol, e.g. 50 → "+$50.00", -50 → "-$50.00".
 *
 * The sign is placed before the currency symbol, which is why the magnitude is
 * formatted separately. The negative branch previously produced an empty sign
 * while still taking Math.abs, so every loss rendered as a positive number —
 * a -$500 position read as "$500.00" in the positions table, the portfolio
 * summary and the performance page. Colour usually carried the meaning; the
 * number did not.
 */
export function fmtPnl(value: number | null | undefined, decimals = 2): string {
  if (value == null || !isFinite(value)) return '—';
  const sign = value < 0 ? '-' : '+';
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

/**
 * Margin level = equity / margin_used * 100.
 *
 * Three cases the raw number handles badly:
 *   - No margin in use. The ratio is undefined (division by zero). Backends
 *     report this as either 0.0 (api/trading.py) or the 9999.0 sentinel
 *     (api/ws_live.py, which chose it precisely because the UI read 0.0 as a
 *     margin call). Both mean "nothing at risk".
 *   - Negligible margin in use. $0.81 against $10,000 equity is a true
 *     1234568%, which is arithmetically correct and completely unreadable.
 *   - Genuinely low margin level, which is the only case worth a number.
 *
 * Anything at or above MARGIN_LEVEL_SAFE is reported as ">999%": accurate,
 * bounded, and unambiguous. Only the actionable range gets a precise figure.
 */
export const MARGIN_LEVEL_SAFE = 1000;

export function fmtMarginLevel(value: number | null | undefined): string {
  if (value == null || !isFinite(value)) return '—';
  if (value <= 0) return '—';
  if (value >= MARGIN_LEVEL_SAFE) return '>999%';
  return `${value.toFixed(0)}%`;
}

/** True when the margin level represents a healthy account (or no exposure). */
export function marginLevelIsSafe(value: number | null | undefined): boolean {
  if (value == null || !isFinite(value)) return true;
  return value <= 0 || value >= MARGIN_LEVEL_SAFE;
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
 *
 * A request timeout / network failure has NO response at all (err.response is
 * undefined), so it falls through to err.message — which for Axios is the raw
 * string "timeout of 30000ms exceeded". That was leaking to users verbatim
 * across every call site that renders this function's result. Detected and
 * replaced with a friendly, actionable message instead.
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
  // Timeout / network error: no HTTP response was ever received. Never show
  // the raw "timeout of Nms exceeded" string — show something the user can
  // act on (retry), which is also the accurate explanation (nothing came back
  // at all, as opposed to the server actively returning an error).
  const code = (err as { code?: unknown })?.code;
  const msg = (err as { message?: unknown })?.message;
  const isTimeoutOrNetwork =
    !response &&
    (code === 'ECONNABORTED' ||
      code === 'ERR_NETWORK' ||
      (typeof msg === 'string' && /timeout of \d+ms exceeded/i.test(msg)));
  if (isTimeoutOrNetwork) return 'Connection is slow or unavailable — please try again.';
  if (typeof msg === 'string' && msg.length > 0) return msg;
  return fallback;
}

/**
 * One-line summary of what closing *all* positions actually does (S10-03).
 *
 * There were two close-all confirmations with different wording and different
 * information: `Trade.tsx` said "this will market-close every open position
 * immediately" — a category, not a quantity — and `PositionsTable` gave a count
 * and nothing else. Neither told the trader the number that matters: the P&L
 * they are about to realise. Closing three winners and closing three losers
 * read identically.
 *
 * Both call sites now use this, so the two cannot drift apart again — the
 * duplication failure mode from S13-01.
 */
export function describeCloseAll(
  positions: ReadonlyArray<{ symbol?: string | null; unrealized_pnl?: number | null }>,
): string {
  const list = positions ?? [];
  if (list.length === 0) return 'There are no open positions to close.';

  // Sum only the P&L we actually have. A missing value must not become 0 and
  // silently understate the total, and must never surface as NaN.
  const known = list.map((p) => p.unrealized_pnl).filter((v): v is number => typeof v === 'number' && isFinite(v));
  const net = known.reduce((a, b) => a + b, 0);
  const partial = known.length !== list.length;

  const symbols = list.map((p) => p.symbol).filter((s): s is string => !!s);
  const unique = Array.from(new Set(symbols));
  const named = unique.length > 0 && unique.length <= 4 ? ` (${unique.join(', ')})` : '';

  const outcome =
    known.length === 0
      ? 'P&L unavailable'
      : `realising a ${net < 0 ? 'loss' : 'profit'} of ${fmtPnl(net)}`;

  const caveat = partial ? ' P&L is missing for some positions, so the total may be understated.' : '';

  return (
    `Market-close ${list.length} open position${list.length === 1 ? '' : 's'}${named}, ` +
    `${outcome}. This cannot be undone.${caveat}`
  );
}

/** Default staleness threshold for on-screen data-age indicators (S10-05). */
export const DATA_STALE_AFTER_MS = 30_000;

/**
 * Human age of a piece of data, in the words a trader reads at a glance.
 *
 * There was no latency or data-age indicator anywhere in the app (S10-05), so a
 * frozen price and a live one were visually identical.
 *
 * A negative age (client/server clock skew) reads as "just now" rather than
 * "-5s ago" — the alternative invites the reader to distrust the whole widget.
 */
export function formatAge(ageMs: number | null | undefined): string {
  if (ageMs == null || !isFinite(ageMs)) return 'unknown';
  const ms = Math.max(0, ageMs);
  if (ms < 1_000) return 'just now';
  const s = Math.floor(ms / 1_000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  return `${Math.floor(m / 60)}h ago`;
}

/**
 * Whether a quality/confidence reading still describes reality (S9-02).
 *
 * `LivePriceTicker` renders the orchestrator's quality score as a percentage.
 * That score is assigned when a tick is ingested and never re-evaluated as the
 * tick ages, so a tick graded GOOD at 14:00 still reported 94% at 15:00 — the
 * one visible freshness cue reinforcing the stalled-feed illusion instead of
 * correcting it.
 *
 * A missing timestamp returns false: never assume fresh.
 */
export function qualityIsMeaningful(
  lastDataAt: number | null | undefined,
  staleAfterMs: number = DATA_STALE_AFTER_MS,
): boolean {
  if (lastDataAt == null || !isFinite(lastDataAt)) return false;
  return Date.now() - lastDataAt < staleAfterMs;
}
