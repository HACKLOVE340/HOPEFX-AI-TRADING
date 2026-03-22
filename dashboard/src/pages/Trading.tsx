import { useEffect, useRef } from 'react'
import { createChart, IChartApi, ISeriesApi, CandlestickData } from 'lightweight-charts'
import { useStore } from '../store/useStore'
import { OrderPanel } from '../components/OrderPanel'
import { PositionTable } from '../components/PositionTable'

export function Trading() {
  const chartContainerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const tick = useStore((state) => state.ticks['XAUUSD'])

  useEffect(() => {
    if (!chartContainerRef.current) return

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { color: '#0f172a' },
        textColor: '#94a3b8',
      },
      grid: {
        vertLines: { color: '#1e293b' },
        horzLines: { color: '#1e293b' },
      },
      rightPriceScale: {
        borderColor: '#334155',
      },
      timeScale: {
        borderColor: '#334155',
      },
    })

    const series = chart.addCandlestickSeries({
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderUpColor: '#22c55e',
      borderDownColor: '#ef4444',
      wickUpColor: '#22c55e',
      wickDownColor: '#ef4444',
    })

    chartRef.current = chart
    seriesRef.current = series

    // Load historical data
    fetch('/api/v1/historical/XAUUSD')
      .then(r => r.json())
      .then(data => series.setData(data))

    const handleResize = () => {
      chart.applyOptions({ width: chartContainerRef.current?.clientWidth })
    }
    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('resize', handleResize)
      chart.remove()
    }
  }, [])

  // Real-time updates
  useEffect(() => {
    if (tick && seriesRef.current) {
      const candle: CandlestickData = {
        time: new Date(tick.timestamp).getTime() / 1000 as any,
        open: tick.bid,
        high: Math.max(tick.bid, tick.ask),
        low: Math.min(tick.bid, tick.ask),
        close: tick.ask,
      }
      seriesRef.current.update(candle)
    }
  }, [tick])

  return (
    <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
      <div className="lg:col-span-3 space-y-6">
        <div className="bg-slate-900 rounded-lg border border-slate-800 p-4">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-lg font-semibold">XAUUSD</h2>
              <div className="flex items-center gap-4 text-sm">
                <span className="text-slate-400">Bid: {tick?.bid.toFixed(2)}</span>
                <span className="text-slate-400">Ask: {tick?.ask.toFixed(2)}</span>
                <span className="text-amber-400">Spread: {tick ? (tick.ask - tick.bid).toFixed(3) : '-'}</span>
              </div>
            </div>
            <div className="flex gap-2">
              <span className="px-2 py-1 bg-green-500/10 text-green-400 text-xs rounded">ML: LONG 78%</span>
              <span className="px-2 py-1 bg-blue-500/10 text-blue-400 text-xs rounded">Trend: BULLISH</span>
            </div>
          </div>
          <div ref={chartContainerRef} className="h-[500px]" />
        </div>
        
        <PositionTable />
      </div>
      
      <div className="space-y-6">
        <OrderPanel />
        
        <div className="bg-slate-900 rounded-lg border border-slate-800 p-4">
          <h3 className="font-semibold mb-3">Risk Metrics</h3>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-slate-400">Daily P&L</span>
              <span className="text-green-400">+$1,234.56</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400">Open Risk</span>
              <span className="text-amber-400">0.8%</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400">Margin Used</span>
              <span className="text-slate-200">$12,450 / $50,000</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
