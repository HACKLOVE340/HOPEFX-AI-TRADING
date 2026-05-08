/**
 * Signal Feed / Social Feed
 * Wires to: GET /api/feed (paginated community signals from opted-in traders)
 */
import { useState, useEffect, useCallback } from 'react'
import {
  Radio, TrendingUp, TrendingDown, Minus,
  Heart, MessageCircle, Share2, RefreshCw,
  AlertTriangle, Loader2,
} from 'lucide-react'
import { useStore } from '../store/useStore'
import { extractApiError } from '../lib/utils'

interface FeedItem {
  signal_id: string
  symbol: string
  direction: 'BUY' | 'SELL' | 'HOLD' | 'long' | 'short' | 'neutral'
  confidence: number
  entry_price?: number
  pnl?: number
  copies?: number
  username: string
  trader_id: string
  thumbs_up: number
  thumbs_down: number
  comment_count: number
  is_public: boolean
  created_at: string
}

type FilterType = 'all' | 'BUY' | 'SELL' | 'HOLD'
type FetchState = 'idle' | 'loading' | 'ok' | 'empty' | 'error'

// Normalise direction to frontend display values
function normaliseDir(d: string): 'long' | 'short' | 'neutral' {
  const u = d.toUpperCase()
  if (u === 'BUY' || u === 'LONG')  return 'long'
  if (u === 'SELL' || u === 'SHORT') return 'short'
  return 'neutral'
}

const DirectionBadge = ({ dir }: { dir: string }) => {
  const norm = normaliseDir(dir)
  const cfg = {
    long:    { icon: TrendingUp,   cls: 'bg-green-500/20 text-green-400 border-green-500/30',  label: 'LONG' },
    short:   { icon: TrendingDown, cls: 'bg-red-500/20 text-red-400 border-red-500/30',        label: 'SHORT' },
    neutral: { icon: Minus,        cls: 'bg-slate-500/20 text-slate-400 border-slate-500/30',  label: 'NEUTRAL' },
  }[norm]
  const Icon = cfg.icon
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-xs font-bold ${cfg.cls}`}>
      <Icon className="w-3 h-3" />{cfg.label}
    </span>
  )
}

export default function SocialFeed() {
  const token = useStore((s) => s.token)
  const [feed, setFeed]           = useState<FeedItem[]>([])
  const [fetchState, setFetchState] = useState<FetchState>('idle')
  const [errorMsg, setErrorMsg]   = useState('')
  const [filter, setFilter]       = useState<FilterType>('all')
  // Local reaction state (optimistic updates)
  const [reactions, setReactions] = useState<Record<string, 'up' | 'down' | null>>({})

  const fetchFeed = useCallback(async () => {
    setFetchState('loading')
    setErrorMsg('')
    try {
      const res = await fetch('/api/feed?limit=50')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      const items: FeedItem[] = data.items ?? []
      setFeed(items)
      setFetchState(items.length === 0 ? 'empty' : 'ok')
    } catch (err: unknown) {
      setErrorMsg(extractApiError(err, 'Unknown error'))
      setFetchState('error')
    }
  }, [])

  useEffect(() => { fetchFeed() }, [fetchFeed])

  const react = async (signalId: string, reaction: 'up' | 'down') => {
    if (!token) return
    const prev = reactions[signalId] ?? null
    const next = prev === reaction ? null : reaction
    // Optimistic update
    setReactions((r) => ({ ...r, [signalId]: next }))
    try {
      await fetch(`/api/feed/${signalId}/react`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ reaction }),
      })
    } catch {
      // Revert on failure
      setReactions((r) => ({ ...r, [signalId]: prev }))
    }
  }

  const filtered = filter === 'all'
    ? feed
    : feed.filter((f) => normaliseDir(f.direction) === normaliseDir(filter))

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Radio className="w-7 h-7 text-amber-400" />
          <div>
            <h1 className="text-2xl font-bold text-slate-100">Signal Feed</h1>
            <p className="text-sm text-slate-400">
              Live signals from opted-in traders. No synthetic data.
            </p>
          </div>
        </div>
        <button
          onClick={fetchFeed}
          disabled={fetchState === 'loading'}
          className="flex items-center gap-2 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-sm transition-colors disabled:opacity-50"
        >
          <RefreshCw className={`w-4 h-4 ${fetchState === 'loading' ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* Filter tabs */}
      <div className="flex gap-2">
        {(['all', 'BUY', 'SELL', 'HOLD'] as FilterType[]).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-4 py-1.5 rounded-full text-sm font-medium transition-colors ${
              filter === f
                ? 'bg-amber-500 text-slate-900'
                : 'bg-slate-800 text-slate-400 hover:text-slate-200'
            }`}
          >
            {f === 'all' ? 'All' : f}
          </button>
        ))}
      </div>

      {/* Loading */}
      {fetchState === 'loading' && (
        <div className="flex items-center justify-center py-16 gap-3 text-slate-500">
          <Loader2 className="w-5 h-5 animate-spin" />
          <span>Loading feed…</span>
        </div>
      )}

      {/* Error */}
      {fetchState === 'error' && (
        <div className="flex items-center gap-3 bg-red-500/10 border border-red-500/30 rounded-lg px-4 py-3 text-sm text-red-400">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          <span>Could not load feed: {errorMsg}</span>
          <button
            onClick={fetchFeed}
            className="ml-auto flex items-center gap-1 hover:text-red-300 transition-colors"
          >
            <RefreshCw className="w-3 h-3" /> Retry
          </button>
        </div>
      )}

      {/* Empty state */}
      {fetchState === 'empty' && (
        <div className="flex flex-col items-center justify-center py-16 gap-3 text-slate-500">
          <Radio className="w-10 h-10 opacity-30" />
          <p className="font-medium">No signals in the feed yet</p>
          <p className="text-sm text-slate-600 text-center max-w-sm">
            Signals appear here when opted-in traders generate high-confidence
            predictions. Go to Settings → Feed to opt in.
          </p>
        </div>
      )}

      {/* Feed items */}
      {fetchState === 'ok' && (
        <div className="space-y-4">
          {filtered.length === 0 ? (
            <p className="text-center text-slate-500 py-8">
              No {filter} signals in the feed.
            </p>
          ) : (
            filtered.map((item) => {
              const myReaction = reactions[item.signal_id] ?? null
              const thumbsUp   = item.thumbs_up   + (myReaction === 'up'   ? 1 : 0)
              const thumbsDown = item.thumbs_down + (myReaction === 'down' ? 1 : 0)
              return (
                <div key={item.signal_id} className="bg-slate-900 rounded-xl border border-slate-800 p-5">
                  <div className="flex items-start gap-3">
                    <div className="w-9 h-9 rounded-full bg-slate-700 text-slate-300 flex items-center justify-center text-sm font-bold flex-shrink-0">
                      {item.username.charAt(0).toUpperCase()}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-semibold text-slate-200 text-sm">{item.username}</span>
                        <span className="text-xs text-slate-600">
                          {new Date(item.created_at).toLocaleString()}
                        </span>
                        <span className="text-xs text-slate-500 bg-slate-800 px-2 py-0.5 rounded">
                          {item.symbol}
                        </span>
                        <DirectionBadge dir={item.direction} />
                        <span className="text-xs text-slate-500">
                          {item.confidence.toFixed(1)}% conf
                        </span>
                      </div>

                      {(item.entry_price || item.pnl !== undefined) && (
                        <div className="flex gap-4 mt-2 text-xs">
                          {item.entry_price && (
                            <span className="text-slate-400">
                              Entry:{' '}
                              <span className="text-slate-200 font-medium">
                                {item.entry_price.toLocaleString()}
                              </span>
                            </span>
                          )}
                          {item.pnl !== undefined && (
                            <span className={item.pnl >= 0 ? 'text-green-400' : 'text-red-400'}>
                              P&L:{' '}
                              <span className="font-medium">
                                {item.pnl >= 0 ? '+' : ''}${item.pnl.toFixed(2)}
                              </span>
                            </span>
                          )}
                          {item.copies !== undefined && item.copies > 0 && (
                            <span className="text-slate-500">{item.copies} copies</span>
                          )}
                        </div>
                      )}

                      <div className="flex items-center gap-4 mt-3">
                        <button
                          onClick={() => react(item.signal_id, 'up')}
                          className={`flex items-center gap-1.5 text-xs transition-colors ${
                            myReaction === 'up'
                              ? 'text-green-400'
                              : 'text-slate-500 hover:text-green-400'
                          }`}
                        >
                          <Heart className={`w-3.5 h-3.5 ${myReaction === 'up' ? 'fill-current' : ''}`} />
                          {thumbsUp}
                        </button>
                        <button className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-blue-400 transition-colors">
                          <MessageCircle className="w-3.5 h-3.5" />
                          {item.comment_count}
                        </button>
                        <button className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-green-400 transition-colors">
                          <Share2 className="w-3.5 h-3.5" />
                          Share
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              )
            })
          )}
        </div>
      )}
    </div>
  )
}
