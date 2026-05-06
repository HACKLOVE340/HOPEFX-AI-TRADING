/**
 * Leaderboard — top traders ranked by return, Sharpe, win rate, followers.
 *
 * Wires to: GET /api/leaderboard?period={monthly|quarterly|all}
 */

import React, { useState, useEffect } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { api } from '../hooks/useApi';

function extractApiError(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: string } } })
    ?.response?.data?.detail;
  return detail ?? fallback;
}

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
}

const MEDAL_COLORS = ['#eab308', '#94a3b8', '#b45309'];

const Leaderboard: React.FC = () => {
  const navigate = useNavigate();
  const [period, setPeriod]   = useState<'monthly' | 'quarterly' | 'all'>('monthly');
  const [traders, setTraders] = useState<Trader[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadErr, setLoadErr] = useState('');
  const [sortBy, setSortBy]   = useState<'return' | 'sharpe' | 'win_rate' | 'followers'>('return');

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setLoadErr('');
    api.get<Trader[]>(`/leaderboard?period=${period}`, { signal: controller.signal })
      .then((r) => { setTraders(Array.isArray(r.data) ? r.data : []); })
      .catch((err: unknown) => {
        if ((err as { name?: string }).name === 'CanceledError') return;
        setLoadErr(extractApiError(err, 'Failed to load leaderboard.'));
        setTraders([]);
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [period]);

  const sorted = [...traders].sort((a, b) => {
    if (sortBy === 'return')    return b.return - a.return;
    if (sortBy === 'sharpe')    return b.sharpe - a.sharpe;
    if (sortBy === 'win_rate')  return (b.win_rate ?? 0) - (a.win_rate ?? 0);
    if (sortBy === 'followers') return b.followers - a.followers;
    return 0;
  });

  const top3 = sorted.slice(0, 3);

  return (
    <div style={s.page}>
      {/* Header */}
      <div style={s.header}>
        <div>
          <h1 style={s.title}>Global Leaderboard</h1>
          <p style={{ fontSize: 13, color: '#64748b', margin: '4px 0 0' }}>
            Top traders ranked by performance. Click a trader to copy their strategy.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {(['monthly', 'quarterly', 'all'] as const).map((p) => (
            <button key={p} onClick={() => setPeriod(p)}
              style={{ ...s.periodBtn, ...(period === p ? s.periodBtnActive : {}) }}>
              {p === 'all' ? 'All Time' : p.charAt(0).toUpperCase() + p.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <p style={{ color: '#64748b', padding: '40px 0' }}>Loading leaderboard…</p>
      ) : loadErr ? (
        <p style={{ color: '#f87171', padding: '40px 0' }}>⚠️ {loadErr}</p>
      ) : traders.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '48px 24px' }}>
          <div style={{ fontSize: 40, marginBottom: 16 }}>🏆</div>
          <div style={{ fontSize: 16, fontWeight: 700, color: '#94a3b8', marginBottom: 8 }}>No traders ranked yet</div>
          <div style={{ fontSize: 13, color: '#64748b', maxWidth: 380, margin: '0 auto', lineHeight: 1.6 }}>
            The leaderboard populates once traders have closed positions.
            Start trading on the <Link to="/trade" style={{ color: '#60a5fa' }}>Trading</Link> page to appear here.
          </div>
        </div>
      ) : (
        <>
          {/* Podium — top 3 */}
          <div style={s.podium}>
            {[top3[1], top3[0], top3[2]].map((trader, i) => (
              trader
                ? <PodiumCard key={trader.rank} trader={trader} medalColor={MEDAL_COLORS[i === 1 ? 0 : i === 0 ? 1 : 2]} tall={i === 1} onCopy={() => navigate('/copy-trading')} />
                : <div key={i} style={{ flex: 1 }} />
            ))}
          </div>

          {/* Sort controls */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
            <span style={{ fontSize: 12, color: '#64748b', alignSelf: 'center' }}>Sort by:</span>
            {(['return', 'sharpe', 'win_rate', 'followers'] as const).map((col) => (
              <button key={col} onClick={() => setSortBy(col)}
                style={{ ...s.periodBtn, ...(sortBy === col ? s.periodBtnActive : {}), fontSize: 11, padding: '5px 10px' }}>
                {col === 'win_rate' ? 'Win Rate' : col.charAt(0).toUpperCase() + col.slice(1)}
              </button>
            ))}
          </div>

          {/* Full table */}
          <div style={s.tableCard}>
            <table style={s.table}>
              <thead>
                <tr>
                  {['Rank', 'Trader', 'Return', 'Sharpe', 'Win Rate', 'Max DD', 'Trades', 'Followers', 'Prize', ''].map((h) => (
                    <th key={h} style={s.th}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sorted.map((trader) => (
                  <tr key={trader.rank} style={s.tr}>
                    <td style={s.td}>
                      {trader.rank <= 3
                        ? <span style={{ color: MEDAL_COLORS[trader.rank - 1], fontSize: 18 }}>🏅</span>
                        : <span style={{ color: '#475569' }}>#{trader.rank}</span>}
                    </td>
                    <td style={{ ...s.td, fontWeight: 600, color: '#f1f5f9' }}>
                      {trader.name}
                      {trader.verified && <span style={{ marginLeft: 6, fontSize: 11, color: '#3b82f6' }}>✓</span>}
                    </td>
                    <td style={{ ...s.td, color: trader.return >= 0 ? '#4ade80' : '#f87171', fontWeight: 600 }}>
                      {trader.return >= 0 ? '+' : ''}{trader.return.toFixed(1)}%
                    </td>
                    <td style={s.td}>{trader.sharpe.toFixed(2)}</td>
                    <td style={{ ...s.td, color: (trader.win_rate ?? 0) >= 60 ? '#4ade80' : '#94a3b8' }}>
                      {trader.win_rate != null ? `${trader.win_rate.toFixed(1)}%` : '—'}
                    </td>
                    <td style={{ ...s.td, color: '#f87171' }}>
                      {trader.max_drawdown != null ? `${trader.max_drawdown.toFixed(1)}%` : '—'}
                    </td>
                    <td style={s.td}>{trader.total_trades?.toLocaleString() ?? '—'}</td>
                    <td style={s.td}>{trader.followers.toLocaleString()}</td>
                    <td style={{ ...s.td, color: '#fbbf24', fontWeight: 600 }}>{trader.prize}</td>
                    <td style={s.td}>
                      <button
                        onClick={() => navigate('/copy-trading')}
                        style={{
                          background: 'rgba(251,191,36,0.12)', border: '1px solid rgba(251,191,36,0.4)',
                          borderRadius: 6, color: '#fbbf24', fontSize: 11, cursor: 'pointer',
                          padding: '5px 12px', fontWeight: 700, whiteSpace: 'nowrap',
                        }}
                      >
                        🔁 Copy
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
};

// ── Podium card ───────────────────────────────────────────────────────────────

const PodiumCard: React.FC<{
  trader: Trader;
  medalColor: string;
  tall?: boolean;
  onCopy: () => void;
}> = ({ trader, medalColor, tall, onCopy }) => (
  <div style={{
    ...s.podiumCard,
    border: `1px solid ${medalColor}55`,
    marginTop: tall ? 0 : 24,
    flex: 1,
  }}>
    <div style={{
      width: 32, height: 32, borderRadius: '50%', background: medalColor,
      color: '#0f172a', fontWeight: 800, fontSize: 14,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      margin: '0 auto 12px',
    }}>
      {trader.rank}
    </div>
    <div style={{ fontSize: 16, fontWeight: 700, color: '#f1f5f9', textAlign: 'center' }}>{trader.name}</div>
    <div style={{ fontSize: 26, fontWeight: 800, color: '#4ade80', textAlign: 'center', margin: '6px 0' }}>
      +{trader.return.toFixed(1)}%
    </div>
    <div style={{ fontSize: 12, color: '#64748b', textAlign: 'center', marginBottom: 12 }}>
      Sharpe {trader.sharpe.toFixed(2)} · {trader.followers.toLocaleString()} followers
    </div>
    <button onClick={onCopy} style={{
      width: '100%', background: medalColor, color: '#0f172a', border: 'none',
      borderRadius: 6, padding: '8px 0', fontWeight: 700, fontSize: 12, cursor: 'pointer',
    }}>
      Copy Trader
    </button>
  </div>
);

// ── Styles ────────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  page:            { padding: 24, maxWidth: 1100, margin: '0 auto' },
  header:          { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 32 },
  title:           { fontSize: 24, fontWeight: 700, color: '#f1f5f9', margin: 0 },
  periodBtn:       { background: '#1e293b', border: '1px solid #334155', borderRadius: 8, color: '#64748b', cursor: 'pointer', fontSize: 13, padding: '7px 14px' },
  periodBtnActive: { background: '#1e3a5f', border: '1px solid #3b82f6', color: '#60a5fa' },
  podium:          { display: 'flex', gap: 16, marginBottom: 32, alignItems: 'flex-end' },
  podiumCard:      { background: '#1e293b', borderRadius: 12, padding: '24px 16px' },
  tableCard:       { background: '#1e293b', border: '1px solid #334155', borderRadius: 12, overflow: 'hidden' },
  table:           { width: '100%', borderCollapse: 'collapse' },
  th:              { textAlign: 'left', color: '#475569', fontSize: 11, fontWeight: 600, textTransform: 'uppercase', padding: '12px 16px', background: '#0f172a', letterSpacing: 0.5 },
  tr:              { borderBottom: '1px solid #334155' },
  td:              { padding: '12px 16px', color: '#94a3b8', fontSize: 13 },
};

export default Leaderboard;
