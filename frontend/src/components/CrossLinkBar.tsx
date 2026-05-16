/**
 * CrossLinkBar — footer navigation strip linking to related pages.
 * Renders a horizontal row of pill-shaped links at the bottom of a page.
 */

import React from 'react';
import { Link } from 'react-router-dom';

export interface CrossLink {
  label: string;
  href: string;
  icon?: string;
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
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 5,
            padding: '5px 12px',
            background: link.color ? `${link.color}12` : 'transparent',
            border: `1px solid ${link.color ? `${link.color}30` : '#1e293b'}`,
            borderRadius: 6,
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
          {link.icon && <span style={{ fontSize: 13 }}>{link.icon}</span>}
          {link.label}
        </Link>
      ))}
    </div>
  </div>
);
