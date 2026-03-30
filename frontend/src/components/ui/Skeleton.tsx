/**
 * components/ui/Skeleton.tsx
 * Shimmer skeleton loaders for panel loading states.
 */

import React from 'react';
import { cn } from '../../lib/utils';

// ── Base skeleton block ───────────────────────────────────────────────────────

interface SkeletonProps {
  className?: string;
  width?:     string | number;
  height?:    string | number;
  style?:     React.CSSProperties;
}

export function Skeleton({ className, width, height, style }: SkeletonProps) {
  return (
    <div
      className={cn(
        'rounded bg-[#1e2d3d] relative overflow-hidden',
        className,
      )}
      style={{ width, height, ...style }}
    >
      <div
        className="absolute inset-0"
        style={{
          background: 'linear-gradient(90deg, transparent 0%, rgba(45,74,107,0.4) 50%, transparent 100%)',
          backgroundSize: '200% 100%',
          animation: 'shimmer 1.5s infinite',
        }}
      />
    </div>
  );
}

// ── Panel skeleton ────────────────────────────────────────────────────────────

export function PanelSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="flex flex-col gap-3 p-4 h-full bg-[#0d1421] border border-[#1e2d3d] rounded-lg">
      {/* Header */}
      <div className="flex items-center justify-between pb-2 border-b border-[#1e2d3d]">
        <Skeleton className="h-2.5 w-24" />
        <Skeleton className="h-2.5 w-16" />
      </div>
      {/* Rows */}
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton className="h-2 flex-1" style={{ opacity: 1 - i * 0.15 }} />
          <Skeleton className="h-2 w-16" style={{ opacity: 1 - i * 0.15 }} />
        </div>
      ))}
    </div>
  );
}

// ── Ticker skeleton ───────────────────────────────────────────────────────────

export function TickerSkeleton() {
  return (
    <div className="flex items-center gap-8 px-5 py-3 bg-[#0d1421] border-b border-[#1e2d3d]">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="flex flex-col gap-1.5">
          <Skeleton className="h-2.5 w-16" />
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-2 w-12" />
        </div>
      ))}
    </div>
  );
}

// ── Chart skeleton ────────────────────────────────────────────────────────────

export function ChartSkeleton() {
  return (
    <div className="flex flex-col gap-3 p-4 h-full bg-[#0d1421] border border-[#1e2d3d] rounded-lg">
      <div className="flex items-center justify-between pb-2 border-b border-[#1e2d3d]">
        <Skeleton className="h-2.5 w-28" />
        <div className="flex gap-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-2.5 w-14" />
          ))}
        </div>
      </div>
      {/* Chart area */}
      <div className="flex-1 relative">
        <Skeleton className="absolute inset-0 rounded" />
      </div>
      {/* Footer stats */}
      <div className="flex gap-4 pt-2 border-t border-[#1e2d3d]">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="flex flex-col gap-1">
            <Skeleton className="h-2 w-12" />
            <Skeleton className="h-3 w-16" />
          </div>
        ))}
      </div>
    </div>
  );
}
