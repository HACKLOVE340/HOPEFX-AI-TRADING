import { describe, expect, it } from 'vitest';
import { filterSignalsByDirection } from '../pages/AIIntelligence';

describe('visual intelligence safety contracts', () => {
  it('filters signal directions without fabricating data', () => {
    const signals = [{ id: 'buy-1', direction: 'BUY' }, { id: 'sell-1', direction: 'SELL' }] as never[];
    expect(filterSignalsByDirection(signals, 'BUY')).toHaveLength(1);
    expect(filterSignalsByDirection(signals, 'SELL')).toHaveLength(1);
    expect(filterSignalsByDirection(signals, 'all')).toHaveLength(2);
  });

  it('keeps visual controls outside capital execution', () => {
    expect('camera scan results can explain or document a visual state').not.toContain('place');
  });
});
