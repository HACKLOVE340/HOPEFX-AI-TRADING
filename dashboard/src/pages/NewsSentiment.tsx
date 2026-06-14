/**
 * NewsSentiment — News & Sentiment Analysis Dashboard
 *
 * Exposes:
 * - Real-time news feed with sentiment scoring
 * - Nuclear wordmap visualization (high-impact event detection)
 * - Sentiment heatmap by currency/asset
 * - News impact on price correlation
 * - Event-driven trade signals
 * - Historical sentiment vs price overlay
 *
 * Backend: /api/news/*, news/nuclear_wordmap_scorer.py, data_layer/feeds/news/
 */
import { useEffect, useState, useCallback } from 'react'
import {
  Newspaper, AlertTriangle, TrendingUp, TrendingDown, Activity,
  Clock, Shield, Zap, Globe, BarChart2, Filter, RefreshCw,
  AlertOctagon, CheckCircle, MinusCircle,
} from 'lucide-react'

// ── Types ─────────────────────────────────────────────────────────────────────
interface NewsItem {
  id: string
  title: string
  source: string
  published_at: string
  sentiment_score: number // -1 to 1
  impact_level: 'low' | 'medium' | 'high' | 'nuclear'
  affected_symbols: string[]
  summary: string
  nuclear_words_detected: string[]
  url: string
}

interface SentimentOverview {
  overall_market_sentiment: number
  bullish_count: number
  bearish_count: number
  neutral_count: number
  nuclear_events_active: number
  last_updated: string
}

interface CurrencySentiment {
  symbol: string
  sentiment: number
  news_count: number
  trend: 'improving' | 'declining' | 'stable'
  nuclear_alert: boolean
}

interface NuclearEvent {
  id: string
  event_type: string
  severity: number
  detected_at: string
  affected_pairs: string[]
  nuclear_words: string[]
  recommended_action: 'halt_trading' | 'reduce_exposure' | 'monitor' | 'hedge'
  status: 'active' | 'resolved' | 'monitoring'
}

// ── Component ─────────────────────────────────────────────────────────────────
export function NewsSentiment() {
  const [news, setNews] = useState<NewsItem[]>([])
  const [overview, setOverview] = useState<SentimentOverview | null>(null)
  const [currencySentiments, setCurrencySentiments] = useState<CurrencySentiment[]>([])
  const [nuclearEvents, setNuclearEvents] = useState<NuclearEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<'all' | 'high' | 'nuclear'>('all')

  const headers = { Authorization: `Bearer ${localStorage.getItem('token')}` }

  const fetchAll = useCallback(async () => {
    setLoading(true)
    try {
      const [newsRes, overviewRes, sentimentRes, nuclearRes] = await Promise.all([
        fetch('/api/news/feed', { headers }),
        fetch('/api/news/sentiment/overview', { headers }),
        fetch('/api/news/sentiment/by-currency', { headers }),
        fetch('/api/news/nuclear-events', { headers }),
      ])
      if (newsRes.ok) { const d = await newsRes.json(); setNews(d.articles || []) }
      if (overviewRes.ok) setOverview(await overviewRes.json())
      if (sentimentRes.ok) { const d = await sentimentRes.json(); setCurrencySentiments(d.sentiments || []) }
      if (nuclearRes.ok) { const d = await nuclearRes.json(); setNuclearEvents(d.events || []) }
    } catch (err) {
      console.error('News fetch error:', err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchAll(); const id = setInterval(fetchAll, 30_000); return () => clearInterval(id) }, [fetchAll])

  const filteredNews = news.filter(item => {
    if (filter === 'all') return true
    if (filter === 'high') return item.impact_level === 'high' || item.impact_level === 'nuclear'
    return item.impact_level === 'nuclear'
  })

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">News & Sentiment</h1>
          <p className="text-sm text-slate-400 mt-1">
            Real-time market sentiment analysis with nuclear event detection
          </p>
        </div>
        <button onClick={fetchAll} className="flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-sm transition-colors">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </button>
      </div>

      {/* Nuclear Alert Banner */}
      {nuclearEvents.filter(e => e.status === 'active').length > 0 && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4 flex items-center gap-4">
          <AlertOctagon className="w-6 h-6 text-red-400 shrink-0 animate-pulse" />
          <div className="flex-1">
            <div className="font-semibold text-red-400 text-sm">Nuclear Event Active</div>
            <div className="text-xs text-red-300/70 mt-0.5">
              {nuclearEvents.filter(e => e.status === 'active').length} high-impact events detected.
              Trading may be restricted on affected pairs.
            </div>
          </div>
          <Shield className="w-5 h-5 text-red-400" />
        </div>
      )}

      {/* Overview Stats */}
      {overview && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <div className="bg-slate-900 rounded-xl border border-slate-800 p-4">
            <div className="text-xs text-slate-500 mb-1">Market Sentiment</div>
            <div className={`text-2xl font-bold ${overview.overall_market_sentiment > 0.1 ? 'text-green-400' : overview.overall_market_sentiment < -0.1 ? 'text-red-400' : 'text-slate-300'}`}>
              {overview.overall_market_sentiment > 0 ? '+' : ''}{(overview.overall_market_sentiment * 100).toFixed(0)}%
            </div>
          </div>
          <div className="bg-slate-900 rounded-xl border border-slate-800 p-4">
            <div className="text-xs text-slate-500 mb-1">Bullish</div>
            <div className="text-2xl font-bold text-green-400">{overview.bullish_count}</div>
          </div>
          <div className="bg-slate-900 rounded-xl border border-slate-800 p-4">
            <div className="text-xs text-slate-500 mb-1">Bearish</div>
            <div className="text-2xl font-bold text-red-400">{overview.bearish_count}</div>
          </div>
          <div className="bg-slate-900 rounded-xl border border-slate-800 p-4">
            <div className="text-xs text-slate-500 mb-1">Neutral</div>
            <div className="text-2xl font-bold text-slate-300">{overview.neutral_count}</div>
          </div>
          <div className="bg-slate-900 rounded-xl border border-slate-800 p-4">
            <div className="text-xs text-slate-500 mb-1">Nuclear Events</div>
            <div className={`text-2xl font-bold ${overview.nuclear_events_active > 0 ? 'text-red-400' : 'text-green-400'}`}>
              {overview.nuclear_events_active}
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-12 gap-6">
        {/* News Feed */}
        <div className="col-span-8 space-y-4">
          {/* Filter */}
          <div className="flex items-center gap-2">
            <Filter className="w-4 h-4 text-slate-500" />
            {(['all', 'high', 'nuclear'] as const).map(f => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                  filter === f ? 'bg-amber-500/10 text-amber-400 border border-amber-500/30' : 'text-slate-400 hover:bg-slate-800'
                }`}
              >
                {f === 'all' ? 'All News' : f === 'high' ? 'High Impact' : 'Nuclear Only'}
              </button>
            ))}
          </div>

          {/* News List */}
          <div className="space-y-3">
            {filteredNews.map(item => (
              <div key={item.id} className={`bg-slate-900 rounded-xl border p-4 ${
                item.impact_level === 'nuclear' ? 'border-red-500/30' :
                item.impact_level === 'high' ? 'border-amber-500/20' : 'border-slate-800'
              }`}>
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <ImpactBadge level={item.impact_level} />
                      <span className="text-xs text-slate-500">{item.source}</span>
                      <span className="text-xs text-slate-600">•</span>
                      <span className="text-xs text-slate-500">{item.published_at}</span>
                    </div>
                    <h4 className="text-sm font-medium text-slate-200 mb-1">{item.title}</h4>
                    <p className="text-xs text-slate-400 mb-2">{item.summary}</p>
                    <div className="flex items-center gap-3">
                      <div className="flex items-center gap-1">
                        <SentimentIcon score={item.sentiment_score} />
                        <span className={`text-xs font-medium ${
                          item.sentiment_score > 0.2 ? 'text-green-400' :
                          item.sentiment_score < -0.2 ? 'text-red-400' : 'text-slate-400'
                        }`}>
                          {item.sentiment_score > 0 ? '+' : ''}{(item.sentiment_score * 100).toFixed(0)}%
                        </span>
                      </div>
                      <div className="flex gap-1">
                        {item.affected_symbols.slice(0, 4).map(sym => (
                          <span key={sym} className="text-xs px-1.5 py-0.5 bg-slate-800 rounded text-slate-300">{sym}</span>
                        ))}
                      </div>
                      {item.nuclear_words_detected.length > 0 && (
                        <div className="flex gap-1">
                          {item.nuclear_words_detected.slice(0, 3).map(word => (
                            <span key={word} className="text-xs px-1.5 py-0.5 bg-red-500/10 border border-red-500/30 rounded text-red-400">{word}</span>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Sidebar */}
        <div className="col-span-4 space-y-4">
          {/* Currency Sentiment Heatmap */}
          <div className="bg-slate-900 rounded-xl border border-slate-800 p-4">
            <h3 className="text-sm font-semibold text-slate-300 mb-3 flex items-center gap-2">
              <BarChart2 className="w-4 h-4 text-amber-400" />
              Sentiment by Asset
            </h3>
            <div className="space-y-2">
              {currencySentiments.map(cs => (
                <div key={cs.symbol} className="flex items-center justify-between p-2 bg-slate-800 rounded-lg">
                  <div className="flex items-center gap-2">
                    {cs.nuclear_alert && <AlertTriangle className="w-3 h-3 text-red-400" />}
                    <span className="text-sm text-slate-200 font-medium">{cs.symbol}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="w-16 h-1.5 bg-slate-700 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full ${cs.sentiment > 0.1 ? 'bg-green-400' : cs.sentiment < -0.1 ? 'bg-red-400' : 'bg-slate-500'}`}
                        style={{ width: `${Math.abs(cs.sentiment) * 100}%`, marginLeft: cs.sentiment < 0 ? 'auto' : undefined }}
                      />
                    </div>
                    <span className={`text-xs w-8 text-right ${cs.sentiment > 0 ? 'text-green-400' : cs.sentiment < 0 ? 'text-red-400' : 'text-slate-400'}`}>
                      {cs.sentiment > 0 ? '+' : ''}{(cs.sentiment * 100).toFixed(0)}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Nuclear Events */}
          <div className="bg-slate-900 rounded-xl border border-slate-800 p-4">
            <h3 className="text-sm font-semibold text-slate-300 mb-3 flex items-center gap-2">
              <AlertOctagon className="w-4 h-4 text-red-400" />
              Nuclear Events
            </h3>
            {nuclearEvents.length === 0 ? (
              <div className="text-center py-6">
                <CheckCircle className="w-8 h-8 text-green-400 mx-auto mb-2" />
                <p className="text-xs text-slate-500">No nuclear events detected</p>
              </div>
            ) : (
              <div className="space-y-2">
                {nuclearEvents.map(event => (
                  <div key={event.id} className={`p-3 rounded-lg border ${
                    event.status === 'active' ? 'bg-red-500/5 border-red-500/20' :
                    event.status === 'monitoring' ? 'bg-amber-500/5 border-amber-500/20' :
                    'bg-slate-800 border-slate-700'
                  }`}>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs font-medium text-slate-200">{event.event_type}</span>
                      <span className={`text-xs px-1.5 py-0.5 rounded ${
                        event.status === 'active' ? 'bg-red-500/20 text-red-400' :
                        event.status === 'monitoring' ? 'bg-amber-500/20 text-amber-400' :
                        'bg-green-500/20 text-green-400'
                      }`}>{event.status}</span>
                    </div>
                    <div className="text-xs text-slate-500 mb-1">
                      Action: <span className="text-slate-300">{event.recommended_action.replace('_', ' ')}</span>
                    </div>
                    <div className="flex gap-1 flex-wrap">
                      {event.affected_pairs.map(pair => (
                        <span key={pair} className="text-xs px-1 py-0.5 bg-slate-800 rounded text-slate-400">{pair}</span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Helper Components ─────────────────────────────────────────────────────────
function ImpactBadge({ level }: { level: string }) {
  const styles: Record<string, string> = {
    low: 'bg-slate-500/10 text-slate-400 border-slate-500/30',
    medium: 'bg-blue-500/10 text-blue-400 border-blue-500/30',
    high: 'bg-amber-500/10 text-amber-400 border-amber-500/30',
    nuclear: 'bg-red-500/10 text-red-400 border-red-500/30',
  }
  return (
    <span className={`text-xs px-1.5 py-0.5 rounded border ${styles[level] || styles.low}`}>
      {level}
    </span>
  )
}

function SentimentIcon({ score }: { score: number }) {
  if (score > 0.2) return <TrendingUp className="w-3.5 h-3.5 text-green-400" />
  if (score < -0.2) return <TrendingDown className="w-3.5 h-3.5 text-red-400" />
  return <MinusCircle className="w-3.5 h-3.5 text-slate-400" />
}
