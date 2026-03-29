/**
 * ThemeToggle — sun/moon icon button that switches dark ↔ light theme.
 * Reads and writes via ThemeContext.
 */

import React from 'react';
import { useTheme } from './ThemeContext';

interface ThemeToggleProps {
  /** Additional inline styles */
  style?: React.CSSProperties;
}

export const ThemeToggle: React.FC<ThemeToggleProps> = ({ style }) => {
  const { theme, toggle } = useTheme();

  return (
    <button
      onClick={toggle}
      title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
      aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
      style={{
        background: 'transparent',
        border: '1px solid var(--border, #334155)',
        borderRadius: 8,
        color: 'var(--text-muted, #94a3b8)',
        cursor: 'pointer',
        fontSize: 16,
        lineHeight: 1,
        padding: '6px 8px',
        transition: 'color 0.15s, border-color 0.15s',
        ...style,
      }}
    >
      {theme === 'dark' ? '☀️' : '🌙'}
    </button>
  );
};
