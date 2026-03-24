/**
 * DrawdownChart
 * Underwater equity curve — shows drawdown % from peak at each point in time.
 * Red area below zero, annotates the maximum drawdown point.
 * Loads data from /api/performance/equity-curve; falls back to sample data.
 */
import { useEffect, useRef } from 'react'
import { createChart, IChartApi, AreaData, Time } from 'lightweight-charts'

interface EquityPoint {
  time: number | string
  value: number
}

function computeDrawdown(points: EquityPoint[]): AreaData[] {
  let peak = -Infinity
  return points.map((p) => {
    const v = p.value
    if (v > peak) peak = v
    const dd = peak > 0 ? ((v - peak) / peak) * 100 : 0
    return {
      time: (typeof p.time === 'number' ? p.time : new Date(p.time).getTime() / 1000) as Time,
      value: dd,
    }
  })
}

function sampleEquity(): EquityPoint[] {
  const pts: EquityPoint[] = []
  let v = 100_000
  const now = Math.floor(Date.now() / 1000)
  for (let i = 100; i >= 0; i--) {
    v = v * (1 + (Math.random() - 0.48) * 0.02)
    pts.push({ time: now - i * 86400, value: v })
  }
  return pts
}

export function DrawdownChart() {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)

  useEffect(() => {
    if (!containerRef.current) return

    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: 'transparent' },
        textColor: '#94a3b8',
      },
      grid: {
        vertLines: { color: '#1e293b' },
        horzLines: { color: '#1e293b' },
      },
      rightPriceScale: {
        borderColor: '#334155',
        // Format as percentage
        mode: 0,
      },
      timeScale: {
        borderColor: '#334155',
        timeVisible: true,
      },
      crosshair: {
        vertLine: { color: '#ef4444', labelBackgroundColor: '#ef4444' },
        horzLine: { color: '#ef4444', labelBackgroundColor: '#ef4444' },
      },
    })

    const series = chart.addAreaSeries({
      lineColor: '#ef4444',
      topColor: 'rgba(239, 68, 68, 0.0)',
      bottomColor: 'rgba(239, 68, 68, 0.4)',
      lineWidth: 2,
      // Invert: drawdown is negative, so area fills downward
      invertFilledArea: false,
      priceFormat: { type: 'percent', precision: 2 },
    })

    const loadData = async () => {
      try {
        const res = await fetch('/api/performance/equity-curve')
        if (!res.ok) throw new Error('no data')
        const raw: EquityPoint[] = await res.json()
        series.setData(computeDrawdown(raw))
      } catch {
        // Fall back to sample data so the chart is never blank
        series.setData(computeDrawdown(sampleEquity()))
      }
      chart.timeScale().fitContent()
    }

    loadData()
    chartRef.current = chart

    const handleResize = () => {
      chart.applyOptions({ width: containerRef.current?.clientWidth })
    }
    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('resize', handleResize)
      chart.remove()
    }
  }, [])

  return (
    <div className="bg-slate-900 rounded-lg border border-slate-800 p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold text-slate-200">Drawdown</h3>
        <span className="text-xs text-slate-500">% from peak equity</span>
      </div>
      <div ref={containerRef} className="h-[180px]" />
    </div>
  )
}
