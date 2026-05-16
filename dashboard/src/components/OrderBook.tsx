/**
 * OrderBook
 *
 * Live bid/ask depth ladder. Polls /api/trading/depth/{symbol} and
 * updates from WebSocket depth_update messages via the store.
 */
import { useEffect, useCallback, useRef } from 'react'
import { useStore } from '../store/useStore'
import { tradingApi } from '../hooks/useApi'
import type { DepthLevel } from '../store/useStore'

interface Props {
  symbol?: string
  levels?: number
}

export function OrderBook({ symbol: propSymbol, levels = 12 }: Props) {
  const activeSymbol = useStore((s) => s.activeSymbol)
  const symbol = propSymbol ?? activeSymbol
  const depth = useStore((s) => s.depth[symbol])
  const setDepth = useStore((s) => s.setDepth)
  const tick = useStore((s) => s.prices[symbol])
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchDepth = useCallback(async () => {
    try {
      const res = await tradingApi.depth(symbol, levels)
      setDepth(res.data)
    } catch {
      // non-fatal — depth is supplementary
    }
  }, [symbol, levels, setDepth])

  useEffect(() => {
    fetchDepth()
    // Poll every 2 s when no WS depth feed
    pollRef.current = setInterval(fetchDepth, 2_000)
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [fetchDepth])

  const bids = depth?.bids.slice(0, levels) ?? []
  const asks = depth?.asks.slice(0, levels) ?? []

  // Max size for bar width normalisation
  const maxBidSize = bids.reduce((m, b) => Math.max(m, b.size), 0.001)
  const maxAskSize = asks.reduce((m, a) => Math.max(m, a.size), 0.001)

  const formatPrice = (p: number) => {
    if (p >= 1000) return p.toFixed(2)
    if (p >= 10)   return p.toFixed(3)
    return p.toFixed(5)
  }

  const formatSize = (s: number) => {
    if (s >= 1000) return `${(s / 1000).toFixed(1)}K`
    return s.toFixed(2)
  }

  return (
    <div className="bg-slate-900 rounded-lg border border-slate-800 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
        <h3 className="text-sm font-semibold text-slate-200">Order Book</h3>
        {tick && (
          <div className="text-xs text-slate-400">
            Spread:{' '}
            <span className="text-amber-400 font-mono">
              {depth ? depth.spread.toFixed(tick.spread < 0.01 ? 5 : 2) : (tick.ask - tick.bid).toFixed(3)}
            </span>
          </div>
        )}
      </div>

      {/* Column headers */}
      <div className="grid grid-cols-3 px-4 py-1.5 text-xs text-slate-500 border-b border-slate-800">
        <span>Size</span>
        <span className="text-center">Price</span>
        <span className="text-right">Size</span>
      </div>

      {/* Depth rows */}
      <div className="divide-y divide-slate-800/50">
        {Array.from({ length: Math.max(bids.length, asks.length, levels) }, (_, i) => {
          const bid: DepthLevel | undefined = bids[i]
          const ask: DepthLevel | undefined = asks[i]
          return (
            <div key={i} className="grid grid-cols-3 items-center px-2 py-0.5 relative hover:bg-slate-800/30 transition-colors">
              {/* Bid side */}
              <div className="relative flex items-center">
                {bid && (
                  <>
                    <div
                      className="absolute inset-y-0 right-0 bg-green-500/10 rounded-sm"
                      style={{ width: `${(bid.size / maxBidSize) * 100}%` }}
                    />
                    <span className="relative text-xs font-mono text-green-400 z-10">
                      {formatSize(bid.size)}
                    </span>
                  </>
                )}
              </div>

              {/* Price column */}
              <div className="text-center">
                {bid && (
                  <span className="text-xs font-mono text-green-300 block">
                    {formatPrice(bid.price)}
                  </span>
                )}
                {ask && (
                  <span className="text-xs font-mono text-red-300 block">
                    {formatPrice(ask.price)}
                  </span>
                )}
              </div>

              {/* Ask side */}
              <div className="relative flex items-center justify-end">
                {ask && (
                  <>
                    <div
                      className="absolute inset-y-0 left-0 bg-red-500/10 rounded-sm"
                      style={{ width: `${(ask.size / maxAskSize) * 100}%` }}
                    />
                    <span className="relative text-xs font-mono text-red-400 z-10">
                      {formatSize(ask.size)}
                    </span>
                  </>
                )}
              </div>
            </div>
          )
        })}
      </div>

      {/* Mid price */}
      {tick && (
        <div className="px-4 py-2 border-t border-slate-800 flex items-center justify-between">
          <span className="text-xs text-slate-500">Mid</span>
          <span className="text-sm font-mono font-bold text-amber-400">
            {formatPrice(tick.mid)}
          </span>
          <span className={`text-xs font-mono ${tick.change_pct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            {tick.change_pct >= 0 ? '+' : ''}{tick.change_pct.toFixed(2)}%
          </span>
        </div>
      )}

      {!depth && !tick && (
        <div className="py-6 text-center text-slate-600 text-xs">
          Awaiting market data…
        </div>
      )}
    </div>
  )
}
