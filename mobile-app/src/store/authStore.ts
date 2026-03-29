// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * store/authStore.ts
 * ==================
 * Zustand auth store with SecureStore persistence.
 *
 * State:
 *  - token / refreshToken — JWT tokens (persisted in SecureStore)
 *  - user                 — current user profile
 *  - isAuthenticated      — derived from token presence
 *  - isLoading            — hydration / login in progress
 *
 * Actions:
 *  - hydrate()   — restore tokens from SecureStore on app start
 *  - login()     — authenticate and persist tokens
 *  - logout()    — clear tokens and disconnect WS
 *  - setUser()   — update user profile after fetch
 */

import { create } from 'zustand';
import * as SecureStore from 'expo-secure-store';
import { apiClient } from '../services/apiClient';
import { wsClient } from '../services/wsClient';
import { User } from '../types';

const TOKEN_KEY = 'hopefx_access_token';
const REFRESH_KEY = 'hopefx_refresh_token';

interface AuthState {
  token: string | null;
  refreshToken: string | null;
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  error: string | null;

  hydrate: () => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, username: string) => Promise<void>;
  logout: () => Promise<void>;
  setUser: (user: User) => void;
  clearError: () => void;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  token: null,
  refreshToken: null,
  user: null,
  isAuthenticated: false,
  isLoading: false,
  error: null,

  hydrate: async () => {
    set({ isLoading: true });
    try {
      const [token, refreshToken] = await Promise.all([
        SecureStore.getItemAsync(TOKEN_KEY),
        SecureStore.getItemAsync(REFRESH_KEY),
      ]);

      if (token) {
        apiClient.setAuthToken(token);
        if (refreshToken) apiClient.setRefreshToken(refreshToken);

        // Validate token by fetching user profile
        try {
          const user = await apiClient.getMe();
          wsClient.connect(token);
          set({ token, refreshToken, user, isAuthenticated: true });
        } catch {
          // Token expired or invalid — clear and require re-login
          await SecureStore.deleteItemAsync(TOKEN_KEY);
          await SecureStore.deleteItemAsync(REFRESH_KEY);
          set({ token: null, refreshToken: null, isAuthenticated: false });
        }
      }
    } catch (e) {
      console.warn('[AuthStore] Hydration error:', e);
    } finally {
      set({ isLoading: false });
    }
  },

  login: async (email, password) => {
    set({ isLoading: true, error: null });
    try {
      const tokens = await apiClient.login(email, password);

      await SecureStore.setItemAsync(TOKEN_KEY, tokens.access_token);
      await SecureStore.setItemAsync(REFRESH_KEY, tokens.refresh_token);

      const user = await apiClient.getMe();
      wsClient.connect(tokens.access_token);

      set({
        token: tokens.access_token,
        refreshToken: tokens.refresh_token,
        user,
        isAuthenticated: true,
      });
    } catch (e: unknown) {
      const msg =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Login failed. Check your credentials.';
      set({ error: msg });
      throw e;
    } finally {
      set({ isLoading: false });
    }
  },

  register: async (email, password, username) => {
    set({ isLoading: true, error: null });
    try {
      const tokens = await apiClient.register(email, password, username);

      await SecureStore.setItemAsync(TOKEN_KEY, tokens.access_token);
      await SecureStore.setItemAsync(REFRESH_KEY, tokens.refresh_token);

      const user = await apiClient.getMe();
      wsClient.connect(tokens.access_token);

      set({
        token: tokens.access_token,
        refreshToken: tokens.refresh_token,
        user,
        isAuthenticated: true,
      });
    } catch (e: unknown) {
      const msg =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Registration failed.';
      set({ error: msg });
      throw e;
    } finally {
      set({ isLoading: false });
    }
  },

  logout: async () => {
    wsClient.disconnect();
    apiClient.clearTokens();
    try {
      await apiClient.logout();
    } catch {
      // Best-effort server-side logout
    }
    await SecureStore.deleteItemAsync(TOKEN_KEY);
    await SecureStore.deleteItemAsync(REFRESH_KEY);
    set({ token: null, refreshToken: null, user: null, isAuthenticated: false });
  },

  setUser: (user) => set({ user }),
  clearError: () => set({ error: null }),
}));
