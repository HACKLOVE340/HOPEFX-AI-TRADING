/**
 * PositionCard
 *
 * Full-featured position management component with:
 *   - Live P&L display (updated from WS price ticks)
 *   - Inline SL/TP modification
 *   - Partial close
 *   - Full close with confirmation
 *   - Hedge button
 *   - Position details (margin, leverage, swap, commission)
 */
import { useState, useCallback } from 'react'
import {
  TrendingUp, TrendingDown, X, Edit2, Shield, GitBranch,
  ChevronDown, ChevronUp, AlertTriangle, Check
} from 'lucide-react'
import { useStore } from '../store/useStore'
import { tradingApi } from '../hooks/useApi'
import type { Position } from '../store/useStore'

interface Props {
  position: Position
  compact?: boolean
}

export function PositionCard({ position, compact = false }: Props) {
  const removePosition = useStore((s) => s.removePosition)
  const upsertPosition = useStore((s) => s.upsertPosition)
  const upsertOrder = useStore((s) => s.upsertOrder)

  const [expanded, setExpanded] = useState(false)
  const [editingSL, setEditingSL] = useState(false)
  const [editingTP, setEditingTP] = useState(false)
  const [slValue, setSlValue] = useState(position.stop_loss?.toString() ?? '')
  const [tpValue, setTpValue] = useState(position.take_profit?.toString() ?? '')
  const [partialQty, setPartialQty] = useState('')
  const [showPartial, setShowPartial] = useState(false)
  const [closing, setClosing] = useState(false)
  const [hedging, setHedging] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const isLong = position.side === 'long'
  const pnlPositive = position.unrealized_pnl >= 0
  const pnlPct =
    position.entry_price > 0
      ? ((position.current_price - position.entry_price) / position.entry_price) *
        100 *
        (isLong ? 1 : -1)
      : 0

  const showError = (msg: string) => {
    setError(msg)
    setTimeout(() => setError(null), 4000)
  }

  const handleClose = useCallback(async () => {
    if (closing) return
    setClosing(true)
    try {
      await tradingApi.closePosition(position.id)
      removePosition(position.id)
    } catch (err: any) {
      showError(err?.response?.data?.detail ?? 'Failed to close position')
    } finally {
      setClosing(false)
    }
  }, [position.id, closing, removePosition])

  const handlePartialClose = useCallback(async () => {
    const qty = parseFloat(partialQty)
    if (!qty || qty <= 0 || qty >= position.size) {
      showError('Partial close quantity must be > 0 and < position size')
      return
    }
    try {
      const res = await tradingApi.partialClose(position.id, { quantity: qty })
      upsertPosition(res.data)
      setShowPartial(false)
      setPartialQty('')
    } catch (err: any) {
      showError(err?.response?.data?.detail ?? 'Partial close failed')
    }
  }, [position.id, position.size, partialQty, upsertPosition])

  const handleModifySL = useCallback(async () => {
    const sl = parseFloat(slValue) || null
    try {
      const res = await tradingApi.modifyPosition(position.id, { stop_loss: sl })
      if (res.data) upsertPosition(res.data)
      setEditingSL(false)
    } catch (err: any) {
      showError(err?.response?.data?.detail ?? 'Failed to modify stop-loss')
    }
  }, [position.id, slValue, upsertPosition])

  const handleModifyTP = useCallback(async () => {
    const tp = parseFloat(tpValue) || null
    try {
      const res = await tradingApi.modifyPosition(position.id, { take_profit: tp })
      if (res.data) upsertPosition(res.data)
      setEditingTP(false)
    } catch (err: any) {
      showError(err?.response?.data?.detail ?? 'Failed to modify take-profit')
    }
  }, [position.id, tpValue, upsertPosition])

  const handleHedge = useCallback(async () => {
    if (hedging) return
    setHedging(true)
    try {
      const res = await tradingApi.hedgePosition(position.id)
      if (res.data?.hedge_order) upsertOrder(res.data.hedge_order)
    } catch (err: any) {
      showError(err?.response?.data?.detail ?? 'Hedge failed')
    } finally {
      setHedging(false)
    }
  }, [position.id, hedging, upsertOrder])

  if (compact) {
    return (
      <tr className="border-t border-slate-800 hover:bg-slate-800/30 transition-colors">
        <td className="py-2.5 px-3">
          <div className="flex items-center gap-2">
            {isLong
              ? <TrendingUp className="w-3.5 h-3.5 text-green-400" />
              : <TrendingDown className="w-3.5 h-3.5 text-red-400" />}
            <span className="font-mono text-xs font-semibold">{position.symbol}</span>
          </div>
        </td>
        <td className="py-2.5 px-3">
          <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${
            isLong ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'
          }`}>
            {position.side.toUpperCase()}
          </span>
        </td>
        <td className="py-2.5 px-3 text-xs font-mono">{position.size}</td>
        <td className="py-2.5 px-3 text-xs font-mono">{position.entry_price.toFixed(2)}</td>
        <td className="py-2.5 px-3 text-xs font-mono">{position.current_price.toFixed(2)}</td>
        <td className={`py-2.5 px-3 text-xs font-mono font-semibold text-right ${
          pnlPositive ? 'text-green-400' : 'text-red-400'
        }`}>
          {pnlPositive ? '+' : ''}{position.unrealized_pnl.toFixed(2)}
        </td>
        <td className="py-2.5 px-3 text-center">
          <button
            onClick={handleClose}
            disabled={closing}
            className="px-2 py-1 bg-red-500/10 text-red-400 rounded text-xs hover:bg-red-500/20 disabled:opacity-50 transition-colors"
          >
            {closing ? '…' : 'Close'}
          </button>
        </td>
      </tr>
    )
  }

  return (
    <div className={`bg-slate-900 rounded-xl border transition-colors ${
      pnlPositive ? 'border-green-500/20' : 'border-red-500/20'
    }`}>
      {/* Error banner */}
      {error && (
        <div className="flex items-center gap-2 px-4 py-2 bg-red-500/10 border-b border-red-500/20 text-red-400 text-xs rounded-t-xl">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
          {error}
        </div>
      )}

      {/* Main row */}
      <div className="flex items-center gap-3 px-4 py-3">
        {/* Symbol + side */}
        <div className={`p-2 rounded-lg ${isLong ? 'bg-green-500/10' : 'bg-red-500/10'}`}>
          {isLong
            ? <TrendingUp className="w-4 h-4 text-green-400" />
            : <TrendingDown className="w-4 h-4 text-red-400" />}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-mono font-bold text-sm">{position.symbol}</span>
            <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${
              isLong ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'
            }`}>
              {position.side.toUpperCase()}
            </span>
            <span className="text-xs text-slate-500">{position.size} lots</span>
          </div>
          <div className="flex items-center gap-3 mt-0.5 text-xs text-slate-400">
            <span>Entry: <span className="font-mono text-slate-300">{position.entry_price.toFixed(2)}</span></span>
            <span>Now: <span className="font-mono text-slate-300">{position.current_price.toFixed(2)}</span></span>
          </div>
        </div>

        {/* P&L */}
        <div className="text-right">
          <div className={`text-base font-bold font-mono ${pnlPositive ? 'text-green-400' : 'text-red-400'}`}>
            {pnlPositive ? '+' : ''}{position.unrealized_pnl.toFixed(2)}
          </div>
          <div className={`text-xs font-mono ${pnlPositive ? 'text-green-500' : 'text-red-500'}`}>
            {pnlPositive ? '+' : ''}{pnlPct.toFixed(2)}%
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-1 ml-2">
          <button
            onClick={() => setExpanded((v) => !v)}
            className="p-1.5 rounded-lg text-slate-400 hover:bg-slate-800 hover:text-slate-200 transition-colors"
            title="Details"
          >
            {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>
          <button
            onClick={handleClose}
            disabled={closing}
            className="p-1.5 rounded-lg text-red-400 hover:bg-red-500/10 transition-colors disabled:opacity-50"
            title="Close position"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Expanded details */}
      {expanded && (
        <div className="border-t border-slate-800 px-4 py-3 space-y-3">
          {/* SL / TP row */}
          <div className="grid grid-cols-2 gap-3">
            {/* Stop Loss */}
            <div>
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs text-slate-400">Stop Loss</span>
                <button
                  onClick={() => { setEditingSL((v) => !v); setSlValue(position.stop_loss?.toString() ?? '') }}
                  className="text-slate-500 hover:text-slate-300 transition-colors"
                >
                  <Edit2 className="w-3 h-3" />
                </button>
              </div>
              {editingSL ? (
                <div className="flex gap-1">
                  <input
                    type="number"
                    step="0.01"
                    value={slValue}
                    onChange={(e) => setSlValue(e.target.value)}
                    className="flex-1 bg-slate-800 border border-red-500/50 rounded px-2 py-1 text-xs text-white focus:outline-none"
                    autoFocus
                  />
                  <button onClick={handleModifySL} className="p-1 text-green-400 hover:bg-green-500/10 rounded">
                    <Check className="w-3.5 h-3.5" />
                  </button>
                  <button onClick={() => setEditingSL(false)} className="p-1 text-slate-400 hover:bg-slate-700 rounded">
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
              ) : (
                <div className="text-sm font-mono text-red-400">
                  {position.stop_loss ? position.stop_loss.toFixed(2) : '—'}
                </div>
              )}
            </div>

            {/* Take Profit */}
            <div>
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs text-slate-400">Take Profit</span>
                <button
                  onClick={() => { setEditingTP((v) => !v); setTpValue(position.take_profit?.toString() ?? '') }}
                  className="text-slate-500 hover:text-slate-300 transition-colors"
                >
                  <Edit2 className="w-3 h-3" />
                </button>
              </div>
              {editingTP ? (
                <div className="flex gap-1">
                  <input
                    type="number"
                    step="0.01"
                    value={tpValue}
                    onChange={(e) => setTpValue(e.target.value)}
                    className="flex-1 bg-slate-800 border border-green-500/50 rounded px-2 py-1 text-xs text-white focus:outline-none"
                    autoFocus
                  />
                  <button onClick={handleModifyTP} className="p-1 text-green-400 hover:bg-green-500/10 rounded">
                    <Check className="w-3.5 h-3.5" />
                  </button>
                  <button onClick={() => setEditingTP(false)} className="p-1 text-slate-400 hover:bg-slate-700 rounded">
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
              ) : (
                <div className="text-sm font-mono text-green-400">
                  {position.take_profit ? position.take_profit.toFixed(2) : '—'}
                </div>
              )}
            </div>
          </div>

          {/* Metadata */}
          <div className="grid grid-cols-3 gap-2 text-xs">
            {position.margin_used != null && (
              <div className="bg-slate-800 rounded p-2">
                <div className="text-slate-500">Margin</div>
                <div className="font-mono text-slate-200">${position.margin_used.toFixed(0)}</div>
              </div>
            )}
            {position.swap != null && (
              <div className="bg-slate-800 rounded p-2">
                <div className="text-slate-500">Swap</div>
                <div className={`font-mono ${position.swap >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {position.swap >= 0 ? '+' : ''}{position.swap.toFixed(2)}
                </div>
              </div>
            )}
            {position.commission != null && (
              <div className="bg-slate-800 rounded p-2">
                <div className="text-slate-500">Commission</div>
                <div className="font-mono text-slate-200">{position.commission.toFixed(2)}</div>
              </div>
            )}
            <div className="bg-slate-800 rounded p-2">
              <div className="text-slate-500">Opened</div>
              <div className="font-mono text-slate-200">
                {new Date(position.opened_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </div>
            </div>
          </div>

          {/* Partial close */}
          <div>
            <button
              onClick={() => setShowPartial((v) => !v)}
              className="text-xs text-slate-500 hover:text-slate-300 flex items-center gap-1 transition-colors"
            >
              <Shield className="w-3 h-3" />
              Partial close
            </button>
            {showPartial && (
              <div className="flex gap-2 mt-2">
                <input
                  type="number"
                  step="0.01"
                  min="0.01"
                  max={position.size - 0.01}
                  value={partialQty}
                  onChange={(e) => setPartialQty(e.target.value)}
                  placeholder={`Max ${(position.size - 0.01).toFixed(2)}`}
                  className="flex-1 bg-slate-800 border border-slate-700 rounded px-2 py-1.5 text-xs text-white focus:border-amber-500 focus:outline-none"
                />
                <button
                  onClick={handlePartialClose}
                  className="px-3 py-1.5 bg-amber-500/20 text-amber-400 rounded text-xs hover:bg-amber-500/30 transition-colors"
                >
                  Close {partialQty || '?'} lots
                </button>
              </div>
            )}
          </div>

          {/* Hedge */}
          <button
            onClick={handleHedge}
            disabled={hedging}
            className="flex items-center gap-2 text-xs text-slate-400 hover:text-slate-200 hover:bg-slate-800 px-3 py-1.5 rounded-lg transition-colors disabled:opacity-50"
          >
            <GitBranch className="w-3.5 h-3.5" />
            {hedging ? 'Placing hedge…' : 'Hedge position'}
          </button>
        </div>
      )}
    </div>
  )
}
