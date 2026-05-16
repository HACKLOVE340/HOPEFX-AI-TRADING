/**
 * WebSocket message parsing and routing tests.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '../store';
import type { PriceTick, Position, Signal, AccountMetrics } from '../store';
import type { EquitySnapshot, RiskSnapshot, VolumeDeltaBar, WsNewsItem } from '../store';
import type { MicrostructureSnapshot, SentimentSignal, NewsArticle } from '../types';

// Simulate the message handler logic from useWebSocket
function handleMessage(raw: string) {
  let msg: { type: string; data?: unknown };
  try {
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return;
    msg = parsed;
  } catch {
    return;
  }

  const store = useStore.getState();
  switch (msg.type) {
    case 'price_tick':
      store.setPrice(msg.data as PriceTick);
      break;
    case 'position_update':
      store.upsertPosition(msg.data as Position);
      break;
    case 'position_close':
      store.removePosition((msg.data as { id: string }).id);
      break;
    case 'signal':
      store.addSignal(msg.data as Signal);
      break;
    case 'account_update':
      store.setAccount(msg.data as AccountMetrics);
      break;
    case 'heartbeat':
      store.setHeartbeat(Date.now());
      break;
    case 'microstructure':
      store.setMicrostructure(msg.data as MicrostructureSnapshot);
      break;
    case 'volume_delta':
      store.setVolumeDelta(msg.data as VolumeDeltaBar);
      break;
    case 'sentiment_update': {
      const raw = msg.data as { signal: unknown; articles: unknown[] };
      store.setSentiment({
        signal: raw?.signal as SentimentSignal,
        recent_articles: (raw?.articles ?? []) as NewsArticle[],
      });
      break;
    }
    case 'risk_update':
      store.setRiskSnapshot(msg.data as RiskSnapshot);
      break;
    case 'equity_update':
      store.setEquitySnapshot(msg.data as EquitySnapshot);
      break;
    case 'news_item':
      store.addNewsItem(msg.data as WsNewsItem);
      break;
    case 'pong':
      store.setHeartbeat(Date.now());
      break;
    case 'subscribed':
    case 'unsubscribed':
      break;
    default:
      break;
  }
}

const makeTick = (): PriceTick => ({
  symbol: 'XAU/USD', bid: 2339.9, ask: 2340.1, mid: 2340.0,
  spread: 0.2, timestamp: Date.now(), change_pct: 0.5,
});

const makeMicro = (): MicrostructureSnapshot => ({
  timestamp: new Date().toISOString(), bid: 2339.9, ask: 2340.1,
  spread: 0.2, spread_pct: 0.0086, volume_delta: 150, cumulative_delta: 3200,
  buy_pressure: 0.62, sell_pressure: 0.38, order_flow_imbalance: 0.24,
  trade_pressure: 0.58, vwap: 2340.05, tick_count: 42,
});

const makeEquitySnap = (): EquitySnapshot => ({
  balance: 100_000, equity: 102_500, unrealized_pnl: 2_500,
  margin_used: 4_000, timestamp: new Date().toISOString(),
});

const makeRiskSnap = (): RiskSnapshot => ({
  daily_loss_pct: 0.012, max_drawdown_pct: 0.035,
  open_risk_pct: 0.02, kill_switch_active: false,
});

const makeVolDelta = (): VolumeDeltaBar => ({
  volume_delta: 250, cumulative_delta: 3450, timestamp: new Date().toISOString(),
});

const makeNewsItem = (): WsNewsItem => ({
  title: 'Gold surges on safe-haven demand', source: 'Reuters',
  sentiment_score: 0.72, sentiment_label: 'bullish',
  published_at: new Date().toISOString(), url: 'https://reuters.com/gold',
});

const makePos = (): Position => ({
  id: 'p1', symbol: 'XAU/USD', side: 'long', size: 1,
  entry_price: 2340, current_price: 2350, unrealized_pnl: 100,
  realized_pnl: 0, opened_at: new Date().toISOString(),
});

const makeSig = (): Signal => ({
  id: 's1', symbol: 'XAU/USD', direction: 'long', confidence: 0.85,
  model: 'XGBoost', entry_price: 2340, stop_loss: 2320, take_profit: 2380,
  generated_at: new Date().toISOString(), status: 'active',
});

const makeAcc = (): AccountMetrics => ({
  balance: 100_000, equity: 102_000, margin_used: 4_000, margin_free: 96_000,
  margin_level: 2550, daily_pnl: 500, daily_pnl_pct: 0.5, total_pnl: 2_000,
  win_rate: 0.65, sharpe_ratio: 1.8, max_drawdown: 0.04, open_trades: 2,
});

beforeEach(() => {
  useStore.setState({
    token: null, user: null, isAuthenticated: false,
    prices: {}, priceHistory: {},
    positions: [], signals: [],
    account: null,
    wsStatus: 'disconnected', lastHeartbeat: null,
  });
});

// ─── price_tick ───────────────────────────────────────────────────────────────

describe('price_tick messages', () => {
  it('updates price in store', () => {
    handleMessage(JSON.stringify({ type: 'price_tick', data: makeTick() }));
    expect(useStore.getState().prices['XAU/USD']?.mid).toBe(2340.0);
  });

  it('updates price history', () => {
    handleMessage(JSON.stringify({ type: 'price_tick', data: makeTick() }));
    expect(useStore.getState().priceHistory['XAU/USD']).toHaveLength(1);
  });

  it('multiple ticks accumulate history', () => {
    for (let i = 0; i < 5; i++) {
      handleMessage(JSON.stringify({ type: 'price_tick', data: { ...makeTick(), mid: 2340 + i } }));
    }
    expect(useStore.getState().priceHistory['XAU/USD']).toHaveLength(5);
  });

  it('latest price is most recent tick', () => {
    handleMessage(JSON.stringify({ type: 'price_tick', data: { ...makeTick(), mid: 2340 } }));
    handleMessage(JSON.stringify({ type: 'price_tick', data: { ...makeTick(), mid: 2345 } }));
    expect(useStore.getState().prices['XAU/USD']?.mid).toBe(2345);
  });

  it('different symbols stored separately', () => {
    handleMessage(JSON.stringify({ type: 'price_tick', data: { ...makeTick(), symbol: 'EUR/USD', mid: 1.085 } }));
    handleMessage(JSON.stringify({ type: 'price_tick', data: { ...makeTick(), symbol: 'GBP/USD', mid: 1.27 } }));
    expect(useStore.getState().prices['EUR/USD']?.mid).toBe(1.085);
    expect(useStore.getState().prices['GBP/USD']?.mid).toBe(1.27);
  });

  it('bid/ask stored correctly', () => {
    handleMessage(JSON.stringify({ type: 'price_tick', data: makeTick() }));
    const tick = useStore.getState().prices['XAU/USD']!;
    expect(tick.bid).toBe(2339.9);
    expect(tick.ask).toBe(2340.1);
  });

  it('change_pct stored correctly', () => {
    handleMessage(JSON.stringify({ type: 'price_tick', data: { ...makeTick(), change_pct: -1.5 } }));
    expect(useStore.getState().prices['XAU/USD']?.change_pct).toBe(-1.5);
  });
});

// ─── position_update ──────────────────────────────────────────────────────────

describe('position_update messages', () => {
  it('adds new position', () => {
    handleMessage(JSON.stringify({ type: 'position_update', data: makePos() }));
    expect(useStore.getState().positions).toHaveLength(1);
  });

  it('updates existing position', () => {
    handleMessage(JSON.stringify({ type: 'position_update', data: makePos() }));
    handleMessage(JSON.stringify({ type: 'position_update', data: { ...makePos(), unrealized_pnl: 500 } }));
    expect(useStore.getState().positions).toHaveLength(1);
    expect(useStore.getState().positions[0].unrealized_pnl).toBe(500);
  });

  it('multiple different positions', () => {
    handleMessage(JSON.stringify({ type: 'position_update', data: makePos() }));
    handleMessage(JSON.stringify({ type: 'position_update', data: { ...makePos(), id: 'p2', symbol: 'EUR/USD' } }));
    expect(useStore.getState().positions).toHaveLength(2);
  });

  it('position side is stored', () => {
    handleMessage(JSON.stringify({ type: 'position_update', data: { ...makePos(), side: 'short' } }));
    expect(useStore.getState().positions[0].side).toBe('short');
  });
});

// ─── position_close ───────────────────────────────────────────────────────────

describe('position_close messages', () => {
  it('removes position by id', () => {
    handleMessage(JSON.stringify({ type: 'position_update', data: makePos() }));
    handleMessage(JSON.stringify({ type: 'position_close', data: { id: 'p1' } }));
    expect(useStore.getState().positions).toHaveLength(0);
  });

  it('removes correct position when multiple exist', () => {
    handleMessage(JSON.stringify({ type: 'position_update', data: makePos() }));
    handleMessage(JSON.stringify({ type: 'position_update', data: { ...makePos(), id: 'p2' } }));
    handleMessage(JSON.stringify({ type: 'position_close', data: { id: 'p1' } }));
    expect(useStore.getState().positions).toHaveLength(1);
    expect(useStore.getState().positions[0].id).toBe('p2');
  });

  it('close non-existent id is safe', () => {
    handleMessage(JSON.stringify({ type: 'position_update', data: makePos() }));
    handleMessage(JSON.stringify({ type: 'position_close', data: { id: 'p999' } }));
    expect(useStore.getState().positions).toHaveLength(1);
  });
});

// ─── signal ───────────────────────────────────────────────────────────────────

describe('signal messages', () => {
  it('adds signal to store', () => {
    handleMessage(JSON.stringify({ type: 'signal', data: makeSig() }));
    expect(useStore.getState().signals).toHaveLength(1);
  });

  it('signal is prepended', () => {
    handleMessage(JSON.stringify({ type: 'signal', data: { ...makeSig(), id: 's1', model: 'first' } }));
    handleMessage(JSON.stringify({ type: 'signal', data: { ...makeSig(), id: 's2', model: 'second' } }));
    expect(useStore.getState().signals[0].model).toBe('second');
  });

  it('signal confidence stored', () => {
    handleMessage(JSON.stringify({ type: 'signal', data: { ...makeSig(), confidence: 0.92 } }));
    expect(useStore.getState().signals[0].confidence).toBe(0.92);
  });

  it('signal direction stored', () => {
    handleMessage(JSON.stringify({ type: 'signal', data: { ...makeSig(), direction: 'short' } }));
    expect(useStore.getState().signals[0].direction).toBe('short');
  });

  it('10 signals stored', () => {
    for (let i = 0; i < 10; i++) {
      handleMessage(JSON.stringify({ type: 'signal', data: { ...makeSig(), id: String(i) } }));
    }
    expect(useStore.getState().signals).toHaveLength(10);
  });
});

// ─── account_update ───────────────────────────────────────────────────────────

describe('account_update messages', () => {
  it('sets account in store', () => {
    handleMessage(JSON.stringify({ type: 'account_update', data: makeAcc() }));
    expect(useStore.getState().account?.balance).toBe(100_000);
  });

  it('overwrites previous account', () => {
    handleMessage(JSON.stringify({ type: 'account_update', data: makeAcc() }));
    handleMessage(JSON.stringify({ type: 'account_update', data: { ...makeAcc(), balance: 200_000 } }));
    expect(useStore.getState().account?.balance).toBe(200_000);
  });

  it('equity stored correctly', () => {
    handleMessage(JSON.stringify({ type: 'account_update', data: makeAcc() }));
    expect(useStore.getState().account?.equity).toBe(102_000);
  });

  it('win_rate stored correctly', () => {
    handleMessage(JSON.stringify({ type: 'account_update', data: makeAcc() }));
    expect(useStore.getState().account?.win_rate).toBe(0.65);
  });
});

// ─── heartbeat ────────────────────────────────────────────────────────────────

describe('heartbeat messages', () => {
  it('updates lastHeartbeat', () => {
    const before = Date.now();
    handleMessage(JSON.stringify({ type: 'heartbeat' }));
    const after = Date.now();
    const hb = useStore.getState().lastHeartbeat!;
    expect(hb).toBeGreaterThanOrEqual(before);
    expect(hb).toBeLessThanOrEqual(after);
  });

  it('multiple heartbeats update timestamp', () => {
    handleMessage(JSON.stringify({ type: 'heartbeat' }));
    const first = useStore.getState().lastHeartbeat;
    handleMessage(JSON.stringify({ type: 'heartbeat' }));
    const second = useStore.getState().lastHeartbeat;
    expect(second).toBeGreaterThanOrEqual(first!);
  });
});

// ─── Invalid messages ─────────────────────────────────────────────────────────

describe('invalid messages', () => {
  it('invalid JSON does not throw', () => {
    expect(() => handleMessage('not json')).not.toThrow();
  });

  it('empty string does not throw', () => {
    expect(() => handleMessage('')).not.toThrow();
  });

  it('unknown type does not throw', () => {
    expect(() => handleMessage(JSON.stringify({ type: 'unknown_type', data: {} }))).not.toThrow();
  });

  it('missing type does not throw', () => {
    expect(() => handleMessage(JSON.stringify({ data: {} }))).not.toThrow();
  });

  it('null message does not throw', () => {
    expect(() => handleMessage(JSON.stringify(null))).not.toThrow();
  });

  it('store state unchanged after invalid message', () => {
    handleMessage('garbage');
    expect(useStore.getState().prices).toEqual({});
    expect(useStore.getState().positions).toEqual([]);
  });

  it('error type does not modify store', () => {
    handleMessage(JSON.stringify({ type: 'error', data: { message: 'server error' } }));
    expect(useStore.getState().prices).toEqual({});
  });
});

// ─── Message sequence ─────────────────────────────────────────────────────────

describe('message sequences', () => {
  it('full trading session sequence', () => {
    // 1. Connect → account update
    handleMessage(JSON.stringify({ type: 'account_update', data: makeAcc() }));
    // 2. Price ticks
    handleMessage(JSON.stringify({ type: 'price_tick', data: makeTick() }));
    // 3. Signal generated
    handleMessage(JSON.stringify({ type: 'signal', data: makeSig() }));
    // 4. Position opened
    handleMessage(JSON.stringify({ type: 'position_update', data: makePos() }));
    // 5. Price update
    handleMessage(JSON.stringify({ type: 'price_tick', data: { ...makeTick(), mid: 2360 } }));
    // 6. Position closed
    handleMessage(JSON.stringify({ type: 'position_close', data: { id: 'p1' } }));
    // 7. Account updated
    handleMessage(JSON.stringify({ type: 'account_update', data: { ...makeAcc(), total_pnl: 2200 } }));

    expect(useStore.getState().account?.total_pnl).toBe(2200);
    expect(useStore.getState().positions).toHaveLength(0);
    expect(useStore.getState().signals).toHaveLength(1);
    expect(useStore.getState().prices['XAU/USD']?.mid).toBe(2360);
  });

  it('rapid price ticks followed by position update', () => {
    for (let i = 0; i < 20; i++) {
      handleMessage(JSON.stringify({ type: 'price_tick', data: { ...makeTick(), mid: 2340 + i } }));
    }
    handleMessage(JSON.stringify({ type: 'position_update', data: makePos() }));
    expect(useStore.getState().priceHistory['XAU/USD']).toHaveLength(20);
    expect(useStore.getState().positions).toHaveLength(1);
  });
});

// ─── microstructure ───────────────────────────────────────────────────────────

describe('microstructure messages', () => {
  it('sets microstructure in store', () => {
    handleMessage(JSON.stringify({ type: 'microstructure', data: makeMicro() }));
    expect(useStore.getState().microstructure?.volume_delta).toBe(150);
  });

  it('overwrites previous microstructure', () => {
    handleMessage(JSON.stringify({ type: 'microstructure', data: makeMicro() }));
    handleMessage(JSON.stringify({ type: 'microstructure', data: { ...makeMicro(), volume_delta: 999 } }));
    expect(useStore.getState().microstructure?.volume_delta).toBe(999);
  });

  it('buy_pressure stored correctly', () => {
    handleMessage(JSON.stringify({ type: 'microstructure', data: makeMicro() }));
    expect(useStore.getState().microstructure?.buy_pressure).toBe(0.62);
  });

  it('order_flow_imbalance stored correctly', () => {
    handleMessage(JSON.stringify({ type: 'microstructure', data: makeMicro() }));
    expect(useStore.getState().microstructure?.order_flow_imbalance).toBe(0.24);
  });
});

// ─── volume_delta ─────────────────────────────────────────────────────────────

describe('volume_delta messages', () => {
  it('sets volumeDelta in store', () => {
    handleMessage(JSON.stringify({ type: 'volume_delta', data: makeVolDelta() }));
    expect(useStore.getState().volumeDelta?.volume_delta).toBe(250);
  });

  it('cumulative_delta stored correctly', () => {
    handleMessage(JSON.stringify({ type: 'volume_delta', data: makeVolDelta() }));
    expect(useStore.getState().volumeDelta?.cumulative_delta).toBe(3450);
  });

  it('overwrites previous volumeDelta', () => {
    handleMessage(JSON.stringify({ type: 'volume_delta', data: makeVolDelta() }));
    handleMessage(JSON.stringify({ type: 'volume_delta', data: { ...makeVolDelta(), volume_delta: -100 } }));
    expect(useStore.getState().volumeDelta?.volume_delta).toBe(-100);
  });
});

// ─── sentiment_update ─────────────────────────────────────────────────────────

describe('sentiment_update messages', () => {
  it('sets sentiment in store', () => {
    const signal = { news_sentiment_score: 0.6, news_sentiment_momentum: 0.1,
                     news_article_count_1h: 5, news_bullish_ratio: 0.7 };
    handleMessage(JSON.stringify({ type: 'sentiment_update', data: { signal, articles: [] } }));
    expect(useStore.getState().sentiment?.signal.news_sentiment_score).toBe(0.6);
  });

  it('articles stored in recent_articles', () => {
    const signal = { news_sentiment_score: 0.5, news_sentiment_momentum: 0,
                     news_article_count_1h: 1, news_bullish_ratio: 0.5 };
    const articles = [{ headline: 'Gold up', source: 'Reuters', published_at: new Date().toISOString(),
                        sentiment_score: 0.8, sentiment_label: 'bullish', gold_relevance: 0.9, impact_score: 0.7 }];
    handleMessage(JSON.stringify({ type: 'sentiment_update', data: { signal, articles } }));
    expect(useStore.getState().sentiment?.recent_articles).toHaveLength(1);
  });

  it('empty articles array is safe', () => {
    const signal = { news_sentiment_score: 0, news_sentiment_momentum: 0,
                     news_article_count_1h: 0, news_bullish_ratio: 0 };
    handleMessage(JSON.stringify({ type: 'sentiment_update', data: { signal, articles: [] } }));
    expect(useStore.getState().sentiment?.recent_articles).toHaveLength(0);
  });
});

// ─── risk_update ──────────────────────────────────────────────────────────────

describe('risk_update messages', () => {
  it('sets riskSnapshot in store', () => {
    handleMessage(JSON.stringify({ type: 'risk_update', data: makeRiskSnap() }));
    expect(useStore.getState().riskSnapshot?.daily_loss_pct).toBe(0.012);
  });

  it('kill_switch_active stored correctly', () => {
    handleMessage(JSON.stringify({ type: 'risk_update', data: { ...makeRiskSnap(), kill_switch_active: true } }));
    expect(useStore.getState().riskSnapshot?.kill_switch_active).toBe(true);
  });

  it('overwrites previous riskSnapshot', () => {
    handleMessage(JSON.stringify({ type: 'risk_update', data: makeRiskSnap() }));
    handleMessage(JSON.stringify({ type: 'risk_update', data: { ...makeRiskSnap(), daily_loss_pct: 0.05 } }));
    expect(useStore.getState().riskSnapshot?.daily_loss_pct).toBe(0.05);
  });

  it('partial risk data is safe', () => {
    handleMessage(JSON.stringify({ type: 'risk_update', data: { kill_switch_active: false } }));
    expect(useStore.getState().riskSnapshot?.kill_switch_active).toBe(false);
  });
});

// ─── equity_update ────────────────────────────────────────────────────────────

describe('equity_update messages', () => {
  it('sets equitySnapshot in store', () => {
    handleMessage(JSON.stringify({ type: 'equity_update', data: makeEquitySnap() }));
    expect(useStore.getState().equitySnapshot?.equity).toBe(102_500);
  });

  it('balance stored correctly', () => {
    handleMessage(JSON.stringify({ type: 'equity_update', data: makeEquitySnap() }));
    expect(useStore.getState().equitySnapshot?.balance).toBe(100_000);
  });

  it('unrealized_pnl stored correctly', () => {
    handleMessage(JSON.stringify({ type: 'equity_update', data: makeEquitySnap() }));
    expect(useStore.getState().equitySnapshot?.unrealized_pnl).toBe(2_500);
  });

  it('overwrites previous equitySnapshot', () => {
    handleMessage(JSON.stringify({ type: 'equity_update', data: makeEquitySnap() }));
    handleMessage(JSON.stringify({ type: 'equity_update', data: { ...makeEquitySnap(), equity: 105_000 } }));
    expect(useStore.getState().equitySnapshot?.equity).toBe(105_000);
  });
});

// ─── news_item ────────────────────────────────────────────────────────────────

describe('news_item messages', () => {
  it('adds news item to store', () => {
    handleMessage(JSON.stringify({ type: 'news_item', data: makeNewsItem() }));
    expect(useStore.getState().newsItems).toHaveLength(1);
  });

  it('news items are prepended (newest first)', () => {
    handleMessage(JSON.stringify({ type: 'news_item', data: { ...makeNewsItem(), title: 'first' } }));
    handleMessage(JSON.stringify({ type: 'news_item', data: { ...makeNewsItem(), title: 'second' } }));
    expect(useStore.getState().newsItems[0].title).toBe('second');
  });

  it('sentiment_label stored correctly', () => {
    handleMessage(JSON.stringify({ type: 'news_item', data: makeNewsItem() }));
    expect(useStore.getState().newsItems[0].sentiment_label).toBe('bullish');
  });

  it('capped at 50 items', () => {
    for (let i = 0; i < 55; i++) {
      handleMessage(JSON.stringify({ type: 'news_item', data: { ...makeNewsItem(), title: `item ${i}` } }));
    }
    expect(useStore.getState().newsItems).toHaveLength(50);
  });
});

// ─── pong / subscribed / unsubscribed ─────────────────────────────────────────

describe('server acknowledgement messages', () => {
  it('pong updates lastHeartbeat', () => {
    const before = Date.now();
    handleMessage(JSON.stringify({ type: 'pong' }));
    expect(useStore.getState().lastHeartbeat).toBeGreaterThanOrEqual(before);
  });

  it('subscribed does not throw', () => {
    expect(() => handleMessage(JSON.stringify({ type: 'subscribed', channels: ['prices'] }))).not.toThrow();
  });

  it('unsubscribed does not throw', () => {
    expect(() => handleMessage(JSON.stringify({ type: 'unsubscribed', channels: ['prices'] }))).not.toThrow();
  });
});

// ─── _setLastMid cap regression tests ─────────────────────────────────────────
// Bug: _lastMid was a plain object with no eviction policy. Unexpected or
// malformed symbol strings from the server caused unbounded memory growth.
// Fix: _setLastMid() evicts the oldest entry when the map exceeds
// MAX_TRACKED_SYMBOLS (100) entries.

import { _setLastMid_testOnly, _lastMid_testOnly } from '../hooks/useWebSocket';

describe('_setLastMid cap (unbounded growth regression)', () => {
  beforeEach(() => {
    // Clear the map before each test via the test-only export
    _lastMid_testOnly.clear();
  });

  it('stores a new symbol', () => {
    _setLastMid_testOnly('XAUUSD', 1950.0);
    expect(_lastMid_testOnly.get('XAUUSD')).toBe(1950.0);
  });

  it('updates an existing symbol without eviction', () => {
    _setLastMid_testOnly('XAUUSD', 1950.0);
    _setLastMid_testOnly('XAUUSD', 1960.0);
    expect(_lastMid_testOnly.get('XAUUSD')).toBe(1960.0);
    expect(_lastMid_testOnly.size).toBe(1);
  });

  it('evicts oldest entry when cap is reached', () => {
    const CAP = 100;
    // Fill to cap
    for (let i = 0; i < CAP; i++) {
      _setLastMid_testOnly(`SYM_${i}`, i * 1.0);
    }
    expect(_lastMid_testOnly.size).toBe(CAP);
    const firstKey = _lastMid_testOnly.keys().next().value;
    expect(firstKey).toBe('SYM_0');

    // Adding one more should evict SYM_0
    _setLastMid_testOnly('SYM_NEW', 999.0);
    expect(_lastMid_testOnly.size).toBe(CAP);
    expect(_lastMid_testOnly.has('SYM_0')).toBe(false);
    expect(_lastMid_testOnly.has('SYM_NEW')).toBe(true);
  });

  it('does not evict when updating an existing key at cap', () => {
    const CAP = 100;
    for (let i = 0; i < CAP; i++) {
      _setLastMid_testOnly(`SYM_${i}`, i * 1.0);
    }
    // Update existing key — should not evict anything
    _setLastMid_testOnly('SYM_0', 42.0);
    expect(_lastMid_testOnly.size).toBe(CAP);
    expect(_lastMid_testOnly.get('SYM_0')).toBe(42.0);
  });
});
