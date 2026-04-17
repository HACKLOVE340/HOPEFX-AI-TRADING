// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * hooks/usePerformance.ts
 * =======================
 * Fetch performance summary and trade history for the Portfolio screen.
 */

import { useCallback, useEffect, useState } from 'react';
import { apiClient } from '../services/apiClient';
import { Trade } from '../types';

export type PerformancePeriod = '7d' | '30d' | '90d' | '1y' | 'all';

export interface PerformanceSummary {
  total_pnl: number;
  total_pnl_pct: number;
  win_rate: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  avg_win: number;
  avg_loss: number;
  profit_factor: number | null;
  sharpe_ratio: number | null;
  sortino_ratio: number | null;
  max_drawdown_pct: number;
  best_trade: number;
  worst_trade: number;
  avg_hold_hours: number;
  data_source: string;
}

const EMPTY_SUMMARY: PerformanceSummary = {
  total_pnl: 0,
  total_pnl_pct: 0,
  win_rate: 0,
  total_trades: 0,
  winning_trades: 0,
  losing_trades: 0,
  avg_win: 0,
  avg_loss: 0,
  profit_factor: null,
  sharpe_ratio: null,
  sortino_ratio: null,
  max_drawdown_pct: 0,
  best_trade: 0,
  worst_trade: 0,
  avg_hold_hours: 0,
  data_source: 'paper_simulation',
};

export function usePerformance(period: PerformancePeriod = '30d') {
  const [summary, setSummary] = useState<PerformanceSummary>(EMPTY_SUMMARY);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [perfRaw, tradesRaw] = await Promise.all([
        apiClient.getPerformance(period),
        apiClient.getTrades(100),
      ]);

      // Map raw API response to typed summary
      const p = perfRaw as Record<string, unknown>;
      setSummary({
        total_pnl: Number(p.total_pnl ?? p.net_pnl ?? 0),
        total_pnl_pct: Number(p.total_return_pct ?? p.total_pnl_pct ?? 0),
        win_rate: Number(p.win_rate ?? 0) * (Number(p.win_rate ?? 0) <= 1 ? 100 : 1),
        total_trades: Number(p.total_trades ?? 0),
        winning_trades: Number(p.winning_trades ?? 0),
        losing_trades: Number(p.losing_trades ?? 0),
        avg_win: Number(p.avg_win ?? 0),
        avg_loss: Number(p.avg_loss ?? 0),
        profit_factor: p.profit_factor != null ? Number(p.profit_factor) : null,
        sharpe_ratio: p.sharpe_ratio != null ? Number(p.sharpe_ratio) : null,
        sortino_ratio: p.sortino_ratio != null ? Number(p.sortino_ratio) : null,
        max_drawdown_pct: Number(p.max_drawdown_pct ?? 0),
        best_trade: Number(p.best_trade ?? 0),
        worst_trade: Number(p.worst_trade ?? 0),
        avg_hold_hours: Number(p.avg_hold_hours ?? 0),
        data_source: String(p.data_source ?? 'paper_simulation'),
      });
      setTrades(tradesRaw);
    } catch (e) {
      setError('Failed to load performance data');
    } finally {
      setIsLoading(false);
    }
  }, [period]);

  useEffect(() => {
    load();
  }, [load]);

  return { summary, trades, isLoading, error, refresh: load };
}
