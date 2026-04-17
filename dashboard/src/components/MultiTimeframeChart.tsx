/**
 * MultiTimeframeChart
 * Three synchronized candlestick panels: H4 / H1 / M15.
 * Crosshairs are synchronized across all panels via lightweight-charts
 * subscribeCrosshairMove API.
 */
import { useEffect, useRef } from 'react'
import {
  createChart,
  IChartApi,
  ISeriesApi,
  CrosshairMode,
  Time,
  CandlestickSeries,
} from 'lightweight-charts'

const TIMEFRAMES = [
  { label: 'H4', tf: '4h', limit: 100 },
  { label: 'H1', tf: '1h', limit: 200 },
  { label: 'M15', tf: '15m', limit: 300 },
]

const CHART_OPTS = {
  layout: {
    background: { color: '#0f172a' },
    textColor: '#94a3b8',
  },
  grid: {
    vertLines: { color: '#1e293b' },
    horzLines: { color: '#1e293b' },
  },
  rightPriceScale: { borderColor: '#334155' },
  timeScale: { borderColor: '#334155', timeVisible: true },
  crosshair: { mode: CrosshairMode.Normal },
}

const CANDLE_OPTS = {
  upColor: '#22c55e',
  downColor: '#ef4444',
  borderUpColor: '#22c55e',
  borderDownColor: '#ef4444',
  wickUpColor: '#22c55e',
  wickDownColor: '#ef4444',
}

interface OHLCVBar {
  timestamp: number | string
  open: number
  high: number
  low: number
  close: number
}

function toChartBar(c: OHLCVBar) {
  return {
    time: (typeof c.timestamp === 'number'
      ? c.timestamp
      : new Date(c.timestamp).getTime() / 1000) as Time,
    open: c.open,
    high: c.high,
    low: c.low,
    close: c.close,
  }
}

async function loadBars(symbol: string, tf: string, limit: number) {
  try {
    const res = await fetch(`/api/trading/ohlcv/${symbol}?timeframe=${tf}&limit=${limit}`)
    if (!res.ok) return []
    const data = await res.json()
    const arr: OHLCVBar[] = Array.isArray(data) ? data : (data.data ?? [])
    return arr.map(toChartBar)
  } catch {
    return []
  }
}

export function MultiTimeframeChart({ symbol = 'XAUUSD' }: { symbol?: string }) {
  const containerRefs = useRef<(HTMLDivElement | null)[]>([null, null, null])
  const chartsRef = useRef<IChartApi[]>([])
  const seriesRef = useRef<ISeriesApi<'Candlestick'>[]>([])

  useEffect(() => {
    const charts: IChartApi[] = []
    const series: ISeriesApi<'Candlestick'>[] = []

    TIMEFRAMES.forEach(({ tf, limit }, i) => {
      const el = containerRefs.current[i]
      if (!el) return

      const chart = createChart(el, {
        ...CHART_OPTS,
        width: el.clientWidth,
        height: 220,
      })
      const s = chart.addSeries(CandlestickSeries, CANDLE_OPTS)
      charts.push(chart)
      series.push(s)

      loadBars(symbol, tf, limit).then((bars) => {
        if (bars.length) s.setData(bars)
      })
    })

    chartsRef.current = charts
    seriesRef.current = series

    // Synchronize crosshairs: when one chart moves, update the others
    charts.forEach((srcChart, srcIdx) => {
      srcChart.subscribeCrosshairMove((param) => {
        charts.forEach((dstChart, dstIdx) => {
          if (dstIdx === srcIdx) return
          if (!param.time) {
            dstChart.clearCrosshairPosition()
            return
          }
          const price = param.seriesData.get(series[srcIdx])
          if (price && 'close' in price) {
            dstChart.setCrosshairPosition(price.close as number, param.time, series[dstIdx])
          }
        })
      })
    })

    // Resize handler
    const handleResize = () => {
      charts.forEach((chart, i) => {
        const el = containerRefs.current[i]
        if (el) chart.applyOptions({ width: el.clientWidth })
      })
    }
    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('resize', handleResize)
      charts.forEach((c) => c.remove())
    }
  }, [symbol])

  return (
    <div className="bg-slate-900 rounded-lg border border-slate-800 p-4">
      <h3 className="text-sm font-semibold text-slate-300 mb-3">
        {symbol} — Multi-Timeframe View
      </h3>
      <div className="space-y-3">
        {TIMEFRAMES.map(({ label }, i) => (
          <div key={label}>
            <div className="text-xs text-slate-500 mb-1">{label}</div>
            <div
              ref={(el) => { containerRefs.current[i] = el }}
              className="w-full"
              style={{ height: 220 }}
            />
          </div>
        ))}
      </div>
    </div>
  )
}
