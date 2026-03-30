// HOPEFX-AI-TRADING — AGPL-3.0
/**
 * services/offlineCache.ts
 * ========================
 * Persists last-known orchestrator state to AsyncStorage.
 * Loaded on app start when network is unavailable.
 * Written on every significant state update.
 */

import AsyncStorage from '@react-native-async-storage/async-storage';
import { CachedState } from '../types';

const CACHE_KEY = 'hopefx_offline_state_v2';
const MAX_AGE_MS = 24 * 60 * 60 * 1000; // 24 hours

class OfflineCacheService {
  private _writeTimer: ReturnType<typeof setTimeout> | null = null;
  private _pendingWrite: CachedState | null = null;

  /**
   * Read cached state. Returns null if cache is missing, corrupt, or expired.
   */
  async read(): Promise<CachedState | null> {
    try {
      const raw = await AsyncStorage.getItem(CACHE_KEY);
      if (!raw) return null;

      const cached: CachedState = JSON.parse(raw);
      if (!cached.cachedAt) return null;

      const age = Date.now() - new Date(cached.cachedAt).getTime();
      if (age > MAX_AGE_MS) {
        await AsyncStorage.removeItem(CACHE_KEY);
        return null;
      }

      return cached;
    } catch (e) {
      console.warn('[OfflineCache] Read error:', e);
      return null;
    }
  }

  /**
   * Write state to cache. Debounced to avoid excessive writes.
   */
  write(state: Omit<CachedState, 'cachedAt'>): void {
    this._pendingWrite = { ...state, cachedAt: new Date().toISOString() };

    if (this._writeTimer) clearTimeout(this._writeTimer);
    this._writeTimer = setTimeout(() => {
      this._flush();
    }, 2_000); // debounce 2s
  }

  /**
   * Force immediate write (call on app background).
   */
  async flush(): Promise<void> {
    if (this._writeTimer) {
      clearTimeout(this._writeTimer);
      this._writeTimer = null;
    }
    await this._flush();
  }

  async clear(): Promise<void> {
    try {
      await AsyncStorage.removeItem(CACHE_KEY);
    } catch (e) {
      console.warn('[OfflineCache] Clear error:', e);
    }
  }

  private async _flush(): Promise<void> {
    if (!this._pendingWrite) return;
    const state = this._pendingWrite;
    this._pendingWrite = null;
    try {
      await AsyncStorage.setItem(CACHE_KEY, JSON.stringify(state));
    } catch (e) {
      console.warn('[OfflineCache] Write error:', e);
    }
  }
}

export const offlineCache = new OfflineCacheService();
