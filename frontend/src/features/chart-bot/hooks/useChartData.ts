/**
 * chart-bot/hooks/useChartData.ts
 *
 * TanStack Query hooks for all chart-bot data.
 * Each hook handles loading/error states, background refetch,
 * and stale-while-revalidate caching.
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  fetchOHLCV,
  fetchSignals,
  fetchSentiment,
  fetchNews,
  fetchRiskMetrics,
  fetchLevels,
  fetchTrendlines,
  fetchPatterns,
  fetchEquityCurve,
  fetchMicrostructure,
  requestAIAnalysis,
  placeOrder,
  closePosition,
  queryKeys,
} from '../services/chart-api';
import type { ChartClickContext, TradeOrder } from '../types';

// ─── OHLCV ────────────────────────────────────────────────────────────────────

export function useOHLCV(symbol: string, timeframe: string, limit = 500) {
  return useQuery({
    queryKey: queryKeys.ohlcv(symbol, timeframe, limit),
    queryFn:  () => fetchOHLCV({ symbol, timeframe, limit }),
    staleTime: 30_000,
    refetchInterval: 60_000,
    retry: 2,
  });
}

// ─── Signals ──────────────────────────────────────────────────────────────────

export function useSignals(symbol: string) {
  return useQuery({
    queryKey: queryKeys.signals(symbol),
    queryFn:  () => fetchSignals(symbol, 20),
    staleTime: 15_000,
    refetchInterval: 30_000,
    retry: 2,
  });
}

// ─── Sentiment ────────────────────────────────────────────────────────────────

export function useSentiment(symbol = 'XAUUSD') {
  return useQuery({
    queryKey: queryKeys.sentiment(symbol),
    queryFn:  () => fetchSentiment(symbol),
    staleTime: 60_000,
    refetchInterval: 120_000,
    retry: 2,
  });
}

export function useNews(symbol = 'XAUUSD') {
  return useQuery({
    queryKey: queryKeys.news(symbol),
    queryFn:  () => fetchNews(symbol, 15),
    staleTime: 60_000,
    refetchInterval: 120_000,
    retry: 2,
  });
}

// ─── Risk ─────────────────────────────────────────────────────────────────────

export function useRiskMetrics() {
  return useQuery({
    queryKey: queryKeys.risk(),
    queryFn:  fetchRiskMetrics,
    staleTime: 10_000,
    refetchInterval: 15_000,
    retry: 2,
  });
}

// ─── Technical Levels ─────────────────────────────────────────────────────────

export function useLevels(symbol: string) {
  return useQuery({
    queryKey: queryKeys.levels(symbol),
    queryFn:  () => fetchLevels(symbol),
    staleTime: 120_000,
    refetchInterval: 300_000,
    retry: 2,
  });
}

export function useTrendlines(symbol: string) {
  return useQuery({
    queryKey: queryKeys.trendlines(symbol),
    queryFn:  () => fetchTrendlines(symbol),
    staleTime: 120_000,
    refetchInterval: 300_000,
    retry: 2,
  });
}

export function usePatterns(symbol: string) {
  return useQuery({
    queryKey: queryKeys.patterns(symbol),
    queryFn:  () => fetchPatterns(symbol),
    staleTime: 60_000,
    refetchInterval: 120_000,
    retry: 2,
  });
}

// ─── Equity Curve ─────────────────────────────────────────────────────────────

export function useEquityCurve(days = 90) {
  return useQuery({
    queryKey: queryKeys.equityCurve(days),
    queryFn:  () => fetchEquityCurve(days),
    staleTime: 300_000,
    refetchInterval: 600_000,
    retry: 2,
  });
}

// ─── Microstructure ───────────────────────────────────────────────────────────

export function useMicrostructure(symbol: string) {
  return useQuery({
    queryKey: queryKeys.microstructure(symbol),
    queryFn:  () => fetchMicrostructure(symbol),
    staleTime: 5_000,
    refetchInterval: 10_000,
    retry: 1,
  });
}

// ─── AI Analysis ──────────────────────────────────────────────────────────────

export function useAIAnalysis() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (context: ChartClickContext) => requestAIAnalysis(context),
    onSuccess: (data) => {
      // Cache the latest analysis so it can be read without re-fetching
      qc.setQueryData(['ai-analysis-latest'], data);
    },
  });
}

// ─── Trade Execution ──────────────────────────────────────────────────────────

export function usePlaceOrder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (order: TradeOrder) => placeOrder(order),
    onSuccess: () => {
      // Invalidate positions and account after a trade
      qc.invalidateQueries({ queryKey: ['positions'] });
      qc.invalidateQueries({ queryKey: ['account'] });
    },
  });
}

export function useClosePosition() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => closePosition(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['positions'] });
      qc.invalidateQueries({ queryKey: ['account'] });
    },
  });
}
