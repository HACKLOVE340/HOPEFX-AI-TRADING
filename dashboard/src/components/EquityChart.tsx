/**
 * EquityChart
 * Loads real equity curve data from /api/pnl/equity-curve.
 * Shows an empty state when no fills have occurred yet.
 * No synthetic/random data is used.
 */
import { useEffect, useRef, useState } from 'react'
import { createChart, IChartApi, AreaData, Time, AreaSeries } from 'lightweight-charts'
import { extractApiError } from '../lib/utils'

interface EquityPoint {
  time: number
  value: number
}

export function EquityChart() {
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
      rightPriceScale: { borderColor: '#334155' },
      timeScale: { borderColor: '#334155', timeVisible: true },
      crosshair: {
        mode: 1,
        vertLine: { color: '#f59e0b', labelBackgroundColor: '#f59e0b' },
        horzLine: { color: '#f59e0b', labelBackgroundColor: '#f59e0b' },
      },
    })

    const series = chart.addSeries(AreaSeries, {
      lineColor: '#f59e0b',
      topColor: 'rgba(245, 158, 11, 0.4)',
      bottomColor: 'rgba(245, 158, 11, 0.0)',
      lineWidth: 2,
    })

    chartRef.current = chart

    const load = async () => {
      try {
        const res = await fetch('/api/pnl/equity-curve')
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const points: EquityPoint[] = await res.json()
        if (!points || points.length === 0) {
          setEmpty(true)
          return
        }
        const data: AreaData[] = points.map((p) => ({
          time: p.time as Time,
          value: p.value,
        }))
        series.setData(data)
        chart.timeScale().fitContent()
        setEmpty(false)
      } catch (err) {
        setError(extractApiError(err, 'Failed to load equity curve'))
      }
    }

    load()

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
    <div className="relative h-[300px]">
      <div ref={containerRef} className="h-full" />
      {empty && (
        <div className="absolute inset-0 flex items-center justify-center text-slate-500 text-sm">
          No fills yet — equity curve will appear after the first trade.
        </div>
      )}
      {error && (
        <div className="absolute inset-0 flex items-center justify-center text-red-400 text-sm">
          {error}
        </div>
      )}
    </div>
  )
}
