/**
 * Modal — accessible dialog overlay.
 *
 * Features:
 * - Focus trap (Tab / Shift+Tab cycle within modal)
 * - Escape key closes
 * - Click-outside closes (optional)
 * - Portal renders into document.body
 * - ARIA role="dialog" + aria-modal + aria-labelledby
 */

import React, { useCallback, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  /** Max width of the dialog panel (default 520px) */
  maxWidth?: number;
  /** Close when clicking the backdrop (default true) */
  closeOnBackdrop?: boolean;
  children: React.ReactNode;
  footer?: React.ReactNode;
}

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])';

export const Modal: React.FC<ModalProps> = ({
  open,
  onClose,
  title,
  maxWidth = 520,
  closeOnBackdrop = true,
  children,
  footer,
}) => {
  const panelRef  = useRef<HTMLDivElement>(null);
  const titleId   = useRef(`modal-title-${Math.random().toString(36).slice(2)}`).current;

  // Focus first focusable element on open
  useEffect(() => {
    if (!open) return;
    const el = panelRef.current?.querySelector<HTMLElement>(FOCUSABLE);
    el?.focus();
  }, [open]);

  // Escape key
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open, onClose]);

  // Focus trap
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      if (e.key !== 'Tab' || !panelRef.current) return;
      const focusable = Array.from(
        panelRef.current.querySelectorAll<HTMLElement>(FOCUSABLE),
      );
      if (focusable.length === 0) return;
      const first = focusable[0]!;
      const last  = focusable[focusable.length - 1]!;
      if (e.shiftKey) {
        if (document.activeElement === first) {
          e.preventDefault();
          last.focus();
        }
      } else {
        if (document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    },
    [],
  );

  if (!open) return null;

  return createPortal(
    <div
      role="presentation"
      style={styles.backdrop}
      onClick={closeOnBackdrop ? onClose : undefined}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? titleId : undefined}
        onKeyDown={handleKeyDown}
        onClick={(e) => e.stopPropagation()}
        style={{ ...styles.panel, maxWidth }}
      >
        {/* Header */}
        {title && (
          <div style={styles.header}>
            <h2 id={titleId} style={styles.title}>{title}</h2>
            <button
              onClick={onClose}
              aria-label="Close dialog"
              style={styles.closeBtn}
            >
              ✕
            </button>
          </div>
        )}

        {/* Body */}
        <div style={styles.body}>{children}</div>

        {/* Footer */}
        {footer && <div style={styles.footer}>{footer}</div>}
      </div>
    </div>,
    document.body,
  );
};

const styles: Record<string, React.CSSProperties> = {
  backdrop: {
    position: 'fixed',
    inset: 0,
    background: 'rgba(0,0,0,0.6)',
    backdropFilter: 'blur(2px)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 1000,
    padding: 16,
  },
  panel: {
    background: 'var(--surface, #1e293b)',
    border: '1px solid var(--border, #334155)',
    borderRadius: 12,
    boxShadow: '0 24px 48px rgba(0,0,0,0.4)',
    display: 'flex',
    flexDirection: 'column',
    maxHeight: '90vh',
    outline: 'none',
    width: '100%',
  },
  header: {
    alignItems: 'center',
    borderBottom: '1px solid var(--border, #334155)',
    display: 'flex',
    justifyContent: 'space-between',
    padding: '16px 20px',
  },
  title: {
    color: 'var(--text, #f1f5f9)',
    fontSize: 16,
    fontWeight: 600,
    margin: 0,
  },
  closeBtn: {
    background: 'transparent',
    border: 'none',
    color: 'var(--text-muted, #64748b)',
    cursor: 'pointer',
    fontSize: 14,
    lineHeight: 1,
    padding: 4,
  },
  body: {
    color: 'var(--text, #f1f5f9)',
    flex: 1,
    overflowY: 'auto',
    padding: '20px',
  },
  footer: {
    borderTop: '1px solid var(--border, #334155)',
    display: 'flex',
    gap: 8,
    justifyContent: 'flex-end',
    padding: '12px 20px',
  },
};
