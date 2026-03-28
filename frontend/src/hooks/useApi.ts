/**
 * useApi — typed axios instance with JWT injection and 401 auto-logout.
 */

import axios, { type AxiosInstance } from 'axios';
import { useStore } from '../store';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const BASE_URL = ((import.meta as any).env?.VITE_API_URL as string | undefined) ?? '/api';

// Singleton axios instance
export const api: AxiosInstance = axios.create({
  baseURL: BASE_URL,
  timeout: 15_000,
  headers: { 'Content-Type': 'application/json' },
});

// Inject JWT on every request
api.interceptors.request.use((config) => {
  const token = useStore.getState().token;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Auto-logout on 401
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err?.response?.status === 401) {
      useStore.getState().clearAuth();
    }
    return Promise.reject(err);
  },
);

// ─── Typed API helpers ────────────────────────────────────────────────────────

export interface LoginPayload  { email: string; password: string }
export interface LoginResponse { access_token: string; token_type: string; user: import('../store').User }

export const authApi = {
  login:    (payload: LoginPayload)  => api.post<LoginResponse>('/auth/login', payload),
  logout:   ()                       => api.post('/auth/logout'),
  me:       ()                       => api.get<import('../store').User>('/auth/me'),
  register: (payload: { email: string; username: string; password: string }) =>
    api.post('/auth/register', payload),
  activateFreeTier: (userId: string, refCode?: string) =>
    api.post('/auth/activate-free-tier', { user_id: userId, ref_code: refCode }),
};

export const tradingApi = {
  positions:  ()                   => api.get('/trading/positions'),
  signals:    ()                   => api.get('/trading/signals'),
  account:    ()                   => api.get('/trading/account'),
  placeOrder: (order: object)      => api.post('/trading/orders', order),
  closePosition: (id: string)      => api.delete(`/trading/positions/${id}`),
};

export const backtestApi = {
  run:     (params: object)        => api.post('/backtesting/run', params),
  results: (id: string)            => api.get(`/backtesting/results/${id}`),
  list:    ()                      => api.get('/backtesting/list'),
};

export const mlApi = {
  predict:  (symbol: string)       => api.get(`/ml/predict/${symbol}`),
  accuracy: ()                     => api.get('/ml/accuracy'),
  models:   ()                     => api.get('/ml/models'),
};
