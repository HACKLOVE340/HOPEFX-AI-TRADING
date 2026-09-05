import { describe, expect, it } from 'vitest';
import { filterSignalsByDirection } from '../pages/AIIntelligence';
import type { EngineSignal } from '../types';

const signal = (id: string, direction: EngineSignal['direction']): EngineSignal => ({
  id, symbol: 'XAUUSD', direction, strength: 'strong', confidence: 0.8, price: 1,
  entry_price: 1, stop_loss: 0.9, take_profit: 1.2, risk_reward_ratio: 2,
  timeframe: '15m', strategies_agreeing: ['test'], total_strategies: 1,
  regime: 'neutral', session: 'london', expiry: '2099-01-01T00:00:00Z',
  timestamp: '2026-01-01T00:00:00Z', is_valid: true,
});

describe('AI command center safety logic', () => {
  it('filters BUY and SELL signals without mutating the source list', () => {
    const signals = [signal('buy-1', 'buy'), signal('sell-1', 'sell'), signal('hold-1', 'hold')];
    expect(filterSignalsByDirection(signals, 'BUY').map(({ id }) => id)).toEqual(['buy-1']);
    expect(filterSignalsByDirection(signals, 'SELL').map(({ id }) => id)).toEqual(['sell-1']);
    expect(filterSignalsByDirection(signals, 'all')).toHaveLength(3);
    expect(signals).toHaveLength(3);
  });

  it('excludes HOLD from directional execution filters', () => {
    expect(filterSignalsByDirection([signal('hold-1', 'hold')], 'BUY')).toEqual([]);
    expect(filterSignalsByDirection([signal('hold-1', 'hold')], 'SELL')).toEqual([]);
  });
});
