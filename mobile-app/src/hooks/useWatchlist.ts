// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * hooks/useWatchlist.ts
 * =====================
 * Manage a persisted watchlist of symbols with live price polling.
 * Symbols are stored in AsyncStorage so they survive app restarts.
 */

import { useCallback, useEffect, useState } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useTradingStore } from '../store/tradingStore';
import { apiClient } from '../services/apiClient';
import { Quote } from '../types';

const STORAGE_KEY = 'hopefx_watchlist';
const DEFAULT_SYMBOLS = ['XAUUSD', 'EURUSD', 'GBPUSD'];
const POLL_INTERVAL_MS = 10_000;

export function useWatchlist() {
  const [symbols, setSymbols] = useState<string[]>(DEFAULT_SYMBOLS);
  const [quotes, setQuotes] = useState<Record<string, Quote>>({});
  const [isLoading, setIsLoading] = useState(false);
  const storeQuotes = useTradingStore((s) => s.quotes);

  // Load persisted symbols
  useEffect(() => {
    AsyncStorage.getItem(STORAGE_KEY)
      .then((raw) => {
        if (raw) {
          const parsed = JSON.parse(raw) as string[];
          if (Array.isArray(parsed) && parsed.length > 0) {
            setSymbols(parsed);
          }
        }
      })
      .catch(() => {});
  }, []);

  // Merge live WS quotes with polled quotes
  useEffect(() => {
    const merged: Record<string, Quote> = { ...quotes };
    for (const sym of symbols) {
      if (storeQuotes[sym]) merged[sym] = storeQuotes[sym];
    }
    setQuotes(merged);
  }, [storeQuotes, symbols]);

  // Poll REST for symbols not covered by WS
  useEffect(() => {
    const poll = async () => {
      setIsLoading(true);
      try {
        const fetched = await apiClient.getQuotes(symbols);
        setQuotes((prev) => {
          const next = { ...prev };
          for (const q of fetched) next[q.symbol] = q;
          return next;
        });
      } catch {
        // Silently ignore poll failures
      } finally {
        setIsLoading(false);
      }
    };

    poll();
    const timer = setInterval(poll, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [symbols]);

  const addSymbol = useCallback(
    async (symbol: string) => {
      const upper = symbol.toUpperCase().replace('/', '');
      if (symbols.includes(upper)) return;
      const updated = [...symbols, upper];
      setSymbols(updated);
      await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
    },
    [symbols]
  );

  const removeSymbol = useCallback(
    async (symbol: string) => {
      const updated = symbols.filter((s) => s !== symbol);
      setSymbols(updated);
      await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
    },
    [symbols]
  );

  const reorder = useCallback(
    async (newOrder: string[]) => {
      setSymbols(newOrder);
      await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(newOrder));
    },
    []
  );

  return {
    symbols,
    quotes,
    isLoading,
    addSymbol,
    removeSymbol,
    reorder,
  };
}
