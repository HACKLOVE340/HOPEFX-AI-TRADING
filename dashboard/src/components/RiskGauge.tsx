/**
 * RiskGauge
 *
 * Circular arc gauge for risk metrics (margin level, daily loss, drawdown).
 * Pure SVG — no external charting library needed.
 */
import React from 'react'

interface Props {
  value: number        // 0–100 (percentage)
  max?: number         // default 100
  label: string
  sublabel?: string
  size?: number        // px, default 120
  thresholds?: {       // colour breakpoints
    warn: number       // default 60
    danger: number     // default 80
  }
  unit?: string
  formatValue?: (v: number) => string
}

export function RiskGauge({
  value,
  max = 100,
  label,
  sublabel,
  size = 120,
  thresholds = { warn: 60, danger: 80 },
  unit = '%',
  formatValue,
}: Props) {
  const pct = Math.min((value / max) * 100, 100)
  const radius = (size - 16) / 2
  const cx = size / 2
  const cy = size / 2
  const circumference = Math.PI * radius  // half-circle arc
  const strokeDashoffset = circumference * (1 - pct / 100)

  const color =
    pct >= thresholds.danger
      ? '#ef4444'   // red
      : pct >= thresholds.warn
      ? '#f59e0b'   // amber
      : '#22c55e'   // green

  const trackColor = '#1e293b'

  const displayValue = formatValue
    ? formatValue(value)
    : `${value.toFixed(1)}${unit}`

  return (
    <div className="flex flex-col items-center gap-1">
      <svg width={size} height={size / 2 + 16} viewBox={`0 0 ${size} ${size / 2 + 16}`}>
        {/* Track arc */}
        <path
          d={`M 8 ${cy} A ${radius} ${radius} 0 0 1 ${size - 8} ${cy}`}
          fill="none"
          stroke={trackColor}
          strokeWidth={8}
          strokeLinecap="round"
        />
        {/* Value arc */}
        <path
          d={`M 8 ${cy} A ${radius} ${radius} 0 0 1 ${size - 8} ${cy}`}
          fill="none"
          stroke={color}
          strokeWidth={8}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={strokeDashoffset}
          style={{ transition: 'stroke-dashoffset 0.5s ease, stroke 0.3s ease' }}
        />
        {/* Value text */}
        <text
          x={cx}
          y={cy - 4}
          textAnchor="middle"
          dominantBaseline="middle"
          fill={color}
          fontSize={size * 0.16}
          fontWeight="700"
          fontFamily="ui-monospace, monospace"
        >
          {displayValue}
        </text>
      </svg>
      <div className="text-center">
        <div className="text-xs font-medium text-slate-300">{label}</div>
        {sublabel && <div className="text-xs text-slate-500">{sublabel}</div>}
      </div>
    </div>
  )
}

// ── Compact horizontal bar variant ────────────────────────────────────────────

interface BarProps {
  label: string
  value: number | null
  max: number
  unit?: string
  color?: 'red' | 'amber' | 'green' | 'blue' | 'purple'
  formatValue?: (v: number) => string
  warnAt?: number
  dangerAt?: number
}

export function RiskBar({
  label,
  value,
  max,
  unit = '%',
  color = 'amber',
  formatValue,
  warnAt,
  dangerAt,
}: BarProps) {
  const pct = value !== null && max > 0 ? Math.min((Math.abs(value) / max) * 100, 100) : 0

  const effectiveColor =
    value !== null && dangerAt !== undefined && Math.abs(value) >= dangerAt
      ? 'red'
      : value !== null && warnAt !== undefined && Math.abs(value) >= warnAt
      ? 'amber'
      : color

  const barColors: Record<string, string> = {
    red: 'bg-red-500',
    amber: 'bg-amber-500',
    green: 'bg-green-500',
    blue: 'bg-blue-500',
    purple: 'bg-purple-500',
  }

  const displayValue =
    value === null
      ? '—'
      : formatValue
      ? formatValue(value)
      : `${value.toFixed(unit === '%' ? 1 : 0)}${unit}`

  const displayMax = formatValue ? formatValue(max) : `${max}${unit}`

  return (
    <div>
      <div className="flex justify-between text-xs mb-1">
        <span className="text-slate-400">{label}</span>
        <span className={value === null ? 'text-slate-600' : 'text-slate-200'}>
          {displayValue}
          {value !== null && ` / ${displayMax}`}
        </span>
      </div>
      <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
        <div
          className={`h-full ${barColors[effectiveColor]} transition-all duration-500 rounded-full`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}
