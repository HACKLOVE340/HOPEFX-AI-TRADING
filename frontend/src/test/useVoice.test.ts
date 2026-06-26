/**
 * useVoice / voicePrefs — tests for the browser-native voice hook and the
 * spoken-alerts preference. The key guarantee is graceful degradation: in an
 * environment without the Web Speech API (jsdom, here), the hook reports
 * unsupported and every method is a safe no-op rather than throwing.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';

// Cloud probe must resolve to "unavailable" so speak() falls back to Web Speech
// (which is itself absent in jsdom → ultimate no-op). No network in tests.
vi.mock('../hooks/useApi', () => ({
  voiceApi: {
    status: vi.fn().mockResolvedValue({ data: { tts_available: false, stt_available: false } }),
    tts: vi.fn(),
    stt: vi.fn(),
  },
}));

import { useVoice } from '../hooks/useVoice';
import { getVoiceAlerts, setVoiceAlerts, useVoiceAlerts } from '../lib/voicePrefs';

describe('useVoice — unsupported environment', () => {
  it('reports no STT/TTS support under jsdom', () => {
    const { result } = renderHook(() => useVoice());
    expect(result.current.sttSupported).toBe(false);
    expect(result.current.ttsSupported).toBe(false);
    expect(result.current.supported).toBe(false);
  });

  it('startListening / stopListening are safe no-ops', () => {
    const { result } = renderHook(() => useVoice());
    const onFinal = vi.fn();
    expect(() => act(() => result.current.startListening(onFinal))).not.toThrow();
    expect(result.current.listening).toBe(false);
    expect(onFinal).not.toHaveBeenCalled();
    expect(() => act(() => result.current.stopListening())).not.toThrow();
  });

  it('speak / cancelSpeak do not throw and ignore empty text', async () => {
    const { result } = renderHook(() => useVoice());
    await act(async () => {
      result.current.speak('');        // empty → ignored immediately
      result.current.speak('hello');   // cloud probe false → Web Speech (absent) → no-op
      await Promise.resolve();
    });
    expect(() => act(() => result.current.cancelSpeak())).not.toThrow();
    expect(result.current.speaking).toBe(false);
  });
});

describe('voicePrefs', () => {
  beforeEach(() => { localStorage.clear(); });
  afterEach(() => { localStorage.clear(); });

  it('defaults to off', () => {
    expect(getVoiceAlerts()).toBe(false);
  });

  it('persists and reads back the preference', () => {
    setVoiceAlerts(true);
    expect(getVoiceAlerts()).toBe(true);
    setVoiceAlerts(false);
    expect(getVoiceAlerts()).toBe(false);
  });

  it('useVoiceAlerts hook reflects updates', () => {
    const { result } = renderHook(() => useVoiceAlerts());
    expect(result.current[0]).toBe(false);
    act(() => result.current[1](true));
    expect(result.current[0]).toBe(true);
  });
});
