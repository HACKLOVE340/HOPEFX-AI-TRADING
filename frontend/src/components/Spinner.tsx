/**
 * Spinner — CSS-only loading indicator.
 * Size: sm (16px) | md (24px) | lg (40px)
 */

import React from 'react';

interface SpinnerProps {
  size?: 'sm' | 'md' | 'lg';
  color?: string;
  style?: React.CSSProperties;
}

const SIZE_PX: Record<NonNullable<SpinnerProps['size']>, number> = {
  sm: 16,
  md: 24,
  lg: 40,
};

export const Spinner: React.FC<SpinnerProps> = ({
  size = 'md',
  color = '#3b82f6',
  style,
}) => {
  const px = SIZE_PX[size];
  return (
    <>
      <style>{`
        @keyframes _hopefx_spin {
          to { transform: rotate(360deg); }
        }
        ._hopefx_spinner {
          animation: _hopefx_spin 0.7s linear infinite;
          border-radius: 50%;
          display: inline-block;
          flex-shrink: 0;
        }
      `}</style>
      <span
        className="_hopefx_spinner"
        role="status"
        aria-label="Loading"
        style={{
          width: px,
          height: px,
          border: `${Math.max(2, px / 8)}px solid rgba(255,255,255,0.1)`,
          borderTopColor: color,
          ...style,
        }}
      />
    </>
  );
};
