/**
 * useVoice — browser-native speech-to-text (dictation) and text-to-speech
 * (read-out) via the Web Speech API. No external service, no API key, no money
 * path: STT runs in the browser, TTS uses the OS voice.
 *
 * Degrades gracefully: on browsers without the API (or in tests/SSR) `supported`
 * is false and every method is a safe no-op, so callers never need to guard.
 *
 * Used by:
 *   - AIChat (talk + listen) — all users
 *   - voice alerts (read-out)  — all users
 *   - voice trading commands   — superadmin only (gated by the caller)
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { voiceApi } from './useApi';

// ── Cloud TTS availability (cached once per page load) ────────────────────────
// The backend /api/voice/* routes provide higher-quality cloud TTS/STT when a
// provider key is configured. We probe once; on any failure (no key → 503, or
// no network) we cache "unavailable" and every caller falls back to Web Speech.
let _cloudTtsProbe: Promise<boolean> | null = null;
function cloudTtsAvailable(): Promise<boolean> {
  if (_cloudTtsProbe) return _cloudTtsProbe;
  _cloudTtsProbe = voiceApi
    .status()
    .then((r) => Boolean(r.data?.tts_available))
    .catch(() => false);
  return _cloudTtsProbe;
}

// ── Minimal Web Speech typings (not in the standard DOM lib) ──────────────────
interface SpeechRecognitionResultLike {
  0: { transcript: string };
  isFinal: boolean;
}
interface SpeechRecognitionEventLike {
  resultIndex: number;
  results: { length: number; [i: number]: SpeechRecognitionResultLike };
}
interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((e: SpeechRecognitionEventLike) => void) | null;
  onerror: ((e: { error?: string }) => void) | null;
  onend: (() => void) | null;
}
type SpeechRecognitionCtor = new () => SpeechRecognitionLike;

function getRecognitionCtor(): SpeechRecognitionCtor | null {
  if (typeof window === 'undefined') return null;
  const w = window as unknown as {
    SpeechRecognition?: SpeechRecognitionCtor;
    webkitSpeechRecognition?: SpeechRecognitionCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

function ttsAvailable(): boolean {
  return typeof window !== 'undefined' && 'speechSynthesis' in window && typeof window.speechSynthesis !== 'undefined';
}

export interface UseVoice {
  /** True when both STT and TTS (or at least one, see sttSupported/ttsSupported) are available. */
  supported: boolean;
  sttSupported: boolean;
  ttsSupported: boolean;
  listening: boolean;
  speaking: boolean;
  transcript: string;
  /** Begin dictation. `onFinal` fires with the final transcript when the user stops. */
  startListening: (onFinal?: (text: string) => void) => void;
  stopListening: () => void;
  /** Speak `text` aloud (cancels any in-progress utterance). */
  speak: (text: string) => void;
  cancelSpeak: () => void;
}

export function useVoice(lang = 'en-US'): UseVoice {
  const sttSupported = getRecognitionCtor() !== null;
  const ttsSupported = ttsAvailable();
  const [listening, setListening] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [transcript, setTranscript] = useState('');
  const recRef = useRef<SpeechRecognitionLike | null>(null);
  const onFinalRef = useRef<((t: string) => void) | undefined>(undefined);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const stopListening = useCallback(() => {
    try { recRef.current?.stop(); } catch { /* ignore */ }
    setListening(false);
  }, []);

  const startListening = useCallback((onFinal?: (text: string) => void) => {
    const Ctor = getRecognitionCtor();
    if (!Ctor) return; // unsupported → no-op
    onFinalRef.current = onFinal;
    setTranscript('');
    const rec = new Ctor();
    rec.lang = lang;
    rec.continuous = false;
    rec.interimResults = true;
    rec.onresult = (e) => {
      let finalText = '';
      let interim = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        const alt = r?.[0];
        if (!alt) continue;
        if (r.isFinal) finalText += alt.transcript;
        else interim += alt.transcript;
      }
      setTranscript((finalText || interim).trim());
      if (finalText && onFinalRef.current) onFinalRef.current(finalText.trim());
    };
    rec.onerror = () => setListening(false);
    rec.onend = () => setListening(false);
    recRef.current = rec;
    try { rec.start(); setListening(true); } catch { setListening(false); }
  }, [lang]);

  const stopCloudAudio = useCallback(() => {
    const a = audioRef.current;
    if (a) {
      try { a.pause(); if (a.src) URL.revokeObjectURL(a.src); } catch { /* ignore */ }
      audioRef.current = null;
    }
  }, []);

  const cancelSpeak = useCallback(() => {
    stopCloudAudio();
    if (ttsAvailable()) { try { window.speechSynthesis.cancel(); } catch { /* ignore */ } }
    setSpeaking(false);
  }, [stopCloudAudio]);

  const speakWebSpeech = useCallback((t: string) => {
    if (!ttsAvailable()) return;
    try {
      window.speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(t);
      u.lang = lang;
      u.onend = () => setSpeaking(false);
      u.onerror = () => setSpeaking(false);
      window.speechSynthesis.speak(u);
      setSpeaking(true);
    } catch {
      setSpeaking(false);
    }
  }, [lang]);

  const speak = useCallback((text: string) => {
    const t = (text ?? '').trim();
    if (!t) return;
    // Prefer cloud TTS when configured; fall back to Web Speech on any failure.
    void cloudTtsAvailable().then((cloud) => {
      if (!cloud || typeof Audio === 'undefined') { speakWebSpeech(t); return; }
      voiceApi
        .tts(t)
        .then((res) => {
          try {
            stopCloudAudio();
            if (ttsAvailable()) window.speechSynthesis.cancel();
            const url = URL.createObjectURL(res.data as Blob);
            const audio = new Audio(url);
            audioRef.current = audio;
            audio.onended = () => { setSpeaking(false); try { URL.revokeObjectURL(url); } catch { /* ignore */ } };
            audio.onerror = () => { setSpeaking(false); speakWebSpeech(t); };
            setSpeaking(true);
            void audio.play().catch(() => { setSpeaking(false); speakWebSpeech(t); });
          } catch {
            speakWebSpeech(t);
          }
        })
        .catch(() => speakWebSpeech(t));
    });
  }, [speakWebSpeech, stopCloudAudio]);

  // Cancel any in-flight speech/recognition on unmount.
  useEffect(() => () => {
    try { recRef.current?.abort(); } catch { /* ignore */ }
    const a = audioRef.current;
    if (a) { try { a.pause(); if (a.src) URL.revokeObjectURL(a.src); } catch { /* ignore */ } }
    if (ttsAvailable()) { try { window.speechSynthesis.cancel(); } catch { /* ignore */ } }
  }, []);

  return {
    supported: sttSupported || ttsSupported,
    sttSupported,
    ttsSupported,
    listening,
    speaking,
    transcript,
    startListening,
    stopListening,
    speak,
    cancelSpeak,
  };
}

export default useVoice;
