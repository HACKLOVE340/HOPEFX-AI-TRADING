/**
 * PositionTable
 *
 * Renders open positions. Uses PositionCard in compact (table-row) mode
 * for the trading page, and full card mode for the positions page.
 */
import { useEffect, useCallback } from 'react'
import { useStore } from '../store/useStore'
import { tradingApi } from '../hooks/useApi'
import { PositionCard } from './PositionCard'

interface Props {
  compact?: boolean
  symbol?: string  // filter to a single symbol when set
}

export function PositionTable({ compact = true, symbol }: Props) {
  const positions = useStore((s) => s.positions)
  const setPositions = useStore((s) => s.setPositions)

  const load = useCallback(async () => {
    try {
      const res = await tradingApi.positions()
      const raw = Array.isArray(res.data) ? res.data : []
      // Map API PositionResponse → store Position shape
      setPositions(
        raw.map((p: any) => ({
          id: p.id,
          symbol: p.symbol,
          side: p.side === 'buy' || p.side === 'long' ? 'long' : 'short',
          size: p.size ?? p.quantity ?? 0,
          entry_price: p.entry_price ?? 0,
          current_price: p.current_price ?? p.entry_price ?? 0,
          unrealized_pnl: p.unrealized_pnl ?? 0,
          realized_pnl: p.realized_pnl ?? 0,
          stop_loss: p.stop_loss ?? null,
          take_profit: p.take_profit ?? null,
          margin_used: p.margin_used ?? null,
          leverage: p.leverage ?? null,
          opened_at: p.opened_at ?? new Date().toISOString(),
          swap: p.swap ?? null,
          commission: p.commission ?? null,
        })),
      )
    } catch {
      // non-fatal — positions come from WS too
    }
  }, [setPositions])

  useEffect(() => {
    load()
    const id = setInterval(load, 10_000)
    return () => clearInterval(id)
  }, [load])

  const filtered = symbol
    ? positions.filter((p) => p.symbol === symbol)
    : positions

  if (filtered.length === 0) {
    return (
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-8 text-center">
        <p className="text-slate-400 text-sm">No open positions</p>
        <p className="text-xs text-slate-600 mt-1">Place an order to see positions here</p>
      </div>
    )
  }

  if (compact) {
    return (
      <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
          <h3 className="font-semibold text-sm">Open Positions</h3>
          <span className="text-xs text-slate-500">{filtered.length} position{filtered.length !== 1 ? 's' : ''}</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="text-left text-xs text-slate-500 border-b border-slate-800">
                <th className="px-3 py-2">Symbol</th>
                <th className="px-3 py-2">Side</th>
                <th className="px-3 py-2">Qty</th>
                <th className="px-3 py-2">Entry</th>
                <th className="px-3 py-2">Current</th>
                <th className="px-3 py-2 text-right">P&amp;L</th>
                <th className="px-3 py-2 text-center">Action</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((pos) => (
                <PositionCard key={pos.id} position={pos} compact />
              ))}
            </tbody>
          </table>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {filtered.map((pos) => (
        <PositionCard key={pos.id} position={pos} compact={false} />
      ))}
    </div>
  )
}
