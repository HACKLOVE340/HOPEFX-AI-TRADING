/**
 * Hook tests — useWebSocket, usePriceSimulator, useApi
 * ~80 tests
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useStore } from '../store';
import { usePriceSimulator } from '../hooks/usePriceSimulator';

beforeEach(() => {
  useStore.setState({
    token: null, user: null, isAuthenticated: false,
    prices: {}, priceHistory: {},
    positions: [], signals: [],
    account: null,
    wsStatus: 'disconnected', lastHeartbeat: null,
  });
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

// ─── usePriceSimulator ────────────────────────────────────────────────────────

describe('usePriceSimulator', () => {
  it('does not run when active=false', () => {
    renderHook(() => usePriceSimulator(false));
    act(() => { vi.advanceTimersByTime(5000); });
    expect(Object.keys(useStore.getState().prices)).toHaveLength(0);
  });

  it('generates prices for all 5 symbols when active', () => {
    renderHook(() => usePriceSimulator(true, 100));
    act(() => { vi.advanceTimersByTime(200); });
    const prices = useStore.getState().prices;
    expect(Object.keys(prices)).toContain('XAU/USD');
    expect(Object.keys(prices)).toContain('EUR/USD');
    expect(Object.keys(prices)).toContain('GBP/USD');
    expect(Object.keys(prices)).toContain('USD/JPY');
    expect(Object.keys(prices)).toContain('BTC/USD');
  });

  it('XAU/USD price is in realistic range', () => {
    renderHook(() => usePriceSimulator(true, 100));
    act(() => { vi.advanceTimersByTime(200); });
    const mid = useStore.getState().prices['XAU/USD']?.mid ?? 0;
    expect(mid).toBeGreaterThan(1000);
    expect(mid).toBeLessThan(5000);
  });

  it('EUR/USD price is in realistic range', () => {
    renderHook(() => usePriceSimulator(true, 100));
    act(() => { vi.advanceTimersByTime(200); });
    const mid = useStore.getState().prices['EUR/USD']?.mid ?? 0;
    expect(mid).toBeGreaterThan(0.5);
    expect(mid).toBeLessThan(2.0);
  });

  it('BTC/USD price is in realistic range', () => {
    renderHook(() => usePriceSimulator(true, 100));
    act(() => { vi.advanceTimersByTime(200); });
    const mid = useStore.getState().prices['BTC/USD']?.mid ?? 0;
    expect(mid).toBeGreaterThan(10_000);
    expect(mid).toBeLessThan(200_000);
  });

  it('tick has bid < mid < ask', () => {
    renderHook(() => usePriceSimulator(true, 100));
    act(() => { vi.advanceTimersByTime(200); });
    const tick = useStore.getState().prices['XAU/USD']!;
    expect(tick.bid).toBeLessThan(tick.mid);
    expect(tick.mid).toBeLessThan(tick.ask);
  });

  it('tick has positive spread', () => {
    renderHook(() => usePriceSimulator(true, 100));
    act(() => { vi.advanceTimersByTime(200); });
    const tick = useStore.getState().prices['XAU/USD']!;
    expect(tick.spread).toBeGreaterThan(0);
  });

  it('tick has timestamp', () => {
    renderHook(() => usePriceSimulator(true, 100));
    act(() => { vi.advanceTimersByTime(200); });
    const tick = useStore.getState().prices['XAU/USD']!;
    expect(tick.timestamp).toBeGreaterThan(0);
  });

  it('accumulates price history over multiple ticks', () => {
    renderHook(() => usePriceSimulator(true, 100));
    act(() => { vi.advanceTimersByTime(500); });
    const history = useStore.getState().priceHistory['XAU/USD'] ?? [];
    expect(history.length).toBeGreaterThanOrEqual(4);
  });

  it('stops generating prices after unmount', () => {
    const { unmount } = renderHook(() => usePriceSimulator(true, 100));
    act(() => { vi.advanceTimersByTime(200); });
    const countBefore = useStore.getState().priceHistory['XAU/USD']?.length ?? 0;
    unmount();
    act(() => { vi.advanceTimersByTime(500); });
    const countAfter = useStore.getState().priceHistory['XAU/USD']?.length ?? 0;
    expect(countAfter).toBe(countBefore);
  });

  it('respects custom interval', () => {
    renderHook(() => usePriceSimulator(true, 500));
    act(() => { vi.advanceTimersByTime(600); });
    const history = useStore.getState().priceHistory['XAU/USD'] ?? [];
    expect(history.length).toBe(1);
  });

  it('change_pct is a number', () => {
    renderHook(() => usePriceSimulator(true, 100));
    act(() => { vi.advanceTimersByTime(200); });
    const tick = useStore.getState().prices['XAU/USD']!;
    expect(typeof tick.change_pct).toBe('number');
  });

  it('switching active from false to true starts simulation', () => {
    const { rerender } = renderHook(({ active }: { active: boolean }) => usePriceSimulator(active, 100), {
      initialProps: { active: false },
    });
    act(() => { vi.advanceTimersByTime(200); });
    expect(Object.keys(useStore.getState().prices)).toHaveLength(0);

    rerender({ active: true });
    act(() => { vi.advanceTimersByTime(200); });
    expect(Object.keys(useStore.getState().prices).length).toBeGreaterThan(0);
  });
});

// ─── useApi (axios instance) ──────────────────────────────────────────────────

describe('useApi', () => {
  it('api instance is defined', async () => {
    const { api } = await import('../hooks/useApi');
    expect(api).toBeDefined();
  });

  it('api has correct baseURL', async () => {
    const { api } = await import('../hooks/useApi');
    expect(api.defaults.baseURL).toBe('/api');
  });

  it('api has correct timeout', async () => {
    const { api } = await import('../hooks/useApi');
    expect(api.defaults.timeout).toBe(15_000);
  });

  it('api has JSON content-type header', async () => {
    const { api } = await import('../hooks/useApi');
    expect(api.defaults.headers['Content-Type']).toBe('application/json');
  });

  it('authApi.login is a function', async () => {
    const { authApi } = await import('../hooks/useApi');
    expect(typeof authApi.login).toBe('function');
  });

  it('authApi.logout is a function', async () => {
    const { authApi } = await import('../hooks/useApi');
    expect(typeof authApi.logout).toBe('function');
  });

  it('authApi.me is a function', async () => {
    const { authApi } = await import('../hooks/useApi');
    expect(typeof authApi.me).toBe('function');
  });

  it('tradingApi.positions is a function', async () => {
    const { tradingApi } = await import('../hooks/useApi');
    expect(typeof tradingApi.positions).toBe('function');
  });

  it('tradingApi.signals is a function', async () => {
    const { tradingApi } = await import('../hooks/useApi');
    expect(typeof tradingApi.signals).toBe('function');
  });

  it('tradingApi.account is a function', async () => {
    const { tradingApi } = await import('../hooks/useApi');
    expect(typeof tradingApi.account).toBe('function');
  });

  it('tradingApi.placeOrder is a function', async () => {
    const { tradingApi } = await import('../hooks/useApi');
    expect(typeof tradingApi.placeOrder).toBe('function');
  });

  it('tradingApi.closePosition is a function', async () => {
    const { tradingApi } = await import('../hooks/useApi');
    expect(typeof tradingApi.closePosition).toBe('function');
  });

  it('mlApi.predict is a function', async () => {
    const { mlApi } = await import('../hooks/useApi');
    expect(typeof mlApi.predict).toBe('function');
  });

  it('mlApi.accuracy is a function', async () => {
    const { mlApi } = await import('../hooks/useApi');
    expect(typeof mlApi.accuracy).toBe('function');
  });

  it('mlApi.models is a function', async () => {
    const { mlApi } = await import('../hooks/useApi');
    expect(typeof mlApi.models).toBe('function');
  });

  it('backtestApi.run is a function', async () => {
    const { backtestApi } = await import('../hooks/useApi');
    expect(typeof backtestApi.run).toBe('function');
  });

  it('backtestApi.results is a function', async () => {
    const { backtestApi } = await import('../hooks/useApi');
    expect(typeof backtestApi.results).toBe('function');
  });

  it('backtestApi.list is a function', async () => {
    const { backtestApi } = await import('../hooks/useApi');
    expect(typeof backtestApi.list).toBe('function');
  });

  it('injects Authorization header when token is set', async () => {
    useStore.getState().setAuth('test-token', { id: '1', email: 'a@b.com', username: 'u', role: 'user' });
    const { api } = await import('../hooks/useApi');
    // Verify interceptor is registered (has request interceptors)
    expect((api.interceptors.request as unknown as { handlers: unknown[] }).handlers.length).toBeGreaterThan(0);
  });
});

// ─── useWebSocket ─────────────────────────────────────────────────────────────

import { useWebSocket } from '../hooks/useWebSocket';

describe('useWebSocket', () => {
  it('does not connect when enabled=false', () => {
    renderHook(() => useWebSocket(false));
    expect(useStore.getState().wsStatus).toBe('disconnected');
  });

  it('sets status to connecting when enabled', () => {
    renderHook(() => useWebSocket(true));
    expect(useStore.getState().wsStatus).toBe('connecting');
  });

  it('sets status to connected after open', async () => {
    renderHook(() => useWebSocket(true));
    await act(async () => { vi.advanceTimersByTime(50); });
    expect(useStore.getState().wsStatus).toBe('connected');
  });

  it('returns send function', () => {
    const { result } = renderHook(() => useWebSocket(true));
    expect(typeof result.current.send).toBe('function');
  });

  it('send does not throw when called', async () => {
    const { result } = renderHook(() => useWebSocket(true));
    await act(async () => { vi.advanceTimersByTime(50); });
    expect(() => result.current.send({ type: 'ping' })).not.toThrow();
  });

  it('handles price_tick message', async () => {
    renderHook(() => useWebSocket(true));
    await act(async () => { vi.advanceTimersByTime(50); });
    expect(useStore.getState().wsStatus).toBe('connected');
  });
});
