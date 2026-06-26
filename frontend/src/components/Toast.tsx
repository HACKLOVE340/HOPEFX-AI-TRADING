/**
 * Toast — lightweight global notification system.
 *
 * Usage:
 *   // In any component:
 *   import { useToast } from '../components/Toast';
 *   const toast = useToast();
 *   toast.success('Position opened');
 *   toast.error('Order failed: insufficient margin');
 *   toast.info('Syncing…');
 *   toast.warning('Approaching daily loss limit');
 *
 * Mount <ToastContainer /> once in App.tsx (outside router).
 */

import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { useVoice } from '../hooks/useVoice';
import { useVoiceAlerts } from '../lib/voicePrefs';

// ── Types ─────────────────────────────────────────────────────────────────────

export type ToastVariant = 'success' | 'error' | 'warning' | 'info';

export interface ToastItem {
  id: string;
  variant: ToastVariant;
  message: string;
  /** Duration in ms. 0 = persist until dismissed. Default 4000. */
  duration?: number;
  /** Optional action button */
  action?: { label: string; onClick: () => void };
}

interface ToastContextValue {
  add:     (item: Omit<ToastItem, 'id'>) => string;
  remove:  (id: string) => void;
  success: (message: string, opts?: Partial<Omit<ToastItem, 'id' | 'variant' | 'message'>>) => string;
  error:   (message: string, opts?: Partial<Omit<ToastItem, 'id' | 'variant' | 'message'>>) => string;
  warning: (message: string, opts?: Partial<Omit<ToastItem, 'id' | 'variant' | 'message'>>) => string;
  info:    (message: string, opts?: Partial<Omit<ToastItem, 'id' | 'variant' | 'message'>>) => string;
}

// ── Context ───────────────────────────────────────────────────────────────────

const ToastContext = createContext<ToastContextValue | null>(null);

// No-op fallback used when no <ToastProvider> is mounted (e.g. in unit tests
// or an isolated render). Toasts are non-critical UI feedback, so a missing
// provider must never crash the page — it just silently drops the toast.
// Production always mounts ToastProvider in App.tsx, so the real toasts show.
const _NOOP_TOAST: ToastContextValue = {
  add: () => '',
  remove: () => {},
  success: () => '',
  error: () => '',
  warning: () => '',
  info: () => '',
};

export function useToast(): ToastContextValue {
  return useContext(ToastContext) ?? _NOOP_TOAST;
}

// ── Config ────────────────────────────────────────────────────────────────────

const VARIANT_STYLES: Record<ToastVariant, { bg: string; border: string; icon: string; color: string }> = {
  success: { bg: '#052e16', border: '#166534', icon: '✓', color: '#4ade80' },
  error:   { bg: '#450a0a', border: '#7f1d1d', icon: '✕', color: '#f87171' },
  warning: { bg: '#431407', border: '#92400e', icon: '⚠', color: '#fb923c' },
  info:    { bg: '#0c1a2e', border: '#1d4ed8', icon: 'ℹ', color: '#60a5fa' },
};

// ── Single toast item ─────────────────────────────────────────────────────────

const ToastCard: React.FC<{ item: ToastItem; onRemove: (id: string) => void }> = ({ item, onRemove }) => {
  const [visible, setVisible] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cfg = VARIANT_STYLES[item.variant];

  const dismiss = useCallback(() => {
    setLeaving(true);
    setTimeout(() => onRemove(item.id), 280);
  }, [item.id, onRemove]);

  useEffect(() => {
    // Trigger enter animation
    const t = setTimeout(() => setVisible(true), 10);
    return () => clearTimeout(t);
  }, []);

  useEffect(() => {
    const dur = item.duration ?? 4000;
    if (dur === 0) return;
    timerRef.current = setTimeout(dismiss, dur);
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
  }, [dismiss, item.duration]);

  return (
    <div
      role="alert"
      aria-live="polite"
      style={{
        display: 'flex', alignItems: 'flex-start', gap: 10,
        background: cfg.bg, border: `1px solid ${cfg.border}`,
        borderRadius: 10, padding: '12px 14px',
        boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
        maxWidth: 380, width: '100%',
        transform: visible && !leaving ? 'translateX(0) scale(1)' : 'translateX(24px) scale(0.97)',
        opacity: visible && !leaving ? 1 : 0,
        transition: 'transform 0.25s cubic-bezier(0.34,1.56,0.64,1), opacity 0.25s ease',
        pointerEvents: 'all',
      }}
    >
      {/* Icon */}
      <div style={{
        width: 22, height: 22, borderRadius: '50%', flexShrink: 0,
        background: `${cfg.color}22`, border: `1px solid ${cfg.border}`,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 11, fontWeight: 900, color: cfg.color, marginTop: 1,
      }}>
        {cfg.icon}
      </div>

      {/* Message */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, color: '#f1f5f9', lineHeight: 1.45, wordBreak: 'break-word' }}>
          {item.message}
        </div>
        {item.action && (
          <button
            onClick={() => { item.action!.onClick(); dismiss(); }}
            style={{
              marginTop: 6, background: 'transparent', border: 'none',
              color: cfg.color, fontSize: 12, fontWeight: 700, cursor: 'pointer',
              padding: 0, textDecoration: 'underline',
            }}
          >
            {item.action.label}
          </button>
        )}
      </div>

      {/* Dismiss */}
      <button
        onClick={dismiss}
        aria-label="Dismiss"
        style={{
          background: 'transparent', border: 'none', color: '#475569',
          cursor: 'pointer', fontSize: 14, padding: '0 2px', flexShrink: 0,
          lineHeight: 1, marginTop: 1,
        }}
        onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.color = '#94a3b8'; }}
        onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.color = '#475569'; }}
      >
        ×
      </button>
    </div>
  );
};

// ── Container ─────────────────────────────────────────────────────────────────

export const ToastContainer: React.FC = () => {
  const ctx = useContext(ToastContext);
  if (!ctx) return null;
  // Access internal toasts via a separate internal context
  const toasts = useContext(ToastListContext);
  if (!toasts) return null;

  return (
    <div
      aria-live="polite"
      style={{
        position: 'fixed', bottom: 24, right: 24, zIndex: 9999,
        display: 'flex', flexDirection: 'column', gap: 10,
        alignItems: 'flex-end', pointerEvents: 'none',
      }}
    >
      {toasts.map(item => (
        <ToastCard key={item.id} item={item} onRemove={ctx.remove} />
      ))}
    </div>
  );
};

// ── Internal list context (keeps ToastContainer decoupled) ────────────────────

const ToastListContext = createContext<ToastItem[] | null>(null);

// ── Provider ──────────────────────────────────────────────────────────────────

let _idCounter = 0;
function genId() { return `toast-${++_idCounter}-${Date.now()}`; }

export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  // Spoken alerts (output-only, opt-in): read important notifications aloud.
  // Kept in refs so `add`'s identity stays stable for consumers.
  const voice = useVoice();
  const [voiceAlerts] = useVoiceAlerts();
  const speakRef = useRef(voice.speak);
  const voiceAlertsRef = useRef(voiceAlerts);
  useEffect(() => { speakRef.current = voice.speak; }, [voice.speak]);
  useEffect(() => { voiceAlertsRef.current = voiceAlerts; }, [voiceAlerts]);

  const remove = useCallback((id: string) => {
    setToasts(prev => prev.filter(t => t.id !== id));
  }, []);

  const add = useCallback((item: Omit<ToastItem, 'id'>): string => {
    const id = genId();
    setToasts(prev => [...prev.slice(-4), { ...item, id }]); // cap at 5
    // Read risk/fill/price alerts aloud when the user has opted in. Limit to
    // the actionable variants so success/info chatter is not spoken.
    if (voiceAlertsRef.current && (item.variant === 'error' || item.variant === 'warning')) {
      try { speakRef.current(item.message); } catch { /* TTS is best-effort */ }
    }
    return id;
  }, []);

  const success = useCallback((message: string, opts?: Partial<Omit<ToastItem, 'id' | 'variant' | 'message'>>) =>
    add({ variant: 'success', message, ...opts }), [add]);
  const error   = useCallback((message: string, opts?: Partial<Omit<ToastItem, 'id' | 'variant' | 'message'>>) =>
    add({ variant: 'error',   message, ...opts }), [add]);
  const warning = useCallback((message: string, opts?: Partial<Omit<ToastItem, 'id' | 'variant' | 'message'>>) =>
    add({ variant: 'warning', message, ...opts }), [add]);
  const info    = useCallback((message: string, opts?: Partial<Omit<ToastItem, 'id' | 'variant' | 'message'>>) =>
    add({ variant: 'info',    message, ...opts }), [add]);

  const value: ToastContextValue = { add, remove, success, error, warning, info };

  return (
    <ToastContext.Provider value={value}>
      <ToastListContext.Provider value={toasts}>
        {children}
        <ToastContainer />
      </ToastListContext.Provider>
    </ToastContext.Provider>
  );
};
