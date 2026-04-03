/**
 * DrawdownChart
 * Underwater equity curve — shows drawdown % from peak at each point in time.
 * Loads real data from /api/pnl/drawdown-curve.
 * Shows an empty state when no fills have occurred yet.
 * No synthetic/random data is used.
 */
import { useEffect, useRef, useState } from 'react'
import { createChart, IChartApi, AreaData, Time } from 'lightweight-charts'

interface DrawdownPoint {
  time: number
  drawdown_pct: number
}

export function DrawdownChart() {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const [empty, setEmpty] = useState(false)
  const [error, setError] = useState<string | null>(null)

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
      rightPriceScale: { borderColor: '#334155', mode: 0 },
      timeScale: { borderColor: '#334155', timeVisible: true },
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
      priceFormat: { type: 'custom', formatter: (v: number) => `${v.toFixed(2)}%` },
    })

    chartRef.current = chart

    const loadData = async () => {
      try {
        const res = await fetch('/api/pnl/drawdown-curve')
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const points: DrawdownPoint[] = await res.json()
        if (!points || points.length === 0) {
          setEmpty(true)
          return
        }
        const data: AreaData[] = points.map((p) => ({
          time: p.time as Time,
          value: p.drawdown_pct,
        }))
        series.setData(data)
        chart.timeScale().fitContent()
        setEmpty(false)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load drawdown data')
      }
    }

    loadData()

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
      <div className="relative h-[180px]">
        <div ref={containerRef} className="h-full" />
        {empty && (
          <div className="absolute inset-0 flex items-center justify-center text-slate-500 text-sm">
            No fills yet — drawdown chart will appear after the first trade.
          </div>
        )}
        {error && (
          <div className="absolute inset-0 flex items-center justify-center text-red-400 text-sm">
            {error}
          </div>
        )}
      </div>
    </div>
  )
}
