import { useEffect, useRef } from 'react'
import { createChart, IChartApi, ISeriesApi, CandlestickData, CandlestickSeries } from 'lightweight-charts'
import { useStore } from '../store/useStore'
import { OrderPanel } from '../components/OrderPanel'
import { PositionTable } from '../components/PositionTable'
import { MultiTimeframeChart } from '../components/MultiTimeframeChart'

export function Trading() {
  const chartContainerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)

  const tick = useStore((state) => state.prices['XAUUSD'])
  const account = useStore((state) => state.account)
  const signals = useStore((state) => state.signals)

  // Latest ML signal for XAUUSD
  const latestSignal = signals.find(
    (s) => s.symbol === 'XAU/USD' || s.symbol === 'XAUUSD'
  )

  // Real account metrics — null until WebSocket delivers account_update
  const dailyPnl = account?.daily_pnl ?? null
  const openRiskPct =
    account && account.equity > 0
      ? (account.margin_used / account.equity) * 100
      : null
  const marginUsed = account?.margin_used ?? null
  const marginTotal =
    account != null ? account.margin_used + account.margin_free : null

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
      rightPriceScale: { borderColor: '#334155' },
      timeScale: { borderColor: '#334155' },
    })

    const series = chart.addSeries(CandlestickSeries, {
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderUpColor: '#22c55e',
      borderDownColor: '#ef4444',
      wickUpColor: '#22c55e',
      wickDownColor: '#ef4444',
    })

    chartRef.current = chart
    seriesRef.current = series

    // Load historical OHLCV from the real endpoint
    fetch('/api/trading/ohlcv/XAUUSD?timeframe=1h&limit=200')
      .then((r) => r.json())
      .then((data) => {
        const candles = Array.isArray(data) ? data : (data.data ?? [])
        series.setData(
          candles.map((c: any) => ({
            time: (typeof c.timestamp === 'number'
              ? c.timestamp
              : new Date(c.timestamp).getTime() / 1000) as any,
            open: c.open,
            high: c.high,
            low: c.low,
            close: c.close,
          }))
        )
      })
      .catch(() => {
        /* chart starts empty until live ticks arrive */
      })

    const handleResize = () => {
      chart.applyOptions({ width: chartContainerRef.current?.clientWidth })
    }
    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('resize', handleResize)
      chart.remove()
    }
  }, [])

  // Real-time candle updates from WebSocket price ticks
  useEffect(() => {
    if (tick && seriesRef.current) {
      const candle: CandlestickData = {
        time: (new Date(tick.timestamp).getTime() / 1000) as any,
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
                <span className="text-slate-400">
                  Bid:{' '}
                  {tick ? tick.bid.toFixed(2) : <span className="text-slate-600">—</span>}
                </span>
                <span className="text-slate-400">
                  Ask:{' '}
                  {tick ? tick.ask.toFixed(2) : <span className="text-slate-600">—</span>}
                </span>
                <span className="text-amber-400">
                  Spread:{' '}
                  {tick ? (tick.ask - tick.bid).toFixed(3) : '—'}
                </span>
              </div>
            </div>
            <div className="flex gap-2">
              {latestSignal ? (
                <>
                  <span
                    className={`px-2 py-1 text-xs rounded ${
                      latestSignal.direction === 'long'
                        ? 'bg-green-500/10 text-green-400'
                        : latestSignal.direction === 'short'
                        ? 'bg-red-500/10 text-red-400'
                        : 'bg-slate-700 text-slate-400'
                    }`}
                  >
                    ML:{' '}
                    {latestSignal.direction === 'long'
                      ? 'LONG'
                      : latestSignal.direction === 'short'
                      ? 'SHORT'
                      : 'NEUTRAL'}{' '}
                    {Math.round(latestSignal.confidence * 100)}%
                  </span>
                </>
              ) : (
                <span className="px-2 py-1 bg-slate-700 text-slate-400 text-xs rounded">
                  ML: awaiting signal
                </span>
              )}
            </div>
          </div>
          <div ref={chartContainerRef} className="h-[500px]" />
        </div>

        <PositionTable />

        <MultiTimeframeChart symbol="XAUUSD" />
      </div>

      <div className="space-y-6">
        <OrderPanel />

        <div className="bg-slate-900 rounded-lg border border-slate-800 p-4">
          <h3 className="font-semibold mb-3">Risk Metrics</h3>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-slate-400">Daily P&L</span>
              {dailyPnl !== null ? (
                <span className={dailyPnl >= 0 ? 'text-green-400' : 'text-red-400'}>
                  {dailyPnl >= 0 ? '+' : ''}${dailyPnl.toFixed(2)}
                </span>
              ) : (
                <span className="text-slate-600">—</span>
              )}
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400">Open Risk</span>
              {openRiskPct !== null ? (
                <span
                  className={
                    openRiskPct > 5
                      ? 'text-red-400'
                      : openRiskPct > 2
                      ? 'text-amber-400'
                      : 'text-slate-200'
                  }
                >
                  {openRiskPct.toFixed(2)}%
                </span>
              ) : (
                <span className="text-slate-600">—</span>
              )}
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400">Margin Used</span>
              {marginUsed !== null && marginTotal !== null ? (
                <span className="text-slate-200">
                  ${marginUsed.toLocaleString(undefined, { maximumFractionDigits: 0 })} /{' '}
                  ${marginTotal.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                </span>
              ) : (
                <span className="text-slate-600">—</span>
              )}
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400">Balance</span>
              {account?.balance != null ? (
                <span className="text-slate-200">
                  ${account.balance.toLocaleString(undefined, {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2,
                  })}
                </span>
              ) : (
                <span className="text-slate-600">—</span>
              )}
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400">Equity</span>
              {account?.equity != null ? (
                <span className="text-slate-200">
                  ${account.equity.toLocaleString(undefined, {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2,
                  })}
                </span>
              ) : (
                <span className="text-slate-600">—</span>
              )}
            </div>
          </div>
          {account === null && (
            <p className="text-xs text-slate-600 mt-3">
              Awaiting account data from WebSocket…
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
