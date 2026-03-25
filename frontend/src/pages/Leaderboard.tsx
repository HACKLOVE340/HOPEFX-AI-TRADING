/**
 * Global Leaderboard — top traders ranked by return, Sharpe, followers.
 *
 * Wires to: GET /api/social/leaderboard?period={monthly|quarterly|all}
 */

import React, { useState, useEffect } from 'react';

interface Trader {
  rank: number;
  name: string;
  return: number;
  sharpe: number;
  followers: number;
  prize: string;
}

const FALLBACK: Trader[] = [
  { rank: 1, name: 'GoldMaster',  return: 156.4, sharpe: 2.8, followers: 3420, prize: '$10,000' },
  { rank: 2, name: 'XAUWhale',    return: 142.8, sharpe: 2.5, followers: 2890, prize: '$5,000'  },
  { rank: 3, name: 'BullionKing', return: 138.2, sharpe: 2.3, followers: 2156, prize: '$2,500'  },
  { rank: 4, name: 'GoldRush',    return: 125.6, sharpe: 2.1, followers: 1890, prize: '$1,000'  },
  { rank: 5, name: 'PreciousAI',  return: 118.3, sharpe: 2.0, followers: 1654, prize: '$500'    },
];

const MEDAL_COLORS = ['#eab308', '#94a3b8', '#b45309'];

const Leaderboard: React.FC = () => {
  const [period, setPeriod]   = useState<'monthly' | 'quarterly' | 'all'>('monthly');
  const [traders, setTraders] = useState<Trader[]>(FALLBACK);

  useEffect(() => {
    fetch(`/api/social/leaderboard?period=${period}`)
      .then((r) => r.ok ? r.json() : null)
      .then((data) => { if (data?.length) setTraders(data); })
      .catch(() => {});
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

      {/* Podium — top 3 */}
      <div style={s.podium}>
        {/* 2nd place (left) */}
        <PodiumCard trader={top3[1]} medalColor={MEDAL_COLORS[1]} order={1} />
        {/* 1st place (center, taller) */}
        <PodiumCard trader={top3[0]} medalColor={MEDAL_COLORS[0]} order={0} tall />
        {/* 3rd place (right) */}
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
      borderColor: `${medalColor}55`,
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
  periodBtnActive: { background: '#1e3a5f', borderColor: '#3b82f6', color: '#60a5fa' },
  podium:        { display: 'flex', gap: 16, marginBottom: 32, alignItems: 'flex-end' },
  podiumCard:    { flex: 1, background: '#1e293b', border: '1px solid', borderRadius: 12, padding: '24px 16px' },
  tableCard:     { background: '#1e293b', border: '1px solid #334155', borderRadius: 12, overflow: 'hidden' },
  table:         { width: '100%', borderCollapse: 'collapse' },
  th:            { textAlign: 'left', color: '#475569', fontSize: 12, fontWeight: 600, textTransform: 'uppercase', padding: '12px 20px', background: '#0f172a', letterSpacing: 0.5 },
  tr:            { borderBottom: '1px solid #334155' },
  td:            { padding: '14px 20px', color: '#94a3b8', fontSize: 14 },
};

export default Leaderboard;
