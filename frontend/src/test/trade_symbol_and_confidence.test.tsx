/**
 * trade_symbol_and_confidence.test.tsx
 *
 * Three defects reported from the deployed terminal.
 *
 * 1. **The Trade page could not change symbol — and the order form knew it.**
 *    `OrderEntryForm` held `useState(symbolProp ?? symbols[0] ?? 'XAU/USD')`.
 *    useState reads its argument once, on mount. The Trade page passes
 *    `symbol={selectedSymbol}` and re-renders with a new value on every symbol
 *    card click, which that state then ignored — permanently holding whatever
 *    was selected when the form first mounted.
 *
 *    The card highlighted, the heading changed, the positions table changed,
 *    and the order form silently kept trading gold. The symbol dropdown that
 *    would have let you correct it is hidden exactly when `symbolProp` is
 *    passed, so there was no way back.
 *
 *    This is a money-path defect: selecting GBP/USD and pressing Buy submitted
 *    an order in XAU/USD. The confirmation dialog names the real symbol, which
 *    is the only thing standing between this and a wrong-instrument fill.
 *
 * 2. **`MARGIN >999%` printed directly above `Used: $0`.** No margin in use
 *    makes the ratio undefined; api/trading.py reports that as 0.0 and
 *    api/ws_live.py as the 9999.0 sentinel, and `fmtMarginLevel` rendered the
 *    first as "—" and the second as ">999%". Two panels disagreed about the
 *    same account purely on which endpoint answered, and ">999%" beside
 *    "Used: $0" reads as a computed ratio rather than as no exposure.
 *
 * 3. **`OFI 100.0%` and `BUY PRESS 100%` beside `TICKS 3`.** Both are
 *    normalised ratios: three ticks that all went one way read 100%, visually
 *    identical to 100% over a thousand ticks. The engine's arithmetic is right;
 *    presenting a three-sample estimate with the confidence of a converged one
 *    is not.
 */

import { describe, it, expect } from 'vitest';
import { fmtMarginLevel, NO_MARGIN_LEVEL, MARGIN_LEVEL_SAFE } from '../lib/utils';

/**
 * Source with comments removed.
 *
 * A bare text search over a file cannot tell code from the comment explaining
 * it — and the comment above this fix quotes the very expression the fix
 * removed, so the first version of the assertion below failed against its own
 * documentation.
 */
function code(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
}

// ── 1. Symbol selection ───────────────────────────────────────────────────────

describe('OrderEntryForm symbol', () => {
  it('is derived from the prop, not captured once into state', async () => {
    const src = await import('../components/panels/OrderEntryForm.tsx?raw').then((m) => m.default);

    expect(
      /useState\(\s*symbolProp/.test(code(src)),
      'symbolProp is seeded into useState again — later prop changes will be ignored',
    ).toBe(false);
    expect(code(src)).toContain('const symbol = symbolProp ?? internalSymbol');
  });

  it('still owns its symbol when the parent does not supply one', async () => {
    const src = await import('../components/panels/OrderEntryForm.tsx?raw').then((m) => m.default);
    // The standalone form keeps a working dropdown; only the controlled case changed.
    expect(src).toContain('setInternalSymbol');
    expect(src).toContain('{!symbolProp && (');
  });

  it('the Trade page passes the selected symbol down', async () => {
    const src = await import('../pages/Trade.tsx?raw').then((m) => m.default);
    expect(src).toContain('symbol={selectedSymbol}');
    expect(src).toContain('onClick={() => setSelectedSymbol(sym)}');
  });
});

// ── 2. Margin level ───────────────────────────────────────────────────────────

describe('fmtMarginLevel', () => {
  it('renders no-margin-in-use identically whichever backend reported it', () => {
    // api/trading.py says 0.0; api/ws_live.py says 9999.0. Same account state.
    expect(fmtMarginLevel(0)).toBe('—');
    expect(fmtMarginLevel(NO_MARGIN_LEVEL)).toBe('—');
  });

  it('says "—" when margin used is zero, whatever the ratio claims', () => {
    expect(fmtMarginLevel(9999, 0)).toBe('—');
    expect(fmtMarginLevel(123456, 0)).toBe('—');
  });

  it('still reports a genuine tiny exposure as >999%', () => {
    // $0.81 used against $10,000 equity is a true 1,234,568% — correct and
    // unreadable. Bounded, but not hidden: there IS exposure here.
    expect(fmtMarginLevel(1234567.9, 0.81)).toBe('>999%');
    expect(fmtMarginLevel(MARGIN_LEVEL_SAFE, 5)).toBe('>999%');
  });

  it('reports the actionable range precisely', () => {
    expect(fmtMarginLevel(180, 500)).toBe('180%');
    expect(fmtMarginLevel(95, 900)).toBe('95%');
  });

  it('handles missing and non-finite values', () => {
    expect(fmtMarginLevel(null)).toBe('—');
    expect(fmtMarginLevel(undefined)).toBe('—');
    expect(fmtMarginLevel(Number.NaN)).toBe('—');
    expect(fmtMarginLevel(Number.POSITIVE_INFINITY)).toBe('—');
  });

  it('every call site that knows margin_used passes it', async () => {
    for (const path of [
      '../pages/Trade.tsx?raw',
      '../components/terminal/AccountBar.tsx?raw',
      '../components/panels/RiskDashboard.tsx?raw',
    ]) {
      const src = await import(/* @vite-ignore */ path).then((m) => m.default);
      const calls = src.match(/fmtMarginLevel\([^)]*\)/g) ?? [];
      expect(calls.length, `no fmtMarginLevel call in ${path}`).toBeGreaterThan(0);
      for (const call of calls) {
        expect(call, `${path}: ${call} does not pass margin_used`).toContain('margin_used');
      }
    }
  });
});

// ── 3. Order-flow confidence ──────────────────────────────────────────────────

describe('microstructure strip', () => {
  it('withholds order-flow ratios below the tick threshold', async () => {
    const src = await import('../components/panels/LivePriceTicker.tsx?raw').then((m) => m.default);

    expect(src).toContain('MIN_TICKS_FOR_FLOW');
    expect(src).toContain('const enough   = ticks >= MIN_TICKS_FOR_FLOW');
    // OFI, delta and buy pressure are all gated; VWAP is a price, not a ratio,
    // and stays visible.
    expect(src).toContain("{enough ? `${(ofi * 100).toFixed(1)}%` : '—'}");
    expect(src).toContain("{enough ? `${(pressure * 100).toFixed(0)}%` : '—'}");
    expect(src).toContain("width:           enough ? `${pressure * 100}%` : '0%'");
  });

  it('flags the tick count itself when it is the limiting factor', async () => {
    const src = await import('../components/panels/LivePriceTicker.tsx?raw').then((m) => m.default);
    expect(src).toContain("color: enough ? '#94a3b8' : '#ffb800'");
  });

  it('requires enough ticks that a single burst cannot read as 100%', async () => {
    const src = await import('../components/panels/LivePriceTicker.tsx?raw').then((m) => m.default);
    const match = src.match(/const MIN_TICKS_FOR_FLOW = (\d+)/);
    expect(match, 'MIN_TICKS_FOR_FLOW is gone').toBeTruthy();
    expect(Number(match![1])).toBeGreaterThanOrEqual(10);
  });
});
