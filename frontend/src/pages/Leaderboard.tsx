/**
 * Leaderboard — top traders ranked by return, Sharpe, win rate, followers.
 *
 * Wires to: GET /api/leaderboard?period={monthly|quarterly|all}&sort={return|sharpe|win_rate|followers}
 */

import React, { useState, useEffect, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { PageHeader, EmptyState, CrossLinkBar } from '../components';
import { RelatedPages } from '../components';
import { Medal, Trophy, BadgeCheck, Users, Radar, BookOpen, LineChart } from 'lucide-react';
import { api } from '../hooks/useApi';
import { extractApiError, fmtPctRaw, fmtRatio } from '../lib/utils';

/** Guarded sort value / integer formatter for possibly missing trader fields. */
const sv = (v: number | null | undefined) => (Number.isFinite(v as number) ? (v as number) : 0);
const fInt = (v: number | null | undefined) =>
  Number.isFinite(v as number) ? (v as number).toLocaleString() : '—';
const fPctPlain = (v: number | null | undefined, d = 1) =>
  Number.isFinite(v as number) ? `${(v as number).toFixed(d)}%` : '—';

interface Trader {
  rank: number;
  user_id?: string;
  name: string;
  return: number;
  sharpe: number;
  win_rate?: number;
  max_drawdown?: number;
  total_trades?: number;
  followers: number;
  prize: string;
  verified?: boolean;
  country?: string;
  strategy_tag?: string;
}

// Rank badges. Emoji medals render differently on every OS and cannot inherit
// the colour map below; a single Lucide medal tinted per rank does (F170).
const MEDAL_LABEL: Record<number, string> = { 1: 'First place', 2: 'Second place', 3: 'Third place' };
const MEDAL_COLORS: Record<number, string> = { 1: '#eab308', 2: '#94a3b8', 3: '#b45309' };

// ── Podium card ───────────────────────────────────────────────────────────────

const PodiumCard: React.FC<{ trader: Trader; tall?: boolean }> = ({ trader, tall }) => {
  const color = MEDAL_COLORS[trader.rank] ?? '#334155';
  const copyTo = trader.user_id
    ? `/copy-trading?trader=${trader.user_id}`
    : '/copy-trading';
  return (
    <div className={`flex-1 rounded-xl p-5 flex flex-col items-center gap-2 border transition-all hover:scale-[1.02] ${tall ? 'mt-0' : 'mt-6'}`}
      style={{ background: '#1e293b', borderColor: color + '55' }}>
      <div className="w-9 h-9 rounded-full flex items-center justify-center font-black text-sm"
        style={{ background: color, color: '#0f172a' }}>
        {trader.rank}
      </div>
      <div className="text-base font-bold text-slate-100 text-center">{trader.name}</div>
      {trader.country && <div className="text-xs text-slate-500">{trader.country}</div>}
      <div className="text-2xl font-black text-green-400">{fmtPctRaw(trader.return, 1)}</div>
      <div className="text-xs text-slate-500 text-center">
        Sharpe {fmtRatio(trader.sharpe)} · {fInt(trader.followers)} followers
      </div>
      {trader.strategy_tag && (
        <span className="text-2xs px-2 py-0.5 rounded-full border border-violet-500/40 text-violet-400 bg-violet-500/10">
          {trader.strategy_tag}
        </span>
      )}
      <div className="flex gap-2 w-full mt-1">
        <Link to={copyTo}
          className="flex-1 text-center py-1.5 rounded-lg font-bold text-xs no-underline transition-colors"
          style={{ background: color, color: '#0f172a' }}>
          🔁 Copy
        </Link>
        {trader.user_id && (
          <Link to={`/profile/${trader.user_id}`}
            className="px-3 py-1.5 rounded-lg text-xs font-semibold no-underline border border-terminal-border text-slate-400 hover:border-slate-500 transition-colors">
            Profile
          </Link>
        )}
      </div>
    </div>
  );
};

// ── Main component ────────────────────────────────────────────────────────────

const Leaderboard: React.FC = () => {
  const [period, setPeriod]   = useState<'monthly' | 'quarterly' | 'all'>('monthly');
  const [traders, setTraders] = useState<Trader[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadErr, setLoadErr] = useState('');
  const [sortBy, setSortBy]   = useState<'return' | 'sharpe' | 'win_rate' | 'followers'>('return');
  const [search, setSearch]   = useState('');
  const [stratFilter, setStratFilter] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setLoadErr('');
    api.get<Trader[]>(`/leaderboard?period=${period}`, { signal: controller.signal })
      .then((r) => setTraders(Array.isArray(r.data) ? r.data : []))
      .catch((err: unknown) => {
        if ((err as { name?: string }).name === 'CanceledError') return;
        setLoadErr(extractApiError(err, 'Failed to load leaderboard.'));
        setTraders([]);
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [period]);

  const stratTags = useMemo(() =>
    Array.from(new Set(traders.map(t => t.strategy_tag).filter(Boolean))) as string[],
    [traders]);

  const sorted = useMemo(() => {
    let list = [...traders];
    if (search) list = list.filter(t => t.name.toLowerCase().includes(search.toLowerCase()));
    if (stratFilter) list = list.filter(t => t.strategy_tag === stratFilter);
    list.sort((a, b) => {
      if (sortBy === 'return')    return sv(b.return) - sv(a.return);
      if (sortBy === 'sharpe')    return sv(b.sharpe) - sv(a.sharpe);
      if (sortBy === 'win_rate')  return sv(b.win_rate) - sv(a.win_rate);
      if (sortBy === 'followers') return sv(b.followers) - sv(a.followers);
      return 0;
    });
    return list;
  }, [traders, search, stratFilter, sortBy]);

  const top3 = sorted.slice(0, 3);

  return (
    <div className="page-content">
      <PageHeader
        title="Global Leaderboard"
        icon={Medal}
        subtitle="Top traders ranked by performance. Click a trader to copy their strategy."
        breadcrumbs={[
          { label: 'Dashboard',    href: '/dashboard' },
          { label: 'Community',    href: '/copy-trading' },
          { label: 'Leaderboard' },
        ]}
        actions={
          <div className="flex items-center gap-2 flex-wrap">
            {(['monthly', 'quarterly', 'all'] as const).map((p) => (
              <button key={p} onClick={() => setPeriod(p)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold border cursor-pointer transition-all ${
                  period === p
                    ? 'bg-blue-500/20 border-blue-500 text-blue-400'
                    : 'bg-transparent border-terminal-border text-slate-500 hover:border-slate-400'
                }`}>
                {p === 'all' ? 'All Time' : p.charAt(0).toUpperCase() + p.slice(1)}
              </button>
            ))}
            <div className="w-px h-5 bg-terminal-border" />
            <Link to="/copy-trading" className="px-3 py-1.5 bg-green-500/10 border border-green-500/30 rounded-lg text-green-400 text-xs font-semibold no-underline hover:bg-green-500/20 transition-colors">🔁 Copy Trading</Link>
            <Link to="/signals"      className="px-3 py-1.5 bg-violet-500/10 border border-violet-500/30 rounded-lg text-violet-400 text-xs font-semibold no-underline hover:bg-violet-500/20 transition-colors">📡 Signals</Link>
          </div>
        }
      />

      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-14 rounded-xl bg-terminal-surface border border-terminal-border animate-pulse" />
          ))}
        </div>
      ) : loadErr ? (
        <div className="bg-red-950/40 border border-red-800 rounded-xl p-4 text-red-400 text-sm">⚠️ {loadErr}</div>
      ) : traders.length === 0 ? (
        <EmptyState
          icon={Trophy}
          title="No traders ranked yet"
          description="The leaderboard populates once traders have closed positions. Start trading to appear here."
          action={
            <div className="flex gap-2">
              <Link to="/trade"        className="px-4 py-2 bg-blue-600 rounded-lg text-white text-sm font-semibold no-underline hover:bg-blue-500 transition-colors">⚡ Start Trading</Link>
              <Link to="/copy-trading" className="px-4 py-2 bg-transparent border border-terminal-border rounded-lg text-slate-400 text-sm no-underline hover:border-slate-500 transition-colors">🔁 Copy Trading</Link>
            </div>
          }
          links={[
            { label: '📡 Signals',    href: '/signals' },
            { label: '🛒 Marketplace',href: '/marketplace' },
          ]}
        />
      ) : (
        <>
          {/* Podium — horizontal scroll on xs, flex on sm+ */}
          <div className="flex gap-3 sm:gap-4 mb-6 sm:mb-8 items-end overflow-x-auto pb-1"
            style={{ scrollbarWidth: 'none' } as React.CSSProperties}>
            {[top3[1], top3[0], top3[2]].map((trader, i) =>
              trader
                ? <PodiumCard key={trader.rank} trader={trader} tall={i === 1} />
                : <div key={i} className="flex-1 min-w-[100px]" />
            )}
          </div>

          {/* Filters row — stacks on mobile */}
          <div className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-3 mb-4">
            <div className="flex gap-2 flex-1">
              <input
                type="text"
                placeholder="Search trader…"
                value={search}
                onChange={e => setSearch(e.target.value)}
                className="flex-1 min-w-0 bg-terminal-raised border border-terminal-border rounded-lg text-slate-100 px-3 py-2 text-sm outline-none focus:border-blue-500 transition-colors"
              />
              {stratTags.length > 0 && (
                <select value={stratFilter} onChange={e => setStratFilter(e.target.value)}
                  className="bg-terminal-raised border border-terminal-border rounded-lg text-slate-100 px-3 py-2 text-sm outline-none focus:border-blue-500 cursor-pointer flex-shrink-0">
                  <option value="">All strategies</option>
                  {stratTags.map(t => <option key={t} value={t}>{t}</option>)}
                </select>
              )}
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs text-slate-600">{sorted.length} traders · Sort:</span>
              {(['return', 'sharpe', 'win_rate', 'followers'] as const).map((col) => (
                <button key={col} onClick={() => setSortBy(col)}
                  className={`px-2.5 py-1 rounded-md text-xs font-semibold border cursor-pointer transition-all whitespace-nowrap ${
                    sortBy === col
                      ? 'bg-blue-500/20 border-blue-500 text-blue-400'
                      : 'bg-transparent border-terminal-border text-slate-500 hover:border-slate-400'
                  }`}>
                  {col === 'win_rate' ? 'Win%' : col.charAt(0).toUpperCase() + col.slice(1)}
                </button>
              ))}
            </div>
          </div>

          {/* Table — horizontal scroll on mobile */}
          <div className="bg-terminal-surface border border-terminal-border rounded-xl overflow-hidden">
            <div className="overflow-x-auto" style={{ WebkitOverflowScrolling: 'touch' } as React.CSSProperties}>
            <table className="w-full border-collapse" style={{ minWidth: 640 }}>
              <thead>
                <tr className="bg-terminal-bg">
                  {['Rank', 'Trader', 'Return', 'Sharpe', 'Win%', 'Max DD', 'Trades', 'Followers', 'Prize', ''].map((h) => (
                    <th key={h} className="text-left text-slate-500 text-2xs font-semibold uppercase tracking-wider px-3 sm:px-4 py-3 whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sorted.map((trader) => {
                  const copyTo = trader.user_id ? `/copy-trading?trader=${trader.user_id}` : '/copy-trading';
                  const profileTo = trader.user_id ? `/profile/${trader.user_id}` : null;
                  return (
                    <tr key={trader.rank} className="border-t border-terminal-border/60 hover:bg-terminal-raised/40 transition-colors">
                      <td className="px-3 sm:px-4 py-3">
                        <div className="flex items-center gap-1">
                          {trader.rank <= 3
                            ? <Medal
                                size={16} strokeWidth={2}
                                aria-label={MEDAL_LABEL[trader.rank]}
                                style={{ color: MEDAL_COLORS[trader.rank] }}
                                className="shrink-0"
                              />
                            : <span className="text-slate-500 text-sm">#{trader.rank}</span>}
                          {/* A green ▲ used to appear for every trader in the top
                              five, which reads as "moved up" — nothing here
                              measures movement, and the API returns no previous
                              rank. Showing a trend we do not have is worse than
                              showing none.
                              The red ▼ that survived that fix had the same
                              problem: it keyed off `rank > 10 && rank <= 15`,
                              an arbitrary band, and told the reader those five
                              traders had fallen. Nothing measured that either,
                              so it is gone too. Restore both together when the
                              API returns a previous rank. */}
                        </div>
                      </td>
                      <td className="px-3 sm:px-4 py-3">
                        <div className="flex items-center gap-1.5 flex-wrap">
                          <span className="font-semibold text-slate-100 text-sm whitespace-nowrap">{trader.name}</span>
                          {trader.verified && (
                            <BadgeCheck size={13} strokeWidth={2} aria-label="Verified trader"
                              className="text-blue-400 shrink-0" />
                          )}
                          {trader.rank === 1 && <span className="text-2xs px-1.5 py-0.5 bg-amber-500/15 border border-amber-500/40 rounded text-amber-400 font-bold">TOP</span>}
                          {trader.strategy_tag && <span className="text-2xs px-1.5 py-0.5 bg-violet-500/10 border border-violet-500/30 rounded text-violet-400 hidden sm:inline">{trader.strategy_tag}</span>}
                        </div>
                        {trader.country && <div className="text-2xs text-slate-600 mt-0.5">{trader.country}</div>}
                      </td>
                      <td className={`px-3 sm:px-4 py-3 font-semibold text-sm tabular-nums whitespace-nowrap ${trader.return >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                        {fmtPctRaw(trader.return, 1)}
                      </td>
                      <td className="px-3 sm:px-4 py-3 text-slate-300 text-sm tabular-nums">{fmtRatio(trader.sharpe)}</td>
                      <td className={`px-3 sm:px-4 py-3 text-sm tabular-nums ${(trader.win_rate ?? 0) >= 60 ? 'text-green-400' : 'text-slate-400'}`}>
                        {fPctPlain(trader.win_rate)}
                      </td>
                      <td className="px-3 sm:px-4 py-3 text-red-400 text-sm tabular-nums">
                        {fPctPlain(trader.max_drawdown)}
                      </td>
                      <td className="px-3 sm:px-4 py-3 text-slate-400 text-sm tabular-nums">{fInt(trader.total_trades)}</td>
                      <td className="px-3 sm:px-4 py-3 text-slate-400 text-sm tabular-nums">{fInt(trader.followers)}</td>
                      <td className="px-3 sm:px-4 py-3 text-amber-400 font-semibold text-sm whitespace-nowrap">{trader.prize}</td>
                      <td className="px-3 sm:px-4 py-3">
                        <div className="flex items-center gap-1.5">
                          <Link to={copyTo}
                            className="bg-amber-500/12 border border-amber-500/40 rounded-md text-amber-400 text-xs font-bold px-2 sm:px-2.5 py-1 no-underline hover:bg-amber-500/20 transition-colors whitespace-nowrap">
                            🔁 Copy
                          </Link>
                          {profileTo && (
                            <Link to={profileTo}
                              className="bg-transparent border border-terminal-border rounded-md text-slate-500 text-xs px-2 py-1 no-underline hover:border-slate-400 hover:text-slate-300 transition-colors hidden sm:inline-block">
                              Profile
                            </Link>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            </div>
          </div>
        </>
      )}

      <CrossLinkBar title="Related" className="mt-6" links={[
        { label: '🔁 Copy Trading', href: '/copy-trading', color: '#34d399' },
        { label: '📡 Signal Feed',  href: '/signals',      color: '#a78bfa' },
        { label: '🛒 Marketplace',  href: '/marketplace',  color: '#60a5fa' },
        { label: '🤝 Affiliate',    href: '/affiliate',    color: '#4ade80' },
        { label: '💬 Chat',         href: '/chat',         color: '#fbbf24' },
        { label: '📊 Performance',  href: '/performance',  color: '#f97316' },
      ]}/>
      <RelatedPages
        links={[
          { to: '/copy-trading', label: 'Copy trading', hint: 'Follow a trader automatically',     icon: Users },
          { to: '/signals',      label: 'Signal feed',  hint: 'What these traders are acting on',  icon: Radar },
          { to: '/performance',  label: 'Your performance', hint: 'How you compare',               icon: LineChart },
          { to: '/journal',      label: 'Trade journal', hint: 'Your own record',                  icon: BookOpen },
        ]}
      />
    </div>
  );
};

export default Leaderboard;
