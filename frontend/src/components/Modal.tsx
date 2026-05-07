/**
 * Modal — accessible dialog overlay.
 *
 * Mobile-first: full-screen sheet on xs, centered panel on sm+.
 * Features:
 * - Focus trap (Tab / Shift+Tab cycle within modal)
 * - Escape key closes
 * - Click-outside closes (optional)
 * - Portal renders into document.body
 * - ARIA role="dialog" + aria-modal + aria-labelledby
 * - Size variants: sm | md | lg | xl | full
 */

import React, { useCallback, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';

type ModalSize = 'sm' | 'md' | 'lg' | 'xl' | 'full';

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  /** Semantic size variant (overrides maxWidth) */
  size?: ModalSize;
  /** Legacy max-width override in px */
  maxWidth?: number;
  closeOnBackdrop?: boolean;
  children: React.ReactNode;
  footer?: React.ReactNode;
  /** Extra class on the panel */
  panelClassName?: string;
}

const SIZE_CLASSES: Record<ModalSize, string> = {
  sm:   'sm:max-w-sm',
  md:   'sm:max-w-lg',
  lg:   'sm:max-w-2xl',
  xl:   'sm:max-w-4xl',
  full: 'sm:max-w-full sm:m-4',
};

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])';

export const Modal: React.FC<ModalProps> = ({
  open,
  onClose,
  title,
  size = 'md',
  maxWidth,
  closeOnBackdrop = true,
  children,
  footer,
  panelClassName = '',
}) => {
  const panelRef = useRef<HTMLDivElement>(null);
  const titleId  = useRef(`modal-title-${Math.random().toString(36).slice(2)}`).current;

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

  // Prevent body scroll when open
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = prev; };
  }, [open]);

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

  const sizeCls = SIZE_CLASSES[size];

  return createPortal(
    <div
      role="presentation"
      className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-end sm:items-center justify-center z-modal p-0 sm:p-4"
      onClick={closeOnBackdrop ? onClose : undefined}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? titleId : undefined}
        onKeyDown={handleKeyDown}
        onClick={(e) => e.stopPropagation()}
        className={`bg-terminal-surface border border-terminal-border rounded-t-2xl sm:rounded-xl shadow-2xl flex flex-col w-full ${sizeCls} max-h-[92vh] sm:max-h-[90vh] outline-none ${panelClassName}`}
        style={maxWidth ? { maxWidth } : undefined}
      >
        {/* Header */}
        {title && (
          <div className="flex items-center justify-between border-b border-terminal-border px-4 sm:px-5 py-3.5 flex-shrink-0">
            <h2
              id={titleId}
              className="text-slate-100 text-base font-semibold m-0 leading-tight"
            >
              {title}
            </h2>
            <button
              onClick={onClose}
              aria-label="Close dialog"
              className="text-slate-500 hover:text-slate-300 bg-transparent border-0 cursor-pointer text-lg leading-none p-1 rounded transition-colors min-w-touch min-h-touch flex items-center justify-center"
            >
              ✕
            </button>
          </div>
        )}

        {/* Body */}
        <div className="text-slate-200 flex-1 overflow-y-auto p-4 sm:p-5">
          {children}
        </div>

        {/* Footer */}
        {footer && (
          <div className="border-t border-terminal-border flex gap-2 justify-end px-4 sm:px-5 py-3 flex-shrink-0 flex-wrap">
            {footer}
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
};
