import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../hooks/useApi';
import { useStore } from '../store';

// ── Types ─────────────────────────────────────────────────────────────────────

interface AffiliateMetrics {
  total_referrals: number;
  converted_referrals: number;
  total_revenue: number;
  total_commissions: number;
  pending_commissions: number;
  conversion_rate: number;
}

interface AffiliateAccount {
  affiliate_id: string;
  code: string;
  level: 'bronze' | 'silver' | 'gold' | 'platinum';
  commission_rate: number;
  status: string;
}

interface Referral {
  referral_id: string;
  referred_user_id: string;
  status: 'pending' | 'converted' | 'paid' | 'expired';
  created_at: string;
  converted_at?: string;
  commission_amount?: number;
}

interface LeaderboardEntry {
  rank: number;
  affiliate_id: string;
  code: string;
  level: string;
  total_commissions: number;
  converted_referrals: number;
}

// ── Constants ─────────────────────────────────────────────────────────────────

const LEVEL_COLORS: Record<string, string> = {
  bronze: '#cd7f32',
  silver: '#94a3b8',
  gold: '#f59e0b',
  platinum: '#a78bfa',
};

const LEVEL_RATES: Record<string, string> = {
  bronze: '10%',
  silver: '15%',
  gold: '20%',
  platinum: '25%',
};

const BASE_URL = window.location.origin;

// ── Helpers ───────────────────────────────────────────────────────────────────

const fmt = (n: number, decimals = 2) =>
  n.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });

const fmtUSD = (n: number) =>
  '$' + fmt(n);

const statusBadge = (s: string) => {
  const map: Record<string, { bg: string; color: string }> = {
    pending:   { bg: '#1e3a5f', color: '#60a5fa' },
    converted: { bg: '#14532d', color: '#4ade80' },
    paid:      { bg: '#1a2e1a', color: '#22c55e' },
    expired:   { bg: '#2d1b1b', color: '#f87171' },
    active:    { bg: '#14532d', color: '#4ade80' },
  };
  const c = map[s] ?? { bg: '#1e293b', color: '#94a3b8' };
  return (
    <span style={{ ...styles.badge, background: c.bg, color: c.color }}>
      {s}
    </span>
  );
};

// ── Sub-components ────────────────────────────────────────────────────────────

const MetricCard: React.FC<{ label: string; value: string; sub?: string }> = ({ label, value, sub }) => (
  <div style={styles.metricCard}>
    <div style={styles.metricValue}>{value}</div>
    <div style={styles.metricLabel}>{label}</div>
    {sub && <div style={styles.metricSub}>{sub}</div>}
  </div>
);

// ── Main component ────────────────────────────────────────────────────────────

const Affiliate: React.FC = () => {
  const [account, setAccount]           = useState<AffiliateAccount | null>(null);
  const [metrics, setMetrics]           = useState<AffiliateMetrics | null>(null);
  const [referrals, setReferrals]       = useState<Referral[]>([]);
  const [leaderboard, setLeaderboard]   = useState<LeaderboardEntry[]>([]);
  const [loading, setLoading]           = useState(true);
  const [apiError, setApiError]         = useState<string | null>(null);
  const [referralErr, setReferralErr]   = useState<string | null>(null);
  const [leaderErr, setLeaderErr]       = useState<string | null>(null);
  const [copied, setCopied]             = useState(false);
  const [signupLoading, setSignupLoading] = useState(false);
  const [activeTab, setActiveTab]       = useState<'overview' | 'referrals' | 'leaderboard'>('overview');

  const user   = useStore((s) => s.user);
  const userId = user?.id;

  const loadData = useCallback(async () => {
    if (!userId) return;
    setLoading(true);
    setApiError(null);
    try {
      const res = await api.get<{
        has_affiliate_account: boolean;
        affiliate: AffiliateAccount;
        metrics: AffiliateMetrics;
      }>(`/monetization/affiliate/${userId}`);
      const data = res.data;
      if (data.has_affiliate_account) {
        setAccount(data.affiliate);
        setMetrics(data.metrics);
        try {
          const rRes = await api.get<{ referrals: Referral[] }>(
            `/monetization/affiliate/${data.affiliate.affiliate_id}/referrals`
          );
          setReferrals(rRes.data.referrals ?? []);
        } catch (err: unknown) {
          setReferralErr(err instanceof Error ? err.message : 'Failed to load referrals.');
        }
      }
      try {
        const lRes = await api.get<{ leaderboard?: LeaderboardEntry[] } | LeaderboardEntry[]>(
          '/monetization/affiliate/leaderboard?limit=10'
        );
        const lData = lRes.data;
        setLeaderboard(Array.isArray(lData) ? lData : (lData as { leaderboard?: LeaderboardEntry[] }).leaderboard ?? []);
      } catch (err: unknown) {
        setLeaderErr(err instanceof Error ? err.message : 'Failed to load leaderboard.');
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to load affiliate data.';
      setApiError(msg);
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => { loadData(); }, [loadData]);

  const handleSignup = async () => {
    if (!userId) return;
    setSignupLoading(true);
    try {
      await api.post('/monetization/affiliate/signup', { user_id: userId });
      await loadData();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Signup failed. Please try again.';
      setApiError(msg);
    } finally {
      setSignupLoading(false);
    }
  };

  const copyLink = () => {
    if (!account) return;
    const link = `${BASE_URL}/?ref=${account.code}`;
    navigator.clipboard.writeText(link).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    });
  };

  if (!userId) {
    return <div style={styles.page}><p style={{ color: '#94a3b8' }}>Please log in to view your affiliate dashboard.</p></div>;
  }

  if (loading) {
    return <div style={styles.page}><p style={{ color: '#94a3b8' }}>Loading affiliate data…</p></div>;
  }

  if (apiError) {
    return (
      <div style={styles.page}>
        <h1 style={styles.heading}>Affiliate Program</h1>
        <div style={{ background: '#450a0a', border: '1px solid #dc2626', borderRadius: 10, padding: '20px 24px', color: '#fca5a5' }}>
          <strong>Error:</strong> {apiError}
          <button onClick={loadData} style={{ marginLeft: 16, background: 'transparent', border: '1px solid #dc2626', color: '#fca5a5', borderRadius: 6, padding: '4px 12px', cursor: 'pointer' }}>
            Retry
          </button>
        </div>
      </div>
    );
  }

  // ── Not enrolled ──────────────────────────────────────────────────────────
  if (!account) {
    return (
      <div style={styles.page}>
        <h1 style={styles.heading}>Affiliate Program</h1>
        <div style={styles.enrollCard}>
          <h2 style={{ fontSize: 22, marginBottom: 12, color: '#f8fafc' }}>Earn by referring traders</h2>
          <p style={{ color: '#94a3b8', marginBottom: 24, lineHeight: 1.6 }}>
            Share your referral link and earn recurring commissions on every subscription
            your referrals purchase. Commissions range from <strong style={{ color: '#f8fafc' }}>10% (Bronze)</strong> to{' '}
            <strong style={{ color: '#a78bfa' }}>25% (Platinum)</strong> based on your performance.
          </p>
          <div style={styles.tierGrid}>
            {Object.entries(LEVEL_RATES).map(([level, rate]) => (
              <div key={level} style={{ ...styles.tierCard, border: `1px solid ${LEVEL_COLORS[level]}` }}>
                <div style={{ color: LEVEL_COLORS[level], fontWeight: 700, textTransform: 'capitalize', marginBottom: 4 }}>{level}</div>
                <div style={{ fontSize: 24, fontWeight: 800, color: '#f8fafc' }}>{rate}</div>
                <div style={{ fontSize: 12, color: '#64748b' }}>commission</div>
              </div>
            ))}
          </div>
          <button
            onClick={handleSignup}
            disabled={signupLoading}
            style={{ ...styles.primaryBtn, marginTop: 24, opacity: signupLoading ? 0.6 : 1 }}
          >
            {signupLoading ? 'Joining…' : 'Join the affiliate program'}
          </button>
        </div>
      </div>
    );
  }

  const referralLink = `${BASE_URL}/?ref=${account.code}`;

  // ── Enrolled ──────────────────────────────────────────────────────────────
  return (
    <div style={styles.page}>
      <div style={styles.pageHeader}>
        <div>
          <h1 style={styles.heading}>Affiliate Program</h1>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ ...styles.levelBadge, background: LEVEL_COLORS[account.level] + '22', color: LEVEL_COLORS[account.level], border: `1px solid ${LEVEL_COLORS[account.level]}` }}>
              {account.level.toUpperCase()}
            </span>
            <span style={{ color: '#64748b', fontSize: 14 }}>
              {(account.commission_rate * 100).toFixed(0)}% commission · {statusBadge(account.status)}
            </span>
          </div>
        </div>
      </div>

      {/* Referral link */}
      <div style={styles.linkCard}>
        <div style={styles.linkLabel}>Your referral link</div>
        <div style={styles.linkRow}>
          <code style={styles.linkCode}>{referralLink}</code>
          <button onClick={copyLink} style={styles.copyBtn}>
            {copied ? '✅ Copied' : 'Copy link'}
          </button>
        </div>
        <div style={{ fontSize: 12, color: '#64748b', marginTop: 8 }}>
          Code: <strong style={{ color: '#94a3b8' }}>{account.code}</strong>
        </div>
      </div>

      {/* Tabs */}
      <div style={styles.tabs}>
        {(['overview', 'referrals', 'leaderboard'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            style={{ ...styles.tab, ...(activeTab === tab ? styles.tabActive : {}) }}
          >
            {tab.charAt(0).toUpperCase() + tab.slice(1)}
          </button>
        ))}
      </div>

      {/* Overview */}
      {activeTab === 'overview' && metrics && (
        <>
          <div style={styles.metricsGrid}>
            <MetricCard label="Total referrals" value={String(metrics.total_referrals)} />
            <MetricCard label="Converted" value={String(metrics.converted_referrals)} sub={`${fmt(metrics.conversion_rate, 1)}% rate`} />
            <MetricCard label="Total earned" value={fmtUSD(metrics.total_commissions)} />
            <MetricCard label="Pending payout" value={fmtUSD(metrics.pending_commissions)} sub="Next payout: 1st of month" />
          </div>
          <div style={styles.card}>
            <h3 style={styles.cardTitle}>How commissions work</h3>
            <ul style={styles.howList}>
              <li>Share your referral link — anyone who signs up through it is tracked for 30 days.</li>
              <li>When a referral subscribes to any paid plan, you earn a commission on their monthly fee.</li>
              <li>Commissions are paid out on the 1st of each month via your registered payment method.</li>
              <li>Reach higher tiers by converting more referrals: Silver (5+), Gold (15+), Platinum (30+).</li>
            </ul>
          </div>
        </>
      )}

      {/* Referrals */}
      {activeTab === 'referrals' && (
        <div style={styles.card}>
          <h3 style={styles.cardTitle}>Referral history</h3>
          {referralErr && <div style={styles.subError}>{referralErr}</div>}
          {!referralErr && referrals.length === 0 ? (
            <p style={{ color: '#64748b', fontSize: 14 }}>No referrals yet. Share your link to get started.</p>
          ) : (
            <table style={styles.table}>
              <thead>
                <tr>
                  <th style={styles.th}>User</th>
                  <th style={styles.th}>Status</th>
                  <th style={styles.th}>Date</th>
                  <th style={styles.th}>Commission</th>
                </tr>
              </thead>
              <tbody>
                {referrals.map((r) => (
                  <tr key={r.referral_id} style={styles.tr}>
                    <td style={styles.td}>{r.referred_user_id}</td>
                    <td style={styles.td}>{statusBadge(r.status)}</td>
                    <td style={styles.td}>{new Date(r.created_at).toLocaleDateString()}</td>
                    <td style={styles.td}>
                      {r.commission_amount != null ? fmtUSD(r.commission_amount) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Leaderboard */}
      {activeTab === 'leaderboard' && (
        <div style={styles.card}>
          <h3 style={styles.cardTitle}>Top affiliates</h3>
          {leaderErr && <div style={styles.subError}>{leaderErr}</div>}
          {!leaderErr && <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>#</th>
                <th style={styles.th}>Code</th>
                <th style={styles.th}>Level</th>
                <th style={styles.th}>Conversions</th>
                <th style={styles.th}>Earned</th>
              </tr>
            </thead>
            <tbody>
              {leaderboard.map((e) => (
                <tr
                  key={e.affiliate_id}
                  style={{
                    ...styles.tr,
                    background: e.affiliate_id === account.affiliate_id ? '#1e3a5f' : undefined,
                  }}
                >
                  <td style={styles.td}>
                    {e.rank === 1 ? '🥇' : e.rank === 2 ? '🥈' : e.rank === 3 ? '🥉' : e.rank}
                  </td>
                  <td style={{ ...styles.td, fontFamily: 'monospace', color: '#e2e8f0' }}>{e.code}</td>
                  <td style={{ ...styles.td, color: LEVEL_COLORS[e.level] ?? '#94a3b8', textTransform: 'capitalize' }}>{e.level}</td>
                  <td style={styles.td}>{e.converted_referrals}</td>
                  <td style={{ ...styles.td, color: '#4ade80' }}>{fmtUSD(e.total_commissions)}</td>
                </tr>
              ))}
            </tbody>
          </table>}
        </div>
      )}
    </div>
  );
};

// ── Styles ────────────────────────────────────────────────────────────────────

const styles: Record<string, React.CSSProperties> = {
  page: {
    maxWidth: 860,
    margin: '0 auto',
    padding: '32px 16px',
    fontFamily: 'system-ui, -apple-system, sans-serif',
    color: '#f1f5f9',
    background: '#0f172a',
    minHeight: '100vh',
  },
  pageHeader: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 28 },
  heading: { fontSize: 28, fontWeight: 700, marginBottom: 6, color: '#f8fafc' },
  levelBadge: {
    fontSize: 11, fontWeight: 700, padding: '2px 10px', borderRadius: 20,
    letterSpacing: 1,
  },
  enrollCard: {
    background: '#1e293b', border: '1px solid #334155', borderRadius: 12,
    padding: '32px 28px', maxWidth: 600,
  },
  tierGrid: { display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 },
  tierCard: {
    background: '#0f172a', border: '1px solid #334155', borderRadius: 8,
    padding: '14px 10px', textAlign: 'center',
  },
  primaryBtn: {
    padding: '12px 28px', background: '#3b82f6', color: '#fff',
    border: 'none', borderRadius: 8, fontSize: 15, fontWeight: 600, cursor: 'pointer',
  },
  linkCard: {
    background: '#1e293b', border: '1px solid #334155', borderRadius: 10,
    padding: '16px 20px', marginBottom: 24,
  },
  linkLabel: { fontSize: 12, color: '#64748b', marginBottom: 8, textTransform: 'uppercase', letterSpacing: 0.5 },
  linkRow: { display: 'flex', alignItems: 'center', gap: 12 },
  linkCode: {
    flex: 1, background: '#0f172a', border: '1px solid #475569', borderRadius: 6,
    padding: '8px 12px', fontSize: 13, color: '#93c5fd', wordBreak: 'break-all',
  },
  copyBtn: {
    padding: '8px 16px', background: '#3b82f6', color: '#fff',
    border: 'none', borderRadius: 6, fontSize: 13, cursor: 'pointer', whiteSpace: 'nowrap',
  },
  tabs: { display: 'flex', gap: 4, marginBottom: 20, borderBottom: '1px solid #1e293b', paddingBottom: 0 },
  tab: {
    padding: '10px 20px', background: 'transparent', border: 'none',
    color: '#64748b', fontSize: 14, cursor: 'pointer', borderBottom: '2px solid transparent',
    fontWeight: 500,
  },
  tabActive: { color: '#3b82f6', borderBottom: '2px solid #3b82f6' },
  metricsGrid: { display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 20 },
  metricCard: {
    background: '#1e293b', border: '1px solid #334155', borderRadius: 10,
    padding: '16px 18px',
  },
  metricValue: { fontSize: 26, fontWeight: 700, color: '#f8fafc', marginBottom: 4 },
  metricLabel: { fontSize: 12, color: '#64748b', textTransform: 'uppercase', letterSpacing: 0.5 },
  metricSub: { fontSize: 12, color: '#4ade80', marginTop: 4 },
  card: {
    background: '#1e293b', border: '1px solid #334155', borderRadius: 10,
    padding: '20px 24px', marginBottom: 16,
  },
  cardTitle: { fontSize: 16, fontWeight: 600, color: '#e2e8f0', marginBottom: 16, marginTop: 0 },
  subError: { background: 'rgba(248,113,113,0.1)', border: '1px solid #f87171', borderRadius: 6, padding: '8px 12px', fontSize: 13, color: '#f87171', marginBottom: 12 },
  howList: { color: '#94a3b8', fontSize: 14, lineHeight: 2, paddingLeft: 20, margin: 0 },
  table: { width: '100%', borderCollapse: 'collapse' },
  th: { textAlign: 'left', fontSize: 12, color: '#64748b', textTransform: 'uppercase', letterSpacing: 0.5, padding: '8px 12px', borderBottom: '1px solid #334155' },
  tr: { borderBottom: '1px solid #1e293b' },
  td: { padding: '10px 12px', fontSize: 14, color: '#cbd5e1' },
  badge: { fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 20, textTransform: 'capitalize' },
};

export default Affiliate;
