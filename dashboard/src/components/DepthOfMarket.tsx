/**
 * DepthOfMarket (DOM)
 *
 * Vertical price ladder showing bid/ask depth with cumulative volume bars,
 * current price highlight, and one-click order entry at any price level.
 */
import { useEffect, useCallback, useRef, useState } from 'react'
import { useStore } from '../store/useStore'
import { tradingApi } from '../hooks/useApi'
import type { DepthLevel } from '../store/useStore'

interface Props {
  symbol?: string
  levels?: number
  onOrderAtPrice?: (price: number, side: 'buy' | 'sell') => void
}

export function DepthOfMarket({ symbol: propSymbol, levels = 16, onOrderAtPrice }: Props) {
  const activeSymbol = useStore((s) => s.activeSymbol)
  const symbol = propSymbol ?? activeSymbol
  const depth = useStore((s) => s.depth[symbol])
  const setDepth = useStore((s) => s.setDepth)
  const tick = useStore((s) => s.prices[symbol])
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [hoveredPrice, setHoveredPrice] = useState<number | null>(null)

  const fetchDepth = useCallback(async () => {
    try {
      const res = await tradingApi.depth(symbol, levels)
      setDepth(res.data)
    } catch {
      // non-fatal
    }
  }, [symbol, levels, setDepth])

  useEffect(() => {
    fetchDepth()
    pollRef.current = setInterval(fetchDepth, 1_500)
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [fetchDepth])

  const bids: DepthLevel[] = depth?.bids.slice(0, levels) ?? []
  const asks: DepthLevel[] = depth?.asks.slice(0, levels) ?? []

  // Reverse asks so highest ask is at top, lowest ask meets bids at mid
  const asksReversed = [...asks].reverse()

  const maxTotal = Math.max(
    bids[bids.length - 1]?.total ?? 0,
    asks[asks.length - 1]?.total ?? 0,
    0.001,
  )

  const formatPrice = (p: number) => {
    if (p >= 10000) return p.toFixed(1)
    if (p >= 100)   return p.toFixed(2)
    if (p >= 1)     return p.toFixed(3)
    return p.toFixed(5)
  }

  const formatSize = (s: number) => {
    if (s >= 1000) return `${(s / 1000).toFixed(1)}K`
    return s.toFixed(2)
  }

  const midPrice = tick?.mid ?? 0

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden select-none">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
        <h3 className="text-sm font-semibold text-slate-200">Depth of Market</h3>
        <div className="flex items-center gap-3 text-xs text-slate-500">
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-sm bg-green-500/40 inline-block" />
            Bid
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-sm bg-red-500/40 inline-block" />
            Ask
          </span>
        </div>
      </div>

      {/* Column headers */}
      <div className="grid grid-cols-4 px-3 py-1.5 text-xs text-slate-600 border-b border-slate-800/50">
        <span>Total</span>
        <span>Size</span>
        <span className="text-center">Price</span>
        <span className="text-right">Size</span>
      </div>

      {/* Ask side (reversed — highest at top) */}
      <div>
        {asksReversed.map((ask, i) => {
          const barPct = (ask.total ?? 0) / maxTotal * 100
          const isHovered = hoveredPrice === ask.price
          return (
            <div
              key={`ask-${i}`}
              className={`relative grid grid-cols-4 items-center px-3 py-0.5 cursor-pointer transition-colors
                ${isHovered ? 'bg-red-500/10' : 'hover:bg-red-500/5'}`}
              onMouseEnter={() => setHoveredPrice(ask.price)}
              onMouseLeave={() => setHoveredPrice(null)}
              onClick={() => onOrderAtPrice?.(ask.price, 'buy')}
            >
              {/* Volume bar (fills from right) */}
              <div
                className="absolute inset-y-0 right-0 bg-red-500/8 pointer-events-none"
                style={{ width: `${barPct}%` }}
              />
              <span className="relative text-xs font-mono text-slate-600 z-10">
                {formatSize(ask.total ?? 0)}
              </span>
              <span className="relative text-xs font-mono text-slate-500 z-10" />
              <span className="relative text-xs font-mono text-red-300 text-center z-10">
                {formatPrice(ask.price)}
              </span>
              <span className="relative text-xs font-mono text-red-400 text-right z-10">
                {formatSize(ask.size)}
              </span>
            </div>
          )
        })}
      </div>

      {/* Mid price separator */}
      {midPrice > 0 && (
        <div className="flex items-center gap-2 px-3 py-1.5 bg-slate-800/60 border-y border-amber-500/20">
          <div className="flex-1 h-px bg-amber-500/20" />
          <span className="text-sm font-mono font-bold text-amber-400 shrink-0">
            {formatPrice(midPrice)}
          </span>
          {tick && (
            <span className={`text-xs font-mono shrink-0 ${tick.change_pct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              {tick.change_pct >= 0 ? '+' : ''}{tick.change_pct.toFixed(2)}%
            </span>
          )}
          <div className="flex-1 h-px bg-amber-500/20" />
        </div>
      )}

      {/* Bid side */}
      <div>
        {bids.map((bid, i) => {
          const barPct = (bid.total ?? 0) / maxTotal * 100
          const isHovered = hoveredPrice === bid.price
          return (
            <div
              key={`bid-${i}`}
              className={`relative grid grid-cols-4 items-center px-3 py-0.5 cursor-pointer transition-colors
                ${isHovered ? 'bg-green-500/10' : 'hover:bg-green-500/5'}`}
              onMouseEnter={() => setHoveredPrice(bid.price)}
              onMouseLeave={() => setHoveredPrice(null)}
              onClick={() => onOrderAtPrice?.(bid.price, 'sell')}
            >
              {/* Volume bar (fills from left) */}
              <div
                className="absolute inset-y-0 left-0 bg-green-500/8 pointer-events-none"
                style={{ width: `${barPct}%` }}
              />
              <span className="relative text-xs font-mono text-slate-600 z-10">
                {formatSize(bid.total ?? 0)}
              </span>
              <span className="relative text-xs font-mono text-green-400 z-10">
                {formatSize(bid.size)}
              </span>
              <span className="relative text-xs font-mono text-green-300 text-center z-10">
                {formatPrice(bid.price)}
              </span>
              <span className="relative text-xs font-mono text-slate-500 text-right z-10" />
            </div>
          )
        })}
      </div>

      {/* Spread footer */}
      {depth && (
        <div className="px-4 py-2 border-t border-slate-800 flex items-center justify-between text-xs text-slate-500">
          <span>Spread</span>
          <span className="font-mono text-amber-400">{depth.spread.toFixed(5)}</span>
          <span className="text-slate-600">
            {new Date(depth.timestamp * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
          </span>
        </div>
      )}

      {!depth && !tick && (
        <div className="py-8 text-center text-slate-600 text-xs">
          Awaiting market data…
        </div>
      )}
    </div>
  )
}
