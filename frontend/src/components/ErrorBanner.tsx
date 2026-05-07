/**
 * ErrorBanner — inline error / warning / info alert strip.
 */

import React from 'react';

type Level = 'error' | 'warning' | 'info' | 'success';

export interface ErrorBannerProps {
  level?: Level;
  message: string;
  onDismiss?: () => void;
  style?: React.CSSProperties;
  className?: string;
}

const LEVEL_STYLES: Record<Level, { bg: string; border: string; color: string; icon: string }> = {
  error:   { bg: 'rgba(248,113,113,0.1)', border: 'rgba(248,113,113,0.3)', color: '#f87171', icon: '✕' },
  warning: { bg: 'rgba(251,191,36,0.1)',  border: 'rgba(251,191,36,0.3)',  color: '#fbbf24', icon: '⚠' },
  info:    { bg: 'rgba(96,165,250,0.1)',  border: 'rgba(96,165,250,0.3)',  color: '#60a5fa', icon: 'ℹ' },
  success: { bg: 'rgba(74,222,128,0.1)',  border: 'rgba(74,222,128,0.3)',  color: '#4ade80', icon: '✓' },
};

export const ErrorBanner: React.FC<ErrorBannerProps> = ({
  level = 'error',
  message,
  onDismiss,
  style,
  className,
}) => {
  const ls = LEVEL_STYLES[level];
  return (
    <div
      role="alert"
      className={className}
      style={{
        alignItems: 'center',
        background: ls.bg,
        border: `1px solid ${ls.border}`,
        borderRadius: 8,
        color: ls.color,
        display: 'flex',
        fontSize: 13,
        gap: 8,
        padding: '10px 14px',
        ...style,
      }}
    >
      <span style={{ flexShrink: 0, fontWeight: 700 }}>{ls.icon}</span>
      <span style={{ flex: 1 }}>{message}</span>
      {onDismiss && (
        <button
          onClick={onDismiss}
          aria-label="Dismiss"
          style={{
            background: 'transparent',
            border: 'none',
            color: ls.color,
            cursor: 'pointer',
            fontSize: 14,
            lineHeight: 1,
            opacity: 0.7,
            padding: 2,
          }}
        >
          ✕
        </button>
      )}
    </div>
  );
};
