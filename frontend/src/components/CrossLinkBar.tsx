/**
 * CrossLinkBar — footer navigation strip linking to related pages.
 * Renders a horizontal row of pill-shaped links at the bottom of a page.
 */

import React from 'react';
import { Link } from 'react-router-dom';
import type { LucideIcon } from 'lucide-react';

export interface CrossLink {
  label: string;
  href: string;
  /**
   * Lucide component preferred. A string is a legacy emoji call site: emoji
   * render differently on every OS and cannot inherit `currentColor`, so they
   * ignore the link's own hover and active colour (audit F170/F175).
   */
  icon?: LucideIcon | string;
  color?: string;
}

export interface CrossLinkBarProps {
  links: CrossLink[];
  title?: string;
  style?: React.CSSProperties;
  className?: string;
}

export const CrossLinkBar: React.FC<CrossLinkBarProps> = ({ links, title, style, className }) => (
  <div
    className={className}
    style={{
      borderTop: '1px solid var(--border, #1e293b)',
      paddingTop: 16,
      marginTop: 8,
      ...style,
    }}
  >
    {title && (
      <div style={{
        fontSize: 10, fontWeight: 700, color: '#334155',
        textTransform: 'uppercase', letterSpacing: '0.08em',
        marginBottom: 10,
      }}>
        {title}
      </div>
    )}
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
      {links.map((link) => (
        <Link
          key={link.href}
          to={link.href}
          // 44px minimum target (rubric: touch-target-size, CRITICAL). These
          // pills were ~26px tall and appear at the foot of most pages, so the
          // fix lifts every page using the bar rather than one.
          className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500
                     focus-visible:ring-offset-2 focus-visible:ring-offset-[#080c14]"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 5,
            minHeight: 44,
            cursor: 'pointer',
            padding: '0 14px',
            background: link.color ? `${link.color}12` : 'transparent',
            border: `1px solid ${link.color ? `${link.color}30` : '#1e293b'}`,
            borderRadius: 8,
            color: link.color ?? '#475569',
            fontSize: 12,
            fontWeight: 500,
            textDecoration: 'none',
            transition: 'border-color 0.15s, color 0.15s, background 0.15s',
          }}
          onMouseEnter={(e) => {
            const el = e.currentTarget as HTMLAnchorElement;
            el.style.borderColor = link.color ? `${link.color}60` : '#334155';
            el.style.color = link.color ?? '#94a3b8';
          }}
          onMouseLeave={(e) => {
            const el = e.currentTarget as HTMLAnchorElement;
            el.style.borderColor = link.color ? `${link.color}30` : '#1e293b';
            el.style.color = link.color ?? '#475569';
          }}
        >
          {link.icon && (
            typeof link.icon === 'string'
              ? <span style={{ fontSize: 13 }}>{link.icon}</span>   /* legacy emoji */
              : React.createElement(link.icon, { size: 14, strokeWidth: 1.75, 'aria-hidden': true })
          )}
          {link.label}
        </Link>
      ))}
    </div>
  </div>
);
