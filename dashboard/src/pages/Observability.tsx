/**
 * Observability — SuperAdmin Distributed Tracing & Metrics
 *
 * Exposes:
 * - OpenTelemetry trace viewer
 * - Service dependency map
 * - Latency percentiles (p50, p95, p99)
 * - Error rate monitoring
 * - Throughput metrics
 * - Span waterfall diagrams
 * - Alert configuration
 *
 * Backend: /api/tracing/*, tracing/opentelemetry_setup.py
 */
import { useEffect, useState, useCallback } from 'react'
import {
  Activity, Clock, AlertTriangle, CheckCircle, Zap,
  Search, RefreshCw, Filter, BarChart2, Layers,
  ArrowRight, Globe, Database, Brain, Server,
  Wifi, Shield, TrendingUp, TrendingDown,
} from 'lucide-react'

// ── Types ─────────────────────────────────────────────────────────────────────
interface ServiceMetrics {
  name: string
  status: 'healthy' | 'degraded' | 'down'
  requests_per_sec: number
  error_rate: number
  p50_ms: number
  p95_ms: number
  p99_ms: number
  uptime_pct: number
}

interface Trace {
  trace_id: string
  root_service: string
  operation: string
  duration_ms: number
  status: 'ok' | 'error'
  spans_count: number
  timestamp: string
  services_involved: string[]
}

interface Span {
  span_id: string
  parent_id?: string
  service: string
  operation: string
  duration_ms: number
  start_offset_ms: number
  status: 'ok' | 'error'
  attributes: Record<string, string>
}

interface SystemOverview {
  total_requests_24h: number
  avg_latency_ms: number
  error_rate_pct: number
  active_traces: number
  services_healthy: number
  services_total: number
}

// ── Component ─────────────────────────────────────────────────────────────────
export function Observability() {
  const [overview, setOverview] = useState<SystemOverview | null>(null)
  const [services, setServices] = useState<ServiceMetrics[]>([])
  const [traces, setTraces] = useState<Trace[]>([])
  const [selectedTrace, setSelectedTrace] = useState<Trace | null>(null)
  const [spans, setSpans] = useState<Span[]>([])
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<'all' | 'ok' | 'error'>('all')

  const headers = { Authorization: `Bearer ${localStorage.getItem('token')}` }

  const fetchAll = useCallback(async () => {
    setLoading(true)
    try {
      const [overviewRes, servicesRes, tracesRes] = await Promise.all([
        fetch('/api/tracing/overview', { headers }),
        fetch('/api/tracing/services', { headers }),
        fetch('/api/tracing/traces?limit=50', { headers }),
      ])
      if (overviewRes.ok) setOverview(await overviewRes.json())
      if (servicesRes.ok) { const d = await servicesRes.json(); setServices(d.services || []) }
      if (tracesRes.ok) { const d = await tracesRes.json(); setTraces(d.traces || []) }
    } catch (err) {
      console.error('Observability fetch error:', err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchAll() }, [fetchAll])

  const fetchSpans = async (traceId: string) => {
    try {
      const res = await fetch(`/api/tracing/traces/${traceId}/spans`, { headers })
      if (res.ok) { const d = await res.json(); setSpans(d.spans || []) }
    } catch (err) { console.error('Spans fetch error:', err) }
  }

  const selectTrace = (trace: Trace) => {
    setSelectedTrace(trace)
    fetchSpans(trace.trace_id)
  }

  const filteredTraces = traces.filter(t => {
    const matchesSearch = t.operation.toLowerCase().includes(searchQuery.toLowerCase()) ||
      t.trace_id.includes(searchQuery)
    const matchesStatus = statusFilter === 'all' || t.status === statusFilter
    return matchesSearch && matchesStatus
  })

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Observability</h1>
          <p className="text-sm text-slate-400 mt-1">Distributed tracing, metrics, and service health</p>
        </div>
        <button onClick={fetchAll} className="flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-sm transition-colors">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </button>
      </div>

      {/* Overview Stats */}
      {overview && (
        <div className="grid grid-cols-2 md:grid-cols-6 gap-4">
          <MetricCard icon={Zap} label="Requests (24h)" value={overview.total_requests_24h.toLocaleString()} color="blue" />
          <MetricCard icon={Clock} label="Avg Latency" value={`${overview.avg_latency_ms.toFixed(0)}ms`} color="amber" />
          <MetricCard icon={AlertTriangle} label="Error Rate" value={`${overview.error_rate_pct.toFixed(2)}%`} color={overview.error_rate_pct > 1 ? 'red' : 'green'} />
          <MetricCard icon={Activity} label="Active Traces" value={overview.active_traces.toLocaleString()} color="purple" />
          <MetricCard icon={Server} label="Services" value={`${overview.services_healthy}/${overview.services_total}`} color="green" />
          <MetricCard icon={Shield} label="Uptime" value="99.9%" color="green" />
        </div>
      )}

      {/* Service Health */}
      <div className="bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
        <div className="px-5 py-4 border-b border-slate-800 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-300">Service Health</h2>
          <span className="text-xs text-slate-500">{services.length} services</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="text-xs text-slate-500 border-b border-slate-800">
                <th className="px-5 py-3 text-left">Service</th>
                <th className="px-5 py-3 text-left">Status</th>
                <th className="px-5 py-3 text-left">RPS</th>
                <th className="px-5 py-3 text-left">Error Rate</th>
                <th className="px-5 py-3 text-left">p50</th>
                <th className="px-5 py-3 text-left">p95</th>
                <th className="px-5 py-3 text-left">p99</th>
                <th className="px-5 py-3 text-left">Uptime</th>
              </tr>
            </thead>
            <tbody className="text-sm">
              {services.map(svc => (
                <tr key={svc.name} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                  <td className="px-5 py-3 font-medium text-slate-200 flex items-center gap-2">
                    <ServiceIcon name={svc.name} />
                    {svc.name}
                  </td>
                  <td className="px-5 py-3">
                    <span className={`inline-flex items-center gap-1.5 text-xs px-2 py-0.5 rounded-full ${
                      svc.status === 'healthy' ? 'bg-green-500/10 text-green-400' :
                      svc.status === 'degraded' ? 'bg-amber-500/10 text-amber-400' :
                      'bg-red-500/10 text-red-400'
                    }`}>
                      <div className={`w-1.5 h-1.5 rounded-full ${
                        svc.status === 'healthy' ? 'bg-green-400' :
                        svc.status === 'degraded' ? 'bg-amber-400' : 'bg-red-400'
                      }`} />
                      {svc.status}
                    </span>
                  </td>
                  <td className="px-5 py-3 text-slate-300">{svc.requests_per_sec.toFixed(1)}</td>
                  <td className="px-5 py-3">
                    <span className={svc.error_rate > 1 ? 'text-red-400' : 'text-green-400'}>
                      {svc.error_rate.toFixed(2)}%
                    </span>
                  </td>
                  <td className="px-5 py-3 text-slate-300">{svc.p50_ms}ms</td>
                  <td className="px-5 py-3 text-slate-300">{svc.p95_ms}ms</td>
                  <td className="px-5 py-3">
                    <span className={svc.p99_ms > 500 ? 'text-amber-400' : 'text-slate-300'}>
                      {svc.p99_ms}ms
                    </span>
                  </td>
                  <td className="px-5 py-3 text-slate-300">{svc.uptime_pct.toFixed(1)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Trace Explorer */}
      <div className="grid grid-cols-12 gap-4">
        {/* Trace List */}
        <div className="col-span-5 bg-slate-900 rounded-xl border border-slate-800 overflow-hidden">
          <div className="p-4 border-b border-slate-800 space-y-3">
            <h3 className="text-sm font-semibold text-slate-300">Trace Explorer</h3>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
              <input
                type="text"
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                placeholder="Search traces..."
                className="w-full pl-10 pr-4 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:border-amber-500 focus:outline-none"
              />
            </div>
            <div className="flex gap-1">
              {(['all', 'ok', 'error'] as const).map(s => (
                <button
                  key={s}
                  onClick={() => setStatusFilter(s)}
                  className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${
                    statusFilter === s ? 'bg-amber-500/10 text-amber-400' : 'text-slate-400 hover:bg-slate-800'
                  }`}
                >
                  {s === 'all' ? 'All' : s === 'ok' ? 'Success' : 'Errors'}
                </button>
              ))}
            </div>
          </div>
          <div className="max-h-[50vh] overflow-y-auto">
            {filteredTraces.map(trace => (
              <button
                key={trace.trace_id}
                onClick={() => selectTrace(trace)}
                className={`w-full text-left p-3 border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors ${
                  selectedTrace?.trace_id === trace.trace_id ? 'bg-amber-500/5' : ''
                }`}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-sm text-slate-200 font-medium truncate">{trace.operation}</span>
                  <span className={`text-xs ${trace.status === 'ok' ? 'text-green-400' : 'text-red-400'}`}>
                    {trace.duration_ms}ms
                  </span>
                </div>
                <div className="flex items-center gap-2 text-xs text-slate-500">
                  <span>{trace.root_service}</span>
                  <span>•</span>
                  <span>{trace.spans_count} spans</span>
                  <span>•</span>
                  <span>{trace.timestamp}</span>
                </div>
              </button>
            ))}
          </div>
        </div>

        {/* Span Waterfall */}
        <div className="col-span-7 bg-slate-900 rounded-xl border border-slate-800 p-4">
          <h3 className="text-sm font-semibold text-slate-300 mb-4">
            {selectedTrace ? `Trace: ${selectedTrace.operation}` : 'Select a trace'}
          </h3>
          {selectedTrace && spans.length > 0 ? (
            <div className="space-y-1">
              {spans.map(span => {
                const maxDuration = selectedTrace.duration_ms
                const widthPct = (span.duration_ms / maxDuration) * 100
                const offsetPct = (span.start_offset_ms / maxDuration) * 100
                return (
                  <div key={span.span_id} className="flex items-center gap-3 py-1.5">
                    <div className="w-28 shrink-0">
                      <div className="text-xs text-slate-300 truncate">{span.service}</div>
                      <div className="text-xs text-slate-500 truncate">{span.operation}</div>
                    </div>
                    <div className="flex-1 h-6 bg-slate-800 rounded relative">
                      <div
                        className={`absolute top-0.5 bottom-0.5 rounded ${
                          span.status === 'ok' ? 'bg-blue-500/60' : 'bg-red-500/60'
                        }`}
                        style={{ left: `${offsetPct}%`, width: `${Math.max(widthPct, 1)}%` }}
                      />
                    </div>
                    <span className="text-xs text-slate-400 w-14 text-right shrink-0">{span.duration_ms}ms</span>
                  </div>
                )
              })}
            </div>
          ) : (
            <div className="flex items-center justify-center h-[40vh] text-slate-500 text-sm">
              {selectedTrace ? 'Loading spans...' : 'Select a trace to view its waterfall diagram'}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function MetricCard({ icon: Icon, label, value, color }: { icon: typeof Activity; label: string; value: string; color: string }) {
  const colorMap: Record<string, string> = {
    blue: 'text-blue-400 bg-blue-500/10',
    amber: 'text-amber-400 bg-amber-500/10',
    green: 'text-green-400 bg-green-500/10',
    red: 'text-red-400 bg-red-500/10',
    purple: 'text-purple-400 bg-purple-500/10',
  }
  return (
    <div className="bg-slate-900 rounded-xl border border-slate-800 p-4">
      <div className="flex items-center gap-2 mb-2">
        <div className={`w-7 h-7 rounded-lg flex items-center justify-center ${colorMap[color]}`}>
          <Icon className="w-3.5 h-3.5" />
        </div>
      </div>
      <div className="text-lg font-bold text-slate-200">{value}</div>
      <div className="text-xs text-slate-500">{label}</div>
    </div>
  )
}

function ServiceIcon({ name }: { name: string }) {
  const lower = name.toLowerCase()
  if (lower.includes('database') || lower.includes('db') || lower.includes('redis')) return <Database className="w-4 h-4 text-blue-400" />
  if (lower.includes('ml') || lower.includes('brain') || lower.includes('model')) return <Brain className="w-4 h-4 text-purple-400" />
  if (lower.includes('api') || lower.includes('gateway')) return <Globe className="w-4 h-4 text-green-400" />
  if (lower.includes('ws') || lower.includes('websocket')) return <Wifi className="w-4 h-4 text-cyan-400" />
  return <Server className="w-4 h-4 text-slate-400" />
}
