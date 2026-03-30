// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * store/authStore.ts
 * ==================
 * Zustand auth store with SecureStore persistence and biometric support.
 */

import { create } from 'zustand';
import * as SecureStore from 'expo-secure-store';
import { apiClient } from '../services/apiClient';
import { wsClient } from '../services/wsClient';
import { biometricAuth } from '../services/biometricAuth';
import { offlineCache } from '../services/offlineCache';
import { User } from '../types';

const TOKEN_KEY   = 'hopefx_access_token';
const REFRESH_KEY = 'hopefx_refresh_token';

interface AuthState {
  token: string | null;
  refreshToken: string | null;
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  biometricAvailable: boolean;
  biometricEnabled: boolean;
  error: string | null;

  hydrate: () => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  loginWithBiometric: () => Promise<void>;
  register: (email: string, password: string, username: string) => Promise<void>;
  logout: () => Promise<void>;
  enableBiometric: () => Promise<{ success: boolean; error?: string }>;
  disableBiometric: () => Promise<void>;
  setUser: (user: User) => void;
  clearError: () => void;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  token: null,
  refreshToken: null,
  user: null,
  isAuthenticated: false,
  isLoading: false,
  biometricAvailable: false,
  biometricEnabled: false,
  error: null,

  hydrate: async () => {
    set({ isLoading: true });
    try {
      // Check biometric capability
      const capability = await biometricAuth.getCapability();
      const biometricEnabled = await biometricAuth.isEnabled();
      set({
        biometricAvailable: capability.isAvailable && capability.isEnrolled,
        biometricEnabled,
      });

      const [token, refreshToken] = await Promise.all([
        SecureStore.getItemAsync(TOKEN_KEY),
        SecureStore.getItemAsync(REFRESH_KEY),
      ]);

      if (token) {
        apiClient.setAuthToken(token);
        if (refreshToken) apiClient.setRefreshToken(refreshToken);

        try {
          const user = await apiClient.getMe();
          wsClient.connect(token);
          set({ token, refreshToken, user, isAuthenticated: true });
        } catch {
          // Token expired — clear and require re-login
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

      // Update biometric stored token if enabled
      await biometricAuth.updateStoredToken(tokens.access_token);

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

  loginWithBiometric: async () => {
    set({ isLoading: true, error: null });
    try {
      const result = await biometricAuth.loginWithBiometric();
      if (!result.success || !result.token) {
        set({ error: result.error ?? 'Biometric authentication failed' });
        return;
      }

      apiClient.setAuthToken(result.token);
      const user = await apiClient.getMe();
      wsClient.connect(result.token);

      set({
        token: result.token,
        user,
        isAuthenticated: true,
      });
    } catch (e: unknown) {
      const msg =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Biometric login failed';
      set({ error: msg });
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
    await offlineCache.flush();
    try { await apiClient.logout(); } catch { /* best-effort */ }
    await SecureStore.deleteItemAsync(TOKEN_KEY);
    await SecureStore.deleteItemAsync(REFRESH_KEY);
    set({ token: null, refreshToken: null, user: null, isAuthenticated: false });
  },

  enableBiometric: async () => {
    const { token } = get();
    if (!token) return { success: false, error: 'Not authenticated' };
    const result = await biometricAuth.enable(token);
    if (result.success) set({ biometricEnabled: true });
    return result;
  },

  disableBiometric: async () => {
    await biometricAuth.disable();
    set({ biometricEnabled: false });
  },

  setUser: (user) => set({ user }),
  clearError: () => set({ error: null }),
}));
