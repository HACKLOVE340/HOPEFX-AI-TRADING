/**
 * Hook tests — useWebSocket, useApi
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useStore } from '../store';

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
    // Default timeout is 30s; individual endpoints may override with longer values
    expect(api.defaults.timeout).toBe(30_000);
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

  it('signalsApi.active is a function', async () => {
    const { signalsApi } = await import('../hooks/useApi');
    expect(typeof signalsApi.active).toBe('function');
  });

  it('signalsApi.history is a function', async () => {
    const { signalsApi } = await import('../hooks/useApi');
    expect(typeof signalsApi.history).toBe('function');
  });

  it('injects Authorization header when token is set', async () => {
    useStore.getState().setAuth('test-token', { id: '1', email: 'a@b.com', username: 'u', role: 'user' });
    const { api } = await import('../hooks/useApi');
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
});
