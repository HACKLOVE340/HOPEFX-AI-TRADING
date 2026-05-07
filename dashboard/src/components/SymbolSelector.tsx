/**
 * SymbolSelector
 *
 * Searchable instrument picker with category tabs and live price display.
 * Reads from the /api/trading/symbols endpoint and live price ticks from the store.
 */
import { useEffect, useRef, useState, useCallback } from 'react'
import { Search, ChevronDown, Star, X } from 'lucide-react'
import { useStore } from '../store/useStore'
import { tradingApi } from '../hooks/useApi'
import type { SymbolInfo } from '../store/useStore'

const CATEGORIES = ['all', 'forex', 'metals', 'crypto', 'indices', 'commodities'] as const
type Category = (typeof CATEGORIES)[number]

interface Props {
  onSelect?: (symbol: string) => void
  compact?: boolean
}

export function SymbolSelector({ onSelect, compact = false }: Props) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState<Category>('all')
  const [symbols, setSymbols] = useState<SymbolInfo[]>([])
  const [loading, setLoading] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)

  const activeSymbol = useStore((s) => s.activeSymbol)
  const setActiveSymbol = useStore((s) => s.setActiveSymbol)
  const prices = useStore((s) => s.prices)
  const watchlist = useStore((s) => s.watchlist)
  const addToWatchlist = useStore((s) => s.addToWatchlist)
  const removeFromWatchlist = useStore((s) => s.removeFromWatchlist)

  const loadSymbols = useCallback(async () => {
    setLoading(true)
    try {
      const res = await tradingApi.symbolList()
      setSymbols(res.data)
    } catch {
      // keep empty — will show no results
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadSymbols()
  }, [loadSymbols])

  // Close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const filtered = symbols.filter((s) => {
    const matchCat = category === 'all' || s.category === category
    const matchQ =
      !query ||
      s.symbol.includes(query.toUpperCase()) ||
      s.description.toLowerCase().includes(query.toLowerCase())
    return matchCat && matchQ
  })

  const activeTick = prices[activeSymbol]

  const handleSelect = (sym: string) => {
    setActiveSymbol(sym)
    onSelect?.(sym)
    setOpen(false)
    setQuery('')
  }

  const toggleWatchlist = (e: React.MouseEvent, sym: string) => {
    e.stopPropagation()
    if (watchlist.includes(sym)) {
      removeFromWatchlist(sym)
    } else {
      addToWatchlist(sym)
    }
  }

  return (
    <div ref={dropdownRef} className="relative">
      {/* Trigger */}
      <button
        onClick={() => setOpen((v) => !v)}
        className={`flex items-center gap-2 bg-slate-800 border border-slate-700 rounded-lg
          hover:border-amber-500/50 transition-colors
          ${compact ? 'px-3 py-1.5 text-sm' : 'px-4 py-2'}`}
      >
        <span className="font-bold text-slate-100">{activeSymbol}</span>
        {activeTick && (
          <span
            className={`text-xs font-mono ${
              activeTick.change_pct >= 0 ? 'text-green-400' : 'text-red-400'
            }`}
          >
            {activeTick.change_pct >= 0 ? '+' : ''}
            {activeTick.change_pct.toFixed(2)}%
          </span>
        )}
        <ChevronDown className={`w-4 h-4 text-slate-400 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {/* Dropdown */}
      {open && (
        <div className="absolute top-full left-0 mt-1 w-80 bg-slate-900 border border-slate-700 rounded-xl shadow-2xl z-50 overflow-hidden">
          {/* Search */}
          <div className="p-3 border-b border-slate-800">
            <div className="flex items-center gap-2 bg-slate-800 rounded-lg px-3 py-2">
              <Search className="w-4 h-4 text-slate-400 shrink-0" />
              <input
                autoFocus
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search symbol or name…"
                className="flex-1 bg-transparent text-sm text-slate-100 placeholder-slate-500 outline-none"
              />
              {query && (
                <button onClick={() => setQuery('')}>
                  <X className="w-3 h-3 text-slate-500 hover:text-slate-300" />
                </button>
              )}
            </div>
          </div>

          {/* Category tabs */}
          <div className="flex gap-1 px-3 py-2 border-b border-slate-800 overflow-x-auto scrollbar-none">
            {CATEGORIES.map((cat) => (
              <button
                key={cat}
                onClick={() => setCategory(cat)}
                className={`px-2.5 py-1 rounded text-xs font-medium whitespace-nowrap transition-colors ${
                  category === cat
                    ? 'bg-amber-500/20 text-amber-400'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
                }`}
              >
                {cat.charAt(0).toUpperCase() + cat.slice(1)}
              </button>
            ))}
          </div>

          {/* Symbol list */}
          <div className="max-h-72 overflow-y-auto">
            {loading ? (
              <div className="py-8 text-center text-slate-500 text-sm">Loading instruments…</div>
            ) : filtered.length === 0 ? (
              <div className="py-8 text-center text-slate-500 text-sm">No instruments found</div>
            ) : (
              filtered.map((sym) => {
                const tick = prices[sym.symbol]
                const inWatchlist = watchlist.includes(sym.symbol)
                const isActive = sym.symbol === activeSymbol
                return (
                  <button
                    key={sym.symbol}
                    onClick={() => handleSelect(sym.symbol)}
                    className={`w-full flex items-center gap-3 px-4 py-2.5 hover:bg-slate-800 transition-colors text-left
                      ${isActive ? 'bg-amber-500/10' : ''}`}
                  >
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className={`font-mono font-semibold text-sm ${isActive ? 'text-amber-400' : 'text-slate-100'}`}>
                          {sym.symbol}
                        </span>
                        <span className={`text-xs px-1.5 py-0.5 rounded ${
                          sym.category === 'metals'      ? 'bg-yellow-500/10 text-yellow-400' :
                          sym.category === 'forex'       ? 'bg-blue-500/10 text-blue-400' :
                          sym.category === 'crypto'      ? 'bg-purple-500/10 text-purple-400' :
                          sym.category === 'indices'     ? 'bg-green-500/10 text-green-400' :
                          sym.category === 'commodities' ? 'bg-orange-500/10 text-orange-400' :
                          'bg-slate-700 text-slate-400'
                        }`}>
                          {sym.category}
                        </span>
                      </div>
                      <div className="text-xs text-slate-500 truncate">{sym.description}</div>
                    </div>
                    <div className="text-right shrink-0">
                      {tick ? (
                        <>
                          <div className="text-sm font-mono text-slate-200">{tick.mid.toFixed(sym.pip_size < 0.001 ? 5 : 2)}</div>
                          <div className={`text-xs ${tick.change_pct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                            {tick.change_pct >= 0 ? '+' : ''}{tick.change_pct.toFixed(2)}%
                          </div>
                        </>
                      ) : (
                        <div className="text-xs text-slate-600">—</div>
                      )}
                    </div>
                    <button
                      onClick={(e) => toggleWatchlist(e, sym.symbol)}
                      className={`p-1 rounded transition-colors ${
                        inWatchlist ? 'text-amber-400' : 'text-slate-600 hover:text-slate-400'
                      }`}
                      title={inWatchlist ? 'Remove from watchlist' : 'Add to watchlist'}
                    >
                      <Star className="w-3.5 h-3.5" fill={inWatchlist ? 'currentColor' : 'none'} />
                    </button>
                  </button>
                )
              })
            )}
          </div>
        </div>
      )}
    </div>
  )
}
