/**
 * ReliabilityDashboard
 *
 * Superadmin view of the platform reliability layer:
 *   - Live circuit breaker states (open / half-open / closed)
 *   - Component health probe results
 *   - Hot-standby role and replication lag
 *   - Auto-rollback history
 *   - Self-test trigger
 *
 * API endpoints:
 *   GET  /api/superadmin/reliability/status
 *   GET  /api/superadmin/reliability/components
 *   POST /api/superadmin/reliability/probe
 *   GET  /api/superadmin/reliability/history
 *   POST /api/superadmin/reliability/self-test
 *   GET  /api/superadmin/reliability/metrics
 */

import { useState, useEffect, useCallback } from 'react'
import {
  Activity, AlertTriangle, CheckCircle, XCircle, RefreshCw,
  Zap, Clock, Server, Shield, RotateCcw, ChevronDown, ChevronUp,
  Play, Cpu, Database, Wifi,
} from 'lucide-react'
import axios from 'axios'

// ── Types ─────────────────────────────────────────────────────────────────────

type BreakerState = 'closed' | 'half_open' | 'open' | 'unknown'

interface CircuitBreaker {
  name: string
  state: BreakerState
  failure_count: number
  success_count: number
  last_failure_at: string | null
  last_state_change: string | null
  config: {
    failure_threshold: number
    success_threshold: number
    timeout_seconds: number
  }
}

interface ComponentProbe {
  name: string
  status: 'healthy' | 'degraded' | 'unhealthy' | 'unknown'
  latency_ms: number | null
  message: string
  checked_at: string
}

interface ReliabilityStatus {
  overall: 'healthy' | 'degraded' | 'unhealthy'
  circuit_breakers: CircuitBreaker[]
  hot_standby: {
    role: 'primary' | 'standby' | 'unknown'
    replication_lag_ms: number | null
    state_version: number
    last_heartbeat_age_s: number | null
  }
  rollback: {
    total_rollbacks: number
    last_rollback_at: string | null
    last_rollback_reason: string | null
  }
  checked_at: string
}

interface RollbackEvent {
  timestamp: string
  service: string
  strategy: string
  trigger: string
  success: boolean
  duration_ms: number
  reason: string
}

interface MetricsSummary {
  uptime_pct_30d: number
  mttr_minutes: number | null
  total_incidents_30d: number
  circuit_trips_24h: number
  rollbacks_7d: number
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const BREAKER_COLOR: Record<BreakerState, string> = {
  closed:    'text-green-400',
  half_open: 'text-amber-400',
  open:      'text-red-400',
  unknown:   'text-slate-400',
}

const BREAKER_BG: Record<BreakerState, string> = {
  closed:    'bg-green-500/10 border-green-500/20',
  half_open: 'bg-amber-500/10 border-amber-500/20',
  open:      'bg-red-500/10 border-red-500/20',
  unknown:   'bg-slate-500/10 border-slate-500/20',
}

const BREAKER_LABEL: Record<BreakerState, string> = {
  closed:    'CLOSED',
  half_open: 'HALF-OPEN',
  open:      'OPEN',
  unknown:   'UNKNOWN',
}

const HEALTH_COLOR: Record<string, string> = {
  healthy:   'text-green-400',
  degraded:  'text-amber-400',
  unhealthy: 'text-red-400',
  unknown:   'text-slate-400',
}

const HEALTH_ICON: Record<string, JSX.Element> = {
  healthy:   <CheckCircle className="w-4 h-4 text-green-400" />,
  degraded:  <AlertTriangle className="w-4 h-4 text-amber-400" />,
  unhealthy: <XCircle className="w-4 h-4 text-red-400" />,
  unknown:   <Activity className="w-4 h-4 text-slate-400" />,
}

const fmtAgo = (iso: string | null): string => {
  if (!iso) return '—'
  const diff = Date.now() - new Date(iso).getTime()
  if (diff < 60_000) return `${Math.round(diff / 1000)}s ago`
  if (diff < 3_600_000) return `${Math.round(diff / 60_000)}m ago`
  if (diff < 86_400_000) return `${Math.round(diff / 3_600_000)}h ago`
  return `${Math.round(diff / 86_400_000)}d ago`
}

const fmtMs = (ms: number | null): string =>
  ms == null ? '—' : ms < 1000 ? `${ms.toFixed(0)}ms` : `${(ms / 1000).toFixed(2)}s`

// ── Sub-components ────────────────────────────────────────────────────────────

const SectionTitle = ({ children }: { children: React.ReactNode }) => (
  <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-widest mb-3 mt-6">
    {children}
  </h2>
)

const StatCard = ({
  label, value, sub, icon: Icon, color = 'text-white',
}: {
  label: string; value: string | number; sub?: string
  icon: React.ElementType; color?: string
}) => (
  <div className="bg-slate-800 border border-slate-700 rounded-xl p-4 flex items-start gap-3">
    <div className="p-2 bg-slate-700 rounded-lg mt-0.5">
      <Icon className="w-4 h-4 text-slate-300" />
    </div>
    <div>
      <div className={`text-xl font-bold ${color}`}>{value}</div>
      <div className="text-xs text-slate-400 mt-0.5">{label}</div>
      {sub && <div className="text-xs text-slate-500 mt-0.5">{sub}</div>}
    </div>
  </div>
)

const BreakerCard = ({ cb }: { cb: CircuitBreaker }) => {
  const [expanded, setExpanded] = useState(false)
  const state = (cb.state ?? 'unknown') as BreakerState
  return (
    <div className={`border rounded-xl overflow-hidden ${BREAKER_BG[state]}`}>
      <button
        className="w-full flex items-center gap-3 px-4 py-3 text-left"
        onClick={() => setExpanded(e => !e)}
      >
        <Shield className={`w-4 h-4 flex-shrink-0 ${BREAKER_COLOR[state]}`} />
        <span className="flex-1 font-medium text-slate-200 text-sm">{cb.name}</span>
        <span className={`text-xs font-bold tracking-wide ${BREAKER_COLOR[state]}`}>
          {BREAKER_LABEL[state]}
        </span>
        {expanded
          ? <ChevronUp className="w-3.5 h-3.5 text-slate-500 ml-2" />
          : <ChevronDown className="w-3.5 h-3.5 text-slate-500 ml-2" />}
      </button>
      {expanded && (
        <div className="px-4 pb-4 grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs border-t border-white/5 pt-3">
          <span className="text-slate-500">Failures</span>
          <span className="text-slate-200 font-mono">{cb.failure_count} / {cb.config.failure_threshold}</span>
          <span className="text-slate-500">Successes (half-open)</span>
          <span className="text-slate-200 font-mono">{cb.success_count} / {cb.config.success_threshold}</span>
          <span className="text-slate-500">Timeout</span>
          <span className="text-slate-200 font-mono">{cb.config.timeout_seconds}s</span>
          <span className="text-slate-500">Last failure</span>
          <span className="text-slate-200">{fmtAgo(cb.last_failure_at)}</span>
          <span className="text-slate-500">State changed</span>
          <span className="text-slate-200">{fmtAgo(cb.last_state_change)}</span>
        </div>
      )}
    </div>
  )
}

const ProbeRow = ({ probe }: { probe: ComponentProbe }) => (
  <div className="flex items-center gap-3 py-2.5 border-b border-slate-700/50 last:border-0">
    <div className="flex-shrink-0">{HEALTH_ICON[probe.status] ?? HEALTH_ICON.unknown}</div>
    <span className="flex-1 text-sm text-slate-200 capitalize">{probe.name.replace(/_/g, ' ')}</span>
    <span className={`text-xs font-semibold ${HEALTH_COLOR[probe.status]}`}>
      {probe.status.toUpperCase()}
    </span>
    {probe.latency_ms != null && (
      <span className="text-xs text-slate-500 font-mono w-14 text-right">{fmtMs(probe.latency_ms)}</span>
    )}
  </div>
)

const RollbackRow = ({ ev }: { ev: RollbackEvent }) => (
  <div className="flex items-start gap-3 py-2.5 border-b border-slate-700/50 last:border-0 text-xs">
    <span className={ev.success ? 'text-green-400' : 'text-red-400'}>
      {ev.success ? <CheckCircle className="w-3.5 h-3.5 mt-0.5" /> : <XCircle className="w-3.5 h-3.5 mt-0.5" />}
    </span>
    <div className="flex-1 min-w-0">
      <div className="text-slate-200 font-medium truncate">{ev.service}</div>
      <div className="text-slate-500 mt-0.5 truncate">{ev.reason}</div>
    </div>
    <div className="text-right flex-shrink-0">
      <div className="text-slate-400">{fmtAgo(ev.timestamp)}</div>
      <div className="text-slate-600 mt-0.5">{ev.strategy} · {fmtMs(ev.duration_ms)}</div>
    </div>
  </div>
)

// ── Main component ────────────────────────────────────────────────────────────

export default function ReliabilityDashboard() {
  const [status, setStatus] = useState<ReliabilityStatus | null>(null)
  const [probes, setProbes] = useState<ComponentProbe[]>([])
  const [history, setHistory] = useState<RollbackEvent[]>([])
  const [metrics, setMetrics] = useState<MetricsSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [probing, setProbing] = useState(false)
  const [selfTesting, setSelfTesting] = useState(false)
  const [selfTestResult, setSelfTestResult] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setError(null)
    try {
      const [statusRes, histRes, metricsRes] = await Promise.allSettled([
        axios.get('/api/superadmin/reliability/status'),
        axios.get('/api/superadmin/reliability/history'),
        axios.get('/api/superadmin/reliability/metrics'),
      ])
      if (statusRes.status === 'fulfilled') setStatus(statusRes.value.data)
      else setError('Could not load reliability status.')
      if (histRes.status === 'fulfilled') setHistory(histRes.value.data.events ?? [])
      if (metricsRes.status === 'fulfilled') setMetrics(metricsRes.value.data)
    } finally {
      setLoading(false)
    }
  }, [])

  const runProbe = useCallback(async () => {
    setProbing(true)
    try {
      const res = await axios.post('/api/superadmin/reliability/probe')
      setProbes(res.data.results ?? [])
    } catch {
      setProbes([])
    } finally {
      setProbing(false)
    }
  }, [])

  const runSelfTest = useCallback(async () => {
    setSelfTesting(true)
    setSelfTestResult(null)
    try {
      const res = await axios.post('/api/superadmin/reliability/self-test')
      setSelfTestResult(res.data.summary ?? 'Self-test complete.')
    } catch {
      setSelfTestResult('Self-test failed — check server logs.')
    } finally {
      setSelfTesting(false)
    }
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(load, 30_000)
    return () => clearInterval(t)
  }, [load])

  const breakers = status?.circuit_breakers ?? []
  const openCount = breakers.filter(b => b.state === 'open').length
  const halfOpenCount = breakers.filter(b => b.state === 'half_open').length
  const standby = status?.hot_standby
  const rollback = status?.rollback

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-2">
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <Shield className="w-5 h-5 text-blue-400" />
            Reliability
          </h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Circuit breakers · Hot standby · Auto-rollback · Component probes
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={load}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-slate-700 hover:bg-slate-600 text-slate-200 rounded-lg border border-slate-600 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
          <button
            onClick={runSelfTest}
            disabled={selfTesting}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-blue-600 hover:bg-blue-500 text-white rounded-lg transition-colors disabled:opacity-50"
          >
            <Play className="w-3.5 h-3.5" />
            {selfTesting ? 'Running…' : 'Self-test'}
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl px-4 py-3 text-sm text-red-400">
          {error}
        </div>
      )}

      {selfTestResult && (
        <div className="bg-blue-500/10 border border-blue-500/20 rounded-xl px-4 py-3 text-sm text-blue-300">
          {selfTestResult}
        </div>
      )}

      {/* Summary metrics */}
      <SectionTitle>Summary</SectionTitle>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard
          label="30-day uptime"
          value={metrics ? `${metrics.uptime_pct_30d.toFixed(2)}%` : '—'}
          icon={Activity}
          color={metrics && metrics.uptime_pct_30d >= 99.9 ? 'text-green-400' : 'text-amber-400'}
        />
        <StatCard
          label="Open breakers"
          value={openCount + halfOpenCount}
          sub={openCount > 0 ? `${openCount} open, ${halfOpenCount} half-open` : 'All closed'}
          icon={Zap}
          color={openCount > 0 ? 'text-red-400' : halfOpenCount > 0 ? 'text-amber-400' : 'text-green-400'}
        />
        <StatCard
          label="Rollbacks (7d)"
          value={metrics?.rollbacks_7d ?? rollback?.total_rollbacks ?? 0}
          icon={RotateCcw}
          color="text-slate-200"
        />
        <StatCard
          label="Standby role"
          value={standby?.role?.toUpperCase() ?? '—'}
          sub={standby?.replication_lag_ms != null ? `Lag: ${fmtMs(standby.replication_lag_ms)}` : undefined}
          icon={Server}
          color={standby?.role === 'primary' ? 'text-green-400' : 'text-amber-400'}
        />
      </div>

      {/* Circuit breakers */}
      <SectionTitle>Circuit Breakers</SectionTitle>
      {breakers.length === 0 ? (
        <div className="bg-slate-800 border border-slate-700 rounded-xl px-4 py-6 text-center text-sm text-slate-500">
          No circuit breakers registered.
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {breakers.map(cb => <BreakerCard key={cb.name} cb={cb} />)}
        </div>
      )}

      {/* Component probes */}
      <SectionTitle>Component Probes</SectionTitle>
      <div className="bg-slate-800 border border-slate-700 rounded-xl overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-700">
          <span className="text-xs text-slate-400">
            {probes.length > 0 ? `${probes.length} components probed` : 'Run a probe to check live component health'}
          </span>
          <button
            onClick={runProbe}
            disabled={probing}
            className="flex items-center gap-1.5 px-3 py-1 text-xs bg-slate-700 hover:bg-slate-600 text-slate-200 rounded-lg border border-slate-600 transition-colors disabled:opacity-50"
          >
            <Cpu className={`w-3 h-3 ${probing ? 'animate-pulse' : ''}`} />
            {probing ? 'Probing…' : 'Run probe'}
          </button>
        </div>
        <div className="px-4 divide-y divide-slate-700/50">
          {probes.length === 0 ? (
            <p className="py-6 text-center text-sm text-slate-600">No probe results yet.</p>
          ) : (
            probes.map(p => <ProbeRow key={p.name} probe={p} />)
          )}
        </div>
      </div>

      {/* Hot standby */}
      <SectionTitle>Hot Standby</SectionTitle>
      <div className="bg-slate-800 border border-slate-700 rounded-xl p-4 grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
        {[
          { label: 'Role', value: standby?.role?.toUpperCase() ?? '—', icon: Server },
          { label: 'State version', value: standby?.state_version ?? '—', icon: Database },
          { label: 'Replication lag', value: fmtMs(standby?.replication_lag_ms ?? null), icon: Wifi },
          { label: 'Heartbeat age', value: standby?.last_heartbeat_age_s != null ? `${standby.last_heartbeat_age_s.toFixed(1)}s` : '—', icon: Clock },
        ].map(({ label, value, icon: Icon }) => (
          <div key={label} className="flex items-center gap-2">
            <Icon className="w-4 h-4 text-slate-500 flex-shrink-0" />
            <div>
              <div className="text-slate-200 font-medium">{value}</div>
              <div className="text-xs text-slate-500">{label}</div>
            </div>
          </div>
        ))}
      </div>

      {/* Rollback history */}
      <SectionTitle>Rollback History</SectionTitle>
      <div className="bg-slate-800 border border-slate-700 rounded-xl overflow-hidden">
        <div className="px-4 divide-y divide-slate-700/50">
          {history.length === 0 ? (
            <p className="py-6 text-center text-sm text-slate-600">No rollback events recorded.</p>
          ) : (
            history.slice(0, 20).map((ev, i) => <RollbackRow key={i} ev={ev} />)
          )}
        </div>
      </div>

      <p className="text-xs text-slate-600 text-right pt-2">
        Auto-refreshes every 30s · {status ? `Last checked ${fmtAgo(status.checked_at)}` : ''}
      </p>
    </div>
  )
}
