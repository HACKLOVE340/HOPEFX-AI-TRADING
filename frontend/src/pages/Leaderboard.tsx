/**
 * Global Leaderboard — top traders ranked by return, Sharpe, followers.
 *
 * Wires to: GET /api/leaderboard?period={monthly|quarterly|all}
 */

import React, { useState, useEffect } from 'react';
import { api } from '../hooks/useApi';

function extractApiError(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: string } } })
    ?.response?.data?.detail;
  return detail ?? fallback;
}

interface Trader {
  rank: number;
  name: string;
  return: number;
  sharpe: number;
  followers: number;
  prize: string;
}

const MEDAL_COLORS = ['#eab308', '#94a3b8', '#b45309'];

const Leaderboard: React.FC = () => {
  const [period, setPeriod]   = useState<'monthly' | 'quarterly' | 'all'>('monthly');
  const [traders, setTraders] = useState<Trader[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadErr, setLoadErr] = useState('');

  useEffect(() => {
    setLoading(true);
    setLoadErr('');
    api.get<Trader[]>(`/leaderboard?period=${period}`)
      .then((r) => { setTraders(Array.isArray(r.data) ? r.data : []); })
      .catch((err: unknown) => {
        console.warn('[Leaderboard] Failed to load leaderboard:', err);
        setLoadErr(extractApiError(err, 'Failed to load leaderboard. Please try again.'));
        setTraders([]);
      })
      .finally(() => setLoading(false));
  }, [period]);

  const top3 = traders.slice(0, 3);

  return (
    <div style={s.page}>
      {/* Header */}
      <div style={s.header}>
        <h1 style={s.title}>Global Leaderboard</h1>
        <div style={{ display: 'flex', gap: 8 }}>
          {(['monthly', 'quarterly', 'all'] as const).map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              style={{ ...s.periodBtn, ...(period === p ? s.periodBtnActive : {}) }}
            >
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
        <p style={{ color: '#64748b', padding: '40px 0' }}>No traders on the leaderboard yet.</p>
      ) : (
        <>
          {/* Podium — top 3 */}
          <div style={s.podium}>
            <PodiumCard trader={top3[1]} medalColor={MEDAL_COLORS[1]} order={1} />
            <PodiumCard trader={top3[0]} medalColor={MEDAL_COLORS[0]} order={0} tall />
            <PodiumCard trader={top3[2]} medalColor={MEDAL_COLORS[2]} order={2} />
          </div>

          {/* Full table */}
          <div style={s.tableCard}>
            <table style={s.table}>
              <thead>
                <tr>
                  {['Rank', 'Trader', 'Return', 'Sharpe', 'Followers', 'Prize'].map((h) => (
                    <th key={h} style={s.th}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {traders.map((trader) => (
                  <tr key={trader.rank} style={s.tr}>
                    <td style={s.td}>
                      {trader.rank <= 3
                        ? <span style={{ color: MEDAL_COLORS[trader.rank - 1], fontSize: 18 }}>🏅</span>
                        : <span style={{ color: '#475569' }}>#{trader.rank}</span>}
                    </td>
                    <td style={{ ...s.td, fontWeight: 600, color: '#f1f5f9' }}>{trader.name}</td>
                    <td style={{ ...s.td, color: '#4ade80', fontWeight: 600 }}>+{trader.return}%</td>
                    <td style={s.td}>{trader.sharpe}</td>
                    <td style={s.td}>{trader.followers.toLocaleString()}</td>
                    <td style={{ ...s.td, color: '#fbbf24', fontWeight: 600 }}>{trader.prize}</td>
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
  trader?: Trader;
  medalColor: string;
  order: number;
  tall?: boolean;
}> = ({ trader, medalColor, order, tall }) => {
  if (!trader) return <div style={{ flex: 1 }} />;
  return (
    <div style={{
      ...s.podiumCard,
      border: `1px solid ${medalColor}55`,
      order,
      marginTop: tall ? 0 : 24,
    }}>
      <div style={{
        width: 32, height: 32, borderRadius: '50%', background: medalColor,
        color: '#0f172a', fontWeight: 800, fontSize: 14,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        margin: '0 auto 12px',
      }}>
        {trader.rank}
      </div>
      <div style={{ fontSize: 18, fontWeight: 700, color: '#f1f5f9', textAlign: 'center' }}>
        {trader.name}
      </div>
      <div style={{ fontSize: 28, fontWeight: 800, color: '#4ade80', textAlign: 'center', margin: '8px 0' }}>
        +{trader.return}%
      </div>
      <div style={{ fontSize: 13, color: '#64748b', textAlign: 'center' }}>
        Prize: {trader.prize}
      </div>
    </div>
  );
};

// ── Styles ────────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  page:          { padding: 24, maxWidth: 900, margin: '0 auto' },
  header:        { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 32 },
  title:         { fontSize: 24, fontWeight: 700, color: '#f1f5f9', margin: 0 },
  periodBtn:     { background: '#1e293b', border: '1px solid #334155', borderRadius: 8, color: '#64748b', cursor: 'pointer', fontSize: 13, padding: '7px 14px' },
  periodBtnActive: { background: '#1e3a5f', border: '1px solid #3b82f6', color: '#60a5fa' },
  podium:        { display: 'flex', gap: 16, marginBottom: 32, alignItems: 'flex-end' },
  podiumCard:    { flex: 1, background: '#1e293b', border: '1px solid #334155', borderRadius: 12, padding: '24px 16px' },
  tableCard:     { background: '#1e293b', border: '1px solid #334155', borderRadius: 12, overflow: 'hidden' },
  table:         { width: '100%', borderCollapse: 'collapse' },
  th:            { textAlign: 'left', color: '#475569', fontSize: 12, fontWeight: 600, textTransform: 'uppercase', padding: '12px 20px', background: '#0f172a', letterSpacing: 0.5 },
  tr:            { borderBottom: '1px solid #334155' },
  td:            { padding: '14px 20px', color: '#94a3b8', fontSize: 14 },
};

export default Leaderboard;
