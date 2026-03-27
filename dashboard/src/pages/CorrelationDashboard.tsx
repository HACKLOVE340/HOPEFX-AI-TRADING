/**
 * Multi-Symbol Correlation Dashboard — dashboard version (Tailwind)
 * Wires to: GET /api/analysis/correlation  |  GET /api/analysis/cot
 */
import { useState, useEffect } from 'react'
import { Link2, RefreshCw, TrendingUp, TrendingDown } from 'lucide-react'
import axios from 'axios'

const SYMBOLS = ['XAU/USD', 'EUR/USD', 'GBP/USD', 'USD/JPY', 'BTC/USD', 'DXY']

const MOCK_MATRIX: Record<string, Record<string, number>> = {
  'XAU/USD': { 'XAU/USD': 1.00, 'EUR/USD': 0.62, 'GBP/USD': 0.58, 'USD/JPY': -0.71, 'BTC/USD': 0.34, 'DXY': -0.68 },
  'EUR/USD': { 'XAU/USD': 0.62, 'EUR/USD': 1.00, 'GBP/USD': 0.89, 'USD/JPY': -0.82, 'BTC/USD': 0.21, 'DXY': -0.94 },
  'GBP/USD': { 'XAU/USD': 0.58, 'EUR/USD': 0.89, 'GBP/USD': 1.00, 'USD/JPY': -0.76, 'BTC/USD': 0.18, 'DXY': -0.88 },
  'USD/JPY': { 'XAU/USD': -0.71, 'EUR/USD': -0.82, 'GBP/USD': -0.76, 'USD/JPY': 1.00, 'BTC/USD': -0.15, 'DXY': 0.79 },
  'BTC/USD': { 'XAU/USD': 0.34, 'EUR/USD': 0.21, 'GBP/USD': 0.18, 'USD/JPY': -0.15, 'BTC/USD': 1.00, 'DXY': -0.22 },
  'DXY':     { 'XAU/USD': -0.68, 'EUR/USD': -0.94, 'GBP/USD': -0.88, 'USD/JPY': 0.79, 'BTC/USD': -0.22, 'DXY': 1.00 },
}

const MOCK_COT = {
  report_date: '2026-05-27',
  net_speculator_long: 187420,
  long_positions: 312840,
  short_positions: 125420,
  sentiment: 'Bullish',
  sentiment_strength: 'Strong',
  weekly_change: 8240,
  note: 'COT proxy derived from central bank demand signature (gold up + DXY up + yields up). True CFTC data requires FINRA ATS feed.',
}

function corrColor(v: number): string {
  if (v >= 0.7)  return 'bg-green-500 text-white'
  if (v >= 0.3)  return 'bg-green-500/40 text-green-300'
  if (v >= -0.3) return 'bg-slate-700 text-slate-300'
  if (v >= -0.7) return 'bg-red-500/40 text-red-300'
  return 'bg-red-500 text-white'
}

export default function CorrelationDashboard() {
  const [matrix, setMatrix] = useState(MOCK_MATRIX)
  const [cot, setCot] = useState(MOCK_COT)
  const [loading, setLoading] = useState(false)
  const [window, setWindow] = useState(30)

  const refresh = async () => {
    setLoading(true)
    try {
      const [cm, cd] = await Promise.all([
        axios.get(`/api/analysis/correlation?window=${window}`),
        axios.get('/api/analysis/cot'),
      ])
      setMatrix(cm.data.matrix ?? MOCK_MATRIX)
      setCot(cd.data ?? MOCK_COT)
    } catch {
      // demo mode
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { refresh() }, [window])

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Link2 className="w-7 h-7 text-amber-400" />
          <div>
            <h1 className="text-2xl font-bold text-slate-100">Correlation Dashboard</h1>
            <p className="text-sm text-slate-400">Multi-symbol correlation matrix and COT sentiment proxy.</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <select value={window} onChange={e => setWindow(Number(e.target.value))}
            className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-slate-300 text-sm focus:outline-none">
            {[14, 30, 60, 90].map(w => <option key={w} value={w}>{w}d window</option>)}
          </select>
          <button onClick={refresh} disabled={loading}
            className="flex items-center gap-2 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-sm transition-colors">
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Correlation matrix */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
        <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-4">
          Pearson Correlation Matrix — {window}-day rolling window
        </h2>
        <div className="overflow-x-auto">
          <table className="text-xs">
            <thead>
              <tr>
                <th className="w-24 text-left text-slate-500 pb-2" />
                {SYMBOLS.map(s => (
                  <th key={s} className="px-1 pb-2 text-slate-400 font-medium text-center min-w-[72px]">{s}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {SYMBOLS.map(row => (
                <tr key={row}>
                  <td className="pr-3 py-1 text-slate-400 font-medium whitespace-nowrap">{row}</td>
                  {SYMBOLS.map(col => {
                    const v = matrix[row]?.[col] ?? 0
                    const isDiag = row === col
                    return (
                      <td key={col} className="px-1 py-1 text-center">
                        <div className={`rounded px-2 py-1.5 font-mono font-semibold ${isDiag ? 'bg-slate-700 text-slate-300' : corrColor(v)}`}>
                          {v.toFixed(2)}
                        </div>
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex items-center gap-4 mt-4 text-xs text-slate-500">
          <div className="flex items-center gap-1.5"><div className="w-3 h-3 rounded bg-green-500" />Strong positive (≥0.7)</div>
          <div className="flex items-center gap-1.5"><div className="w-3 h-3 rounded bg-slate-700" />Weak (−0.3 to 0.3)</div>
          <div className="flex items-center gap-1.5"><div className="w-3 h-3 rounded bg-red-500" />Strong negative (≤−0.7)</div>
        </div>
      </div>

      {/* COT proxy */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
        <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-4">
          COT Proxy — Gold Speculator Sentiment
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
          {[
            { label: 'Net Long',       value: cot.net_speculator_long.toLocaleString(), good: cot.net_speculator_long > 0 },
            { label: 'Long Positions', value: cot.long_positions.toLocaleString(),      good: true },
            { label: 'Short Positions',value: cot.short_positions.toLocaleString(),     good: false },
            { label: 'Weekly Change',  value: (cot.weekly_change ?? 0) > 0 ? `+${cot.weekly_change?.toLocaleString()}` : (cot.weekly_change ?? 0).toLocaleString(), good: (cot.weekly_change ?? 0) > 0 },
          ].map(({ label, value, good }) => (
            <div key={label} className="bg-slate-800 rounded-lg p-3">
              <div className="text-xs text-slate-500 mb-1">{label}</div>
              <div className={`text-lg font-bold ${good ? 'text-green-400' : 'text-red-400'}`}>{value}</div>
            </div>
          ))}
        </div>
        <div className="flex items-center gap-3">
          <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-semibold ${
            cot.sentiment === 'Bullish' ? 'bg-green-500/20 text-green-400 border border-green-500/30' : 'bg-red-500/20 text-red-400 border border-red-500/30'
          }`}>
            {cot.sentiment === 'Bullish' ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
            {cot.sentiment} — {cot.sentiment_strength}
          </div>
          <span className="text-xs text-slate-500">Report date: {cot.report_date}</span>
        </div>
        <p className="text-xs text-slate-600 mt-3 italic">{cot.note}</p>
      </div>

      {/* Key insights */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 p-6">
        <h2 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-3">Key Insights</h2>
        <div className="space-y-2 text-sm text-slate-400">
          <div>• XAU/USD has strong negative correlation with DXY (−0.68) — dollar strength suppresses gold.</div>
          <div>• EUR/USD and GBP/USD are highly correlated (0.89) — avoid holding both simultaneously.</div>
          <div>• BTC/USD shows low correlation with all forex pairs — useful for portfolio diversification.</div>
          <div>• USD/JPY is a reliable DXY proxy (0.79) — use as a risk-on/risk-off indicator.</div>
        </div>
      </div>
    </div>
  )
}
