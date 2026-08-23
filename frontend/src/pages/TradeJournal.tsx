/**
 * Trade Journal page.
 *
 * - Auto-entry per trade (from fills)
 * - Notes, tags, emotion tracking per trade
 * - Monthly win rate breakdown by tag
 * - Mistakes tab: trades where rules were deviated from
 *
 * Wires to: GET /api/journal/trades
 *           GET /api/journal/stats
 *           GET /api/journal/mistakes
 *           PATCH /api/journal/trades/{id}
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { journalApi } from '../hooks/useApi';
import { useDataFreshness } from '../hooks/useDataFreshness';
import { StaleDataNotice } from '../components/ui/StaleDataNotice';
import { PageHeader, Section, RelatedPages } from '../components';
import { EmptyState } from '../components/EmptyState';
import {
  BookOpen, TrendingUp, Shield, Brain, CalendarDays, Download,
  AlertTriangle, Zap, Target, LineChart,
} from 'lucide-react';
import { extractApiError, fmtPnl } from '../lib/utils';

// ── Types ─────────────────────────────────────────────────────────────────────

interface JournalEntry {
  trade_id: string;
  symbol: string;
  side: string;
  entry_price: number;
  exit_price: number | null;
  size: number;
  pnl: number | null;
  opened_at: string;
  closed_at: string | null;
  notes: string;
  tags: string[];
  emotion: string | null;
  followed_rules: boolean;
  rule_deviation: string | null;
}

interface TagStats {
  tag: string;
  count: number;
  win_rate: number;
  avg_pnl: number;
}

interface JournalStats {
  total_trades: number;
  win_rate: number;
  avg_pnl: number;
  best_trade_pnl: number;
  worst_trade_pnl: number;
  by_tag: TagStats[];
  by_emotion: TagStats[];
  rule_deviation_count: number;
}

type Tab = 'trades' | 'stats' | 'mistakes' | 'emotions' | 'weekly';

// ── Helpers ───────────────────────────────────────────────────────────────────

const EMOTION_TAGS = ['patient', 'fomo', 'revenge', 'disciplined', 'hesitant', 'overconfident', 'fearful'];
const TRADE_TAGS   = ['trend', 'breakout', 'reversal', 'news', 'scalp', 'swing', 'mistake', 'best-trade'];

const EMOTION_EMOJI: Record<string, string> = {
  patient: '😌', fomo: '😰', revenge: '😤', disciplined: '🎯',
  hesitant: '😟', overconfident: '😎', fearful: '😨',
};

function fmt(n: number | null | undefined, d = 2): string {
  if (n == null || !Number.isFinite(n)) return '—';
  return n.toFixed(d);
}

function pnlColor(pnl: number | null): string {
  if (pnl === null) return '#94a3b8';
  return pnl >= 0 ? '#4ade80' : '#f87171';
}

/**
 * Defensive normaliser: the render path reads `entry.side.toUpperCase()` and
 * `entry.tags.length/.map` directly. If the backend ever omits `tags` or `side`
 * (e.g. a partial/legacy row) those would throw and blank the whole list, so
 * coerce them to safe defaults at the ingestion boundary.
 */
function normalizeEntry(e: JournalEntry): JournalEntry {
  return {
    ...e,
    side: typeof e.side === 'string' ? e.side : '',
    tags: Array.isArray(e.tags) ? e.tags : [],
  };
}

// ── Component ─────────────────────────────────────────────────────────────────

const TradeJournal: React.FC = () => {
  const navigate = useNavigate();
  const [tab, setTab]             = useState<Tab>('trades');
  // `/journal/emotion-stats` and `/journal/weekly-report` are built and were
  // never called by any page (audit F185). Loaded lazily on first tab open so
  // the default view costs nothing extra.
  const [emotions, setEmotions]   = useState<Record<string, unknown> | null>(null);
  const [weekly, setWeekly]       = useState<Record<string, unknown> | null>(null);
  const [extraLoading, setExtraLoading] = useState(false);
  const [extraErr, setExtraErr]   = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [trades, setTrades]       = useState<JournalEntry[]>([]);
  const [mistakes, setMistakes]   = useState<JournalEntry[]>([]);
  const [stats, setStats]         = useState<JournalStats | null>(null);
  const [loading, setLoading]     = useState(true);
  // F1-01: every failed fetch below became an empty list, so a dead backend
  // rendered exactly like an empty journal.
  const freshness = useDataFreshness('your journal');
  const [editing, setEditing]     = useState<string | null>(null);
  const [editForm, setEditForm]   = useState<Partial<JournalEntry>>({});
  const [saving, setSaving]       = useState(false);
  const [saveErr, setSaveErr]     = useState<string | null>(null);
  const [filterTag, setFilterTag] = useState('');

  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, unknown> = {};
      if (filterTag) params.tag = filterTag;
      const [tradesRes, statsRes, mistakesRes] = await Promise.allSettled([
        journalApi.trades(params),
        journalApi.stats(),
        journalApi.mistakes(),
      ]);
      if (!mountedRef.current) return;
      // F1-01: every rejection below became an empty array or null, so a total
      // backend failure rendered exactly like a genuinely empty journal —
      // "All Trades (0)" stated as fact. Record it instead.
      const anyFailed = [tradesRes, statsRes, mistakesRes].some((r) => r.status === 'rejected');
      if (anyFailed) freshness.markFailed('your journal'); else freshness.markOk();
      if (tradesRes.status === 'fulfilled') {
        const d = tradesRes.value.data as JournalEntry[] | { trades?: JournalEntry[] };
        setTrades((Array.isArray(d) ? d : (d.trades ?? [])).map(normalizeEntry));
      } else { setTrades([]); }
      if (statsRes.status === 'fulfilled') {
        setStats(statsRes.value.data as JournalStats);
      } else { setStats(null); }
      if (mistakesRes.status === 'fulfilled') {
        const d = mistakesRes.value.data as JournalEntry[] | { mistakes?: JournalEntry[] };
        setMistakes((Array.isArray(d) ? d : (d.mistakes ?? [])).map(normalizeEntry));
      } else { setMistakes([]); }
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, [filterTag, freshness]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const startEdit = (entry: JournalEntry) => {
    setEditing(entry.trade_id);
    setEditForm({ notes: entry.notes, tags: entry.tags, emotion: entry.emotion ?? undefined, followed_rules: entry.followed_rules, rule_deviation: entry.rule_deviation ?? undefined });
  };

  const saveEdit = async () => {
    if (!editing) return;
    setSaving(true);
    setSaveErr(null);
    try {
      await journalApi.updateTrade(editing, editForm as Record<string, unknown>);
      setEditing(null);
      await fetchAll();
    } catch (err: unknown) {
      setSaveErr(extractApiError(err, 'Failed to save journal entry. Please try again.'));
    } finally {
      setSaving(false);
    }
  };

  const toggleTag = (tag: string) => {
    setEditForm((f) => ({
      ...f,
      tags: f.tags?.includes(tag) ? f.tags.filter((t) => t !== tag) : [...(f.tags ?? []), tag],
    }));
  };

  useEffect(() => {
    if (tab !== 'emotions' && tab !== 'weekly') return;
    if (tab === 'emotions' && emotions) return;
    if (tab === 'weekly' && weekly) return;
    let alive = true;
    setExtraLoading(true);
    setExtraErr(null);
    (tab === 'emotions' ? journalApi.emotionStats() : journalApi.weeklyReport())
      .then((r) => {
        if (!alive) return;
        if (tab === 'emotions') setEmotions(r.data as Record<string, unknown>);
        else setWeekly(r.data as Record<string, unknown>);
      })
      .catch((e: unknown) => { if (alive) setExtraErr(extractApiError(e, 'Could not load this view.')); })
      .finally(() => { if (alive) setExtraLoading(false); });
    return () => { alive = false; };
  }, [tab, emotions, weekly]);

  const handleExport = async (format: 'csv' | 'json') => {
    setExporting(true);
    try {
      const res = await journalApi.export(format);
      const blob = new Blob([res.data as BlobPart], {
        type: format === 'csv' ? 'text/csv' : 'application/json',
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `trade-journal.${format}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e: unknown) {
      setExtraErr(extractApiError(e, 'Export failed.'));
    }
    setExporting(false);
  };

  return (
    <div className="page-content">
      <PageHeader
        title="Trade journal"
        icon={BookOpen}
        subtitle="Every trade logged automatically. Add notes, emotions and tags to find what you keep repeating."
        badge={<StaleDataNotice failed={freshness.failed} what={freshness.what} />}
        activeTab={tab}
        onTabChange={(k) => setTab(k as Tab)}
        tabs={[
          { key: 'trades',   label: 'All trades', icon: BookOpen,      badge: trades.length },
          { key: 'stats',    label: 'Stats & tags', icon: Target },
          { key: 'mistakes', label: 'Mistakes',   icon: AlertTriangle, badge: mistakes.length },
          { key: 'emotions', label: 'Emotions',   icon: Brain },
          { key: 'weekly',   label: 'Weekly review', icon: CalendarDays },
        ]}
        actions={
          <>
            <button
              onClick={() => void handleExport('csv')}
              disabled={exporting}
              className="inline-flex min-h-[44px] items-center gap-1.5 rounded-lg px-3.5 text-[12.5px]
                         font-semibold text-slate-400 ring-1 ring-inset ring-[#1e2d3d] cursor-pointer
                         transition-colors duration-150 hover:bg-[#141c2b] hover:text-slate-200
                         disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none
                         focus-visible:ring-2 focus-visible:ring-sky-500"
            >
              <Download size={14} strokeWidth={1.75} aria-hidden />
              {exporting ? 'Exporting…' : 'Export CSV'}
            </button>
          </>
        }
      />

      {extraErr && (tab === 'emotions' || tab === 'weekly') && (
        <p role="alert" className="mx-4 mt-4 rounded-lg bg-red-500/10 px-3 py-2 text-[12.5px]
                                   text-red-300 ring-1 ring-inset ring-red-500/30">{extraErr}</p>
      )}

      {/* ── EMOTIONS TAB — surfaces /journal/emotion-stats (F185) ── */}
      {tab === 'emotions' && (
        <div className="mt-4 px-4">
          <Section
            title="Emotional state vs outcome"
            description="Which state of mind precedes your winning and losing trades."
          >
            {extraLoading ? (
              <EmptyState title="Loading emotion statistics…" compact />
            ) : emotions && Object.keys(emotions).length > 0 ? (
              <pre className="overflow-x-auto whitespace-pre-wrap rounded-lg bg-[#0b1220] p-3
                              text-[12px] leading-relaxed text-slate-300">
                {JSON.stringify(emotions, null, 2)}
              </pre>
            ) : (
              <EmptyState
                icon={Brain}
                title="No emotion data yet"
                description="Tag a few trades with how you felt before entering. Patterns appear once several trades carry a state."
                links={[{ label: 'Tag your trades', href: '/journal' }]}
              />
            )}
          </Section>
        </div>
      )}

      {/* ── WEEKLY TAB — surfaces /journal/weekly-report (F185) ── */}
      {tab === 'weekly' && (
        <div className="mt-4 px-4">
          <Section
            title="This week"
            description="A rollup of the week's trades, mistakes and results."
          >
            {extraLoading ? (
              <EmptyState title="Loading this week's review…" compact />
            ) : weekly && Object.keys(weekly).length > 0 ? (
              <pre className="overflow-x-auto whitespace-pre-wrap rounded-lg bg-[#0b1220] p-3
                              text-[12px] leading-relaxed text-slate-300">
                {JSON.stringify(weekly, null, 2)}
              </pre>
            ) : (
              <EmptyState
                icon={CalendarDays}
                title="No trades logged this week"
                description="The weekly review builds once you have closed trades in the current week."
                links={[{ label: 'Open the ticket', href: '/trade' }]}
              />
            )}
          </Section>
        </div>
      )}

      {/* ── TRADES TAB ── */}
      {tab === 'trades' && (
        <>
          <div style={s.filterRow}>
            <select value={filterTag} onChange={(e) => setFilterTag(e.target.value)} style={s.select}>
              <option value="">All tags</option>
              {TRADE_TAGS.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>

          {loading ? <div style={s.empty}>Loading…</div> :
           trades.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '48px 24px' }}>
              <div style={{ fontSize: 36, marginBottom: 12 }}>📓</div>
              <div style={{ fontSize: 15, fontWeight: 700, color: '#94a3b8', marginBottom: 8 }}>No journal entries yet</div>
              <div style={{ fontSize: 13, color: '#64748b', maxWidth: 360, margin: '0 auto', lineHeight: 1.6 }}>
                Journal entries are created automatically when you close a trade.
                Head to the <a href="/trade" style={{ color: '#60a5fa' }}>Trading</a> page to make your first trade.
              </div>
            </div>
           ) :
           trades.map((entry) => (
            <div key={entry.trade_id} style={s.tradeCard}>
              {/* Header row */}
              <div style={s.tradeHeader}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{ ...s.sideBadge, background: entry.side === 'long' ? '#14532d' : '#450a0a', color: entry.side === 'long' ? '#4ade80' : '#f87171' }}>
                    {entry.side.toUpperCase()}
                  </span>
                  <span style={{ fontWeight: 700, color: '#f1f5f9' }}>{entry.symbol}</span>
                  {entry.emotion && <span title={entry.emotion}>{EMOTION_EMOJI[entry.emotion] ?? '🤔'}</span>}
                  {!entry.followed_rules && <span style={s.deviationBadge}>⚠ Rule deviation</span>}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontSize: 18, fontWeight: 700, color: pnlColor(entry.pnl) }}>
                    {entry.pnl !== null ? `${entry.pnl >= 0 ? '+' : ''}$${fmt(entry.pnl)}` : 'Open'}
                  </span>
                  {entry.closed_at && (
                    <button
                      onClick={() => navigate('/trade', { state: { signal: { symbol: entry.symbol, direction: entry.side === 'long' ? 'BUY' : 'SELL' } } })}
                      style={{ background: 'rgba(96,165,250,0.12)', border: '1px solid rgba(96,165,250,0.35)', borderRadius: 5, color: '#60a5fa', fontSize: 11, fontWeight: 700, padding: '3px 9px', cursor: 'pointer' }}
                      title="Open a new trade with the same symbol and direction"
                    >
                      🔁 Re-trade
                    </button>
                  )}
                  <button onClick={() => editing === entry.trade_id ? setEditing(null) : startEdit(entry)} style={s.editBtn}>
                    {editing === entry.trade_id ? 'Cancel' : 'Edit'}
                  </button>
                </div>
              </div>

              {/* Price info */}
              <div style={s.priceRow}>
                <span style={s.priceItem}>Entry: <strong>{fmt(entry.entry_price)}</strong></span>
                {entry.exit_price && <span style={s.priceItem}>Exit: <strong>{fmt(entry.exit_price)}</strong></span>}
                <span style={s.priceItem}>Size: <strong>{entry.size}</strong></span>
                <span style={s.priceItem}>{new Date(entry.opened_at).toLocaleDateString()}</span>
              </div>

              {/* Tags */}
              {entry.tags.length > 0 && (
                <div style={s.tagRow}>
                  {entry.tags.map((t) => <span key={t} style={s.tag}>{t}</span>)}
                </div>
              )}

              {/* Notes */}
              {entry.notes && <p style={s.notes}>{entry.notes}</p>}

              {/* Edit form */}
              {editing === entry.trade_id && (
                <div style={s.editForm}>
                  <label style={s.label}>Notes</label>
                  <textarea value={editForm.notes ?? ''} onChange={(e) => setEditForm({ ...editForm, notes: e.target.value })}
                    style={s.textarea} rows={3} />

                  <label style={s.label}>Tags</label>
                  <div style={s.tagPicker}>
                    {TRADE_TAGS.map((t) => (
                      <button key={t} onClick={() => toggleTag(t)}
                        style={{ ...s.tagPickerBtn, ...(editForm.tags?.includes(t) ? s.tagPickerBtnActive : {}) }}>
                        {t}
                      </button>
                    ))}
                  </div>

                  <label style={s.label}>Emotion</label>
                  <div style={s.tagPicker}>
                    {EMOTION_TAGS.map((em) => (
                      <button key={em} onClick={() => setEditForm({ ...editForm, emotion: em })}
                        style={{ ...s.tagPickerBtn, ...(editForm.emotion === em ? s.tagPickerBtnActive : {}) }}>
                        {EMOTION_EMOJI[em]} {em}
                      </button>
                    ))}
                  </div>

                  <label style={s.label}>
                    <input type="checkbox" checked={!editForm.followed_rules}
                      onChange={(e) => setEditForm({ ...editForm, followed_rules: !e.target.checked })} />
                    {' '}Rule deviation
                  </label>
                  {!editForm.followed_rules && (
                    <input value={editForm.rule_deviation ?? ''} onChange={(e) => setEditForm({ ...editForm, rule_deviation: e.target.value })}
                      placeholder="What rule did you break?" style={{ ...s.input, marginTop: 6 }} />
                  )}

                  {saveErr && (
                    <div style={s.saveErrBox}>{saveErr}</div>
                  )}
                  <button onClick={saveEdit} disabled={saving} style={s.saveBtn}>
                    {saving ? 'Saving…' : 'Save'}
                  </button>
                </div>
              )}
            </div>
          ))}
        </>
      )}

      {/* ── STATS TAB ── */}
      {tab === 'stats' && stats && (
        <div>
          <div style={s.statsGrid}>
            <StatCard label="Total Trades" value={String(stats.total_trades)} />
            <StatCard label="Win Rate" value={`${fmt(stats.win_rate, 0)}%`} positive={stats.win_rate >= 50} />
            <StatCard label="Avg P&L" value={`$${fmt(stats.avg_pnl)}`} positive={stats.avg_pnl >= 0} />
            {/* The best trade in a losing run is still a loss — the sign and the colour
                both have to come from the number. */}
            <StatCard label="Best Trade" value={fmtPnl(stats.best_trade_pnl)} positive={stats.best_trade_pnl >= 0} />
            <StatCard label="Worst Trade" value={fmtPnl(stats.worst_trade_pnl)} positive={stats.worst_trade_pnl >= 0} />
            <StatCard label="Rule Deviations" value={String(stats.rule_deviation_count)} positive={stats.rule_deviation_count === 0} />
          </div>

          <h3 style={s.sectionTitle}>Win Rate by Tag</h3>
          {(stats.by_tag ?? []).map((t) => <TagRow key={t.tag} stat={t} />)}

          <h3 style={s.sectionTitle}>Win Rate by Emotion</h3>
          {(stats.by_emotion ?? []).length > 0 && (
            <div style={{ marginBottom: 20 }}>
              {/* CSS bar chart — categorical emotion data */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {(stats.by_emotion ?? []).map((e) => {
                  const pct = Math.min(Math.max(e.win_rate, 0), 100);
                  const color = pct >= 50 ? '#4ade80' : '#f87171';
                  return (
                    <div key={e.tag} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ width: 110, fontSize: 11, color: '#94a3b8', textAlign: 'right', flexShrink: 0 }}>
                        {EMOTION_EMOJI[e.tag] ?? ''} {e.tag}
                      </span>
                      <div style={{ flex: 1, height: 14, background: '#1e293b', borderRadius: 3, overflow: 'hidden' }}>
                        <div style={{ height: '100%', width: `${pct}%`, background: color, borderRadius: 3, transition: 'width 0.4s ease' }} />
                      </div>
                      <span style={{ width: 42, fontSize: 11, color, fontFamily: 'monospace', textAlign: 'right', flexShrink: 0 }}>
                        {pct.toFixed(1)}%
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
          {(stats.by_emotion ?? []).map((e) => <TagRow key={e.tag} stat={e} emoji={EMOTION_EMOJI[e.tag]} />)}
        </div>
      )}

      {/* ── MISTAKES TAB ── */}
      {tab === 'mistakes' && (
        <>
          {mistakes.length === 0
            ? <div style={s.empty}>No rule deviations recorded. Keep it up! 🎯</div>
            : (
              <>
                {/* Summary banner */}
                <div style={{ background: '#450a0a', border: '1px solid #7f1d1d', borderRadius: 8, padding: '12px 16px', marginBottom: 16, display: 'flex', gap: 24 }}>
                  <div>
                    <div style={{ fontSize: 11, color: '#f87171', marginBottom: 2 }}>TOTAL DEVIATIONS</div>
                    <div style={{ fontSize: 22, fontWeight: 700, color: '#fca5a5' }}>{mistakes.length}</div>
                  </div>
                  <div>
                    <div style={{ fontSize: 11, color: '#f87171', marginBottom: 2 }}>COST OF MISTAKES</div>
                    <div style={{ fontSize: 22, fontWeight: 700, color: '#fca5a5' }}>
                      ${Math.abs(mistakes.reduce((sum, m) => sum + (m.pnl ?? 0), 0)).toFixed(2)}
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: 11, color: '#f87171', marginBottom: 2 }}>WIN RATE ON MISTAKES</div>
                    <div style={{ fontSize: 22, fontWeight: 700, color: '#fca5a5' }}>
                      {mistakes.length > 0
                        ? `${((mistakes.filter(m => (m.pnl ?? 0) > 0).length / mistakes.length) * 100).toFixed(0)}%`
                        : '—'}
                    </div>
                  </div>
                </div>
                {mistakes.map((entry) => (
                  <div key={entry.trade_id} style={{ ...s.tradeCard, border: '1px solid #7f1d1d' }}>
                    <div style={s.tradeHeader}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        <span style={{ ...s.sideBadge, background: '#450a0a', color: '#f87171' }}>{entry.side.toUpperCase()}</span>
                        <span style={{ fontWeight: 700, color: '#f1f5f9' }}>{entry.symbol}</span>
                        <span style={s.deviationBadge}>⚠ {entry.rule_deviation ?? 'Rule deviation'}</span>
                        {entry.emotion && <span title={entry.emotion}>{EMOTION_EMOJI[entry.emotion] ?? '🤔'}</span>}
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                        <span style={{ fontSize: 12, color: '#64748b' }}>{new Date(entry.opened_at).toLocaleDateString()}</span>
                        <span style={{ fontSize: 16, fontWeight: 700, color: pnlColor(entry.pnl) }}>
                          {entry.pnl !== null ? `${entry.pnl >= 0 ? '+' : ''}$${fmt(entry.pnl)}` : 'Open'}
                        </span>
                      </div>
                    </div>
                    {entry.notes && <p style={s.notes}>{entry.notes}</p>}
                    {entry.tags.length > 0 && (
                      <div style={s.tagRow}>
                        {entry.tags.map(t => <span key={t} style={s.tag}>{t}</span>)}
                      </div>
                    )}
                  </div>
                ))}
              </>
            )
          }
        </>
      )}
      <RelatedPages
        links={[
          { to: '/performance',     label: 'Performance',     hint: 'Sharpe, drawdown and the equity curve', icon: TrendingUp },
          { to: '/pnl',             label: 'P&L breakdown',   hint: 'Where the money actually came from',    icon: LineChart },
          { to: '/risk-calculator', label: 'Risk calculator', hint: 'Size the next trade before you take it', icon: Shield },
          { to: '/trade',           label: 'Trading ticket',  hint: 'Place the next order',                  icon: Zap },
        ]}
      />
    </div>
  );
};

// ── Sub-components ────────────────────────────────────────────────────────────

const StatCard: React.FC<{ label: string; value: string; positive?: boolean }> = ({ label, value, positive }) => (
  <div style={s.statCard}>
    <div style={{ fontSize: 12, color: '#64748b', marginBottom: 4 }}>{label}</div>
    <div style={{ fontSize: 20, fontWeight: 700, color: positive === undefined ? '#f1f5f9' : positive ? '#4ade80' : '#f87171' }}>{value}</div>
  </div>
);

const TagRow: React.FC<{ stat: TagStats; emoji?: string }> = ({ stat, emoji }) => (
  <div style={s.tagStatRow}>
    <span style={{ width: 120, color: '#f1f5f9', fontSize: 13 }}>{emoji ? `${emoji} ` : ''}{stat.tag}</span>
    <span style={{ width: 50, color: '#64748b', fontSize: 12 }}>{stat.count}×</span>
    <div style={{ flex: 1, background: '#0f172a', borderRadius: 4, height: 8, overflow: 'hidden' }}>
      <div style={{ width: `${stat.win_rate}%`, height: '100%', background: stat.win_rate >= 50 ? '#4ade80' : '#f87171', borderRadius: 4 }} />
    </div>
    <span style={{ width: 50, textAlign: 'right', color: (stat.win_rate ?? 0) >= 50 ? '#4ade80' : '#f87171', fontSize: 13, fontWeight: 600 }}>{Number.isFinite(stat.win_rate) ? stat.win_rate : '—'}%</span>
    <span style={{ width: 70, textAlign: 'right', color: (stat.avg_pnl ?? 0) >= 0 ? '#4ade80' : '#f87171', fontSize: 13 }}>${Number.isFinite(stat.avg_pnl) ? stat.avg_pnl.toFixed(0) : '—'}</span>
  </div>
);

// ── Styles ────────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  page:            { padding: 24, maxWidth: 900, margin: '0 auto' },
  header:          { marginBottom: 20 },
  title:           { fontSize: 24, fontWeight: 700, color: '#f1f5f9', margin: '0 0 6px' },
  subtitle:        { fontSize: 14, color: '#64748b', margin: 0 },
  tabs:            { display: 'flex', gap: 8, marginBottom: 20 },
  tab:             { background: '#1e293b', border: '1px solid #334155', borderRadius: 8, color: '#64748b', cursor: 'pointer', padding: '8px 16px', fontSize: 13 },
  tabActive:       { background: '#1e3a5f', border: '1px solid #3b82f6', color: '#60a5fa' },
  filterRow:       { marginBottom: 16 },
  select:          { background: '#1e293b', border: '1px solid #334155', borderRadius: 8, color: '#f1f5f9', padding: '8px 12px', fontSize: 14 },
  tradeCard:       { background: '#1e293b', border: '1px solid #334155', borderRadius: 10, padding: '14px 16px', marginBottom: 10 },
  tradeHeader:     { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 },
  sideBadge:       { borderRadius: 4, fontSize: 11, fontWeight: 700, padding: '2px 8px' },
  deviationBadge:  { background: '#450a0a', color: '#f87171', fontSize: 11, padding: '2px 8px', borderRadius: 4 },
  priceRow:        { display: 'flex', gap: 16, marginBottom: 8 },
  priceItem:       { fontSize: 13, color: '#64748b' },
  tagRow:          { display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 },
  tag:             { background: '#0f172a', border: '1px solid #334155', borderRadius: 4, color: '#94a3b8', fontSize: 11, padding: '2px 8px' },
  notes:           { fontSize: 13, color: '#94a3b8', margin: '4px 0 0', lineHeight: 1.5 },
  editBtn:         { background: '#334155', border: 'none', borderRadius: 6, color: '#94a3b8', cursor: 'pointer', fontSize: 12, padding: '4px 10px' },
  editForm:        { borderTop: '1px solid #334155', marginTop: 12, paddingTop: 12 },
  label:           { display: 'block', fontSize: 13, color: '#94a3b8', marginBottom: 6, fontWeight: 500 },
  textarea:        { width: '100%', background: '#0f172a', border: '1px solid #334155', borderRadius: 8, color: '#f1f5f9', padding: '8px 12px', fontSize: 13, resize: 'vertical', boxSizing: 'border-box', fontFamily: 'inherit', marginBottom: 12 },
  input:           { width: '100%', background: '#0f172a', border: '1px solid #334155', borderRadius: 8, color: '#f1f5f9', padding: '8px 12px', fontSize: 13, boxSizing: 'border-box' },
  tagPicker:       { display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 },
  tagPickerBtn:    { background: '#0f172a', border: '1px solid #334155', borderRadius: 6, color: '#64748b', cursor: 'pointer', fontSize: 12, padding: '4px 10px' },
  tagPickerBtnActive: { background: '#1e3a5f', border: '1px solid #3b82f6', color: '#60a5fa' },
  saveBtn:         { background: '#059669', border: 'none', borderRadius: 8, color: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer', padding: '8px 20px', marginTop: 8 },
  saveErrBox:      { background: 'rgba(248,113,113,0.1)', border: '1px solid #f87171', borderRadius: 6, padding: '6px 10px', fontSize: 12, color: '#f87171', marginTop: 8 },
  statsGrid:       { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 12, marginBottom: 24 },
  statCard:        { background: '#1e293b', border: '1px solid #334155', borderRadius: 8, padding: '12px 16px' },
  sectionTitle:    { fontSize: 16, fontWeight: 700, color: '#f1f5f9', margin: '20px 0 10px' },
  tagStatRow:      { display: 'flex', alignItems: 'center', gap: 12, padding: '8px 0', borderBottom: '1px solid #1e293b' },
  empty:           { textAlign: 'center', color: '#475569', padding: 40 },
};

export default TradeJournal;
