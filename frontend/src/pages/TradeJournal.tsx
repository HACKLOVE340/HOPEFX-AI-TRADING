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
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
} from 'recharts';
import { journalApi } from '../hooks/useApi';

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

type Tab = 'trades' | 'stats' | 'mistakes';

// ── Helpers ───────────────────────────────────────────────────────────────────

const EMOTION_TAGS = ['patient', 'fomo', 'revenge', 'disciplined', 'hesitant', 'overconfident', 'fearful'];
const TRADE_TAGS   = ['trend', 'breakout', 'reversal', 'news', 'scalp', 'swing', 'mistake', 'best-trade'];

const EMOTION_EMOJI: Record<string, string> = {
  patient: '😌', fomo: '😰', revenge: '😤', disciplined: '🎯',
  hesitant: '😟', overconfident: '😎', fearful: '😨',
};

function fmt(n: number | null | undefined, d = 2): string {
  if (n == null) return '—';
  return n.toFixed(d);
}

function pnlColor(pnl: number | null): string {
  if (pnl === null) return '#94a3b8';
  return pnl >= 0 ? '#4ade80' : '#f87171';
}

// ── Component ─────────────────────────────────────────────────────────────────

const TradeJournal: React.FC = () => {
  const navigate = useNavigate();
  const [tab, setTab]             = useState<Tab>('trades');
  const [trades, setTrades]       = useState<JournalEntry[]>([]);
  const [mistakes, setMistakes]   = useState<JournalEntry[]>([]);
  const [stats, setStats]         = useState<JournalStats | null>(null);
  const [loading, setLoading]     = useState(true);
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
      if (tradesRes.status === 'fulfilled') {
        const d = tradesRes.value.data as JournalEntry[] | { trades?: JournalEntry[] };
        setTrades(Array.isArray(d) ? d : (d.trades ?? []));
      } else { setTrades([]); }
      if (statsRes.status === 'fulfilled') {
        setStats(statsRes.value.data as JournalStats);
      } else { setStats(null); }
      if (mistakesRes.status === 'fulfilled') {
        const d = mistakesRes.value.data as JournalEntry[] | { mistakes?: JournalEntry[] };
        setMistakes(Array.isArray(d) ? d : (d.mistakes ?? []));
      } else { setMistakes([]); }
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, [filterTag]);

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
      setSaveErr(err instanceof Error ? err.message : 'Failed to save journal entry. Please try again.');
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

  return (
    <div style={s.page}>
      <div style={s.header}>
        <div>
          <h1 style={s.title}>Trade Journal</h1>
          <p style={s.subtitle}>Every trade logged automatically. Add notes, emotions, and tags to improve.</p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            onClick={() => navigate('/performance')}
            style={{ background: 'rgba(74,222,128,0.1)', border: '1px solid rgba(74,222,128,0.3)', borderRadius: 7, color: '#4ade80', fontSize: 12, fontWeight: 700, padding: '7px 14px', cursor: 'pointer' }}
          >
            📈 Performance
          </button>
          <button
            onClick={() => navigate('/risk-calculator')}
            style={{ background: 'rgba(251,191,36,0.1)', border: '1px solid rgba(251,191,36,0.3)', borderRadius: 7, color: '#fbbf24', fontSize: 12, fontWeight: 700, padding: '7px 14px', cursor: 'pointer' }}
          >
            🛡 Risk Calculator
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div style={s.tabs}>
        {(['trades', 'stats', 'mistakes'] as Tab[]).map((t) => (
          <button key={t} onClick={() => setTab(t)} style={{ ...s.tab, ...(tab === t ? s.tabActive : {}) }}>
            {t === 'trades' ? `All Trades (${trades.length})` :
             t === 'stats' ? 'Stats & Tags' :
             `⚠ Mistakes (${mistakes.length})`}
          </button>
        ))}
      </div>

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
            <StatCard label="Win Rate" value={`${stats.win_rate}%`} positive={stats.win_rate >= 50} />
            <StatCard label="Avg P&L" value={`$${fmt(stats.avg_pnl)}`} positive={stats.avg_pnl >= 0} />
            <StatCard label="Best Trade" value={`+$${fmt(stats.best_trade_pnl)}`} positive />
            <StatCard label="Worst Trade" value={`$${fmt(stats.worst_trade_pnl)}`} positive={false} />
            <StatCard label="Rule Deviations" value={String(stats.rule_deviation_count)} positive={stats.rule_deviation_count === 0} />
          </div>

          <h3 style={s.sectionTitle}>Win Rate by Tag</h3>
          {(stats.by_tag ?? []).map((t) => <TagRow key={t.tag} stat={t} />)}

          <h3 style={s.sectionTitle}>Win Rate by Emotion</h3>
          {(stats.by_emotion ?? []).length > 0 && (
            <div style={{ marginBottom: 20 }}>
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={(stats.by_emotion ?? []).map(e => ({
                  name: `${EMOTION_EMOJI[e.tag] ?? ''} ${e.tag}`,
                  win_rate: e.win_rate,
                  avg_pnl: e.avg_pnl,
                }))} margin={{ top: 4, right: 8, left: 0, bottom: 40 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis dataKey="name" tick={{ fill: '#64748b', fontSize: 11 }} angle={-30} textAnchor="end" interval={0} />
                  <YAxis tick={{ fill: '#64748b', fontSize: 11 }} domain={[0, 100]} unit="%" />
                  <Tooltip
                    contentStyle={{ background: '#0d1421', border: '1px solid #1e2d3d', borderRadius: 6, fontSize: 11 }}
                    formatter={(v: unknown) => [`${Number(v).toFixed(1)}%`, 'Win Rate']}
                  />
                  <Bar dataKey="win_rate" radius={[4, 4, 0, 0]}>
                    {(stats.by_emotion ?? []).map((e, i) => (
                      <Cell key={i} fill={e.win_rate >= 50 ? '#4ade80' : '#f87171'} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
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
    <span style={{ width: 50, textAlign: 'right', color: stat.win_rate >= 50 ? '#4ade80' : '#f87171', fontSize: 13, fontWeight: 600 }}>{stat.win_rate}%</span>
    <span style={{ width: 70, textAlign: 'right', color: stat.avg_pnl >= 0 ? '#4ade80' : '#f87171', fontSize: 13 }}>${stat.avg_pnl.toFixed(0)}</span>
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
