/**
 * F5-01 (follow-up) — the risk calculator reads the server's instrument specs.
 *
 * The original finding was that `RiskCalculator` sized positions from its own
 * hardcoded pip/contract table while the server served the same spec at
 * `GET /api/trading/symbols` — and that the two had already drifted on ETH/USD.
 *
 * The fix has to satisfy two rules that pull against each other:
 *
 *   - the server is the authority, because its catalogue is what the
 *     backtester, the order path and symbol search all use;
 *   - **but F1-01 forbids a silent fallback on this page.** That finding was
 *     this very component swallowing a failed price fetch and quietly
 *     substituting a store price, while that price is the input to position
 *     sizing. Swapping one silent substitution for another is the same defect
 *     in a different coat.
 *
 * So the built-in table stays as an offline default — legitimate, because a
 * backend test fails CI if it ever disagrees with the server's — and the hook
 * reports **which one is in use**. These tests are mostly about that reporting.
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, renderHook } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

import {
  BUILTIN_SPECS,
  toSlashPair,
  quoteIsUsd,
} from '../hooks/useInstrumentSpecs';

const wrapper = ({ children }: { children: React.ReactNode }) => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
};

const row = (symbol: string, pip: number, lot: number) => ({
  symbol, description: symbol, category: 'fx',
  pip_size: pip, lot_size: lot, min_lot: 0.01, max_lot: 50, margin_rate: 0.02,
});

const mountHook = async (impl: () => Promise<unknown>) => {
  vi.resetModules();
  vi.doMock('../hooks/useApi', async () => {
    const actual = await vi.importActual<Record<string, unknown>>('../hooks/useApi');
    return { ...actual, tradingApi: { ...(actual.tradingApi as object), symbols: vi.fn(impl) } };
  });
  const { useInstrumentSpecs } = await import('../hooks/useInstrumentSpecs');
  return renderHook(() => useInstrumentSpecs(), { wrapper });
};

describe('helpers — F5-01', () => {
  it('slashes a compact pair', () => {
    expect(toSlashPair('XAUUSD')).toBe('XAU/USD');
    expect(toSlashPair('XAU/USD')).toBe('XAU/USD');
  });

  it('leaves an index or anything not six characters alone', () => {
    expect(toSlashPair('NAS100')).toBe('NAS/100');   // six chars — documented limit
    expect(toSlashPair('US30')).toBe('US30');
  });

  it('knows which pairs quote in USD', () => {
    // The USD/JPY case: a pip is ¥1,000, not $1,000. Getting this wrong
    // overstated pip value ~150x and made the suggested position ~150x small.
    expect(quoteIsUsd('XAU/USD')).toBe(true);
    expect(quoteIsUsd('USD/JPY')).toBe(false);
  });
});

describe('useInstrumentSpecs — F5-01', () => {
  beforeEach(() => vi.resetModules());

  it('uses the server catalogue when it loads', async () => {
    const { result } = await mountHook(async () => ({
      data: [row('XAUUSD', 0.01, 100), row('EURUSD', 0.0001, 100000)],
    }));
    await waitFor(() => expect(result.current.source).toBe('server'));
    expect(result.current.specs['XAU/USD']?.pipSize).toBe(0.01);
    expect(result.current.specs['XAU/USD']?.contractSize).toBe(100);
    expect(result.current.failed).toBe(false);
  });

  it("takes the server's number even when it differs from the built-in", async () => {
    // The point of the change: the server wins, so the two cannot drift.
    const { result } = await mountHook(async () => ({ data: [row('ETHUSD', 0.5, 2)] }));
    await waitFor(() => expect(result.current.source).toBe('server'));
    expect(result.current.specs['ETH/USD']?.pipSize).toBe(0.5);
    expect(result.current.specs['ETH/USD']?.pipSize).not.toBe(BUILTIN_SPECS['ETH/USD']!.pipSize);
  });

  it('derives quoteIsUsd, which the server does not send', async () => {
    const { result } = await mountHook(async () => ({
      data: [row('USDJPY', 0.01, 100000), row('XAUUSD', 0.01, 100)],
    }));
    await waitFor(() => expect(result.current.source).toBe('server'));
    expect(result.current.specs['USD/JPY']?.quoteIsUsd).toBe(false);
    expect(result.current.specs['XAU/USD']?.quoteIsUsd).toBe(true);
  });

  it('falls back to the built-in table when the catalogue cannot be read', async () => {
    const { result } = await mountHook(async () => { throw new Error('down'); });
    await waitFor(() => expect(result.current.failed).toBe(true));
    // toEqual, not toBe: `vi.resetModules()` gives the hook its own copy of the
    // module, so the two BUILTIN_SPECS objects are equal but not identical.
    expect(result.current.specs).toEqual(BUILTIN_SPECS);
  });

  it('SAYS it fell back — the F1-01 rule', async () => {
    const { result } = await mountHook(async () => { throw new Error('down'); });
    await waitFor(() => expect(result.current.source).toBe('builtin'));
  });

  it('does not claim the server source while still loading', async () => {
    const { result } = await mountHook(() => new Promise(() => {}));
    expect(result.current.source).toBe('builtin');
    expect(result.current.loading).toBe(true);
  });

  it('skips a spec with unusable numbers rather than sizing against NaN', async () => {
    const { result } = await mountHook(async () => ({
      data: [row('XAUUSD', 0.01, 100), row('BADSYM', 0, 100), { symbol: 'NOPIP', lot_size: 100 }],
    }));
    await waitFor(() => expect(result.current.source).toBe('server'));
    expect(result.current.specs['XAU/USD']).toBeTruthy();
    expect(result.current.specs['BAD/SYM']).toBeUndefined();
    expect(result.current.specs['NOP/IP']).toBeUndefined();
  });

  it('an empty catalogue is a failure, not an empty instrument list', async () => {
    // An empty selector would look like "no instruments are tradeable".
    const { result } = await mountHook(async () => ({ data: [] }));
    await waitFor(() => expect(result.current.source).toBe('builtin'));
  });
});

// ── The page must show it ────────────────────────────────────────────────────

describe('RiskCalculator surfaces the fallback — F5-01 / F1-01', () => {
  const renderPage = async (impl: () => Promise<unknown>) => {
    vi.resetModules();
    vi.doMock('../hooks/useApi', async () => {
      const actual = await vi.importActual<Record<string, unknown>>('../hooks/useApi');
      return {
        ...actual,
        tradingApi: { ...(actual.tradingApi as object), symbols: vi.fn(impl) },
        riskCalcApi: {
          ...(actual.riskCalcApi as object),
          livePrice: vi.fn(async () => ({ data: { mid: 2350 } })),
          history: vi.fn(async () => ({ data: [] })),
        },
      };
    });
    const { default: RiskCalculator } = await import('../pages/RiskCalculator');
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={qc}>
        <MemoryRouter><RiskCalculator /></MemoryRouter>
      </QueryClientProvider>,
    );
  };

  it('says nothing extra when the server catalogue loaded', async () => {
    const { container } = await renderPage(async () => ({ data: [row('XAUUSD', 0.01, 100)] }));
    await waitFor(() => expect(container.textContent ?? '').toMatch(/risk/i));
    expect(container.textContent ?? '').not.toMatch(/built-in|offline specification/i);
  });

  it('tells the user when it is sizing from the built-in table', async () => {
    const { container } = await renderPage(async () => { throw new Error('down'); });
    await waitFor(() =>
      expect(
        container.textContent ?? '',
        'the calculator fell back to its own pip table without saying so — the ' +
          'F1-01 defect, on the input to position sizing (F5-01)',
      ).toMatch(/built-in|offline specification/i),
    );
  });
});
