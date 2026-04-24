/**
 * hooks/useOrchestratorData.ts
 * TanStack Query hooks for all data-layer REST endpoints.
 * Polls at appropriate intervals and writes directly into Zustand store.
 */

import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useStore, useHasHydrated, selectIsAuth } from '../store';
import { dataLayerApi, performanceApi, tradingApi, signalsApi, mlExtendedApi, calendarApi } from '../lib/api';
import type {
  OrchestratorHealth,
  QualityReport,
  MicrostructureSnapshot,
  SentimentResponse,
  MacroResponse,
  EquityPoint,
  PerformanceSummary,
  AccountMetrics,
  Signal,
  Position,
} from '../types';

// ── Orchestrator health (every 10s) ───────────────────────────────────────────

export function useOrchestratorHealth() {
  const setOrchestratorHealth = useStore((s) => s.setOrchestratorHealth);
  const setQualityReport      = useStore((s) => s.setQualityReport);
  const isAuth                = useStore(selectIsAuth);
  const hydrated              = useHasHydrated();

  const query = useQuery<OrchestratorHealth>({
    queryKey: ['orchestrator', 'health'],
    queryFn:  async () => {
      const res = await dataLayerApi.health();
      return res.data;
    },
    enabled:         hydrated && isAuth,
    refetchInterval: 10_000,
    staleTime:       5_000,
  });

  useEffect(() => {
    if (query.data) {
      setOrchestratorHealth(query.data);
      if (query.data.data_quality) {
        setQualityReport(query.data.data_quality as QualityReport);
      }
    }
  }, [query.data, setOrchestratorHealth, setQualityReport]);

  return query;
}

// ── Microstructure (every 3s) ─────────────────────────────────────────────────

export function useMicrostructure(symbol = 'XAU_USD') {
  const setMicrostructure = useStore((s) => s.setMicrostructure);
  const isAuth            = useStore(selectIsAuth);
  const hydrated          = useHasHydrated();

  const query = useQuery<{ snapshot: MicrostructureSnapshot | null; features: Record<string, number> }>({
    queryKey: ['microstructure', symbol],
    queryFn:  async () => {
      const res = await dataLayerApi.microstructure(symbol);
      return res.data as { snapshot: MicrostructureSnapshot | null; features: Record<string, number> };
    },
    enabled:         hydrated && isAuth,
    refetchInterval: 3_000,
    staleTime:       1_500,
  });

  useEffect(() => {
    if (query.data?.snapshot) {
      setMicrostructure(query.data.snapshot);
    }
  }, [query.data, setMicrostructure]);

  return query;
}

// ── Sentiment (every 30s) ─────────────────────────────────────────────────────

export function useSentiment() {
  const setSentiment = useStore((s) => s.setSentiment);
  const isAuth       = useStore(selectIsAuth);
  const hydrated     = useHasHydrated();

  const query = useQuery<SentimentResponse>({
    queryKey: ['sentiment'],
    queryFn:  async () => {
      const res = await dataLayerApi.sentiment();
      return res.data;
    },
    enabled:         hydrated && isAuth,
    refetchInterval: 30_000,
    staleTime:       15_000,
  });

  useEffect(() => {
    if (query.data) setSentiment(query.data);
  }, [query.data, setSentiment]);

  return query;
}

// ── Macro calendar (every 60s) ────────────────────────────────────────────────

export function useMacro() {
  const setMacro = useStore((s) => s.setMacro);
  const isAuth   = useStore(selectIsAuth);
  const hydrated = useHasHydrated();

  const query = useQuery<MacroResponse>({
    queryKey: ['macro'],
    queryFn:  async () => {
      const res = await dataLayerApi.macro();
      return res.data;
    },
    enabled:         hydrated && isAuth,
    refetchInterval: 60_000,
    staleTime:       30_000,
  });

  useEffect(() => {
    if (query.data) setMacro(query.data);
  }, [query.data, setMacro]);

  return query;
}

// ── Quality report (every 15s) ────────────────────────────────────────────────

export function useQualityReport(symbol = 'XAU_USD') {
  const setQualityReport = useStore((s) => s.setQualityReport);
  const isAuth           = useStore(selectIsAuth);
  const hydrated         = useHasHydrated();

  const query = useQuery<QualityReport>({
    queryKey: ['quality', symbol],
    queryFn:  async () => {
      const res = await dataLayerApi.quality(symbol);
      return res.data;
    },
    enabled:         hydrated && isAuth,
    refetchInterval: 15_000,
    staleTime:       7_500,
  });

  useEffect(() => {
    if (query.data) setQualityReport(query.data);
  }, [query.data, setQualityReport]);

  return query;
}

// ── Equity curve (every 30s) ──────────────────────────────────────────────────

export function useEquityCurve() {
  const setEquityCurve = useStore((s) => s.setEquityCurve);
  const isAuth         = useStore(selectIsAuth);
  const hydrated       = useHasHydrated();

  const query = useQuery<EquityPoint[]>({
    queryKey: ['performance', 'equity-curve'],
    queryFn:  async () => {
      const res = await performanceApi.equityCurve();
      return res.data;
    },
    enabled:         hydrated && isAuth,
    refetchInterval: 30_000,
    staleTime:       15_000,
  });

  useEffect(() => {
    if (query.data) setEquityCurve(query.data);
  }, [query.data, setEquityCurve]);

  return query;
}

// ── Performance summary (every 30s) ──────────────────────────────────────────

export function usePerformanceSummary() {
  const setPerformanceSummary = useStore((s) => s.setPerformanceSummary);
  const isAuth                = useStore(selectIsAuth);
  const hydrated              = useHasHydrated();

  const query = useQuery<PerformanceSummary>({
    queryKey: ['performance', 'summary'],
    queryFn:  async () => {
      const res = await performanceApi.summary();
      return res.data;
    },
    enabled:         hydrated && isAuth,
    refetchInterval: 30_000,
    staleTime:       15_000,
  });

  useEffect(() => {
    // Only store if the response contains at least one numeric field — guards
    // against empty-object responses from the API during cold-start.
    if (query.data && typeof query.data.total_trades === 'number') {
      setPerformanceSummary(query.data);
    }
  }, [query.data, setPerformanceSummary]);

  return query;
}

// ── Account (every 10s — fallback when WS is down) ────────────────────────────
// Always fetches once on mount so the account bar is populated immediately.
// The WS account_update message only fires on state *changes*, not on initial
// subscription — so without this initial fetch, account stays null until the
// first trade event arrives.

export function useAccount() {
  const setAccount = useStore((s) => s.setAccount);
  const account    = useStore((s) => s.account);
  const wsStatus   = useStore((s) => s.wsStatus);
  const isAuth     = useStore(selectIsAuth);
  const hydrated   = useHasHydrated();

  const query = useQuery<AccountMetrics>({
    queryKey: ['account'],
    queryFn:  async () => {
      const res = await tradingApi.account();
      return res.data as AccountMetrics;
    },
    enabled: hydrated && isAuth,
    // When WS is connected: suppress interval polling (WS pushes changes),
    // but still allow the initial fetch (staleTime=0 when account is null).
    refetchInterval: wsStatus === 'connected' ? false : 10_000,
    // If account is already populated from WS, treat cached data as fresh for
    // 30s. If account is null (first load), staleTime=0 forces an immediate fetch.
    staleTime: account !== null ? 30_000 : 0,
  });

  useEffect(() => {
    if (query.data) setAccount(query.data);
  }, [query.data, setAccount]);

  return query;
}

// ── Positions (every 10s — fallback when WS is down) ─────────────────────────
// Always fetches once on mount. WS position_update only fires on changes,
// not on initial subscription — without this, positions shows empty until
// the first trade event.

export function usePositions() {
  const setPositions = useStore((s) => s.setPositions);
  const wsStatus     = useStore((s) => s.wsStatus);
  const isAuth       = useStore(selectIsAuth);
  const hydrated     = useHasHydrated();

  const query = useQuery<Position[]>({
    queryKey: ['positions'],
    queryFn:  async () => {
      const res = await tradingApi.positions();
      // Backend may return { positions: [...] } or a bare array
      const raw = res.data as Position[] | { positions: Position[] };
      return Array.isArray(raw) ? raw : (raw?.positions ?? []);
    },
    enabled:         hydrated && isAuth,
    refetchInterval: wsStatus === 'connected' ? false : 10_000,
    // staleTime=0 ensures an immediate fetch on mount even when WS is up,
    // since WS only pushes changes — not the initial snapshot.
    staleTime: 0,
  });

  useEffect(() => {
    if (Array.isArray(query.data)) setPositions(query.data);
  }, [query.data, setPositions]);

  return query;
}

// ── Signals (every 15s — fallback when WS is down) ───────────────────────────
// Backend returns { signals: Signal[], count: number } — unwrap here.
// Always fetches once on mount so the signal feed is populated immediately
// even when WS is connected (WS only pushes new signals, not the backlog).

export function useSignals() {
  const setSignals = useStore((s) => s.setSignals);
  const wsStatus   = useStore((s) => s.wsStatus);
  const isAuth     = useStore(selectIsAuth);
  const hydrated   = useHasHydrated();

  const query = useQuery<Signal[]>({
    queryKey: ['signals', 'active'],
    queryFn:  async () => {
      const res = await signalsApi.active();
      // Unwrap envelope: { signals: [...], count: N } or flat array
      const raw = res.data as Signal[] | { signals: Signal[]; count: number };
      return Array.isArray(raw) ? raw : (raw.signals ?? []);
    },
    enabled:         hydrated && isAuth,
    refetchInterval: wsStatus === 'connected' ? false : 15_000,
    // staleTime=0 ensures an immediate fetch on mount even when WS is up,
    // since WS only pushes new signals — not the existing backlog.
    staleTime: 0,
  });

  useEffect(() => {
    if (query.data) setSignals(query.data);
  }, [query.data, setSignals]);

  return query;
}

// ── Active signals with analytics (used by signal panels) ────────────────────

export function useSignalSummary() {
  const isAuth   = useStore(selectIsAuth);
  const hydrated = useHasHydrated();

  return useQuery({
    queryKey: ['signals', 'summary'],
    queryFn:  async () => {
      const res = await signalsApi.summary();
      return res.data;
    },
    enabled:         hydrated && isAuth,
    refetchInterval: 30_000,
    staleTime:       15_000,
  });
}

// ── Weekly performance report (every 5 min) ───────────────────────────────────

export function useWeeklyPerformance() {
  const isAuth   = useStore(selectIsAuth);
  const hydrated = useHasHydrated();

  return useQuery({
    queryKey: ['performance', 'weekly'],
    queryFn:  async () => {
      const res = await performanceApi.weekly();
      return res.data;
    },
    enabled:         hydrated && isAuth,
    refetchInterval: 5 * 60_000,
    staleTime:       2.5 * 60_000,
  });
}

// ── Signal analytics (every 60s) ──────────────────────────────────────────────

export function useSignalAnalytics() {
  const isAuth   = useStore(selectIsAuth);
  const hydrated = useHasHydrated();

  return useQuery({
    queryKey: ['signals', 'analytics'],
    queryFn:  async () => {
      const res = await signalsApi.analytics();
      return res.data;
    },
    enabled:         hydrated && isAuth,
    refetchInterval: 60_000,
    staleTime:       30_000,
  });
}

// ── ML model health (every 60s) ───────────────────────────────────────────────

export function useMLHealth() {
  const isAuth   = useStore(selectIsAuth);
  const hydrated = useHasHydrated();

  return useQuery({
    queryKey: ['ml', 'health'],
    queryFn:  async () => {
      const res = await mlExtendedApi.health();
      return res.data;
    },
    enabled:         hydrated && isAuth,
    refetchInterval: 60_000,
    staleTime:       30_000,
  });
}

// ── High-impact calendar events (every 15 min) ────────────────────────────────

export function useHighImpactCalendar() {
  const isAuth   = useStore(selectIsAuth);
  const hydrated = useHasHydrated();

  return useQuery({
    queryKey: ['calendar', 'high-impact'],
    queryFn:  async () => {
      const res = await calendarApi.highImpact();
      return res.data;
    },
    enabled:         hydrated && isAuth,
    refetchInterval: 15 * 60_000,
    staleTime:       7.5 * 60_000,
  });
}

// ── Data feed status (every 30s) ──────────────────────────────────────────────

export function useDataFeeds() {
  const isAuth   = useStore(selectIsAuth);
  const hydrated = useHasHydrated();

  return useQuery({
    queryKey: ['data-layer', 'feeds'],
    queryFn:  async () => {
      const res = await dataLayerApi.feeds();
      return res.data;
    },
    enabled:         hydrated && isAuth,
    refetchInterval: 30_000,
    staleTime:       15_000,
  });
}

// ── Bootstrap all data on mount ───────────────────────────────────────────────

export function useBootstrapData() {
  useOrchestratorHealth();
  useMicrostructure();
  useSentiment();
  useMacro();
  useQualityReport();
  useEquityCurve();
  usePerformanceSummary();
  useWeeklyPerformance();
  useAccount();
  usePositions();
  useSignals();
  useSignalSummary();
  useSignalAnalytics();
  useMLHealth();
  useHighImpactCalendar();
  useDataFeeds();
}
