/**
 * voicePrefs — user preference for spoken alerts (TTS read-out of notifications).
 *
 * Persisted in localStorage and synced across components/tabs via a custom event
 * plus the native `storage` event. Output-only: this controls whether toast
 * notifications (fills, risk, price alerts) are read aloud. Defaults to OFF so
 * the app never speaks unprompted; the user opts in (Settings → Notifications).
 */
import { useCallback, useEffect, useState } from 'react';

const KEY = 'hopefx.voiceAlerts';
const EVENT = 'hopefx:voiceAlerts';

export function getVoiceAlerts(): boolean {
  try {
    return typeof localStorage !== 'undefined' && localStorage.getItem(KEY) === '1';
  } catch {
    return false;
  }
}

export function setVoiceAlerts(enabled: boolean): void {
  try {
    localStorage.setItem(KEY, enabled ? '1' : '0');
  } catch {
    /* ignore (private mode / no storage) */
  }
  try {
    window.dispatchEvent(new CustomEvent(EVENT, { detail: enabled }));
  } catch {
    /* ignore (SSR / no window) */
  }
}

/** React hook: `[enabled, setEnabled]`, kept in sync across components and tabs. */
export function useVoiceAlerts(): [boolean, (enabled: boolean) => void] {
  const [enabled, setEnabled] = useState<boolean>(getVoiceAlerts);

  useEffect(() => {
    const onCustom = (e: Event) => setEnabled(Boolean((e as CustomEvent).detail));
    const onStorage = (e: StorageEvent) => { if (e.key === KEY) setEnabled(e.newValue === '1'); };
    window.addEventListener(EVENT, onCustom);
    window.addEventListener('storage', onStorage);
    return () => {
      window.removeEventListener(EVENT, onCustom);
      window.removeEventListener('storage', onStorage);
    };
  }, []);

  const set = useCallback((v: boolean) => setVoiceAlerts(v), []);
  return [enabled, set];
}
