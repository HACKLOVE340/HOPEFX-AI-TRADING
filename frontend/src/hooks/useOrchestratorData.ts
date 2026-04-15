/**
 * hooks/useOrchestratorData.ts
 * TanStack Query hooks for all data-layer REST endpoints.
 * Polls at appropriate intervals and writes directly into Zustand store.
 */

import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useStore } from '../store';
import { dataLayerApi, performanceApi, tradingApi, signalsApi } from '../lib/api';
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

  const query = useQuery<OrchestratorHealth>({
    queryKey: ['orchestrator', 'health'],
    queryFn:  async () => {
      const res = await dataLayerApi.health();
      return res.data;
    },
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

  const query = useQuery<{ snapshot: MicrostructureSnapshot | null; features: Record<string, number> }>({
    queryKey: ['microstructure', symbol],
    queryFn:  async () => {
      const res = await dataLayerApi.microstructure(symbol);
      return res.data as { snapshot: MicrostructureSnapshot | null; features: Record<string, number> };
    },
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

  const query = useQuery<SentimentResponse>({
    queryKey: ['sentiment'],
    queryFn:  async () => {
      const res = await dataLayerApi.sentiment();
      return res.data;
    },
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

  const query = useQuery<MacroResponse>({
    queryKey: ['macro'],
    queryFn:  async () => {
      const res = await dataLayerApi.macro();
      return res.data;
    },
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

  const query = useQuery<QualityReport>({
    queryKey: ['quality', symbol],
    queryFn:  async () => {
      const res = await dataLayerApi.quality(symbol);
      return res.data;
    },
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

  const query = useQuery<EquityPoint[]>({
    queryKey: ['performance', 'equity-curve'],
    queryFn:  async () => {
      const res = await performanceApi.equityCurve();
      return res.data;
    },
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

  const query = useQuery<PerformanceSummary>({
    queryKey: ['performance', 'summary'],
    queryFn:  async () => {
      const res = await performanceApi.summary();
      return res.data;
    },
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

export function useAccount() {
  const setAccount = useStore((s) => s.setAccount);
  const wsStatus   = useStore((s) => s.wsStatus);

  const query = useQuery<AccountMetrics>({
    queryKey: ['account'],
    queryFn:  async () => {
      const res = await tradingApi.account();
      return res.data as AccountMetrics;
    },
    // Only poll when WS is not connected
    refetchInterval: wsStatus === 'connected' ? false : 10_000,
    staleTime:       5_000,
  });

  useEffect(() => {
    if (query.data) setAccount(query.data);
  }, [query.data, setAccount]);

  return query;
}

// ── Positions (every 10s — fallback when WS is down) ─────────────────────────

export function usePositions() {
  const setPositions = useStore((s) => s.setPositions);
  const wsStatus     = useStore((s) => s.wsStatus);

  const query = useQuery<Position[]>({
    queryKey: ['positions'],
    queryFn:  async () => {
      const res = await tradingApi.positions();
      // Backend may return { positions: [...] } or a bare array
      const raw = res.data as Position[] | { positions: Position[] };
      return Array.isArray(raw) ? raw : (raw?.positions ?? []);
    },
    refetchInterval: wsStatus === 'connected' ? false : 10_000,
    staleTime:       5_000,
  });

  useEffect(() => {
    if (Array.isArray(query.data)) setPositions(query.data);
  }, [query.data, setPositions]);

  return query;
}

// ── Signals (every 15s — fallback when WS is down) ───────────────────────────
// Backend returns { signals: Signal[], count: number } — unwrap here.

export function useSignals() {
  const setSignals = useStore((s) => s.setSignals);
  const wsStatus   = useStore((s) => s.wsStatus);

  const query = useQuery<Signal[]>({
    queryKey: ['signals', 'active'],
    queryFn:  async () => {
      const res = await signalsApi.active();
      // Unwrap envelope: { signals: [...], count: N } or flat array
      const raw = res.data as Signal[] | { signals: Signal[]; count: number };
      return Array.isArray(raw) ? raw : (raw.signals ?? []);
    },
    refetchInterval: wsStatus === 'connected' ? false : 15_000,
    staleTime:       7_500,
  });

  useEffect(() => {
    if (query.data) setSignals(query.data);
  }, [query.data, setSignals]);

  return query;
}

// ── Active signals with analytics (used by signal panels) ────────────────────

export function useSignalSummary() {
  return useQuery({
    queryKey: ['signals', 'summary'],
    queryFn:  async () => {
      const res = await signalsApi.summary();
      return res.data;
    },
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
  useAccount();
  usePositions();
  useSignals();
  useSignalSummary();
}
