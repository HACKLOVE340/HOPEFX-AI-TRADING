/**
 * spread_units.test.ts
 *
 * One quantity, four renderings, two of them on screen at once.
 *
 * The deployed terminal showed `SPREAD 30.0 pts` for XAU/USD while the
 * dashboard's risk card showed `SPREAD (XAU) $0.88` for the same instrument.
 * Not two ways of writing one number — two different numbers, from two
 * different sources (the WebSocket quote versus the microstructure snapshot),
 * in two different units. The unit difference hid the source difference, which
 * is the one that mattered: 0.30 was the seeded quote constant and 0.88 was the
 * real measured spread.
 *
 * Every absolute spread now goes through `fmtSpread`, so a discrepancy between
 * two panels is visible as a discrepancy instead of being mistaken for a
 * formatting choice:
 *
 *   LivePriceTicker      fmtSpread(tick.spread)              already correct
 *   Dashboard risk card  `$${micro.spread.toFixed(2)}`   →   fmtSpread
 *   CoreChart            (spread * 100).toFixed(1)+' pts' →   fmtSpread
 *                        (the formatter's own body, inlined)
 *   NuclearCandleChart   fmtPrice(price.spread)          →   fmtSpread
 *                        (a spread rendered with price formatting, so 0.30
 *                        read as a price rather than a width)
 *
 * `spread_pct` is a different quantity and keeps its own percentage rendering.
 */

import { describe, it, expect } from 'vitest';
import { fmtSpread } from '../lib/utils';

/** Source with comments stripped — a text search cannot otherwise tell code
 *  from the comment describing it. */
function code(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
}

describe('fmtSpread', () => {
  it('renders the seeded gold spread the terminal showed', () => {
    expect(fmtSpread(0.3)).toBe('30.0 pts');
  });

  it('renders the measured spread the dashboard showed, in the same unit', () => {
    // Same call, same unit — so "88.0 pts" beside "30.0 pts" now reads as the
    // disagreement it is, rather than as dollars beside points.
    expect(fmtSpread(0.88)).toBe('88.0 pts');
  });

  it('renders the silver spread from the same screenshot', () => {
    expect(fmtSpread(0.03)).toBe('3.0 pts');
  });

  it('handles absent and non-finite values', () => {
    expect(fmtSpread(null)).toBe('—');
    expect(fmtSpread(undefined)).toBe('—');
    expect(fmtSpread(Number.NaN)).toBe('—');
    expect(fmtSpread(Number.POSITIVE_INFINITY)).toBe('—');
  });

  it('does not collapse a zero spread to a dash', () => {
    // Zero is a real, if unusual, reading — it is not missing data.
    expect(fmtSpread(0)).toBe('0.0 pts');
  });
});

describe('every absolute spread goes through the one formatter', () => {
  const files = [
    '../pages/Dashboard.tsx?raw',
    '../components/panels/LivePriceTicker.tsx?raw',
    '../features/chart-bot/components/CoreChart.tsx?raw',
    '../features/chart-bot/components/NuclearCandleChart.tsx?raw',
  ];

  it('no panel renders a spread as a dollar amount', async () => {
    for (const path of files) {
      const src = code(await import(/* @vite-ignore */ path).then((m) => m.default));
      expect(
        /\$\$\{[^}]*spread[^}]*\}/i.test(src),
        `${path} still renders a spread as currency`,
      ).toBe(false);
    }
  });

  it('no panel re-implements the points conversion inline', async () => {
    for (const path of files) {
      const src = code(await import(/* @vite-ignore */ path).then((m) => m.default));
      expect(
        /spread[^;\n]*\*\s*100[^;\n]*toFixed/i.test(src),
        `${path} duplicates fmtSpread's body`,
      ).toBe(false);
    }
  });

  it('no panel formats a spread with the price formatter', async () => {
    for (const path of files) {
      const src = code(await import(/* @vite-ignore */ path).then((m) => m.default));
      expect(
        /fmtPrice\(\s*[a-zA-Z_.]*spread/i.test(src),
        `${path} formats a spread as a price`,
      ).toBe(false);
    }
  });

  it('each of them imports the shared formatter', async () => {
    for (const path of files) {
      const src = await import(/* @vite-ignore */ path).then((m) => m.default);
      expect(src, `${path} does not import fmtSpread`).toContain('fmtSpread');
    }
  });
});

describe('percentage spread is left alone', () => {
  it('is a different quantity and keeps its own rendering', async () => {
    const src = await import(
      '../features/chart-bot/components/MicrostructurePanel.tsx?raw'
    ).then((m) => m.default);
    // spread_pct is already a ratio; running it through fmtSpread would report
    // a percentage as points.
    expect(src).toContain('spreadPct');
    expect(/fmtSpread\(\s*spreadPct/.test(src)).toBe(false);
  });
});
