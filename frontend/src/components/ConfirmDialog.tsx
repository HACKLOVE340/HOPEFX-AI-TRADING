/**
 * ConfirmDialog — accessible modal confirmation replacing window.confirm().
 *
 * Usage (imperative API — no JSX needed at call site):
 *   import { useConfirm } from '../components/ConfirmDialog';
 *   const confirm = useConfirm();
 *
 *   const ok = await confirm({
 *     title:       'Delete tenant?',
 *     description: 'This cannot be undone.',
 *     confirmLabel: 'Delete',
 *     variant:      'danger',
 *   });
 *   if (ok) { ... }
 *
 * Mount <ConfirmDialogProvider> once in App.tsx (wraps children).
 */

import React, { createContext, useCallback, useContext, useRef, useState } from 'react';

// ── Types ─────────────────────────────────────────────────────────────────────

export interface ConfirmOptions {
  title:         string;
  description?:  string;
  confirmLabel?: string;
  cancelLabel?:  string;
  /** 'danger' renders the confirm button in red. Default 'default'. */
  variant?:      'default' | 'danger' | 'warning';
}

type Resolver = (value: boolean) => void;

interface ConfirmContextValue {
  confirm: (opts: ConfirmOptions) => Promise<boolean>;
}

// ── Context ───────────────────────────────────────────────────────────────────

const ConfirmContext = createContext<ConfirmContextValue | null>(null);

export function useConfirm(): (opts: ConfirmOptions) => Promise<boolean> {
  const ctx = useContext(ConfirmContext);
  // Fail-safe when no provider is mounted (e.g. unit tests / isolated render):
  // resolve to false (cancel) so a destructive action never proceeds without an
  // explicit confirmation. Production mounts ConfirmDialogProvider in App.tsx.
  if (!ctx) return async () => false;
  return ctx.confirm;
}

// ── Variant styles ────────────────────────────────────────────────────────────

const CONFIRM_BTN: Record<string, React.CSSProperties> = {
  default: { background: '#1d4ed8', border: '1px solid #3b82f6', color: '#fff' },
  danger:  { background: '#7f1d1d', border: '1px solid #ef4444', color: '#fca5a5' },
  warning: { background: '#78350f', border: '1px solid #f59e0b', color: '#fde68a' },
};

// ── Dialog component ──────────────────────────────────────────────────────────

interface DialogState {
  open:    boolean;
  opts:    ConfirmOptions;
}

const DEFAULT_OPTS: ConfirmOptions = { title: 'Are you sure?' };

export const ConfirmDialogProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [state, setState] = useState<DialogState>({ open: false, opts: DEFAULT_OPTS });
  const resolverRef = useRef<Resolver | null>(null);

  // F8-01: the dialog declares aria-modal="true" and its backdrop blocks the
  // mouse, but the keyboard walked straight out of it. `autoFocus` on the
  // confirm button moved focus in; nothing kept it there, and nothing put it
  // back afterwards.
  //
  // On a money path that is not merely an accessibility gap: with focus back on
  // the submit button behind the dialog, Enter re-submits the form. That is the
  // mechanism behind F2-02 — this fixes the cause, that fixed the consequence.
  const dialogRef  = useRef<HTMLDivElement | null>(null);
  const restoreRef = useRef<HTMLElement | null>(null);

  const focusables = () =>
    Array.from(
      dialogRef.current?.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
      ) ?? [],
    ).filter((el) => !el.hasAttribute('disabled'));

  const onKeyDownTrap = (e: React.KeyboardEvent) => {
    if (e.key !== 'Tab') return;
    const items = focusables();
    const first = items[0];
    const last  = items[items.length - 1];
    if (!first || !last) return;
    const active = document.activeElement as HTMLElement | null;

    if (e.shiftKey && (active === first || !dialogRef.current?.contains(active))) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && (active === last || !dialogRef.current?.contains(active))) {
      e.preventDefault();
      first.focus();
    }
  };

  const confirm = useCallback((opts: ConfirmOptions): Promise<boolean> => {
    // F2-02: `resolverRef` is one slot. A second confirm() used to overwrite the
    // first resolver, leaving that promise never settled — and every caller
    // does `const ok = await confirm(...)` before setting its busy flag, so the
    // displaced caller hung forever and its `finally` never ran. A submit
    // button disabled while a confirmation is pending stayed disabled for the
    // life of the page.
    //
    // Settle it `false`: nobody is looking at a dialog that has been replaced,
    // and the only safe answer to a confirmation nobody saw is no.
    resolverRef.current?.(false);
    // Remember where focus came from so it can go back (F8-01). Only on the
    // first open — a displaced confirmation must not overwrite the original.
    if (!restoreRef.current) {
      restoreRef.current = document.activeElement as HTMLElement | null;
    }
    setState({ open: true, opts });
    return new Promise<boolean>(resolve => { resolverRef.current = resolve; });
  }, []);

  const resolve = useCallback((value: boolean) => {
    setState(s => ({ ...s, open: false }));
    resolverRef.current?.(value);
    resolverRef.current = null;
    // Focus goes back where it came from. Without this it falls to <body>, and
    // the next keystroke goes nowhere.
    const restore = restoreRef.current;
    restoreRef.current = null;
    if (restore?.isConnected) restore.focus();
  }, []);

  const { opts } = state;
  const variant  = opts.variant ?? 'default';
  const btnStyle = CONFIRM_BTN[variant];

  return (
    <ConfirmContext.Provider value={{ confirm }}>
      {children}

      {/* Backdrop */}
      {state.open && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="confirm-title"
          style={{
            position: 'fixed', inset: 0, zIndex: 10000,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)',
            animation: 'fadeIn 0.15s ease',
          }}
          ref={dialogRef}
          onClick={e => { if (e.target === e.currentTarget) resolve(false); }}
          onKeyDown={e => {
            if (e.key === 'Escape') { resolve(false); return; }
            onKeyDownTrap(e);
          }}
        >
          <style>{`@keyframes fadeIn { from { opacity: 0 } to { opacity: 1 } }
            @keyframes slideUp { from { transform: translateY(12px); opacity: 0 } to { transform: translateY(0); opacity: 1 } }`}
          </style>

          <div style={{
            background: '#0d1421', border: '1px solid #1e293b',
            borderRadius: 14, padding: '28px 28px 24px',
            maxWidth: 420, width: '90%',
            boxShadow: '0 24px 64px rgba(0,0,0,0.6)',
            animation: 'slideUp 0.2s cubic-bezier(0.34,1.56,0.64,1)',
          }}>
            {/* Icon */}
            <div style={{
              width: 44, height: 44, borderRadius: 12, marginBottom: 16,
              background: variant === 'danger' ? '#450a0a' : variant === 'warning' ? '#431407' : '#1e3a5f',
              border: `1px solid ${variant === 'danger' ? '#7f1d1d' : variant === 'warning' ? '#92400e' : '#1d4ed8'}`,
              display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 20,
            }}>
              {variant === 'danger' ? '🗑' : variant === 'warning' ? '⚠️' : '❓'}
            </div>

            <h2 id="confirm-title" style={{ fontSize: 17, fontWeight: 700, color: '#f1f5f9', margin: '0 0 8px' }}>
              {opts.title}
            </h2>

            {opts.description && (
              <p style={{ fontSize: 13, color: '#64748b', margin: '0 0 24px', lineHeight: 1.6 }}>
                {opts.description}
              </p>
            )}

            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: opts.description ? 0 : 24 }}>
              <button
                autoFocus
                onClick={() => resolve(false)}
                style={{
                  background: 'transparent', border: '1px solid #334155',
                  borderRadius: 8, color: '#94a3b8', cursor: 'pointer',
                  fontSize: 13, fontWeight: 600, padding: '9px 18px',
                }}
                onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.borderColor = '#475569'; (e.currentTarget as HTMLButtonElement).style.color = '#f1f5f9'; }}
                onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.borderColor = '#334155'; (e.currentTarget as HTMLButtonElement).style.color = '#94a3b8'; }}
              >
                {opts.cancelLabel ?? 'Cancel'}
              </button>

              <button
                onClick={() => resolve(true)}
                style={{
                  ...btnStyle,
                  borderRadius: 8, cursor: 'pointer',
                  fontSize: 13, fontWeight: 700, padding: '9px 18px',
                }}
              >
                {opts.confirmLabel ?? 'Confirm'}
              </button>
            </div>
          </div>
        </div>
      )}
    </ConfirmContext.Provider>
  );
};
