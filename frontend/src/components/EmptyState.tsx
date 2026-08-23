/**
 * EmptyState — zero-data placeholder with icon, title, description,
 * optional CTA button, and optional cross-links to related pages.
 */

import React from 'react';
import { Link } from 'react-router-dom';
import type { LucideIcon } from 'lucide-react';
import { Inbox } from 'lucide-react';

export interface EmptyStateLink {
  label: string;
  href: string;
  icon?: string;
}

interface EmptyStateProps {
  /**
   * Lucide component. Was a string emoji, which renders differently on every
   * OS and cannot inherit `currentColor` — see audit F170/F175. A string is
   * still accepted so the 20+ existing call sites keep working, but it is
   * deprecated: pass a component.
   */
  icon?: LucideIcon | string;
  title: string;
  description?: string;
  /**
   * Verbatim explanation from the API. Several endpoints in this platform
   * return one and the UI discarded it — /correlation showed a blank card for
   * ~20s while the server had sent the remedy in plain English (F189), and
   * /news presents 0.0 as a measurement when the sentiment engine is not
   * running (F194). When the server explains itself, show its words.
   */
  serverNote?: string | null;
  action?: React.ReactNode;
  /** Quick-links to related pages shown below the CTA */
  links?: EmptyStateLink[];
  style?: React.CSSProperties;
  /** Compact variant — less vertical padding */
  compact?: boolean;
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  icon = Inbox,
  title,
  description,
  serverNote,
  action,
  links,
  style,
  compact = false,
}) => (
  <div
    style={{
      alignItems: 'center',
      color: '#64748b',
      display: 'flex',
      flexDirection: 'column',
      gap: 10,
      padding: compact ? '28px 24px' : '56px 24px',
      textAlign: 'center',
      ...style,
    }}
  >
    <div style={{
      width: 64, height: 64, borderRadius: 16,
      background: 'rgba(30,41,59,0.8)',
      border: '1px solid #1e293b',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: 28, lineHeight: 1,
      marginBottom: 4,
      color: '#475569',
    }}>
      {typeof icon === 'string'
        ? icon                                  /* legacy emoji call sites */
        : React.createElement(icon, { size: 26, strokeWidth: 1.5, 'aria-hidden': true })}
    </div>
    <p style={{ color: '#94a3b8', fontSize: 15, fontWeight: 600, margin: 0 }}>{title}</p>
    {description && (
      <p style={{ fontSize: 13, margin: 0, maxWidth: 360, lineHeight: 1.6, color: '#64748b' }}>
        {description}
      </p>
    )}
    {serverNote && (
      <p style={{
        fontSize: 12.5, margin: 0, maxWidth: 520, lineHeight: 1.6,
        color: '#94a3b8', textAlign: 'left',
        background: '#0b1220', border: '1px solid #1e2d3d',
        borderRadius: 8, padding: '8px 12px',
      }}>
        {serverNote}
      </p>
    )}
    {action && <div style={{ marginTop: 8 }}>{action}</div>}
    {links && links.length > 0 && (
      <div style={{
        display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'center',
        marginTop: action ? 4 : 8,
      }}>
        {links.map((l) => (
          <Link
            key={l.href}
            to={l.href}
            // 44px minimum target (rubric: touch-target-size, CRITICAL).
            // These links were ~26px tall and are the primary way out of an
            // empty screen, so they are exactly the ones that must be tappable.
            className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500
                       focus-visible:ring-offset-2 focus-visible:ring-offset-[#0d1421]"
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 5,
              minHeight: 44, fontSize: 12, color: '#475569',
              padding: '0 14px', borderRadius: 8,
              border: '1px solid #1e293b',
              background: 'rgba(30,41,59,0.5)',
              textDecoration: 'none', cursor: 'pointer',
              transition: 'color 0.15s, border-color 0.15s',
            }}
            onMouseEnter={(e) => {
              const el = e.currentTarget as HTMLAnchorElement;
              el.style.color = '#94a3b8';
              el.style.borderColor = '#334155';
            }}
            onMouseLeave={(e) => {
              const el = e.currentTarget as HTMLAnchorElement;
              el.style.color = '#475569';
              el.style.borderColor = '#1e293b';
            }}
          >
            {l.icon && <span>{l.icon}</span>}
            {l.label}
          </Link>
        ))}
      </div>
    )}
  </div>
);
