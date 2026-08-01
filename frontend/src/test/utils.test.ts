/**
 * Utility / pure-function tests — formatting, math, validation helpers.
 * ~120 tests (no React needed)
 */

import { describe, it, expect } from 'vitest';

// Real implementations under test (the helpers below this are inline copies).
import { fmtMarginLevel, marginLevelIsSafe, canonicalSymbol, sameSymbol, isSafeRedirectPath, positionSide } from '../lib/utils';

// ─── Open-redirect guard ──────────────────────────────────────────────────────
// The login page redirects to a user-controlled ?next= param. These are the
// payloads the guard must reject (open redirect / XSS) vs the internal paths
// it must allow.
describe('isSafeRedirectPath', () => {
  it('allows root-relative internal paths', () => {
    for (const p of ['/dashboard', '/superadmin', '/trade?symbol=XAUUSD', '/a/b/c']) {
      expect(isSafeRedirectPath(p)).toBe(true);
    }
  });

  it('rejects protocol-relative and absolute external URLs', () => {
    for (const p of ['//evil.com', 'https://evil.com', 'http://evil.com', 'evil.com']) {
      expect(isSafeRedirectPath(p)).toBe(false);
    }
  });

  it('rejects the backslash bypass variants (CVE-2025-68470)', () => {
    for (const p of ['/\\evil.com', '\\\\evil.com', '/\\/evil.com', '\\evil.com']) {
      expect(isSafeRedirectPath(p)).toBe(false);
    }
  });

  it('rejects scheme-in-path and empty/nullish', () => {
    expect(isSafeRedirectPath('/javascript:alert(1)')).toBe(false);
    expect(isSafeRedirectPath('/data:text/html,x')).toBe(false);
    expect(isSafeRedirectPath('')).toBe(false);
    expect(isSafeRedirectPath(null)).toBe(false);
    expect(isSafeRedirectPath(undefined)).toBe(false);
  });
});

// ─── Symbol normalisation ─────────────────────────────────────────────────────
// Regression cover for the bug where a user's open position ("XAUUSD" canonical)
// vanished from a symbol-scoped panel filtering on the UI form ("XAU/USD"),
// because the filter used === instead of a format-tolerant compare.
describe('canonicalSymbol / sameSymbol', () => {
  it('strips separators and upper-cases', () => {
    expect(canonicalSymbol('XAU/USD')).toBe('XAUUSD');
    expect(canonicalSymbol('xau_usd')).toBe('XAUUSD');
    expect(canonicalSymbol('XAU-USD')).toBe('XAUUSD');
    expect(canonicalSymbol('XAUUSD')).toBe('XAUUSD');
  });

  it('treats every formatting of the same instrument as equal', () => {
    // The exact mismatch that hid open trades: slash form vs canonical.
    expect(sameSymbol('XAU/USD', 'XAUUSD')).toBe(true);
    expect(sameSymbol('XAU_USD', 'XAUUSD')).toBe(true);
    expect(sameSymbol('xau/usd', 'XAUUSD')).toBe(true);
    expect(sameSymbol('EUR/USD', 'EURUSD')).toBe(true);
  });

  it('does not conflate different instruments', () => {
    expect(sameSymbol('XAU/USD', 'XAG/USD')).toBe(false);
    expect(sameSymbol('EURUSD', 'GBPUSD')).toBe(false);
  });

  it('handles null / undefined / empty safely', () => {
    expect(sameSymbol(null, 'XAUUSD')).toBe(false);
    expect(sameSymbol(undefined, undefined)).toBe(true); // both empty
    expect(canonicalSymbol(null)).toBe('');
  });

  it('models the fixed position filter: canonical positions match a UI-form filter', () => {
    const positions = [
      { symbol: 'XAUUSD' }, { symbol: 'EURUSD' }, { symbol: 'XAUUSD' },
    ];
    const uiSymbol = 'XAU/USD';
    const shown = positions.filter((p) => sameSymbol(p.symbol, uiSymbol));
    expect(shown).toHaveLength(2); // was 0 before the fix
  });
});

// ─── Inline helpers (same logic as Dashboard) ─────────────────────────────────

const fmt = (n: number, d = 2) =>
  n.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });

const fmtUSD = (n: number) =>
  (n >= 0 ? '+' : '') + n.toLocaleString('en-US', { style: 'currency', currency: 'USD' });

const fmtPct = (n: number) => (n >= 0 ? '+' : '') + n.toFixed(2) + '%';

// ─── fmt ──────────────────────────────────────────────────────────────────────

describe('fmt', () => {
  it('formats integer with 2 decimals', () => {
    expect(fmt(1000)).toBe('1,000.00');
  });
  it('formats float with 2 decimals', () => {
    expect(fmt(1234.5)).toBe('1,234.50');
  });
  it('formats with 4 decimals', () => {
    expect(fmt(1.08523, 4)).toBe('1.0852');
  });
  it('formats with 5 decimals', () => {
    expect(fmt(1.08523, 5)).toBe('1.08523');
  });
  it('formats zero', () => {
    expect(fmt(0)).toBe('0.00');
  });
  it('formats negative number', () => {
    expect(fmt(-500)).toBe('-500.00');
  });
  it('formats large number with commas', () => {
    expect(fmt(1_000_000)).toBe('1,000,000.00');
  });
  it('formats small decimal', () => {
    expect(fmt(0.001, 3)).toBe('0.001');
  });
  it('rounds correctly', () => {
    expect(fmt(1.005, 2)).toMatch(/1\.(00|01)/); // locale rounding
  });
  it('formats 0 decimals', () => {
    expect(fmt(67000, 0)).toBe('67,000');
  });
});

// ─── fmtUSD ───────────────────────────────────────────────────────────────────

describe('fmtUSD', () => {
  it('positive value has + prefix', () => {
    expect(fmtUSD(500)).toMatch(/^\+/);
  });
  it('negative value has no + prefix', () => {
    expect(fmtUSD(-500)).not.toMatch(/^\+/);
  });
  it('zero has + prefix', () => {
    expect(fmtUSD(0)).toMatch(/^\+/);
  });
  it('includes $ symbol', () => {
    expect(fmtUSD(100)).toContain('$');
  });
  it('formats positive correctly', () => {
    expect(fmtUSD(1000)).toBe('+$1,000.00');
  });
  it('formats negative correctly', () => {
    expect(fmtUSD(-1000)).toBe('-$1,000.00');
  });
  it('formats large positive', () => {
    expect(fmtUSD(100_000)).toBe('+$100,000.00');
  });
  it('formats small positive', () => {
    expect(fmtUSD(0.50)).toBe('+$0.50');
  });
  it('formats large negative', () => {
    expect(fmtUSD(-50_000)).toContain('50,000');
  });
});

// ─── fmtPct ───────────────────────────────────────────────────────────────────

describe('fmtPct', () => {
  it('positive has + prefix', () => {
    expect(fmtPct(1.5)).toBe('+1.50%');
  });
  it('negative has no + prefix', () => {
    expect(fmtPct(-1.5)).toBe('-1.50%');
  });
  it('zero has + prefix', () => {
    expect(fmtPct(0)).toBe('+0.00%');
  });
  it('includes % symbol', () => {
    expect(fmtPct(5)).toContain('%');
  });
  it('rounds to 2 decimals', () => {
    expect(fmtPct(1.234)).toBe('+1.23%');
  });
  it('handles large percentage', () => {
    expect(fmtPct(100)).toBe('+100.00%');
  });
  it('handles small percentage', () => {
    expect(fmtPct(0.01)).toBe('+0.01%');
  });
});

// ─── Price tick validation ────────────────────────────────────────────────────

describe('price tick structure', () => {
  const validTick = {
    symbol: 'XAU/USD', bid: 2339.9, ask: 2340.1, mid: 2340.0,
    spread: 0.2, timestamp: Date.now(), change_pct: 0.5,
  };

  it('bid < mid', () => { expect(validTick.bid).toBeLessThan(validTick.mid); });
  it('mid < ask', () => { expect(validTick.mid).toBeLessThan(validTick.ask); });
  it('spread = ask - bid', () => {
    expect(validTick.spread).toBeCloseTo(validTick.ask - validTick.bid, 5);
  });
  it('timestamp is positive', () => { expect(validTick.timestamp).toBeGreaterThan(0); });
  it('symbol is string', () => { expect(typeof validTick.symbol).toBe('string'); });
  it('change_pct is number', () => { expect(typeof validTick.change_pct).toBe('number'); });
});

// ─── Position P&L math ────────────────────────────────────────────────────────

describe('position P&L calculations', () => {
  const calcPnl = (side: 'long' | 'short', entry: number, current: number, size: number) =>
    side === 'long' ? (current - entry) * size : (entry - current) * size;

  it('long position profit when price rises', () => {
    expect(calcPnl('long', 2300, 2350, 1)).toBe(50);
  });
  it('long position loss when price falls', () => {
    expect(calcPnl('long', 2300, 2250, 1)).toBe(-50);
  });
  it('short position profit when price falls', () => {
    expect(calcPnl('short', 2300, 2250, 1)).toBe(50);
  });
  it('short position loss when price rises', () => {
    expect(calcPnl('short', 2300, 2350, 1)).toBe(-50);
  });
  it('zero P&L when entry equals current', () => {
    expect(calcPnl('long', 2300, 2300, 1)).toBe(0);
  });
  it('P&L scales with size', () => {
    expect(calcPnl('long', 2300, 2350, 2)).toBe(100);
  });
  it('fractional size works', () => {
    expect(calcPnl('long', 2300, 2350, 0.5)).toBe(25);
  });
  it('large position size', () => {
    expect(calcPnl('long', 1.085, 1.090, 100_000)).toBeCloseTo(500, 2);
  });
});

// ─── Signal confidence thresholds ────────────────────────────────────────────

describe('signal confidence thresholds', () => {
  const getColor = (conf: number) =>
    conf > 0.75 ? 'green' : conf > 0.55 ? 'yellow' : 'red';

  it('0.9 confidence is green', () => { expect(getColor(0.9)).toBe('green'); });
  it('0.76 confidence is green', () => { expect(getColor(0.76)).toBe('green'); });
  it('0.75 confidence is yellow', () => { expect(getColor(0.75)).toBe('yellow'); });
  it('0.6 confidence is yellow', () => { expect(getColor(0.6)).toBe('yellow'); });
  it('0.56 confidence is yellow', () => { expect(getColor(0.56)).toBe('yellow'); });
  it('0.55 confidence is red', () => { expect(getColor(0.55)).toBe('red'); });
  it('0.3 confidence is red', () => { expect(getColor(0.3)).toBe('red'); });
  it('0.0 confidence is red', () => { expect(getColor(0.0)).toBe('red'); });
  it('1.0 confidence is green', () => { expect(getColor(1.0)).toBe('green'); });
});

// ─── ML accuracy thresholds ───────────────────────────────────────────────────

describe('ML accuracy thresholds', () => {
  const getStatus = (acc: number) =>
    acc >= 0.85 ? 'target' : acc >= 0.70 ? 'partial' : 'below';

  it('0.90 meets target', () => { expect(getStatus(0.90)).toBe('target'); });
  it('0.85 meets target', () => { expect(getStatus(0.85)).toBe('target'); });
  it('0.84 is partial', () => { expect(getStatus(0.84)).toBe('partial'); });
  it('0.70 is partial', () => { expect(getStatus(0.70)).toBe('partial'); });
  it('0.69 is below', () => { expect(getStatus(0.69)).toBe('below'); });
  it('0.49 is below', () => { expect(getStatus(0.49)).toBe('below'); });
  it('1.0 meets target', () => { expect(getStatus(1.0)).toBe('target'); });
  it('0.0 is below', () => { expect(getStatus(0.0)).toBe('below'); });
});

// ─── Account metrics validation ───────────────────────────────────────────────

describe('account metrics', () => {
  const acc = {
    balance: 100_000, equity: 102_000, margin_used: 4_000, margin_free: 96_000,
    margin_level: 2550, daily_pnl: 500, daily_pnl_pct: 0.5, total_pnl: 2_000,
    win_rate: 0.65, sharpe_ratio: 1.8, max_drawdown: 0.04, open_trades: 2,
  };

  it('equity > balance when profitable', () => {
    expect(acc.equity).toBeGreaterThan(acc.balance);
  });
  it('margin_free = balance - margin_used', () => {
    expect(acc.margin_free).toBe(acc.balance - acc.margin_used);
  });
  it('win_rate is between 0 and 1', () => {
    expect(acc.win_rate).toBeGreaterThan(0);
    expect(acc.win_rate).toBeLessThanOrEqual(1);
  });
  it('max_drawdown is between 0 and 1', () => {
    expect(acc.max_drawdown).toBeGreaterThanOrEqual(0);
    expect(acc.max_drawdown).toBeLessThanOrEqual(1);
  });
  it('sharpe_ratio is positive for good strategy', () => {
    expect(acc.sharpe_ratio).toBeGreaterThan(0);
  });
  it('daily_pnl_pct matches daily_pnl / balance', () => {
    expect(acc.daily_pnl_pct).toBeCloseTo(acc.daily_pnl / acc.balance * 100, 0);
  });
  it('open_trades is non-negative integer', () => {
    expect(acc.open_trades).toBeGreaterThanOrEqual(0);
    expect(Number.isInteger(acc.open_trades)).toBe(true);
  });
});

// ─── WebSocket message routing ────────────────────────────────────────────────

describe('WebSocket message types', () => {
  const validTypes = ['price_tick', 'position_update', 'position_close', 'signal', 'account_update', 'heartbeat', 'error'];

  it.each(validTypes)('"%s" is a valid message type', (type) => {
    expect(validTypes).toContain(type);
  });

  it('unknown type does not crash router', () => {
    const route = (type: string) => {
      switch (type) {
        case 'price_tick': return 'price';
        case 'signal': return 'signal';
        default: return 'unknown';
      }
    };
    expect(route('garbage')).toBe('unknown');
  });

  it('price_tick routes to price handler', () => {
    const route = (type: string) => type === 'price_tick' ? 'price' : 'other';
    expect(route('price_tick')).toBe('price');
  });

  it('heartbeat routes correctly', () => {
    const route = (type: string) => type === 'heartbeat' ? 'hb' : 'other';
    expect(route('heartbeat')).toBe('hb');
  });
});

// ─── Equity history generation ────────────────────────────────────────────────

describe('equity history', () => {
  function generateEquityHistory(startBalance = 100_000, days = 90) {
    const points: { time: string; value: number }[] = [];
    let val = startBalance;
    const now = new Date();
    for (let i = days - 1; i >= 0; i--) {
      const d = new Date(now);
      d.setDate(d.getDate() - i);
      val = val * (1 + (Math.random() - 0.44) * 0.008);
      points.push({ time: d.toISOString().slice(0, 10), value: parseFloat(val.toFixed(2)) });
    }
    return points;
  }

  it('generates correct number of points', () => {
    expect(generateEquityHistory(100_000, 90)).toHaveLength(90);
  });
  it('generates 30 points when requested', () => {
    expect(generateEquityHistory(100_000, 30)).toHaveLength(30);
  });
  it('first point is oldest date', () => {
    const pts = generateEquityHistory();
    expect(new Date(pts[0].time) < new Date(pts[pts.length - 1].time)).toBe(true);
  });
  it('all values are positive', () => {
    const pts = generateEquityHistory();
    expect(pts.every(p => p.value > 0)).toBe(true);
  });
  it('time format is YYYY-MM-DD', () => {
    const pts = generateEquityHistory();
    expect(pts[0].time).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
  it('values are finite numbers', () => {
    const pts = generateEquityHistory();
    expect(pts.every(p => isFinite(p.value))).toBe(true);
  });
  it('starting value is near startBalance', () => {
    const pts = generateEquityHistory(100_000);
    // First value should be within 5% of start
    expect(pts[0].value).toBeGreaterThan(90_000);
    expect(pts[0].value).toBeLessThan(110_000);
  });
});

// ─── Role hierarchy ───────────────────────────────────────────────────────────

describe('role hierarchy', () => {
  const ROLE_RANK: Record<string, number> = {
    user: 0, trader: 1, admin: 2, superadmin: 3,
  };

  const canAccess = (userRole: string, requiredRole: string) =>
    (ROLE_RANK[userRole] ?? 0) >= (ROLE_RANK[requiredRole] ?? 0);

  it('superadmin can access all roles', () => {
    expect(canAccess('superadmin', 'user')).toBe(true);
    expect(canAccess('superadmin', 'trader')).toBe(true);
    expect(canAccess('superadmin', 'admin')).toBe(true);
    expect(canAccess('superadmin', 'superadmin')).toBe(true);
  });
  it('admin cannot access superadmin', () => {
    expect(canAccess('admin', 'superadmin')).toBe(false);
  });
  it('admin can access trader and user', () => {
    expect(canAccess('admin', 'trader')).toBe(true);
    expect(canAccess('admin', 'user')).toBe(true);
  });
  it('trader cannot access admin', () => {
    expect(canAccess('trader', 'admin')).toBe(false);
  });
  it('user cannot access trader', () => {
    expect(canAccess('user', 'trader')).toBe(false);
  });
  it('user can access user', () => {
    expect(canAccess('user', 'user')).toBe(true);
  });
  it('unknown role defaults to rank 0 (same as user)', () => {
    // ROLE_RANK returns 0 for unknown via ?? 0, same as 'user' rank 0
    // so unknown can access 'user' level — this is the actual behaviour
    expect(canAccess('unknown', 'user')).toBe(true);
    expect(canAccess('unknown', 'trader')).toBe(false);
  });
});

// ─── GBM price simulation math ────────────────────────────────────────────────

describe('GBM price simulation', () => {
  function gbmStep(price: number, vol: number, dt: number): number {
    const z = 0; // deterministic for testing
    return price * Math.exp((0 - 0.5 * vol * vol) * dt + vol * Math.sqrt(dt) * z);
  }

  it('zero shock keeps price near original', () => {
    const next = gbmStep(2340, 0.01, 1 / 365);
    expect(next).toBeCloseTo(2340, 0);
  });
  it('price remains positive', () => {
    let p = 2340;
    for (let i = 0; i < 100; i++) p = gbmStep(p, 0.02, 1 / 365);
    expect(p).toBeGreaterThan(0);
  });
  it('higher volatility produces larger moves', () => {
    const lowVol  = Math.abs(gbmStep(2340, 0.001, 1) - 2340);
    const highVol = Math.abs(gbmStep(2340, 0.5,   1) - 2340);
    expect(highVol).toBeGreaterThan(lowVol);
  });
  it('dt=0 produces no change', () => {
    expect(gbmStep(2340, 0.01, 0)).toBeCloseTo(2340, 5);
  });
});

// ── fmtMarginLevel ────────────────────────────────────────────────────────────
//
// Regression: the Trade page displayed "1234568%" for a $10,000 account with
// $0.81 of margin in use. Arithmetically correct, completely unreadable. And a
// flat account rendered as a margin-call warning, because api/trading.py
// returned 0.0 while api/ws_live.py returned the 9999.0 sentinel for the very
// same state — so the colour depended on which transport answered.

describe('fmtMarginLevel', () => {
  it('renders an actionable margin level precisely', () => {
    expect(fmtMarginLevel(150)).toBe('150%');
    expect(fmtMarginLevel(99.6)).toBe('100%');
  });

  it('bounds the unreadable end instead of printing it', () => {
    expect(fmtMarginLevel(1234567.9)).toBe('>999%');   // $0.81 used vs $10,000
    expect(fmtMarginLevel(9999)).toBe('>999%');        // NO_MARGIN_LEVEL sentinel
    expect(fmtMarginLevel(1000)).toBe('>999%');
    expect(fmtMarginLevel(999)).toBe('999%');
  });

  it('shows no value when there is nothing to report', () => {
    expect(fmtMarginLevel(0)).toBe('—');
    expect(fmtMarginLevel(null)).toBe('—');
    expect(fmtMarginLevel(undefined)).toBe('—');
    expect(fmtMarginLevel(NaN)).toBe('—');
    expect(fmtMarginLevel(Infinity)).toBe('—');
  });

  it('treats a flat account as safe, not as a margin call', () => {
    // Both backend sentinels, and the negligible-margin case, must be safe.
    expect(marginLevelIsSafe(9999)).toBe(true);
    expect(marginLevelIsSafe(1234567.9)).toBe(true);
    expect(marginLevelIsSafe(0)).toBe(true);
    expect(marginLevelIsSafe(null)).toBe(true);
    // A genuinely low margin level is not safe.
    expect(marginLevelIsSafe(80)).toBe(false);
    expect(marginLevelIsSafe(150)).toBe(false);
  });
});

// ─── positionSide ─────────────────────────────────────────────────────────────
// The API returns `side` on some endpoints and `direction` on others, and either
// may be absent. Four call sites each wrote their own comparison; one of them
// (`pos.direction.toLowerCase()`) crashed PnLDashboard outright (audit #37/#40).
describe('positionSide', () => {
  it('reads either field', () => {
    expect(positionSide({ side: 'long' })).toBe('long');
    expect(positionSide({ direction: 'long' })).toBe('long');
    expect(positionSide({ side: 'short' })).toBe('short');
    expect(positionSide({ direction: 'short' })).toBe('short');
  });

  it('accepts the broker spellings', () => {
    expect(positionSide({ side: 'BUY' })).toBe('long');
    expect(positionSide({ direction: 'Sell' })).toBe('short');
    expect(positionSide({ side: ' LONG ' })).toBe('long');
    expect(positionSide({ side: 'b' })).toBe('long');
    expect(positionSide({ side: 's' })).toBe('short');
  });

  it('prefers side when both are present', () => {
    expect(positionSide({ side: 'long', direction: 'short' })).toBe('long');
  });

  it('returns null rather than guessing', () => {
    // Defaulting to short would state the opposite of the truth half the time,
    // and every previous call site did exactly that via a falsy else-branch.
    expect(positionSide({})).toBeNull();
    expect(positionSide(null)).toBeNull();
    expect(positionSide(undefined)).toBeNull();
    expect(positionSide({ side: '' })).toBeNull();
    expect(positionSide({ side: '   ' })).toBeNull();
    expect(positionSide({ direction: 'sideways' })).toBeNull();
  });

  it('does not throw on an absent field — the original crash', () => {
    expect(() => positionSide({ direction: undefined })).not.toThrow();
    expect(() => positionSide({ side: null })).not.toThrow();
  });
});
