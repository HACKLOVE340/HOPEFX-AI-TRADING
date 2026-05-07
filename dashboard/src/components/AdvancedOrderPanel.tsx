/**
 * AdvancedOrderPanel
 *
 * Full-featured order entry panel supporting:
 *   - Market, Limit, Stop, Stop-Limit, Trailing Stop order types
 *   - Lot size with risk-based auto-sizing
 *   - Stop-loss / take-profit with pip distance display
 *   - Risk/reward ratio preview
 *   - Margin required calculation
 *   - One-click order submission with confirmation toast
 */
import { useState, useCallback, useMemo } from 'react'
import { AlertTriangle, TrendingUp, TrendingDown, Calculator, ChevronDown, ChevronUp } from 'lucide-react'
import { useStore } from '../store/useStore'
import { tradingApi } from '../hooks/useApi'
import type { PlaceOrderPayload } from '../hooks/useApi'

type OrderType = 'market' | 'limit' | 'stop' | 'stop_limit' | 'trailing_stop'
type Side = 'buy' | 'sell'

interface Toast {
  type: 'success' | 'error'
  message: string
}

interface Props {
  symbol?: string
}

export function AdvancedOrderPanel({ symbol: propSymbol }: Props) {
  const activeSymbol = useStore((s) => s.activeSymbol)
  const symbol = propSymbol ?? activeSymbol
  const tick = useStore((s) => s.prices[symbol])
  const account = useStore((s) => s.account)
  const upsertOrder = useStore((s) => s.upsertOrder)

  const [side, setSide] = useState<Side>('buy')
  const [orderType, setOrderType] = useState<OrderType>('market')
  const [size, setSize] = useState('0.01')
  const [limitPrice, setLimitPrice] = useState('')
  const [stopPrice, setStopPrice] = useState('')
  const [stopLoss, setStopLoss] = useState('')
  const [takeProfit, setTakeProfit] = useState('')
  const [trailingDist, setTrailingDist] = useState('')
  const [riskPct, setRiskPct] = useState('1.0')
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [toast, setToast] = useState<Toast | null>(null)

  const currentPrice = side === 'buy' ? (tick?.ask ?? 0) : (tick?.bid ?? 0)
  const sizeNum = parseFloat(size) || 0
  const slNum = parseFloat(stopLoss) || 0
  const tpNum = parseFloat(takeProfit) || 0
  const limitNum = parseFloat(limitPrice) || 0

  // Pip distance helpers
  const pipSize = symbol.includes('JPY') ? 0.01 : symbol.startsWith('XAU') ? 0.01 : 0.0001
  const slPips = slNum > 0 && currentPrice > 0
    ? Math.abs(currentPrice - slNum) / pipSize
    : null
  const tpPips = tpNum > 0 && currentPrice > 0
    ? Math.abs(tpNum - currentPrice) / pipSize
    : null
  const riskReward = slPips && tpPips && slPips > 0 ? tpPips / slPips : null

  // Margin required (simplified: price × size / leverage)
  const leverage = account?.leverage ?? 30
  const marginRequired = currentPrice > 0 && sizeNum > 0
    ? (currentPrice * sizeNum * 100000) / leverage
    : null

  // Auto-size from risk %
  const autoSize = useCallback(() => {
    if (!account || !slNum || !currentPrice) return
    const riskAmount = account.equity * (parseFloat(riskPct) / 100)
    const slDistance = Math.abs(currentPrice - slNum)
    if (slDistance <= 0) return
    const lots = riskAmount / (slDistance * 100000)
    setSize(Math.max(0.01, Math.round(lots * 100) / 100).toFixed(2))
  }, [account, slNum, currentPrice, riskPct])

  const showToast = (t: Toast) => {
    setToast(t)
    setTimeout(() => setToast(null), 4000)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (submitting) return
    setSubmitting(true)

    const payload: PlaceOrderPayload = {
      symbol,
      side,
      order_type: orderType,
      quantity: sizeNum,
      price: limitNum > 0 ? limitNum : null,
      stop_price: parseFloat(stopPrice) > 0 ? parseFloat(stopPrice) : null,
      stop_loss: slNum > 0 ? slNum : null,
      take_profit: tpNum > 0 ? tpNum : null,
      trailing_distance: parseFloat(trailingDist) > 0 ? parseFloat(trailingDist) : null,
    }

    try {
      const res = await tradingApi.placeOrder(payload)
      const fill = res.data
      upsertOrder({
        id: fill.order_id,
        symbol,
        side,
        order_type: orderType,
        quantity: sizeNum,
        status: fill.status === 'filled' ? 'filled' : 'open',
        created_at: fill.timestamp,
        fill_price: fill.fill_price,
        commission: fill.commission,
      })
      showToast({
        type: 'success',
        message: `${side.toUpperCase()} ${sizeNum} ${symbol} @ ${fill.fill_price?.toFixed(2) ?? 'market'}`,
      })
      // Reset form
      setStopLoss('')
      setTakeProfit('')
      setLimitPrice('')
      setStopPrice('')
      setTrailingDist('')
    } catch (err: any) {
      const detail = err?.response?.data?.detail ?? err?.message ?? 'Order rejected'
      showToast({ type: 'error', message: typeof detail === 'string' ? detail : JSON.stringify(detail) })
    } finally {
      setSubmitting(false)
    }
  }

  const needsLimitPrice = orderType === 'limit' || orderType === 'stop_limit'
  const needsStopPrice = orderType === 'stop' || orderType === 'stop_limit'
  const needsTrailing = orderType === 'trailing_stop'

  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
      {/* Toast */}
      {toast && (
        <div
          className={`px-4 py-2.5 text-sm font-medium flex items-center gap-2 ${
            toast.type === 'success'
              ? 'bg-green-500/10 text-green-400 border-b border-green-500/20'
              : 'bg-red-500/10 text-red-400 border-b border-red-500/20'
          }`}
        >
          {toast.type === 'error' && <AlertTriangle className="w-4 h-4 shrink-0" />}
          <span className="truncate">{toast.message}</span>
        </div>
      )}

      {/* Buy / Sell toggle */}
      <div className="grid grid-cols-2">
        <button
          type="button"
          onClick={() => setSide('buy')}
          className={`py-3 font-bold text-sm flex items-center justify-center gap-2 transition-colors ${
            side === 'buy'
              ? 'bg-green-600 text-white'
              : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
          }`}
        >
          <TrendingUp className="w-4 h-4" />
          BUY / LONG
        </button>
        <button
          type="button"
          onClick={() => setSide('sell')}
          className={`py-3 font-bold text-sm flex items-center justify-center gap-2 transition-colors ${
            side === 'sell'
              ? 'bg-red-600 text-white'
              : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
          }`}
        >
          <TrendingDown className="w-4 h-4" />
          SELL / SHORT
        </button>
      </div>

      <form onSubmit={handleSubmit} className="p-4 space-y-4">
        {/* Order type */}
        <div>
          <label className="block text-xs text-slate-400 mb-1.5">Order Type</label>
          <div className="grid grid-cols-3 gap-1">
            {(['market', 'limit', 'stop'] as OrderType[]).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setOrderType(t)}
                className={`py-1.5 text-xs rounded font-medium transition-colors ${
                  orderType === t
                    ? 'bg-amber-500/20 text-amber-400 border border-amber-500/30'
                    : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
                }`}
              >
                {t.charAt(0).toUpperCase() + t.slice(1)}
              </button>
            ))}
            {(['stop_limit', 'trailing_stop'] as OrderType[]).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setOrderType(t)}
                className={`py-1.5 text-xs rounded font-medium transition-colors ${
                  orderType === t
                    ? 'bg-amber-500/20 text-amber-400 border border-amber-500/30'
                    : 'bg-slate-800 text-slate-400 hover:bg-slate-700'
                }`}
              >
                {t === 'stop_limit' ? 'Stop-Limit' : 'Trailing'}
              </button>
            ))}
          </div>
        </div>

        {/* Lot size */}
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <label className="text-xs text-slate-400">Lot Size</label>
            <div className="flex gap-1">
              {['0.01', '0.05', '0.10', '0.50', '1.00'].map((v) => (
                <button
                  key={v}
                  type="button"
                  onClick={() => setSize(v)}
                  className={`px-1.5 py-0.5 text-xs rounded transition-colors ${
                    size === v
                      ? 'bg-amber-500/20 text-amber-400'
                      : 'bg-slate-800 text-slate-500 hover:text-slate-300'
                  }`}
                >
                  {v}
                </button>
              ))}
            </div>
          </div>
          <input
            type="number"
            step="0.01"
            min="0.01"
            max="100"
            value={size}
            onChange={(e) => setSize(e.target.value)}
            className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:border-amber-500 focus:outline-none"
          />
        </div>

        {/* Limit price */}
        {needsLimitPrice && (
          <div>
            <label className="block text-xs text-slate-400 mb-1.5">Limit Price</label>
            <input
              type="number"
              step="0.00001"
              value={limitPrice}
              onChange={(e) => setLimitPrice(e.target.value)}
              placeholder={currentPrice > 0 ? currentPrice.toFixed(2) : ''}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:border-amber-500 focus:outline-none"
            />
          </div>
        )}

        {/* Stop trigger price */}
        {needsStopPrice && (
          <div>
            <label className="block text-xs text-slate-400 mb-1.5">Stop Trigger Price</label>
            <input
              type="number"
              step="0.00001"
              value={stopPrice}
              onChange={(e) => setStopPrice(e.target.value)}
              placeholder={currentPrice > 0 ? currentPrice.toFixed(2) : ''}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:border-amber-500 focus:outline-none"
            />
          </div>
        )}

        {/* Trailing distance */}
        {needsTrailing && (
          <div>
            <label className="block text-xs text-slate-400 mb-1.5">Trailing Distance (price units)</label>
            <input
              type="number"
              step="0.01"
              min="0.01"
              value={trailingDist}
              onChange={(e) => setTrailingDist(e.target.value)}
              placeholder="e.g. 5.00"
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:border-amber-500 focus:outline-none"
            />
          </div>
        )}

        {/* SL / TP */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs text-slate-400 mb-1.5">
              Stop Loss
              {slPips !== null && (
                <span className="ml-1 text-red-400">({slPips.toFixed(0)} pips)</span>
              )}
            </label>
            <input
              type="number"
              step="0.00001"
              value={stopLoss}
              onChange={(e) => setStopLoss(e.target.value)}
              placeholder={currentPrice > 0 ? (side === 'buy' ? currentPrice * 0.99 : currentPrice * 1.01).toFixed(2) : ''}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:border-red-500 focus:outline-none"
            />
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1.5">
              Take Profit
              {tpPips !== null && (
                <span className="ml-1 text-green-400">({tpPips.toFixed(0)} pips)</span>
              )}
            </label>
            <input
              type="number"
              step="0.00001"
              value={takeProfit}
              onChange={(e) => setTakeProfit(e.target.value)}
              placeholder={currentPrice > 0 ? (side === 'buy' ? currentPrice * 1.02 : currentPrice * 0.98).toFixed(2) : ''}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:border-green-500 focus:outline-none"
            />
          </div>
        </div>

        {/* Advanced: risk-based sizing */}
        <div>
          <button
            type="button"
            onClick={() => setShowAdvanced((v) => !v)}
            className="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-300 transition-colors"
          >
            <Calculator className="w-3.5 h-3.5" />
            Risk-based sizing
            {showAdvanced ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
          </button>
          {showAdvanced && (
            <div className="mt-2 p-3 bg-slate-800/50 rounded-lg space-y-2">
              <div className="flex items-center gap-2">
                <label className="text-xs text-slate-400 whitespace-nowrap">Risk %</label>
                <input
                  type="number"
                  step="0.1"
                  min="0.1"
                  max="10"
                  value={riskPct}
                  onChange={(e) => setRiskPct(e.target.value)}
                  className="w-20 bg-slate-700 border border-slate-600 rounded px-2 py-1 text-white text-xs focus:border-amber-500 focus:outline-none"
                />
                <button
                  type="button"
                  onClick={autoSize}
                  disabled={!slNum || !currentPrice}
                  className="px-2 py-1 bg-amber-500/20 text-amber-400 rounded text-xs hover:bg-amber-500/30 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  Auto-size
                </button>
              </div>
              {account && (
                <div className="text-xs text-slate-500">
                  Equity: ${account.equity.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                  {' · '}
                  Risk: ${(account.equity * parseFloat(riskPct) / 100).toFixed(2)}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Order summary */}
        <div className="border-t border-slate-800 pt-3 space-y-1.5">
          <div className="flex justify-between text-xs">
            <span className="text-slate-400">Entry Price</span>
            <span className="text-slate-200 font-mono">
              {orderType === 'market'
                ? currentPrice > 0 ? `~${currentPrice.toFixed(2)}` : '—'
                : limitNum > 0 ? limitNum.toFixed(2) : '—'}
            </span>
          </div>
          {riskReward !== null && (
            <div className="flex justify-between text-xs">
              <span className="text-slate-400">Risk / Reward</span>
              <span className={`font-mono ${riskReward >= 2 ? 'text-green-400' : riskReward >= 1 ? 'text-amber-400' : 'text-red-400'}`}>
                1 : {riskReward.toFixed(2)}
              </span>
            </div>
          )}
          {marginRequired !== null && (
            <div className="flex justify-between text-xs">
              <span className="text-slate-400">Margin Required</span>
              <span className="text-slate-200 font-mono">
                ${marginRequired.toLocaleString(undefined, { maximumFractionDigits: 0 })}
              </span>
            </div>
          )}
        </div>

        {/* Submit */}
        <button
          type="submit"
          disabled={submitting || sizeNum <= 0}
          className={`w-full py-3 rounded-lg font-bold text-sm text-white transition-all active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed ${
            side === 'buy'
              ? 'bg-gradient-to-r from-green-600 to-green-500 hover:from-green-500 hover:to-green-400'
              : 'bg-gradient-to-r from-red-600 to-red-500 hover:from-red-500 hover:to-red-400'
          }`}
        >
          {submitting
            ? 'Placing order…'
            : `${side === 'buy' ? 'BUY' : 'SELL'} ${sizeNum} ${symbol} @ ${
                orderType === 'market'
                  ? currentPrice > 0 ? currentPrice.toFixed(2) : 'Market'
                  : orderType === 'limit' && limitNum > 0 ? limitNum.toFixed(2) : 'Limit'
              }`}
        </button>
      </form>
    </div>
  )
}
