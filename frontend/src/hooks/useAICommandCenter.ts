import { useQueries } from '@tanstack/react-query';
import { accountsApi, backtestApi, dataLayerApi, mlApi, tradingApi, walkForwardApi } from './useApi';
import { useDisplays } from '../hub/useDisplays';

type SourceState<T> = {
  data?: T;
  status: 'loading' | 'ready' | 'degraded';
  source: string;
  updatedAt?: number;
  error?: string;
};

function resolve<T>(query: { data?: T; isLoading: boolean; isError: boolean; error?: Error | null; dataUpdatedAt?: number }, source: string): SourceState<T> {
  return {
    data: query.data,
    status: query.isLoading ? 'loading' : query.isError ? 'degraded' : 'ready',
    source,
    updatedAt: query.dataUpdatedAt,
    error: query.error?.message,
  };
}

export function useAICommandCenter(symbol = 'XAUUSD') {
  const results = useQueries({
    queries: [
      { queryKey: ['command-center', 'prices', symbol], queryFn: () => tradingApi.prices(), refetchInterval: 10_000, retry: 1 },
      { queryKey: ['command-center', 'brain-state'], queryFn: () => tradingApi.brainState(), refetchInterval: 15_000, retry: 1 },
      { queryKey: ['command-center', 'risk'], queryFn: () => tradingApi.riskMetrics(), refetchInterval: 15_000, retry: 1 },
      { queryKey: ['command-center', 'ml-health'], queryFn: () => mlApi.health(), refetchInterval: 30_000, retry: 1 },
      { queryKey: ['command-center', 'data-health'], queryFn: () => dataLayerApi.health(), refetchInterval: 30_000, retry: 1 },
      { queryKey: ['command-center', 'symbols'], queryFn: () => tradingApi.symbols(), staleTime: 300_000, retry: 1 },
      { queryKey: ['command-center', 'teams'], queryFn: () => accountsApi.listTeams(), staleTime: 60_000, retry: 1 },
      { queryKey: ['command-center', 'backtests'], queryFn: () => backtestApi.list(), staleTime: 60_000, retry: 1 },
      { queryKey: ['command-center', 'walk-forward'], queryFn: () => walkForwardApi.list(), staleTime: 60_000, retry: 1 },
    ],
  });

  const [prices, brain, risk, mlHealth, dataHealth, symbols, teams, backtests, walkForward] = results;
  const sources = {
    prices: resolve(prices, 'trading.prices'),
    brain: resolve(brain, 'trading.brain-state'),
    risk: resolve(risk, 'trading.risk'),
    mlHealth: resolve(mlHealth, 'ml.health'),
    dataHealth: resolve(dataHealth, 'data-layer.health'),
    symbols: resolve(symbols, 'trading.symbols'),
    teams: resolve(teams, 'accounts.teams'),
    backtests: resolve(backtests, 'backtesting.list'),
    walkForward: resolve(walkForward, 'backtesting.walk-forward'),
  };

  // §10. The console's other half: how many screens it is actually on.
  //
  // This hook aggregated nine sources and called itself a multi-display
  // console, which it was not — "multi-display" means spanning more than one
  // physical screen, and nothing here had ever asked how many there were.
  // `displays.state` distinguishes "this browser cannot tell" from "you have
  // one screen", because an operator on a three-monitor desk told they have
  // one goes looking for a fault in their hardware.
  //
  // Reading is a probe: it never raises a permission prompt. `requestDisplays`
  // is the path an operator takes deliberately.
  const { snapshot: displays, request: requestDisplays } = useDisplays();

  return {
    sources,
    displays,
    requestDisplays,
    isRefreshing: results.some((query) => query.isFetching),
    hasDegradedSources: Object.values(sources).some((source) => source.status === 'degraded'),
    refresh: () => results.forEach((query) => void query.refetch()),
  };
}
