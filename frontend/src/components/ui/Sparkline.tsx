/**
 * components/ui/Sparkline.tsx
 * Minimal SVG sparkline for price history in ticker rows.
 */

import React, { useMemo } from 'react';

interface SparklineProps {
  data:      number[];
  width?:    number;
  height?:   number;
  color?:    string;
  className?: string;
}

export function Sparkline({
  data,
  width  = 80,
  height = 28,
  color,
  className,
}: SparklineProps) {
  const path = useMemo(() => {
    if (data.length < 2) return '';
    const min = Math.min(...data);
    const max = Math.max(...data);
    const range = max - min || 1;
    const pad = 2;
    const w = width  - pad * 2;
    const h = height - pad * 2;

    const points = data.map((v, i) => {
      const x = pad + (i / (data.length - 1)) * w;
      const y = pad + h - ((v - min) / range) * h;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    });

    return `M ${points.join(' L ')}`;
  }, [data, width, height]);

  const trend = data.length >= 2 ? data[data.length - 1] - data[0] : 0;
  const autoColor = trend >= 0 ? '#00e676' : '#ff1744';
  const strokeColor = color ?? autoColor;

  if (!path) return null;

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={className}
      aria-hidden="true"
    >
      <defs>
        <linearGradient id={`sg-${strokeColor.replace('#', '')}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={strokeColor} stopOpacity="0.15" />
          <stop offset="100%" stopColor={strokeColor} stopOpacity="0" />
        </linearGradient>
      </defs>
      {/* Fill area */}
      <path
        d={`${path} L ${width - 2},${height - 2} L 2,${height - 2} Z`}
        fill={`url(#sg-${strokeColor.replace('#', '')})`}
      />
      {/* Line */}
      <path
        d={path}
        fill="none"
        stroke={strokeColor}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
