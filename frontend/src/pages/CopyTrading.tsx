/**
 * Copy Trading Marketplace — browse top traders, allocate capital, start copying.
 *
 * Wires to: GET  /api/leaderboard
 *           POST /api/social/copy/{trader_id}
 *           GET  /api/social/copy/active
 *           DELETE /api/social/copy/{trader_id}
 */

import React, { useState, useEffect } from 'react';
import { useStore } from '../store';
import { api } from '../hooks/useApi';

function extractApiError(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: string } } })
    ?.response?.data?.detail;
  return detail ?? fallback;
}

// ── Types ─────────────────────────────────────────────────────────────────────

interface Leader {
  id: string;
  name: string;
  return_3m: number;
  sharpe: number;
  max_dd: number;
  followers: number;
  aum: number;
  fee: number;
  win_rate: number;
  trades_per_week: number;
  avg_trade_duration: string;
}



// ── Leader card ───────────────────────────────────────────────────────────────

const LeaderCard: React.FC<{
  leader: Leader;
  selected: boolean;
  onSelect: () => void;
}> = ({ leader, selected, onSelect }) => (
  <div
    onClick={onSelect}
    style={{
      ...s.leaderCard,
      border: `1px solid ${selected ? '#f59e0b' : '#334155'}`,
      boxShadow: selected ? '0 0 0 1px #f59e0b' : 'none',
      cursor: 'pointer',
    }}
  >
    <div style={s.leaderTop}>
      <div>
        <div style={s.leaderName}>{leader.name}</div>
        <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>
          👥 {leader.followers.toLocaleString()} followers
        </div>
      </div>
      <div style={{ textAlign: 'right' }}>
        <div style={{ fontSize: 24, fontWeight: 700, color: '#4ade80' }}>
          +{leader.return_3m}%
        </div>
        <div style={{ fontSize: 11, color: '#475569' }}>3M Return</div>
      </div>
    </div>

    <div style={s.metricsRow}>
      <div style={s.metric}>
        <div style={s.metricVal}>{leader.sharpe}</div>
        <div style={s.metricLbl}>Sharpe</div>
      </div>
      <div style={s.metric}>
        <div style={{ ...s.metricVal, color: '#f87171' }}>{leader.max_dd}%</div>
        <div style={s.metricLbl}>Max DD</div>
      </div>
      <div style={s.metric}>
        <div style={s.metricVal}>{leader.win_rate}%</div>
        <div style={s.metricLbl}>Win Rate</div>
      </div>
    </div>

    <div style={s.leaderFooter}>
      <span style={{ fontSize: 13, color: '#94a3b8' }}>
        AUM: <strong>${(leader.aum / 1_000_000).toFixed(2)}M</strong>
      </span>
      <span style={{ fontSize: 13, color: '#94a3b8' }}>
        Fee: <strong>{leader.fee}%</strong>
      </span>
    </div>
  </div>
);

// ── Main component ────────────────────────────────────────────────────────────

const CopyTrading: React.FC = () => {
  const [leaders, setLeaders]       = useState<Leader[]>([]);
  const [loading, setLoading]       = useState(true);
  const [loadErr, setLoadErr]       = useState('');
  const [selected, setSelected]     = useState<string | null>(null);
  const [allocation, setAllocation] = useState(10000);
  const [sortBy, setSortBy]         = useState<'return' | 'sharpe' | 'followers'>('return');
  const [copying, setCopying]       = useState(false);
  const [copyMsg, setCopyMsg]       = useState('');

  useEffect(() => {
    api.get<Leader[]>('/leaderboard')
      .then((r) => { setLeaders(r.data ?? []); setLoadErr(''); })
      .catch((err: unknown) => {
        console.warn('[CopyTrading] Failed to load leaders:', err);
        setLoadErr(extractApiError(err, 'Failed to load traders. Please try again.'));
        setLeaders([]);
      })
      .finally(() => setLoading(false));
  }, []);

  const sorted = [...leaders].sort((a, b) => {
    if (sortBy === 'return')    return b.return_3m - a.return_3m;
    if (sortBy === 'sharpe')    return b.sharpe - a.sharpe;
    if (sortBy === 'followers') return b.followers - a.followers;
    return 0;
  });

  const selectedLeader = leaders.find((l) => l.id === selected);

  const handleStartCopy = async () => {
    if (!selected) return;
    setCopying(true);
    setCopyMsg('');
    try {
      await api.post(`/social/copy/${selected}`, { allocation_amount: allocation });
      setCopyMsg(`Now copying ${selectedLeader?.name}. Allocation: $${allocation.toLocaleString()}`);
    } catch (e: unknown) {
      setCopyMsg(`Failed: ${(e as { message?: string })?.message ?? 'Unknown error'}`);
    }
    setCopying(false);
  };

  const estimatedMonthlyFee = selectedLeader
    ? (allocation * (selectedLeader.fee / 100) / 12).toFixed(2)
    : '0.00';

  return (
    <div style={s.page}>
      <div style={s.header}>
        <h1 style={s.title}>Copy Trading Marketplace</h1>
        <div style={{ display: 'flex', gap: 8 }}>
          <select value={sortBy} onChange={(e) => setSortBy(e.target.value as 'return' | 'sharpe' | 'followers')} style={s.select}>
            <option value="return">Sort by Return</option>
            <option value="sharpe">Sort by Sharpe</option>
            <option value="followers">Sort by Followers</option>
          </select>
        </div>
      </div>

      {/* Leader cards */}
      {loading ? (
        <p style={{ color: '#64748b', padding: '40px 0' }}>Loading traders…</p>
      ) : loadErr ? (
        <p style={{ color: '#f87171', padding: '40px 0' }}>⚠️ {loadErr}</p>
      ) : leaders.length === 0 ? (
        <p style={{ color: '#64748b', padding: '40px 0' }}>No traders available yet. Check back soon.</p>
      ) : (
        <div style={s.grid}>
          {sorted.map((leader) => (
            <LeaderCard
              key={leader.id}
              leader={leader}
              selected={selected === leader.id}
              onSelect={() => setSelected(leader.id === selected ? null : leader.id)}
            />
          ))}
        </div>
      )}

      {/* Allocation panel */}
      {selected && selectedLeader && (
        <div style={s.allocationCard}>
          <h3 style={s.cardTitle}>Start Copying — {selectedLeader.name}</h3>

          <div style={s.allocationGrid}>
            <div>
              <label style={s.label}>Allocation Amount</label>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <input
                  type="range"
                  min={1000}
                  max={100000}
                  step={1000}
                  value={allocation}
                  onChange={(e) => setAllocation(Number(e.target.value))}
                  style={{ flex: 1 }}
                />
                <input
                  type="number"
                  value={allocation}
                  onChange={(e) => setAllocation(Number(e.target.value))}
                  style={{ ...s.input, width: 120 }}
                />
              </div>
            </div>

            <div style={s.summaryBox}>
              <div style={s.summaryRow}>
                <span style={s.summaryLabel}>Estimated Monthly Fee</span>
                <span style={s.summaryVal}>${estimatedMonthlyFee}</span>
              </div>
              <div style={s.summaryRow}>
                <span style={s.summaryLabel}>Max Drawdown Stop</span>
                <span style={{ ...s.summaryVal, color: '#f87171' }}>
                  ${(allocation * Math.abs(selectedLeader.max_dd) / 100).toFixed(0)}
                </span>
              </div>
              <div style={s.summaryRow}>
                <span style={s.summaryLabel}>Trades / Week</span>
                <span style={s.summaryVal}>{selectedLeader.trades_per_week}</span>
              </div>
              <div style={s.summaryRow}>
                <span style={s.summaryLabel}>Avg Trade Duration</span>
                <span style={s.summaryVal}>{selectedLeader.avg_trade_duration}</span>
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginTop: 16 }}>
            <button
              onClick={handleStartCopy}
              disabled={copying}
              style={{ ...s.copyBtn, opacity: copying ? 0.6 : 1 }}
            >
              {copying ? 'Starting…' : 'Start Copy Trading'}
            </button>
            <button onClick={() => setSelected(null)} style={s.cancelBtn}>Cancel</button>
          </div>

          {copyMsg && (
            <div style={{
              marginTop: 12, fontSize: 14,
              color: copyMsg.startsWith('Failed') ? '#f87171' : '#4ade80',
            }}>
              {copyMsg}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

// ── Styles ────────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  page:          { padding: 24, maxWidth: 1100, margin: '0 auto' },
  header:        { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 },
  title:         { fontSize: 24, fontWeight: 700, color: '#f1f5f9', margin: 0 },
  select:        { background: '#1e293b', border: '1px solid #334155', borderRadius: 8, color: '#f1f5f9', padding: '8px 12px', fontSize: 13 },
  grid:          { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 16, marginBottom: 24 },
  leaderCard:    { background: '#1e293b', border: '1px solid #334155', borderRadius: 12, padding: 16, transition: 'border-color 0.15s' },
  leaderTop:     { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 },
  leaderName:    { fontSize: 16, fontWeight: 700, color: '#f1f5f9' },
  metricsRow:    { display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginBottom: 16 },
  metric:        { textAlign: 'center' },
  metricVal:     { fontSize: 18, fontWeight: 700, color: '#f1f5f9' },
  metricLbl:     { fontSize: 11, color: '#475569', marginTop: 2 },
  leaderFooter:  { display: 'flex', justifyContent: 'space-between', paddingTop: 12, borderTop: '1px solid #334155' },
  allocationCard:{ background: '#1e293b', border: '1px solid #f59e0b55', borderRadius: 12, padding: 24 },
  cardTitle:     { fontSize: 18, fontWeight: 700, color: '#f1f5f9', margin: '0 0 20px' },
  allocationGrid:{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 },
  label:         { display: 'block', fontSize: 13, color: '#94a3b8', marginBottom: 8 },
  input:         { background: '#0f172a', border: '1px solid #334155', borderRadius: 8, color: '#f1f5f9', padding: '8px 12px', fontSize: 14 },
  summaryBox:    { background: '#0f172a', border: '1px solid #334155', borderRadius: 8, padding: 16 },
  summaryRow:    { display: 'flex', justifyContent: 'space-between', marginBottom: 10 },
  summaryLabel:  { fontSize: 13, color: '#64748b' },
  summaryVal:    { fontSize: 13, fontWeight: 600, color: '#f1f5f9' },
  copyBtn:       { background: '#f59e0b', border: 'none', borderRadius: 8, color: '#0f172a', fontSize: 14, fontWeight: 700, cursor: 'pointer', padding: '12px 24px' },
  cancelBtn:     { background: 'transparent', border: '1px solid #334155', borderRadius: 8, color: '#94a3b8', fontSize: 14, cursor: 'pointer', padding: '12px 20px' },
};

export default CopyTrading;
