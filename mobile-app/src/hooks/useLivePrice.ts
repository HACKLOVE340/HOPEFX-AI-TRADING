// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * hooks/useLivePrice.ts
 * =====================
 * Subscribe to live price updates for a symbol via the trading store.
 * Falls back to REST polling every 5 s when WebSocket is disconnected.
 */

import { useEffect, useRef, useState } from 'react';
import { useTradingStore } from '../store/tradingStore';
import { apiClient } from '../services/apiClient';
import { wsClient } from '../services/wsClient';
import { Quote } from '../types';

const POLL_INTERVAL_MS = 5_000;

export function useLivePrice(symbol: string): Quote | null {
  const quotes = useTradingStore((s) => s.quotes);
  const [polledQuote, setPolledQuote] = useState<Quote | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    // If WS is connected, the store is updated via subscribeToLive()
    // Poll as fallback when WS is not connected
    const startPolling = () => {
      if (pollRef.current) return;
      pollRef.current = setInterval(async () => {
        if (wsClient.isConnected) {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          return;
        }
        try {
          const q = await apiClient.getQuote(symbol);
          setPolledQuote(q);
        } catch {
          // Silently ignore poll failures
        }
      }, POLL_INTERVAL_MS);
    };

    if (!wsClient.isConnected) {
      startPolling();
    }

    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = null;
    };
  }, [symbol]);

  return quotes[symbol] ?? polledQuote;
}
