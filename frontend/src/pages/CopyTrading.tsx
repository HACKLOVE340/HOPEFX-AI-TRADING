/**
 * Copy Trading Marketplace — browse top traders, allocate capital, start copying.
 *
 * Wires to: GET  /api/leaderboard
 *           POST /api/social/copy/{trader_id}
 *           GET  /api/social/copy/active
 *           DELETE /api/social/copy/{trader_id}
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { PageHeader, EmptyState } from '../components';
import { useStore } from '../store';
import { copyTradingApi } from '../hooks/useApi';

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

interface ActiveSession {
  trader_id: string;
  trader_name: string;
  allocation_amount: number;
  unrealised_pnl: number | null;
  realised_pnl: number | null;
  started_at: string;
  status: string;
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
  const navigate = useNavigate();
  const [leaders, setLeaders]           = useState<Leader[]>([]);
  const [loading, setLoading]           = useState(true);
  const [loadErr, setLoadErr]           = useState('');
  const [selected, setSelected]         = useState<string | null>(null);
  const [allocation, setAllocation]     = useState(10000);
  const [sortBy, setSortBy]             = useState<'return' | 'sharpe' | 'followers'>('return');
  const [copying, setCopying]           = useState(false);
  const [copyMsg, setCopyMsg]           = useState('');
  const [sessions, setSessions]         = useState<ActiveSession[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [stoppingId, setStoppingId]     = useState<string | null>(null);
  const [updatingId, setUpdatingId]     = useState<string | null>(null);
  const [editAlloc, setEditAlloc]       = useState<Record<string, number>>({});
  const [activeTab, setActiveTab]       = useState<'browse' | 'active'>('browse');

  const mountedRef = useRef(true);
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

  const loadLeaders = useCallback(async () => {
    setLoading(true);
    try {
      const r = await copyTradingApi.leaders();
      if (!mountedRef.current) return;
      const d = r.data as Leader[] | { traders?: Leader[]; leaderboard?: Leader[] };
      setLeaders(Array.isArray(d) ? d : (d.traders ?? d.leaderboard ?? []));
      setLoadErr('');
    } catch (err: unknown) {
      if (!mountedRef.current) return;
      if ((err as {name?:string}).name === 'CanceledError') return;
      setLoadErr(extractApiError(err, 'Failed to load traders. Please try again.'));
      setLeaders([]);
    } finally { if (mountedRef.current) setLoading(false); }
  }, []);

  const loadSessions = useCallback(async () => {
    setSessionsLoading(true);
    try {
      const r = await copyTradingApi.activeSessions();
      if (!mountedRef.current) return;
      const d = r.data as ActiveSession[] | { sessions?: ActiveSession[] };
      setSessions(Array.isArray(d) ? d : (d.sessions ?? []));
    } catch {
      if (!mountedRef.current) return;
      setSessions([]);
    }
    finally { if (mountedRef.current) setSessionsLoading(false); }
  }, []);

  useEffect(() => { loadLeaders(); loadSessions(); }, [loadLeaders, loadSessions]);

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
      await copyTradingApi.startCopy(selected, { allocation_amount: allocation });
      setCopyMsg(`Now copying ${selectedLeader?.name}. Allocation: $${allocation.toLocaleString()}`);
      setSelected(null);
      await loadSessions();
      setActiveTab('active');
    } catch (e: unknown) {
      setCopyMsg(`Failed: ${(e as { message?: string })?.message ?? 'Unknown error'}`);
    }
    setCopying(false);
  };

  const handleStopCopy = async (traderId: string) => {
    setStoppingId(traderId);
    try {
      await copyTradingApi.stopCopy(traderId);
      await loadSessions();
    } catch { /* non-fatal */ }
    finally { setStoppingId(null); }
  };

  const handleUpdateAllocation = async (traderId: string) => {
    const amount = editAlloc[traderId];
    if (!amount || amount <= 0) return;
    setUpdatingId(traderId);
    try {
      await copyTradingApi.updateAllocation(traderId, amount);
      await loadSessions();
      setEditAlloc(prev => { const n = { ...prev }; delete n[traderId]; return n; });
    } catch { /* non-fatal */ }
    finally { setUpdatingId(null); }
  };

  const estimatedMonthlyFee = selectedLeader
    ? (allocation * (selectedLeader.fee / 100) / 12).toFixed(2)
    : '0.00';

  return (
    <div style={s.page}>
      <PageHeader
        title="Copy Trading Marketplace"
        subtitle="Mirror top traders automatically. Allocate capital and start earning."
        breadcrumbs={[
          { label: 'Dashboard', href: '/dashboard' },
          { label: 'Community', href: '/leaderboard' },
          { label: 'Copy Trading' },
        ]}
        actions={
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            {(['browse', 'active'] as const).map(t => (
              <button key={t} onClick={() => setActiveTab(t)} style={{
                ...s.tabBtn,
                ...(activeTab === t ? s.tabBtnActive : {}),
              }}>
                {t === 'browse' ? '🔍 Browse Traders' : `📋 Active Sessions (${sessions.length})`}
              </button>
            ))}
            <div style={{ width: 1, height: 24, background: '#334155' }} />
            <button
              onClick={() => navigate('/leaderboard')}
              style={{ background: 'rgba(251,191,36,0.1)', border: '1px solid rgba(251,191,36,0.3)', borderRadius: 7, color: '#fbbf24', fontSize: 12, fontWeight: 600, padding: '6px 12px', cursor: 'pointer', fontFamily: 'inherit' }}
            >
              🏆 Leaderboard
            </button>
            <button
              onClick={() => navigate('/signals')}
              style={{ background: 'rgba(167,139,250,0.1)', border: '1px solid rgba(167,139,250,0.3)', borderRadius: 7, color: '#a78bfa', fontSize: 12, fontWeight: 600, padding: '6px 12px', cursor: 'pointer', fontFamily: 'inherit' }}
            >
              📡 Signals
            </button>
          </div>
        }
      />

      {/* ── Active Sessions Tab ── */}
      {activeTab === 'active' && (
        <div>
          {sessionsLoading && <p style={{ color: '#64748b' }}>Loading sessions…</p>}
          {!sessionsLoading && sessions.length === 0 && (
            <EmptyState
              icon="📋"
              title="No active copy sessions"
              description="Browse top traders and allocate capital to start mirroring their trades automatically."
              action={
                <div style={{ display: 'flex', gap: 8 }}>
                  <button
                    onClick={() => setActiveTab('browse')}
                    style={{ padding: '8px 18px', background: '#3b82f6', border: 'none', borderRadius: 8, color: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit' }}
                  >
                    🔍 Browse Traders
                  </button>
                  <button
                    onClick={() => navigate('/leaderboard')}
                    style={{ padding: '8px 18px', background: 'transparent', border: '1px solid #334155', borderRadius: 8, color: '#94a3b8', fontSize: 13, cursor: 'pointer', fontFamily: 'inherit' }}
                  >
                    🏆 Leaderboard
                  </button>
                </div>
              }
            />
          )}
          {sessions.map(sess => {
            const totalPnl = (sess.unrealised_pnl ?? 0) + (sess.realised_pnl ?? 0);
            return (
              <div key={sess.trader_id} style={{ ...s.allocationCard, marginBottom: 12 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <div>
                    <div style={{ fontSize: 16, fontWeight: 700, color: '#f1f5f9' }}>{sess.trader_name}</div>
                    <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>
                      Started {new Date(sess.started_at).toLocaleDateString()} ·{' '}
                      <span style={{ color: sess.status === 'active' ? '#4ade80' : '#f59e0b' }}>{sess.status}</span>
                    </div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div style={{ fontSize: 22, fontWeight: 700, color: totalPnl >= 0 ? '#4ade80' : '#f87171' }}>
                      {totalPnl >= 0 ? '+' : ''}${totalPnl.toFixed(2)}
                    </div>
                    <div style={{ fontSize: 11, color: '#64748b' }}>Total P&L</div>
                  </div>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 12, margin: '16px 0' }}>
                  <div style={s.sessMetric}>
                    <div style={{ fontSize: 11, color: '#64748b' }}>Allocation</div>
                    <div style={{ fontSize: 16, fontWeight: 700, color: '#f1f5f9' }}>${sess.allocation_amount.toLocaleString()}</div>
                  </div>
                  <div style={s.sessMetric}>
                    <div style={{ fontSize: 11, color: '#64748b' }}>Unrealised P&L</div>
                    <div style={{ fontSize: 16, fontWeight: 700, color: (sess.unrealised_pnl ?? 0) >= 0 ? '#4ade80' : '#f87171' }}>
                      {sess.unrealised_pnl != null ? `${sess.unrealised_pnl >= 0 ? '+' : ''}$${sess.unrealised_pnl.toFixed(2)}` : '—'}
                    </div>
                  </div>
                  <div style={s.sessMetric}>
                    <div style={{ fontSize: 11, color: '#64748b' }}>Realised P&L</div>
                    <div style={{ fontSize: 16, fontWeight: 700, color: (sess.realised_pnl ?? 0) >= 0 ? '#4ade80' : '#f87171' }}>
                      {sess.realised_pnl != null ? `${sess.realised_pnl >= 0 ? '+' : ''}$${sess.realised_pnl.toFixed(2)}` : '—'}
                    </div>
                  </div>
                </div>

                {/* Allocation update */}
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 12 }}>
                  <input
                    type="number"
                    placeholder="New allocation…"
                    value={editAlloc[sess.trader_id] ?? ''}
                    onChange={e => setEditAlloc(prev => ({ ...prev, [sess.trader_id]: Number(e.target.value) }))}
                    style={{ ...s.input, width: 160 }}
                  />
                  <button
                    onClick={() => handleUpdateAllocation(sess.trader_id)}
                    disabled={updatingId === sess.trader_id}
                    style={{ ...s.copyBtn, padding: '8px 14px', fontSize: 13, background: '#3b82f6' }}
                  >
                    {updatingId === sess.trader_id ? 'Updating…' : 'Update Allocation'}
                  </button>
                </div>

                <button
                  onClick={() => handleStopCopy(sess.trader_id)}
                  disabled={stoppingId === sess.trader_id}
                  style={{ background: '#450a0a', border: '1px solid #7f1d1d', borderRadius: 8, color: '#f87171', cursor: 'pointer', fontSize: 13, fontWeight: 600, padding: '8px 16px' }}
                >
                  {stoppingId === sess.trader_id ? 'Stopping…' : '⏹ Stop Copying'}
                </button>
              </div>
            );
          })}
        </div>
      )}

      {/* ── Browse Tab ── */}
      {activeTab === 'browse' && (
      <>
      {/* Sort controls */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        <select value={sortBy} onChange={(e) => setSortBy(e.target.value as typeof sortBy)} style={s.select}>
          <option value="return">Sort by Return</option>
          <option value="sharpe">Sort by Sharpe</option>
          <option value="followers">Sort by Followers</option>
        </select>
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
      </>
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
  tabBtn:        { background: '#1e293b', border: '1px solid #334155', borderRadius: 8, color: '#64748b', cursor: 'pointer', fontSize: 13, fontWeight: 600, padding: '8px 16px' },
  tabBtnActive:  { background: '#1e3a5f', border: '1px solid #3b82f6', color: '#60a5fa' },
  sessMetric:    { background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8, padding: '10px 14px' },
};

export default CopyTrading;
