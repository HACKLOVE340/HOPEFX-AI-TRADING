/**
 * Trading — Advanced Trading Terminal
 *
 * Layout:
 *   Left panel  (col-span-3): SymbolSelector + price header, main chart,
 *                              multi-timeframe charts, open orders table
 *   Right panel (col-span-1): AdvancedOrderPanel, DepthOfMarket / OrderBook,
 *                              risk metrics, ML signal overlay
 *   Bottom:                   PositionTable (compact)
 */
import { useEffect, useRef, useState, useCallback } from 'react'
import {
  createChart,
  IChartApi,
  ISeriesApi,
  CandlestickData,
  CandlestickSeries,
  LineSeries,
  CrosshairMode,
} from 'lightweight-charts'
import {
  Activity, AlertTriangle, BarChart2, Brain, Clock,
  RefreshCw, TrendingDown, TrendingUp, X, Zap,
} from 'lucide-react'
import { useStore } from '../store/useStore'
import { tradingApi } from '../hooks/useApi'
import { SymbolSelector } from '../components/SymbolSelector'
import { AdvancedOrderPanel } from '../components/AdvancedOrderPanel'
import { PositionTable } from '../components/PositionTable'
import { MultiTimeframeChart } from '../components/MultiTimeframeChart'
import { DepthOfMarket } from '../components/DepthOfMarket'
import { RiskBar } from '../components/RiskGauge'

// ── Timeframe selector ────────────────────────────────────────────────────────

const TIMEFRAMES = ['1m', '5m', '15m', '30m', '1h', '4h', '1d', '1w'] as const
type TF = (typeof TIMEFRAMES)[number]

// ── Open orders mini-table ────────────────────────────────────────────────────

function OpenOrdersTable() {
  const orders = useStore((s) => s.orders.filter((o) => o.status === 'open' || o.status === 'pending'))
  const removeOrder = useStore((s) => s.removeOrder)
  const [cancelling, setCancelling] = useState<string | null>(null)

  const handleCancel = async (id: string) => {
    setCancelling(id)
    try {
      await tradingApi.cancelOrder(id)
      removeOrder(id)
    } catch {
      // show nothing — order stays in list
    } finally {
      setCancelling(null)
    }
  }

  if (orders.length === 0) return null

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
        <h3 className="text-sm font-semibold">Pending Orders</h3>
        <span className="text-xs text-slate-500">{orders.length}</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="text-xs text-slate-500 border-b border-slate-800">
              <th className="px-3 py-2 text-left">Symbol</th>
              <th className="px-3 py-2 text-left">Type</th>
              <th className="px-3 py-2 text-left">Side</th>
              <th className="px-3 py-2 text-left">Qty</th>
              <th className="px-3 py-2 text-left">Price</th>
              <th className="px-3 py-2 text-left">SL</th>
              <th className="px-3 py-2 text-left">TP</th>
              <th className="px-3 py-2 text-center">Cancel</th>
            </tr>
          </thead>
          <tbody className="text-sm">
            {orders.map((o) => (
              <tr key={o.id} className="border-t border-slate-800 hover:bg-slate-800/30 transition-colors">
                <td className="px-3 py-2 font-mono text-xs font-semibold">{o.symbol}</td>
                <td className="px-3 py-2 text-xs text-slate-400 capitalize">{o.order_type.replace('_', ' ')}</td>
                <td className="px-3 py-2">
                  <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${
                    o.side === 'buy' ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'
                  }`}>
                    {o.side.toUpperCase()}
                  </span>
                </td>
                <td className="px-3 py-2 text-xs font-mono">{o.quantity}</td>
                <td className="px-3 py-2 text-xs font-mono">{o.price?.toFixed(2) ?? '—'}</td>
                <td className="px-3 py-2 text-xs font-mono text-red-400">{o.stop_loss?.toFixed(2) ?? '—'}</td>
                <td className="px-3 py-2 text-xs font-mono text-green-400">{o.take_profit?.toFixed(2) ?? '—'}</td>
                <td className="px-3 py-2 text-center">
                  <button
                    onClick={() => handleCancel(o.id)}
                    disabled={cancelling === o.id}
                    className="p-1 text-red-400 hover:bg-red-500/10 rounded transition-colors disabled:opacity-50"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Signal overlay badge ──────────────────────────────────────────────────────

function SignalBadge({ symbol }: { symbol: string }) {
  const signals = useStore((s) => s.signals)
  const sig = signals.find((s) => s.symbol === symbol || s.symbol === symbol.replace('USD', '/USD'))
  if (!sig) return null

  return (
    <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium ${
      sig.direction === 'long'
        ? 'bg-green-500/10 border border-green-500/20 text-green-400'
        : sig.direction === 'short'
        ? 'bg-red-500/10 border border-red-500/20 text-red-400'
        : 'bg-slate-800 border border-slate-700 text-slate-400'
    }`}>
      <Brain className="w-3.5 h-3.5" />
      <span>ML: {sig.direction.toUpperCase()}</span>
      <span className="opacity-70">{(sig.confidence * 100).toFixed(0)}%</span>
      {sig.risk_reward > 0 && (
        <span className="opacity-70">R:R {sig.risk_reward.toFixed(1)}</span>
      )}
    </div>
  )
}

// ── Main chart ────────────────────────────────────────────────────────────────

interface MainChartProps {
  symbol: string
  timeframe: TF
}

function MainChart({ symbol, timeframe }: MainChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const emaSeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [barCount, setBarCount] = useState(0)

  const tick = useStore((s) => s.prices[symbol])
  const signals = useStore((s) => s.signals)
  const sig = signals.find((s) => s.symbol === symbol || s.symbol === symbol.replace('USD', '/USD'))

  const loadChart = useCallback(async () => {
    if (!candleSeriesRef.current) return
    setLoading(true)
    setError(null)
    try {
      const res = await tradingApi.ohlcv(symbol, timeframe, 300)
      const bars = Array.isArray(res.data) ? res.data : (res.data as any)?.data ?? []
      if (bars.length === 0) {
        setError('No OHLCV data available for this symbol/timeframe')
        setLoading(false)
        return
      }
      const candles: CandlestickData[] = bars.map((c: any) => ({
        time: (typeof c.timestamp === 'number'
          ? c.timestamp
          : new Date(c.timestamp).getTime() / 1000) as any,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      }))
      candleSeriesRef.current.setData(candles)
      setBarCount(candles.length)

      // EMA-20 overlay
      if (emaSeriesRef.current && candles.length >= 20) {
        const emaData: { time: any; value: number }[] = []
        let ema = candles[0].close
        const k = 2 / (20 + 1)
        for (const c of candles) {
          ema = c.close * k + ema * (1 - k)
          emaData.push({ time: c.time, value: ema })
        }
        emaSeriesRef.current.setData(emaData)
      }

      chartRef.current?.timeScale().fitContent()
    } catch (err: any) {
      setError(err?.response?.data?.detail?.message ?? err?.message ?? 'Failed to load chart data')
    } finally {
      setLoading(false)
    }
  }, [symbol, timeframe])

  useEffect(() => {
    if (!containerRef.current) return

    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: '#0f172a' },
        textColor: '#94a3b8',
      },
      grid: {
        vertLines: { color: '#1e293b' },
        horzLines: { color: '#1e293b' },
      },
      rightPriceScale: { borderColor: '#334155' },
      timeScale: { borderColor: '#334155', timeVisible: true, secondsVisible: false },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: '#f59e0b', labelBackgroundColor: '#f59e0b' },
        horzLine: { color: '#f59e0b', labelBackgroundColor: '#f59e0b' },
      },
    })

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderUpColor: '#22c55e',
      borderDownColor: '#ef4444',
      wickUpColor: '#22c55e',
      wickDownColor: '#ef4444',
    })

    const emaSeries = chart.addSeries(LineSeries, {
      color: '#f59e0b',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
    })

    chartRef.current = chart
    candleSeriesRef.current = candleSeries
    emaSeriesRef.current = emaSeries

    loadChart()

    const handleResize = () => {
      chart.applyOptions({ width: containerRef.current?.clientWidth })
    }
    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('resize', handleResize)
      chart.remove()
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Reload when symbol or timeframe changes
  useEffect(() => {
    loadChart()
  }, [loadChart])

  // Live tick updates
  useEffect(() => {
    if (tick && candleSeriesRef.current) {
      const candle: CandlestickData = {
        time: (Math.floor(tick.timestamp / 1000)) as any,
        open: tick.bid,
        high: Math.max(tick.bid, tick.ask),
        low: Math.min(tick.bid, tick.ask),
        close: tick.ask,
      }
      candleSeriesRef.current.update(candle)
    }
  }, [tick])

  return (
    <div className="relative">
      <div ref={containerRef} className="h-[480px]" />
      {loading && (
        <div className="absolute inset-0 flex items-center justify-center bg-slate-900/60">
          <RefreshCw className="w-5 h-5 text-amber-400 animate-spin" />
        </div>
      )}
      {error && !loading && (
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="flex items-center gap-2 text-red-400 text-sm bg-slate-900/80 px-4 py-2 rounded-lg">
            <AlertTriangle className="w-4 h-4" />
            {error}
          </div>
        </div>
      )}
      {!loading && !error && barCount > 0 && (
        <div className="absolute top-2 left-2 text-xs text-slate-600 pointer-events-none">
          {barCount} bars · EMA-20
        </div>
      )}
      {/* Signal price lines overlay */}
      {sig && sig.entry_price > 0 && (
        <div className="absolute top-2 right-2 flex flex-col gap-1 pointer-events-none">
          {sig.take_profit > 0 && (
            <div className="text-xs font-mono text-green-400 bg-green-500/10 px-2 py-0.5 rounded">
              TP {sig.take_profit.toFixed(2)}
            </div>
          )}
          {sig.entry_price > 0 && (
            <div className="text-xs font-mono text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded">
              Entry {sig.entry_price.toFixed(2)}
            </div>
          )}
          {sig.stop_loss > 0 && (
            <div className="text-xs font-mono text-red-400 bg-red-500/10 px-2 py-0.5 rounded">
              SL {sig.stop_loss.toFixed(2)}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Trading page ──────────────────────────────────────────────────────────────

export function Trading() {
  const activeSymbol = useStore((s) => s.activeSymbol)
  const activeTimeframe = useStore((s) => s.activeTimeframe) as TF
  const setActiveTimeframe = useStore((s) => s.setActiveTimeframe)
  const tick = useStore((s) => s.prices[activeSymbol])
  const account = useStore((s) => s.account)
  const positions = useStore((s) => s.positions)
  const [rightTab, setRightTab] = useState<'order' | 'dom' | 'book'>('order')
  const [showMTF, setShowMTF] = useState(false)

  // Derived risk metrics
  const dailyPnl = account?.daily_pnl ?? null
  const openRiskPct = account && account.equity > 0
    ? (account.margin_used / account.equity) * 100
    : null
  const marginLevel = account?.margin_level ?? null
  const totalUnrealizedPnl = positions.reduce((sum, p) => sum + p.unrealized_pnl, 0)

  return (
    <div className="space-y-4">
      {/* ── Top bar: symbol selector + price + timeframe ── */}
      <div className="flex flex-wrap items-center gap-3">
        <SymbolSelector />

        {/* Live price */}
        {tick ? (
          <div className="flex items-center gap-4 text-sm">
            <div className="flex items-center gap-2">
              <span className="text-slate-400 text-xs">Bid</span>
              <span className="font-mono font-bold text-slate-100">{tick.bid.toFixed(2)}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-slate-400 text-xs">Ask</span>
              <span className="font-mono font-bold text-slate-100">{tick.ask.toFixed(2)}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-slate-400 text-xs">Spread</span>
              <span className="font-mono text-amber-400">{(tick.ask - tick.bid).toFixed(3)}</span>
            </div>
            {tick.daily_high && tick.daily_low && (
              <>
                <div className="flex items-center gap-1 text-xs text-slate-500">
                  <TrendingUp className="w-3 h-3 text-green-400" />
                  {tick.daily_high.toFixed(2)}
                </div>
                <div className="flex items-center gap-1 text-xs text-slate-500">
                  <TrendingDown className="w-3 h-3 text-red-400" />
                  {tick.daily_low.toFixed(2)}
                </div>
              </>
            )}
            <span className={`text-xs font-medium ${tick.change_pct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              {tick.change_pct >= 0 ? '+' : ''}{tick.change_pct.toFixed(2)}%
            </span>
          </div>
        ) : (
          <span className="text-xs text-slate-600">Awaiting price feed…</span>
        )}

        {/* ML signal badge */}
        <SignalBadge symbol={activeSymbol} />

        {/* Timeframe selector */}
        <div className="ml-auto flex items-center gap-1 bg-slate-900 border border-slate-800 rounded-lg p-1">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              onClick={() => setActiveTimeframe(tf)}
              className={`px-2.5 py-1 text-xs rounded font-medium transition-colors ${
                activeTimeframe === tf
                  ? 'bg-amber-500/20 text-amber-400'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              {tf}
            </button>
          ))}
        </div>
      </div>

      {/* ── Main grid ── */}
      <div className="grid grid-cols-1 xl:grid-cols-4 gap-4">
        {/* Left: chart + orders */}
        <div className="xl:col-span-3 space-y-4">
          {/* Chart card */}
          <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
            <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-800">
              <div className="flex items-center gap-2">
                <BarChart2 className="w-4 h-4 text-amber-400" />
                <span className="font-semibold text-sm">{activeSymbol}</span>
                <span className="text-xs text-slate-500">{activeTimeframe.toUpperCase()}</span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setShowMTF((v) => !v)}
                  className={`text-xs px-2 py-1 rounded transition-colors ${
                    showMTF
                      ? 'bg-amber-500/20 text-amber-400'
                      : 'text-slate-500 hover:text-slate-300 hover:bg-slate-800'
                  }`}
                >
                  Multi-TF
                </button>
                <Zap className="w-3.5 h-3.5 text-slate-600" />
                <span className="text-xs text-slate-600">EMA-20</span>
              </div>
            </div>
            <MainChart symbol={activeSymbol} timeframe={activeTimeframe} />
          </div>

          {/* Multi-timeframe charts */}
          {showMTF && <MultiTimeframeChart symbol={activeSymbol} />}

          {/* Open positions */}
          <PositionTable compact symbol={activeSymbol} />

          {/* Pending orders */}
          <OpenOrdersTable />
        </div>

        {/* Right: order panel + depth + risk */}
        <div className="space-y-4">
          {/* Tab switcher */}
          <div className="flex gap-1 bg-slate-900 border border-slate-800 rounded-lg p-1">
            {(['order', 'dom', 'book'] as const).map((tab) => (
              <button
                key={tab}
                onClick={() => setRightTab(tab)}
                className={`flex-1 py-1.5 text-xs rounded font-medium transition-colors ${
                  rightTab === tab
                    ? 'bg-amber-500/20 text-amber-400'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                {tab === 'order' ? 'Order' : tab === 'dom' ? 'DOM' : 'Book'}
              </button>
            ))}
          </div>

          {rightTab === 'order' && <AdvancedOrderPanel symbol={activeSymbol} />}
          {rightTab === 'dom' && <DepthOfMarket symbol={activeSymbol} levels={16} />}
          {rightTab === 'book' && (
            <div className="bg-slate-900 rounded-xl border border-slate-800 p-4">
              <h3 className="text-sm font-semibold mb-3">Order Book</h3>
              <DepthOfMarket symbol={activeSymbol} levels={10} />
            </div>
          )}

          {/* Risk metrics */}
          <div className="bg-slate-900 rounded-xl border border-slate-800 p-4 space-y-3">
            <div className="flex items-center gap-2 mb-1">
              <Activity className="w-4 h-4 text-amber-400" />
              <h3 className="text-sm font-semibold">Risk Metrics</h3>
            </div>

            <div className="grid grid-cols-2 gap-3 text-xs">
              <div className="bg-slate-800 rounded-lg p-2.5">
                <div className="text-slate-500 mb-0.5">Balance</div>
                <div className="font-mono font-bold text-slate-100">
                  {account?.balance != null
                    ? `$${account.balance.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
                    : '—'}
                </div>
              </div>
              <div className="bg-slate-800 rounded-lg p-2.5">
                <div className="text-slate-500 mb-0.5">Equity</div>
                <div className="font-mono font-bold text-slate-100">
                  {account?.equity != null
                    ? `$${account.equity.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
                    : '—'}
                </div>
              </div>
              <div className="bg-slate-800 rounded-lg p-2.5">
                <div className="text-slate-500 mb-0.5">Daily P&amp;L</div>
                <div className={`font-mono font-bold ${
                  dailyPnl === null ? 'text-slate-600' :
                  dailyPnl >= 0 ? 'text-green-400' : 'text-red-400'
                }`}>
                  {dailyPnl !== null
                    ? `${dailyPnl >= 0 ? '+' : ''}$${dailyPnl.toFixed(2)}`
                    : '—'}
                </div>
              </div>
              <div className="bg-slate-800 rounded-lg p-2.5">
                <div className="text-slate-500 mb-0.5">Float P&amp;L</div>
                <div className={`font-mono font-bold ${
                  totalUnrealizedPnl >= 0 ? 'text-green-400' : 'text-red-400'
                }`}>
                  {positions.length > 0
                    ? `${totalUnrealizedPnl >= 0 ? '+' : ''}$${totalUnrealizedPnl.toFixed(2)}`
                    : '—'}
                </div>
              </div>
            </div>

            <div className="space-y-2.5 pt-1">
              <RiskBar
                label="Open Risk"
                value={openRiskPct}
                max={100}
                unit="%"
                color="amber"
                warnAt={50}
                dangerAt={80}
              />
              <RiskBar
                label="Daily Loss"
                value={dailyPnl !== null && account?.equity ? Math.abs(Math.min(dailyPnl, 0)) / account.equity * 100 : null}
                max={2}
                unit="%"
                color="red"
                warnAt={1}
                dangerAt={1.8}
              />
              <RiskBar
                label="Margin Level"
                value={marginLevel}
                max={1000}
                unit="%"
                color="green"
                warnAt={200}
                dangerAt={120}
              />
              <RiskBar
                label="Max Drawdown"
                value={account?.max_drawdown != null ? Math.abs(account.max_drawdown) : null}
                max={10}
                unit="%"
                color="purple"
                warnAt={5}
                dangerAt={8}
              />
            </div>

            {account === null && (
              <div className="flex items-center gap-2 text-xs text-slate-600 pt-1">
                <Clock className="w-3 h-3" />
                Awaiting account data from WebSocket…
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── All positions (full view) ── */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-semibold text-sm">All Open Positions</h3>
          <span className="text-xs text-slate-500">{positions.length} total</span>
        </div>
        <PositionTable compact />
      </div>
    </div>
  )
}
