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
