/**
 * usePriceSimulator
 * =================
 * Generates realistic simulated price ticks when the WebSocket is not
 * connected (dev mode / demo).  Feeds directly into the Zustand store
 * so all components see live-looking data without a backend.
 */

import { useEffect, useRef } from 'react';
import { useStore, type PriceTick } from '../store';

interface SymbolConfig {
  base: number;
  spread: number;
  volatility: number; // daily vol as fraction
}

const SYMBOLS: Record<string, SymbolConfig> = {
  'XAU/USD': { base: 2340.00, spread: 0.30, volatility: 0.012 },
  'EUR/USD': { base: 1.0850,  spread: 0.0001, volatility: 0.006 },
  'GBP/USD': { base: 1.2700,  spread: 0.0002, volatility: 0.007 },
  'USD/JPY': { base: 149.50,  spread: 0.02,   volatility: 0.006 },
  'BTC/USD': { base: 67000.0, spread: 10.0,   volatility: 0.025 },
};

// Geometric Brownian Motion step
function gbmStep(price: number, vol: number, dt: number): number {
  const drift = 0;
  const z = (Math.random() + Math.random() + Math.random() - 1.5) * Math.sqrt(4 / 3); // approx normal
  return price * Math.exp((drift - 0.5 * vol * vol) * dt + vol * Math.sqrt(dt) * z);
}

export function usePriceSimulator(active = true, intervalMs = 1000) {
  const setPrice = useStore((s) => s.setPrice);
  const prices   = useRef<Record<string, number>>(
    Object.fromEntries(Object.entries(SYMBOLS).map(([sym, cfg]) => [sym, cfg.base])),
  );
  const openPrices = useRef<Record<string, number>>(
    Object.fromEntries(Object.entries(SYMBOLS).map(([sym, cfg]) => [sym, cfg.base])),
  );

  useEffect(() => {
    if (!active) return;

    const dt = intervalMs / (1000 * 60 * 60 * 24); // fraction of a day

    const timer = setInterval(() => {
      const now = Date.now();
      for (const [symbol, cfg] of Object.entries(SYMBOLS)) {
        const prev = prices.current[symbol];
        const next = gbmStep(prev, cfg.volatility, dt);
        prices.current[symbol] = next;

        const mid    = next;
        const half   = cfg.spread / 2;
        const open   = openPrices.current[symbol];
        const change = (mid - open) / open;

        const tick: PriceTick = {
          symbol,
          bid:        parseFloat((mid - half).toFixed(5)),
          ask:        parseFloat((mid + half).toFixed(5)),
          mid:        parseFloat(mid.toFixed(5)),
          spread:     cfg.spread,
          timestamp:  now,
          change_pct: parseFloat((change * 100).toFixed(3)),
        };

        setPrice(tick);
      }
    }, intervalMs);

    return () => clearInterval(timer);
  }, [active, intervalMs, setPrice]);
}
