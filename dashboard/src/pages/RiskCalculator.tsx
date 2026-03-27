/**
 * Risk/Reward Calculator — dashboard version (Tailwind)
 * Pure-frontend: no backend required.
 */
import { useState, useCallback } from 'react'
import { Calculator, TrendingUp, TrendingDown, AlertTriangle } from 'lucide-react'

const SYMBOLS: Record<string, { pipSize: number; contractSize: number; label: string }> = {
  'XAU/USD': { pipSize: 0.01,   contractSize: 100,    label: 'Gold (XAU/USD)' },
  'EUR/USD': { pipSize: 0.0001, contractSize: 100000, label: 'EUR/USD' },
  'GBP/USD': { pipSize: 0.0001, contractSize: 100000, label: 'GBP/USD' },
  'USD/JPY': { pipSize: 0.01,   contractSize: 100000, label: 'USD/JPY' },
  'BTC/USD': { pipSize: 1,      contractSize: 1,      label: 'Bitcoin (BTC/USD)' },
  'ETH/USD': { pipSize: 0.01,   contractSize: 1,      label: 'Ethereum (ETH/USD)' },
}

interface CalcState {
  symbol: string
  accountBalance: string
  riskPercent: string
  entryPrice: string
  stopLoss: string
  takeProfit: string
  leverage: string
}

interface CalcResult {
  rrRatio: number
  riskAmount: number
  rewardAmount: number
  stopPips: number
  tpPips: number
  lotSize: number
  marginRequired: number
  breakEvenWinRate: number
}

function calculate(s: CalcState): CalcResult | null {
  const balance  = parseFloat(s.accountBalance)
  const riskPct  = parseFloat(s.riskPercent) / 100
  const entry    = parseFloat(s.entryPrice)
  const sl       = parseFloat(s.stopLoss)
  const tp       = parseFloat(s.takeProfit)
  const leverage = parseFloat(s.leverage) || 1
  const sym      = SYMBOLS[s.symbol]
  if (!sym || [balance, entry, sl, tp].some(isNaN) || entry <= 0 || sl === entry) return null

  const stopDist = Math.abs(entry - sl)
  const tpDist   = Math.abs(tp - entry)
  if (stopDist === 0) return null

  const rrRatio  = tpDist / stopDist
  const stopPips = stopDist / sym.pipSize
  const tpPips   = tpDist  / sym.pipSize
  const riskAmount   = balance * riskPct
  const rewardAmount = riskAmount * rrRatio
  const pipValuePerLot = sym.pipSize * sym.contractSize
  const lotSize = stopPips > 0 ? riskAmount / (stopPips * pipValuePerLot) : 0
  const notional = entry * sym.contractSize * lotSize
  const marginRequired = notional / leverage
  const breakEvenWinRate = (1 / (1 + rrRatio)) * 100

  return { rrRatio, riskAmount, rewardAmount, stopPips, tpPips, lotSize, marginRequired, breakEvenWinRate }
}

export default function RiskCalculator() {
  const [state, setState] = useState<CalcState>({
    symbol: 'XAU/USD', accountBalance: '10000', riskPercent: '1',
    entryPrice: '2350', stopLoss: '2340', takeProfit: '2380', leverage: '100',
  })

  const set = useCallback((key: keyof CalcState) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setState(prev => ({ ...prev, [key]: e.target.value })), [])

  const result = calculate(state)
  const rrColor = !result ? 'text-slate-400' : result.rrRatio >= 2 ? 'text-green-400' : result.rrRatio >= 1 ? 'text-amber-400' : 'text-red-400'

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <Calculator className="w-7 h-7 text-amber-400" />
        <div>
          <h1 className="text-2xl font-bold text-slate-100">Risk / Reward Calculator</h1>
          <p className="text-sm text-slate-400">Calculate position size, pip value, and margin before every trade.</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Inputs */}
        <div className="bg-slate-900 rounded-xl border border-slate-800 p-6 space-y-4">
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider">Trade Setup</h2>

          <div>
            <label className="block text-sm text-slate-400 mb-1">Symbol</label>
            <select value={state.symbol} onChange={set('symbol')}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-slate-100 text-sm focus:outline-none focus:border-amber-500">
              {Object.entries(SYMBOLS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
            </select>
          </div>

          {[
            { key: 'accountBalance' as const, label: 'Account Balance', prefix: '$' },
            { key: 'riskPercent'    as const, label: 'Risk Per Trade',   suffix: '%' },
            { key: 'leverage'       as const, label: 'Leverage',         suffix: ':1' },
          ].map(({ key, label, prefix, suffix }) => (
            <div key={key}>
              <label className="block text-sm text-slate-400 mb-1">{label}</label>
              <div className="flex items-center bg-slate-800 border border-slate-700 rounded-lg overflow-hidden">
                {prefix && <span className="px-3 text-slate-500 text-sm border-r border-slate-700">{prefix}</span>}
                <input type="number" value={state[key]} onChange={set(key)}
                  className="flex-1 bg-transparent px-3 py-2 text-slate-100 text-sm focus:outline-none" />
                {suffix && <span className="px-3 text-slate-500 text-sm border-l border-slate-700">{suffix}</span>}
              </div>
            </div>
          ))}

          <hr className="border-slate-700" />

          {[
            { key: 'entryPrice' as const, label: 'Entry Price' },
            { key: 'stopLoss'   as const, label: 'Stop Loss' },
            { key: 'takeProfit' as const, label: 'Take Profit' },
          ].map(({ key, label }) => (
            <div key={key}>
              <label className="block text-sm text-slate-400 mb-1">{label}</label>
              <input type="number" value={state[key]} onChange={set(key)}
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-slate-100 text-sm focus:outline-none focus:border-amber-500" />
            </div>
          ))}
        </div>

        {/* Results */}
        <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-4">Results</h2>

          <div className="text-center py-6 border-b border-slate-800 mb-4">
            <div className="text-xs text-slate-500 mb-2">Risk : Reward</div>
            <div className={`text-5xl font-black ${rrColor}`}>
              {result ? `1 : ${result.rrRatio.toFixed(2)}` : '—'}
            </div>
            {result && (
              <div className="text-xs text-slate-500 mt-2">
                Break-even win rate: {result.breakEvenWinRate.toFixed(1)}%
              </div>
            )}
          </div>

          {result ? (
            <div className="space-y-2">
              {[
                { label: 'Risk Amount',      value: `$${result.riskAmount.toFixed(2)}`,      highlight: true },
                { label: 'Reward Amount',    value: `$${result.rewardAmount.toFixed(2)}`,    highlight: true },
                { label: 'Stop Loss Pips',   value: result.stopPips.toFixed(1) },
                { label: 'Take Profit Pips', value: result.tpPips.toFixed(1) },
                { label: 'Lot Size',         value: result.lotSize.toFixed(4) },
                { label: 'Margin Required',  value: `$${result.marginRequired.toFixed(2)}` },
              ].map(({ label, value, highlight }) => (
                <div key={label} className={`flex justify-between items-center py-2 ${highlight ? 'bg-slate-800 rounded-lg px-3' : 'border-b border-slate-800/50'}`}>
                  <span className="text-sm text-slate-400">{label}</span>
                  <span className={`text-sm font-semibold ${highlight ? 'text-slate-100' : 'text-slate-300'}`}>{value}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-slate-500 text-sm text-center py-8">Fill in all fields to see results.</p>
          )}
        </div>

        {/* Tips */}
        <div className="bg-slate-900 rounded-xl border border-slate-800 p-6 space-y-4">
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider">Quick Tips</h2>
          <div className="space-y-3">
            {[
              { icon: TrendingUp,    color: 'text-green-400', text: 'Minimum R:R of 1:2 recommended' },
              { icon: TrendingUp,    color: 'text-green-400', text: 'Risk no more than 1–2% per trade' },
              { icon: TrendingDown,  color: 'text-amber-400', text: 'At 1:2 R:R you only need 34% win rate to profit' },
              { icon: AlertTriangle, color: 'text-red-400',   text: 'Higher leverage = higher margin efficiency but more risk' },
            ].map(({ icon: Icon, color, text }) => (
              <div key={text} className="flex items-start gap-3">
                <Icon className={`w-4 h-4 mt-0.5 flex-shrink-0 ${color}`} />
                <span className="text-sm text-slate-400">{text}</span>
              </div>
            ))}
          </div>

          <hr className="border-slate-700" />
          <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider">Position Sizing Formula</h2>
          <div className="bg-slate-800 rounded-lg p-4 font-mono text-xs text-slate-300 space-y-1">
            <div>Lot Size = Risk$ / (Stop Pips × Pip Value)</div>
            <div className="text-slate-500">Risk$ = Balance × Risk%</div>
            <div className="text-slate-500">Pip Value = Pip Size × Contract Size</div>
          </div>
        </div>
      </div>
    </div>
  )
}
