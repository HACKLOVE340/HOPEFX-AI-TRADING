/**
 * chart-bot/hooks/useOrchestratorWS.ts
 *
 * React hook that initialises the OrchestratorWSClient singleton and
 * provides typed subscription helpers. Components subscribe to specific
 * event types — no unnecessary re-renders from unrelated messages.
 *
 * Usage:
 *   const { status, subscribe } = useOrchestratorWS();
 *   useEffect(() => subscribe('price_tick', (tick) => { ... }), [subscribe]);
 */

import { useEffect, useCallback, useRef, useState } from 'react';
import { orchestratorWS, type EventMap } from '../services/orchestrator-ws';
import { useStore } from '../../../store';

// Re-export EventMap type for consumers
export type { EventMap };

type SubscribeFn = <K extends keyof EventMap>(
  event: K,
  handler: (data: EventMap[K]) => void
) => () => void;

export function useOrchestratorWS() {
  const token = useStore((s) => s.token);
  const [status, setStatus] = useState(orchestratorWS.status);
  const tokenRef = useRef(token);
  tokenRef.current = token;

  // Initialise singleton once
  useEffect(() => {
    orchestratorWS.init(() => tokenRef.current);

    const unConnected    = orchestratorWS.bus.on('connected',    () => setStatus('connected'));
    const unDisconnected = orchestratorWS.bus.on('disconnected', () => setStatus('disconnected'));
    const unError        = orchestratorWS.bus.on('error',        () => setStatus('error'));

    return () => {
      unConnected();
      unDisconnected();
      unError();
    };
  }, []); // intentionally empty — singleton lifecycle

  const subscribe: SubscribeFn = useCallback((event, handler) => {
    return orchestratorWS.bus.on(event, handler);
  }, []);

  const send = useCallback((msg: object) => {
    orchestratorWS.send(msg);
  }, []);

  return { status, subscribe, send };
}

// ─── Convenience hooks for specific data streams ──────────────────────────────

import { useEffect as _useEffect, useRef as _useRef } from 'react';
import { useChartBotStore } from '../store/chart-bot-store';
import type {
  PriceTick,
  MicrostructureSnapshot,
  VolumeDeltaBar,
  SentimentSnapshot,
  RiskMetrics,
  ChartPattern,
  SupportResistanceLevel,
  EquityPoint,
  NewsItem,
  MLSignal,
} from '../types';

/**
 * Subscribes to live price ticks and pushes them into the chart-bot store.
 * Call once at the dashboard root — not per-component.
 */
export function useLivePriceFeed(symbol: string) {
  const { subscribe } = useOrchestratorWS();
  const setLiveTick   = useChartBotStore((s) => s.setLiveTick);
  const addVolumeDelta = useChartBotStore((s) => s.addVolumeDelta);

  _useEffect(() => {
    // Drop the previous symbol's tick immediately on switch. Without this the
    // store keeps serving the old price until a tick for the NEW symbol
    // arrives — and if that feed is slow or absent, it never does. The result
    // is the header reading "XAG/USD  4,070.80": silver's label over gold's
    // price, which looks like live data and is not.
    setLiveTick(null);

    const unPrice = subscribe('price_tick', (tick: PriceTick) => {
      if (tick.symbol === symbol || tick.symbol === symbol.replace('/', '')) {
        setLiveTick(tick);
      }
    });
    const unDelta = subscribe('volume_delta', (bar: VolumeDeltaBar) => {
      addVolumeDelta(bar);
    });
    return () => { unPrice(); unDelta(); };
  }, [symbol, subscribe, setLiveTick, addVolumeDelta]);
}

export function useLiveMicrostructure() {
  const { subscribe } = useOrchestratorWS();
  const setMicro = useChartBotStore((s) => s.setMicrostructure);

  _useEffect(() => {
    return subscribe('microstructure', (snap: MicrostructureSnapshot) => {
      setMicro(snap);
    });
  }, [subscribe, setMicro]);
}

export function useLiveSentiment() {
  const { subscribe } = useOrchestratorWS();
  const setSentiment = useChartBotStore((s) => s.setSentiment);
  const addNews      = useChartBotStore((s) => s.addNewsItem);

  _useEffect(() => {
    const unSent = subscribe('sentiment_update', (snap: SentimentSnapshot) => {
      setSentiment(snap);
    });
    const unNews = subscribe('news_item', (item: NewsItem) => {
      addNews(item);
    });
    return () => { unSent(); unNews(); };
  }, [subscribe, setSentiment, addNews]);
}

export function useLiveRisk() {
  const { subscribe } = useOrchestratorWS();
  const setRisk = useChartBotStore((s) => s.setRiskMetrics);

  _useEffect(() => {
    return subscribe('risk_update', (metrics: RiskMetrics) => {
      setRisk(metrics);
    });
  }, [subscribe, setRisk]);
}

export function useLiveSignals() {
  const { subscribe } = useOrchestratorWS();
  const addSignal = useChartBotStore((s) => s.addSignal);

  _useEffect(() => {
    return subscribe('signal', (signal: MLSignal) => {
      addSignal(signal);
    });
  }, [subscribe, addSignal]);
}

export function useLiveLevels() {
  const { subscribe } = useOrchestratorWS();
  const setLevels   = useChartBotStore((s) => s.setLevels);
  const addPattern  = useChartBotStore((s) => s.addPattern);
  const addEquity   = useChartBotStore((s) => s.addEquityPoint);

  _useEffect(() => {
    const unLevels  = subscribe('level_update',     (levels: SupportResistanceLevel[]) => setLevels(levels));
    const unPattern = subscribe('pattern_detected', (p: ChartPattern)                  => addPattern(p));
    const unEquity  = subscribe('equity_update',    (pt: EquityPoint)                  => addEquity(pt));
    return () => { unLevels(); unPattern(); unEquity(); };
  }, [subscribe, setLevels, addPattern, addEquity]);
}
