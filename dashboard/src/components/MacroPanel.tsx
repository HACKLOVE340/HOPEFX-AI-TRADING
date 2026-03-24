import { useEffect, useState } from 'react'
import { TrendingUp, TrendingDown, Minus, RefreshCw } from 'lucide-react'

interface MacroSnapshot {
  dxy: number | null
  yield_10y: number | null
  yield_2y: number | null
  yield_spread: number | null
  cpi_latest: number | null
  cpi_yoy_pct: number | null
  macro_regime_score: number
  macro_stance: string
  refreshed_at: string
}

function MetricRow({
  label,
  value,
  unit = '',
  bullishWhenLow = false,
  description,
}: {
  label: string
  value: number | null
  unit?: string
  bullishWhenLow?: boolean
  description: string
}) {
  if (value === null) {
    return (
      <div className="flex items-center justify-between py-2 border-b border-slate-800">
        <div>
          <p className="text-sm font-medium text-slate-300">{label}</p>
          <p className="text-xs text-slate-500">{description}</p>
        </div>
        <span className="text-slate-500 text-sm">—</span>
      </div>
    )
  }

  const formatted = `${value.toFixed(2)}${unit}`
  return (
    <div className="flex items-center justify-between py-2 border-b border-slate-800">
      <div>
        <p className="text-sm font-medium text-slate-300">{label}</p>
        <p className="text-xs text-slate-500">{description}</p>
      </div>
      <span className="text-sm font-mono font-semibold text-slate-100">{formatted}</span>
    </div>
  )
}

function ScoreGauge({ score }: { score: number }) {
  const pct = Math.min(100, Math.max(0, score))
  const color =
    pct >= 70 ? 'bg-emerald-500' : pct >= 45 ? 'bg-amber-400' : 'bg-red-500'
  const textColor =
    pct >= 70 ? 'text-emerald-400' : pct >= 45 ? 'text-amber-400' : 'text-red-400'

  return (
    <div className="mb-4">
      <div className="flex justify-between items-center mb-1">
        <span className="text-xs text-slate-400">Bearish for Gold</span>
        <span className={`text-lg font-bold ${textColor}`}>{pct}/100</span>
        <span className="text-xs text-slate-400">Bullish for Gold</span>
      </div>
      <div className="w-full bg-slate-700 rounded-full h-3">
        <div
          className={`h-3 rounded-full transition-all duration-500 ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}

export function MacroPanel() {
  const [data, setData] = useState<MacroSnapshot | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/macro/snapshot')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setData(await res.json())
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // Refresh every 30 minutes
    const id = setInterval(load, 30 * 60 * 1000)
    return () => clearInterval(id)
  }, [])

  return (
    <div className="bg-slate-900 rounded-lg border border-slate-800 p-4">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-semibold text-slate-100">Macro Intelligence</h3>
        <button
          onClick={load}
          disabled={loading}
          className="p-1.5 rounded hover:bg-slate-800 text-slate-400 hover:text-slate-200 transition-colors"
          title="Refresh macro data"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {error && (
        <p className="text-xs text-red-400 mb-3">
          FRED data unavailable: {error}
        </p>
      )}

      {data && (
        <>
          <ScoreGauge score={data.macro_regime_score} />

          <div className="mb-4 px-3 py-2 rounded bg-slate-800 text-sm text-slate-300">
            <span className="font-medium">Macro Stance: </span>
            {data.macro_stance}
          </div>

          <div className="space-y-0">
            <MetricRow
              label="DXY (Dollar Index)"
              value={data.dxy}
              description="Higher = stronger dollar = bearish gold"
              bullishWhenLow
            />
            <MetricRow
              label="US 10Y Yield"
              value={data.yield_10y}
              unit="%"
              description="Rising yields = higher opportunity cost for gold"
              bullishWhenLow
            />
            <MetricRow
              label="US 2Y Yield"
              value={data.yield_2y}
              unit="%"
              description="Short-end rate expectations"
            />
            <MetricRow
              label="Yield Spread (10Y–2Y)"
              value={data.yield_spread}
              unit="%"
              description="Negative = inverted curve = risk-off = gold bullish"
            />
            <MetricRow
              label="CPI YoY"
              value={data.cpi_yoy_pct}
              unit="%"
              description="Higher inflation = stronger gold demand"
            />
          </div>

          {data.refreshed_at && (
            <p className="text-xs text-slate-600 mt-3">
              Source: FRED (St. Louis Fed) · Updated{' '}
              {new Date(data.refreshed_at).toLocaleTimeString()}
            </p>
          )}
        </>
      )}

      {loading && !data && (
        <div className="flex items-center justify-center h-32 text-slate-500 text-sm">
          Loading macro data…
        </div>
      )}
    </div>
  )
}
