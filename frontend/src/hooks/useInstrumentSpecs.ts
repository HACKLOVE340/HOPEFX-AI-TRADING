/**
 * hooks/useInstrumentSpecs.ts
 *
 * Pip and contract sizes from the server, with the built-in table as a *stated*
 * fallback (audit F5-01).
 *
 * `RiskCalculator` carried its own hardcoded `SYMBOLS` map and sized positions
 * from it while the server served the same spec at `GET /api/trading/symbols`.
 * They had already drifted — ETH/USD was `0.01` on the client against `0.1` on
 * the server — which is the S13-01 pattern: every duplicated pair in this
 * codebase has produced a defect.
 *
 * Two rules shape this hook, and they pull in opposite directions:
 *
 * **The server is the authority.** Its catalogue is what the backtester, the
 * order path and the symbol search all use. A calculator that disagrees with it
 * is sizing against numbers nothing else in the system agrees with.
 *
 * **But F1-01 forbids a silent fallback on this page.** The finding there was
 * `RiskCalculator` swallowing a failed price fetch and quietly substituting a
 * store price, *while that price is the input to position sizing*. Replacing one
 * silent substitution with another would be the same defect wearing a different
 * hat.
 *
 * So: fall back to the built-in table — it is legitimate, because
 * `tests/unit/test_instrument_specs_match_the_frontend.py` fails CI if it ever
 * disagrees with the server's — and report which one is in use. `source` is the
 * point of this hook, not an afterthought.
 *
 * `quoteIsUsd` is derived rather than fetched: the server catalogue has no such
 * field, and it is a property of the symbol. A pip is worth
 * `pipSize * contractSize` in the **quote** currency, which is dollars only when
 * the pair is quoted in USD. Treating USD/JPY's ¥1,000 pip as $1,000 overstated
 * pip value ~150× and, since lot size divides risk by it, made the suggested
 * position ~150× too small.
 */

import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { tradingApi } from './useApi';

export interface InstrumentSpec {
  pipSize: number;
  contractSize: number;
  quoteIsUsd: boolean;
  label: string;
}

/**
 * Offline default. Verified against `api/trading.py::_SYMBOL_CATALOGUE` by a
 * backend test, so it is a legitimate fallback rather than a second opinion.
 */
export const BUILTIN_SPECS: Record<string, InstrumentSpec> = {
  'XAU/USD': { pipSize: 0.01,   contractSize: 100,    quoteIsUsd: true,  label: 'Gold (XAU/USD)' },
  'EUR/USD': { pipSize: 0.0001, contractSize: 100000, quoteIsUsd: true,  label: 'EUR/USD' },
  'GBP/USD': { pipSize: 0.0001, contractSize: 100000, quoteIsUsd: true,  label: 'GBP/USD' },
  'USD/JPY': { pipSize: 0.01,   contractSize: 100000, quoteIsUsd: false, label: 'USD/JPY' },
  'BTC/USD': { pipSize: 1,      contractSize: 1,      quoteIsUsd: true,  label: 'Bitcoin (BTC/USD)' },
  'ETH/USD': { pipSize: 0.1,    contractSize: 1,      quoteIsUsd: true,  label: 'Ethereum (ETH/USD)' },
};

/** `XAUUSD` → `XAU/USD`; already-slashed input is returned unchanged. */
export function toSlashPair(symbol: string): string {
  if (!symbol || symbol.includes('/')) return symbol;
  if (symbol.length !== 6) return symbol;
  return `${symbol.slice(0, 3)}/${symbol.slice(3)}`;
}

/** True when the pair's quote currency is USD, so a pip is already dollars. */
export function quoteIsUsd(slashPair: string): boolean {
  return slashPair.split('/')[1] === 'USD';
}

export interface InstrumentSpecs {
  specs: Record<string, InstrumentSpec>;
  /** Which table is in use. Rendered, not swallowed — see the module note. */
  source: 'server' | 'builtin';
  loading: boolean;
  /** True when the server catalogue could not be read. */
  failed: boolean;
}

export function useInstrumentSpecs(): InstrumentSpecs {
  const query = useQuery({
    queryKey: ['trading', 'symbols'],
    queryFn: async () => (await tradingApi.symbols()).data,
    // The instrument catalogue is a constant in practice; refetching it every
    // few seconds would be noise. An hour is long enough to be free and short
    // enough that a real change lands the same session.
    staleTime: 60 * 60_000,
    retry: 1,
  });

  return useMemo(() => {
    const rows = query.data;
    if (!Array.isArray(rows) || rows.length === 0) {
      return {
        specs: BUILTIN_SPECS,
        source: 'builtin' as const,
        loading: query.isLoading,
        failed: query.isError,
      };
    }

    const specs: Record<string, InstrumentSpec> = {};
    for (const r of rows) {
      if (!r?.symbol) continue;
      const pip = Number(r.pip_size);
      const lot = Number(r.lot_size);
      // A spec missing its numbers is worse than absent: it would size against
      // NaN. Skip it and let the symbol simply not be offered.
      if (!Number.isFinite(pip) || pip <= 0 || !Number.isFinite(lot) || lot <= 0) continue;
      const pair = toSlashPair(r.symbol);
      specs[pair] = {
        pipSize: pip,
        contractSize: lot,
        quoteIsUsd: quoteIsUsd(pair),
        label: r.description ? `${r.description} (${pair})` : pair,
      };
    }

    if (Object.keys(specs).length === 0) {
      return { specs: BUILTIN_SPECS, source: 'builtin' as const, loading: false, failed: true };
    }
    return { specs, source: 'server' as const, loading: false, failed: false };
  }, [query.data, query.isLoading, query.isError]);
}

export default useInstrumentSpecs;
