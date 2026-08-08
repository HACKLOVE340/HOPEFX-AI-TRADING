/**
 * F5-02 — a side comparison that decides the sign of a number.
 *
 * docs/FRONTEND_AUDIT_PLAYBOOK.md slice F5: *"P&L whose sign can be wrong for
 * shorts"*.
 *
 * `lib/utils.ts` already owns this rule, and its docstring says why:
 *
 *     Normalise a position's direction to 'long' | 'short' | null.
 *
 *     The API is inconsistent: some endpoints return `side`, others
 *     `direction`, and either may be absent — which is why
 *     `pos.direction.toLowerCase()` crashed PnLDashboard (audit #37/#40) while
 *     three other call sites each wrote their own slightly different
 *     comparison. `null` means "not reported", which callers must render as
 *     unknown rather than defaulting to short.
 *
 * `PositionsTable.tsx:351` did not use it:
 *
 *     const pnlPct =
 *       ((pos.current_price - pos.entry_price) / pos.entry_price) * 100 *
 *       (pos.side === 'long' ? 1 : -1);
 *
 * Three ways that is wrong, all of them ways `positionSide` exists to handle:
 *
 *   - `side: 'buy'` → falls to `-1`. A profitable long renders as a loss.
 *   - `side: 'LONG'` → same, on case alone.
 *   - `direction: 'long'` with no `side` → same.
 *   - no side reported at all → `-1`, i.e. **defaults to short**, which is the
 *     one thing the helper's docstring says not to do.
 *
 * And the badge on the very next line *does* call `positionSide(pos)`, so the
 * same row shows **LONG** beside a percentage signed as if it were short. The
 * two disagree about the same position, on screen, at the same time.
 *
 * `Portfolio.tsx:550` has the same shape in the allocation breakdown —
 * `if (p.side === 'long') row.long += notional; else row.short += notional;` —
 * where a `'buy'` position is counted as short exposure.
 *
 * Everything else the grep turned up (arrows, badge colours, filter buttons) is
 * cosmetic miscoding, not a wrong number, and is left alone deliberately.
 */

import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { useStore } from '../store';
import { PositionsTable } from '../components/panels/PositionsTable';

const renderPanel = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <PositionsTable />
    </QueryClientProvider>,
  );
};

/** A position 10% in profit if long, 10% in loss if short. */
const winner = (over: Record<string, unknown>) => ({
  id: 'p1',
  symbol: 'XAUUSD',
  size: 1,
  quantity: 1,
  entry_price: 2000,
  current_price: 2200,
  unrealized_pnl: 200,
  realized_pnl: 0,
  ...over,
});

beforeEach(() => {
  useStore.setState({
    account: { balance: 100_000, equity: 100_000 },
    wsStatus: 'connected',
    feedStale: false,
    lastDataAt: Date.now(),
  } as never);
});

describe('PositionsTable percentage sign — F5-02', () => {
  const pctOf = (container: HTMLElement) => {
    const m = (container.textContent ?? '').match(/([+-]\d+\.\d+)%/);
    return m ? parseFloat(m[1]!) : null;
  };

  it("a long reported as side: 'long' shows a gain", () => {
    useStore.setState({ positions: [winner({ side: 'long' })] } as never);
    expect(pctOf(renderPanel().container)).toBeGreaterThan(0);
  });

  it("a long reported as side: 'buy' also shows a gain", () => {
    // The API returns 'buy' from some endpoints. This rendered −10%.
    useStore.setState({ positions: [winner({ side: 'buy' })] } as never);
    expect(
      pctOf(renderPanel().container),
      "a profitable long reported as side:'buy' rendered as a loss (F5-02)",
    ).toBeGreaterThan(0);
  });

  it('a long reported in upper case also shows a gain', () => {
    useStore.setState({ positions: [winner({ side: 'LONG' })] } as never);
    expect(pctOf(renderPanel().container)).toBeGreaterThan(0);
  });

  it('a long reported only via `direction` also shows a gain', () => {
    useStore.setState({ positions: [winner({ side: undefined, direction: 'long' })] } as never);
    expect(pctOf(renderPanel().container)).toBeGreaterThan(0);
  });

  it('a genuine short on the same prices shows a loss', () => {
    useStore.setState({ positions: [winner({ side: 'short' })] } as never);
    expect(pctOf(renderPanel().container)).toBeLessThan(0);
  });

  it("a short reported as 'sell' also shows a loss", () => {
    useStore.setState({ positions: [winner({ side: 'sell' })] } as never);
    expect(pctOf(renderPanel().container)).toBeLessThan(0);
  });

  it('does not assert a direction when none was reported', () => {
    // The helper's rule: null means "not reported", never "short".
    useStore.setState({ positions: [winner({ side: undefined, direction: undefined })] } as never);
    const { container } = renderPanel();
    const pct = pctOf(container);
    expect(
      pct === null || pct > 0,
      'an unreported side was rendered as a short, inventing a loss (F5-02)',
    ).toBe(true);
  });

  it('the badge and the percentage agree about the same position', () => {
    useStore.setState({ positions: [winner({ side: 'buy' })] } as never);
    const { container } = renderPanel();
    const saysLong = /long/i.test(container.textContent ?? '');
    const pct = pctOf(container);
    expect(
      !saysLong || (pct ?? 0) > 0,
      'the row shows LONG beside a percentage signed as if it were short',
    ).toBe(true);
  });
});

// ── The rule must have one owner ─────────────────────────────────────────────

describe('no surface re-derives the side rule where it decides a number — F5-02', () => {
  const SITES = [
    'src/components/panels/PositionsTable.tsx',
    'src/pages/Portfolio.tsx',
    'src/pages/Performance.tsx',
    'src/pages/Trading.tsx',
    'src/pages/Trade.tsx',
  ];

  it.each(SITES)('%s uses positionSide for its side rule', async (rel) => {
    const fs = await import('node:fs');
    const path = await import('node:path');
    const src = fs.readFileSync(path.resolve(process.cwd(), rel), 'utf8');

    // The five-times-repeated hand-rolled variant, which drops `direction`
    // and any casing the API might send.
    const handRolled = /side\s*===\s*'long'\s*\|\|\s*\w*\.?side\s*===\s*'buy'/.test(src);
    expect(
      handRolled,
      `${rel} re-derives "is this long?" by hand. positionSide() exists because ` +
        `that comparison was already written three different ways and one of ` +
        `them crashed PnLDashboard (F5-02).`,
    ).toBe(false);
  });
});
