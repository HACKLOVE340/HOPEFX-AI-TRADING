/**
 * src/test/screenshot_batch_fixes.test.tsx
 * ========================================
 * Three runtime failures reported from the live deployment.
 *
 * **1. Risk Monitor crashed the panel.**
 *
 *     undefined is not an object (evaluating 'n.positionSizePct.toFixed')
 *
 * `fetchRiskMetrics` read:
 *
 *     if ('cvar95' in raw) return raw as RiskMetrics;
 *
 * — a test for ONE field followed by a cast asserting all fifteen. `res.data`
 * is untyped, so TypeScript accepts it, and a response carrying `cvar95`
 * without `positionSizePct` type-checks and then throws in the component.
 * `RiskHeatmap`'s `if (!risk)` guard cannot catch it: the object exists, it is
 * merely incomplete. Same shape as the audit-trail and ML-Ops defects — an
 * interface describing a response the server does not send.
 *
 * **2. The onboarding backtest could never run.**
 *
 *     [{"type":"missing","loc":["body","start_date"],"msg":"Field required"},
 *      {"type":"missing","loc":["body","end_date"],"msg":"Field required"}]
 *
 * The request sent `period_days: 30`, which `BacktestRequest` does not declare,
 * while `start_date` and `end_date` are both `Field(...)` — required. Every run
 * 422'd, so step 4 of the wizard was impossible to complete.
 *
 * **3. Core Chart threw on a timeframe switch.**
 *
 *     Cannot update oldest data, last time=[object Object], new time=[object Object]
 *
 * lightweight-charts rejects an `update()` older than the series' newest bar.
 * `setData()` replaces the series on a timeframe switch while the live-tick
 * effect still closes over the previous `candles`, so it updates a bar that no
 * longer exists in the new series.
 */

import { describe, it, expect } from 'vitest';
import { normaliseRisk } from '../features/chart-bot/services/chart-api';

// ── 1. Risk metrics are complete by construction ─────────────────────────────

describe('normaliseRisk never returns a partial object', () => {
  const REQUIRED = [
    'cvar95', 'cvar99', 'var95', 'var99',
    'positionSizePct', 'maxPositionSize',
    'currentDrawdown', 'maxDrawdown',
    'dailyLossLimit', 'dailyLossUsed',
    'dataQualityScore', 'marginUtilisation', 'riskScore',
  ] as const;

  it('fills a response that has cvar95 but not positionSizePct', () => {
    // The exact deployed payload shape: passes the `'cvar95' in raw` test,
    // then crashes on .toFixed().
    const risk = normaliseRisk({ cvar95: -1200, var95: -800 });

    expect(risk.cvar95).toBe(-1200);
    expect(typeof risk.positionSizePct).toBe('number');
    expect(() => risk.positionSizePct.toFixed(1)).not.toThrow();
  });

  it('returns every numeric field as a finite number, whatever arrives', () => {
    for (const payload of [
      null,
      undefined,
      {},
      { cvar95: 'not-a-number' },
      { cvar95: NaN },
      { data: { cvar95: -5 } },
      { positionSizePct: Infinity },
    ]) {
      const risk = normaliseRisk(payload);
      for (const key of REQUIRED) {
        expect(Number.isFinite(risk[key]), `${key} from ${JSON.stringify(payload)}`).toBe(true);
      }
    }
  });

  it('unwraps a { data: … } envelope', () => {
    expect(normaliseRisk({ data: { cvar95: -42, positionSizePct: 3 } }).positionSizePct).toBe(3);
  });

  it('keeps real values rather than flattening everything to defaults', () => {
    // Control — without this the tests above pass by always returning zeros.
    const risk = normaliseRisk({ cvar95: -1200, positionSizePct: 7.5, killSwitchActive: true });
    expect(risk.positionSizePct).toBe(7.5);
    expect(risk.killSwitchActive).toBe(true);
  });

  it('coerces NaN and Infinity rather than rendering "NaN%"', () => {
    // NaN reaches .toFixed() happily and renders as a real-looking reading.
    expect(normaliseRisk({ positionSizePct: NaN }).positionSizePct).toBe(0);
    expect(normaliseRisk({ riskScore: Infinity }).riskScore).toBe(0);
  });
});

// ── 2. The backtest request matches what the API requires ────────────────────

describe('the onboarding backtest sends the fields the API declares', () => {
  it('sends start_date and end_date, not period_days', async () => {
    const fs = await import('node:fs/promises');
    const url = await import('node:url');
    const path = await import('node:path');

    const here = path.dirname(url.fileURLToPath(import.meta.url));
    const src = await fs.readFile(path.join(here, '../pages/Onboarding.tsx'), 'utf-8');

    const call = src.slice(src.indexOf("post<"), src.indexOf("post<") + 900);
    expect(call).toContain('start_date');
    expect(call).toContain('end_date');
    expect(call).not.toContain('period_days:');
  });
});

// ── 3. The chart guards its live update ──────────────────────────────────────

describe('the chart does not update a bar older than the series', () => {
  it('tracks the newest bar time and guards update() against it', async () => {
    const fs = await import('node:fs/promises');
    const url = await import('node:url');
    const path = await import('node:path');

    const here = path.dirname(url.fileURLToPath(import.meta.url));
    const src = await fs.readFile(path.join(here, '../components/charts/AIChart.tsx'), 'utf-8');

    // Strip comments — the explanation names the error string and the guard,
    // so a raw scan would match the prose rather than the code. This has been
    // the failure mode five times in this codebase.
    const code = src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');

    expect(code).toContain('lastBarTimeRef');
    expect(code).toMatch(/barTime\s*<\s*lastBarTimeRef\.current/);
    expect(code).toMatch(/Number\.isFinite\(barTime\)/);
  });
});

// ── 4. The terminal layout is responsive ─────────────────────────────────────

describe('the trading terminal does not overlap its panels on narrow viewports', () => {
  it('stacks below xl instead of forcing three fixed columns', async () => {
    const fs = await import('node:fs/promises');
    const url = await import('node:url');
    const path = await import('node:path');

    const here = path.dirname(url.fileURLToPath(import.meta.url));
    const src = await fs.readFile(path.join(here, '../pages/Trading.tsx'), 'utf-8');
    const code = src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');

    // The row stacks by default and only becomes a row at xl.
    expect(code).toContain('flex-col xl:flex-row');

    // Neither side panel may be unconditionally fixed-width and unshrinkable:
    // 280 + centre + 280 + gaps overflows a tablet, and the parent clipped it.
    expect(code).not.toMatch(/className="w-\[280px\] shrink-0/);
    expect((code.match(/xl:w-\[280px\]/g) ?? []).length).toBe(2);
  });

  it('lets the stacked layout scroll rather than clipping it', async () => {
    const fs = await import('node:fs/promises');
    const url = await import('node:url');
    const path = await import('node:path');

    const here = path.dirname(url.fileURLToPath(import.meta.url));
    const src = await fs.readFile(path.join(here, '../pages/Trading.tsx'), 'utf-8');
    const code = src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');

    // overflow-hidden unconditionally is what made the overflow invisible
    // instead of scrollable.
    expect(code).toContain('overflow-y-auto xl:overflow-hidden');
  });
});

// ── 5. The chart behaves like a real chart ───────────────────────────────────

describe('the terminal chart is configured like a real trading chart', () => {
  const load = async () => {
    const fs = await import('node:fs/promises');
    const url = await import('node:url');
    const path = await import('node:path');
    const here = path.dirname(url.fileURLToPath(import.meta.url));
    const src = await fs.readFile(path.join(here, '../pages/Trading.tsx'), 'utf-8');
    return src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
  };

  it('formats price per instrument instead of a flat 2 decimals', async () => {
    const code = await load();
    // Default precision rendered EUR/USD as 1.08, collapsing the price scale.
    expect(code).toContain('priceFormatFor');
    expect(code).toMatch(/priceFormat:\s*\{\s*type:\s*'price'/);
  });

  it('re-applies precision when the symbol changes', async () => {
    const code = await load();
    // The chart is created with deps [], so precision was frozen at mount.
    expect(code).toMatch(/applyOptions\(\{\s*priceFormat/);
  });

  it('sizes to its container rather than a hard-coded height', async () => {
    const code = await load();
    expect(code).toContain('containerRef.current.clientHeight');
    expect(code).not.toMatch(/height:\s*340,\s*\}\);/);
  });

  it('does not discard the user zoom on every refresh', async () => {
    const code = await load();
    // fitContent() ran on every 30s poll, resetting zoom and pan.
    expect(code).toContain('didFitRef');
  });

  it('refuses a tick that disagrees with the series about the instrument', async () => {
    const code = await load();
    // XAU/USD header at 3,299.85 with candles at ~4,390 drew a vertical line.
    expect(code).toContain('tickIsOffScale');
  });

  it('stores candles sorted, since the tick updates the last one', async () => {
    const code = await load();
    expect(code).toContain('setCandles(sorted)');
    expect(code).not.toContain('setCandles(data)');
  });
});

describe('priceFormatFor covers the instrument classes the terminal offers', () => {
  it('gives FX 5 decimals, JPY 3, metals and crypto 2', async () => {
    // SYMBOLS in Trading.tsx: XAU/USD, EUR/USD, GBP/USD, USD/JPY, BTC/USD, ETH/USD
    const { priceFormatFor } = await import('../pages/Trading');

    expect(priceFormatFor('EUR/USD').precision).toBe(5);
    expect(priceFormatFor('GBP/USD').precision).toBe(5);
    expect(priceFormatFor('USD/JPY').precision).toBe(3);
    expect(priceFormatFor('XAU/USD').precision).toBe(2);
    expect(priceFormatFor('BTC/USD').precision).toBe(2);
    expect(priceFormatFor('ETH/USD').precision).toBe(2);
  });

  it('minMove matches the precision', async () => {
    const { priceFormatFor } = await import('../pages/Trading');
    for (const sym of ['EUR/USD', 'USD/JPY', 'XAU/USD', 'BTC/USD']) {
      const { precision, minMove } = priceFormatFor(sym);
      expect(minMove).toBeCloseTo(Math.pow(10, -precision), 10);
    }
  });
});

describe('tickIsOffScale separates a price move from a source mismatch', () => {
  it('rejects the deployed XAU/USD case', async () => {
    const { tickIsOffScale } = await import('../pages/Trading');
    // Header 3,299.85 against candles at 4,390 — a 25% gap.
    expect(tickIsOffScale(3299.85, 4390.20)).toBe(true);
  });

  it('accepts a normal intrabar move', async () => {
    const { tickIsOffScale } = await import('../pages/Trading');
    expect(tickIsOffScale(4392.10, 4390.20)).toBe(false);
    expect(tickIsOffScale(1.08512, 1.08490)).toBe(false);
  });

  it('rejects non-finite or zero references rather than dividing by them', async () => {
    const { tickIsOffScale } = await import('../pages/Trading');
    expect(tickIsOffScale(NaN, 100)).toBe(true);
    expect(tickIsOffScale(100, 0)).toBe(true);
  });
});
