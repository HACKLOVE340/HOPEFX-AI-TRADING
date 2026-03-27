/**
 * Signal Feed / Social Feed — dashboard version (Tailwind)
 * Wires to: GET /api/social/feed  |  GET /api/trading/signals
 */
import { useState, useEffect } from 'react'
import { Radio, TrendingUp, TrendingDown, Minus, Heart, MessageCircle, Share2, RefreshCw } from 'lucide-react'
import axios from 'axios'

interface FeedItem {
  id: string
  type: 'signal' | 'trade' | 'analysis'
  author: string
  avatar: string
  timestamp: string
  symbol: string
  direction: 'long' | 'short' | 'neutral'
  confidence?: number
  entry?: number
  sl?: number
  tp?: number
  content: string
  likes: number
  comments: number
  liked: boolean
}

const MOCK_FEED: FeedItem[] = [
  { id: '1', type: 'signal', author: 'HopeFX AI', avatar: 'H', timestamp: '2m ago', symbol: 'XAU/USD', direction: 'long', confidence: 72.4, entry: 2341.20, sl: 2328.50, tp: 2368.00, content: 'ML ensemble signal: LONG XAU/USD. COT proxy shows central bank demand signature. Regime: trending. ATR stop at 1.5×.', likes: 14, comments: 3, liked: false },
  { id: '2', type: 'trade', author: 'AlgoTrader_99', avatar: 'A', timestamp: '18m ago', symbol: 'EUR/USD', direction: 'short', confidence: 65.1, entry: 1.0842, sl: 1.0870, tp: 1.0790, content: 'Shorting EUR/USD on DXY strength. NFP tomorrow — tight stop.', likes: 7, comments: 1, liked: true },
  { id: '3', type: 'analysis', author: 'MacroView', avatar: 'M', timestamp: '1h ago', symbol: 'XAU/USD', direction: 'neutral', content: 'Gold consolidating at 2340 support. Watch for breakout above 2360 or breakdown below 2320. COT data shows net longs at 6-month high.', likes: 22, comments: 8, liked: false },
  { id: '4', type: 'signal', author: 'HopeFX AI', avatar: 'H', timestamp: '3h ago', symbol: 'BTC/USD', direction: 'long', confidence: 61.8, entry: 67240, sl: 65800, tp: 70500, content: 'BTC/USD breakout signal. Volume anomaly detected (+2.3σ). Regime: trending. Lower confidence — reduce size.', likes: 31, comments: 12, liked: false },
  { id: '5', type: 'trade', author: 'GoldBull_FX', avatar: 'G', timestamp: '5h ago', symbol: 'XAU/USD', direction: 'long', entry: 2335.00, sl: 2322.00, tp: 2361.00, content: 'Closed XAU/USD long +$26.00 (+1.11%). Held 9.2 hours. Model called it right again.', likes: 18, comments: 5, liked: true },
]

const DirectionBadge = ({ dir }: { dir: 'long' | 'short' | 'neutral' }) => {
  const cfg = {
    long:    { icon: TrendingUp,   cls: 'bg-green-500/20 text-green-400 border-green-500/30',  label: 'LONG' },
    short:   { icon: TrendingDown, cls: 'bg-red-500/20 text-red-400 border-red-500/30',        label: 'SHORT' },
    neutral: { icon: Minus,        cls: 'bg-slate-500/20 text-slate-400 border-slate-500/30',  label: 'NEUTRAL' },
  }[dir]
  const Icon = cfg.icon
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-xs font-bold ${cfg.cls}`}>
      <Icon className="w-3 h-3" />{cfg.label}
    </span>
  )
}

export default function SocialFeed() {
  const [feed, setFeed] = useState<FeedItem[]>(MOCK_FEED)
  const [loading, setLoading] = useState(false)
  const [filter, setFilter] = useState<'all' | 'signal' | 'trade' | 'analysis'>('all')

  const refresh = async () => {
    setLoading(true)
    try {
      const res = await axios.get('/api/social/feed')
      setFeed(res.data.items ?? MOCK_FEED)
    } catch {
      setFeed(MOCK_FEED)
    } finally {
      setLoading(false)
    }
  }

  const toggleLike = (id: string) => {
    setFeed(prev => prev.map(item =>
      item.id === id ? { ...item, liked: !item.liked, likes: item.liked ? item.likes - 1 : item.likes + 1 } : item
    ))
  }

  const filtered = filter === 'all' ? feed : feed.filter(f => f.type === filter)

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Radio className="w-7 h-7 text-amber-400" />
          <div>
            <h1 className="text-2xl font-bold text-slate-100">Signal Feed</h1>
            <p className="text-sm text-slate-400">Live ML signals, trades, and market analysis.</p>
          </div>
        </div>
        <button onClick={refresh} disabled={loading}
          className="flex items-center gap-2 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-sm transition-colors">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* Filter tabs */}
      <div className="flex gap-2">
        {(['all', 'signal', 'trade', 'analysis'] as const).map(f => (
          <button key={f} onClick={() => setFilter(f)}
            className={`px-4 py-1.5 rounded-full text-sm font-medium transition-colors capitalize ${
              filter === f ? 'bg-amber-500 text-slate-900' : 'bg-slate-800 text-slate-400 hover:text-slate-200'
            }`}>
            {f}
          </button>
        ))}
      </div>

      {/* Feed */}
      <div className="space-y-4">
        {filtered.map(item => (
          <div key={item.id} className="bg-slate-900 rounded-xl border border-slate-800 p-5">
            <div className="flex items-start gap-3">
              <div className={`w-9 h-9 rounded-full flex items-center justify-center text-sm font-bold flex-shrink-0 ${
                item.author === 'HopeFX AI' ? 'bg-amber-500 text-slate-900' : 'bg-slate-700 text-slate-300'
              }`}>
                {item.avatar}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-semibold text-slate-200 text-sm">{item.author}</span>
                  {item.author === 'HopeFX AI' && (
                    <span className="text-xs bg-amber-500/20 text-amber-400 border border-amber-500/30 px-1.5 py-0.5 rounded-full">AI</span>
                  )}
                  <span className="text-xs text-slate-600">{item.timestamp}</span>
                  <span className="text-xs text-slate-500 bg-slate-800 px-2 py-0.5 rounded">{item.symbol}</span>
                  <DirectionBadge dir={item.direction} />
                  {item.confidence && (
                    <span className="text-xs text-slate-500">{item.confidence.toFixed(1)}% conf</span>
                  )}
                </div>

                <p className="text-sm text-slate-300 mt-2 leading-relaxed">{item.content}</p>

                {(item.entry || item.sl || item.tp) && (
                  <div className="flex gap-4 mt-3 text-xs">
                    {item.entry && <span className="text-slate-400">Entry: <span className="text-slate-200 font-medium">{item.entry.toLocaleString()}</span></span>}
                    {item.sl    && <span className="text-red-400">SL: <span className="font-medium">{item.sl.toLocaleString()}</span></span>}
                    {item.tp    && <span className="text-green-400">TP: <span className="font-medium">{item.tp.toLocaleString()}</span></span>}
                  </div>
                )}

                <div className="flex items-center gap-4 mt-3">
                  <button onClick={() => toggleLike(item.id)}
                    className={`flex items-center gap-1.5 text-xs transition-colors ${item.liked ? 'text-red-400' : 'text-slate-500 hover:text-red-400'}`}>
                    <Heart className={`w-3.5 h-3.5 ${item.liked ? 'fill-current' : ''}`} />
                    {item.likes}
                  </button>
                  <button className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-blue-400 transition-colors">
                    <MessageCircle className="w-3.5 h-3.5" />
                    {item.comments}
                  </button>
                  <button className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-green-400 transition-colors">
                    <Share2 className="w-3.5 h-3.5" />
                    Share
                  </button>
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
