/**
 * ThemeToggle — sun/moon icon button that switches dark ↔ light theme.
 * Reads and writes via ThemeContext.
 */

import React from 'react';
import { useTheme } from './ThemeContext';
import { Moon, Sun } from 'lucide-react';

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
        border: '1px solid var(--border, var(--border-strong))',
        borderRadius: 8,
        color: 'var(--text-muted, var(--text-dim))',
        cursor: 'pointer',
        fontSize: 16,
        lineHeight: 1,
        padding: '6px 8px',
        transition: 'color 0.15s, border-color 0.15s',
        ...style,
      }}
    >
      {theme === 'dark' ? <Sun size={16} aria-hidden /> : <Moon size={16} aria-hidden />}
    </button>
  );
};
