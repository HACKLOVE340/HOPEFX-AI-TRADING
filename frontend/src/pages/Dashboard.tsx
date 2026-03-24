import React, { useEffect, useState } from 'react';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler,
} from 'chart.js';
import { Line } from 'react-chartjs-2';

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend, Filler);

// ── Types ─────────────────────────────────────────────────────────────────────

interface AccountInfo {
  balance: number;
  equity: number;
  margin_used: number;
  unrealized_pnl: number;
}

interface Position {
  symbol: string;
  side: string;
  quantity: number;
  entry_price: number;
  current_price: number;
  unrealized_pnl: number;
}

interface BrainState {
  system_state: string;
  active_strategies: number;
  signals_today: number;
  trades_today: number;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const fmtUSD = (n: number) =>
  (n >= 0 ? '+' : '') + n.toLocaleString('en-US', { style: 'currency', currency: 'USD' });

const fmtNum = (n: number, d = 2) =>
  n.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });

// ── Mock data ─────────────────────────────────────────────────────────────────

const MOCK_ACCOUNT: AccountInfo = {
  balance: 100_000,
  equity: 102_340.5,
  margin_used: 4_200,
  unrealized_pnl: 2_340.5,
};

const MOCK_POSITIONS: Position[] = [
  { symbol: 'XAUUSD', side: 'buy',  quantity: 0.5,   entry_price: 2041.20, current_price: 2058.40, unrealized_pnl: 860 },
  { symbol: 'EURUSD', side: 'sell', quantity: 10000, entry_price: 1.0872,  current_price: 1.0851,  unrealized_pnl: 210 },
];

const MOCK_BRAIN: BrainState = {
  system_state: 'running',
  active_strategies: 3,
  signals_today: 12,
  trades_today: 4,
};

const MOCK_LABELS = Array.from({ length: 30 }, (_, i) => {
  const d = new Date();
  d.setDate(d.getDate() - (29 - i));
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
});

const MOCK_EQUITY = MOCK_LABELS.reduce<number[]>((acc, _, i) => {
  const prev = acc[i - 1] ?? 100_000;
  acc.push(prev + (Math.random() - 0.42) * 600);
  return acc;
}, []);

// ── Sub-components ────────────────────────────────────────────────────────────

const StatCard: React.FC<{ label: string; value: string; positive?: boolean }> = ({ label, value, positive }) => (
  <div style={s.statCard}>
    <div style={s.statLabel}>{label}</div>
    <div style={{ ...s.statValue, color: positive === true ? '#4ade80' : positive === false ? '#f87171' : '#f8fafc' }}>
      {value}
    </div>
  </div>
);

// ── Main ──────────────────────────────────────────────────────────────────────

const Dashboard: React.FC = () => {
  const [account, setAccount] = useState<AccountInfo>(MOCK_ACCOUNT);
  const [positions, setPositions] = useState<Position[]>(MOCK_POSITIONS);
  const [brain, setBrain] = useState<BrainState>(MOCK_BRAIN);

  useEffect(() => {
    const load = async () => {
      try {
        const [accRes, posRes, brainRes] = await Promise.all([
          fetch('/api/v1/account'),
          fetch('/api/v1/positions'),
          fetch('/api/v1/brain/state'),
        ]);
        if (accRes.ok)   setAccount(await accRes.json());
        if (posRes.ok)   setPositions((await posRes.json()).positions ?? []);
        if (brainRes.ok) setBrain((await brainRes.json()).state);
      } catch (_) { /* keep mock data */ }
    };
    load();
    const t = setInterval(load, 15_000);
    return () => clearInterval(t);
  }, []);

  const chartData = {
    labels: MOCK_LABELS,
    datasets: [{
      label: 'Equity',
      data: MOCK_EQUITY,
      borderColor: '#3b82f6',
      backgroundColor: 'rgba(59,130,246,0.08)',
      borderWidth: 2,
      pointRadius: 0,
      fill: true,
      tension: 0.4,
    }],
  };

  const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: {
      x: { grid: { color: '#1e293b' }, ticks: { color: '#64748b', maxTicksLimit: 6 } },
      y: { grid: { color: '#1e293b' }, ticks: { color: '#64748b', callback: (v: unknown) => '$' + Number(v).toLocaleString() } },
    },
  };

  return (
    <div style={s.page}>
      <div style={s.header}>
        <h1 style={s.heading}>Dashboard</h1>
        <div style={{ fontSize: 13, color: '#64748b', display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: brain.system_state === 'running' ? '#22c55e' : '#f59e0b', display: 'inline-block' }} />
          <span style={{ textTransform: 'capitalize' }}>{brain.system_state}</span>
          <span>· {brain.active_strategies} strategies</span>
        </div>
      </div>

      <div style={s.statsGrid}>
        <StatCard label="Balance"        value={'$' + fmtNum(account.balance)} />
        <StatCard label="Equity"         value={'$' + fmtNum(account.equity)} />
        <StatCard label="Unrealized P&L" value={fmtUSD(account.unrealized_pnl)} positive={account.unrealized_pnl >= 0} />
        <StatCard label="Margin used"    value={'$' + fmtNum(account.margin_used)} />
        <StatCard label="Signals today"  value={String(brain.signals_today)} />
        <StatCard label="Trades today"   value={String(brain.trades_today)} />
      </div>

      <div style={s.card}>
        <div style={s.cardTitle}>Equity curve — last 30 days</div>
        <div style={{ height: 220 }}>
          <Line data={chartData} options={chartOptions} />
        </div>
      </div>

      <div style={s.card}>
        <div style={s.cardTitle}>Open positions</div>
        {positions.length === 0 ? (
          <p style={{ color: '#64748b', fontSize: 14 }}>No open positions.</p>
        ) : (
          <table style={s.table}>
            <thead>
              <tr>{['Symbol','Side','Size','Entry','Current','P&L'].map(h => <th key={h} style={s.th}>{h}</th>)}</tr>
            </thead>
            <tbody>
              {positions.map((p, i) => (
                <tr key={i} style={s.tr}>
                  <td style={{ ...s.td, fontWeight: 600, color: '#e2e8f0' }}>{p.symbol}</td>
                  <td style={{ ...s.td, color: p.side === 'buy' ? '#4ade80' : '#f87171', fontWeight: 600, textTransform: 'uppercase' }}>{p.side}</td>
                  <td style={s.td}>{p.quantity}</td>
                  <td style={s.td}>{fmtNum(p.entry_price, 4)}</td>
                  <td style={s.td}>{fmtNum(p.current_price, 4)}</td>
                  <td style={{ ...s.td, color: p.unrealized_pnl >= 0 ? '#4ade80' : '#f87171', fontWeight: 600 }}>{fmtUSD(p.unrealized_pnl)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};

const s: Record<string, React.CSSProperties> = {
  page:      { padding: '28px 24px', maxWidth: 1100, margin: '0 auto' },
  header:    { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 },
  heading:   { fontSize: 24, fontWeight: 700, color: '#f8fafc' },
  statsGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12, marginBottom: 20 },
  statCard:  { background: '#1e293b', border: '1px solid #334155', borderRadius: 10, padding: '14px 16px' },
  statLabel: { fontSize: 11, color: '#64748b', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 6 },
  statValue: { fontSize: 22, fontWeight: 700 },
  card:      { background: '#1e293b', border: '1px solid #334155', borderRadius: 10, padding: '18px 20px', marginBottom: 16 },
  cardTitle: { fontSize: 11, fontWeight: 600, color: '#64748b', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 14 },
  table:     { width: '100%', borderCollapse: 'collapse' },
  th:        { textAlign: 'left', fontSize: 11, color: '#64748b', textTransform: 'uppercase', letterSpacing: 0.5, padding: '6px 10px', borderBottom: '1px solid #334155' },
  tr:        { borderBottom: '1px solid #1e293b' },
  td:        { padding: '10px 10px', fontSize: 14, color: '#cbd5e1' },
};

export default Dashboard;
