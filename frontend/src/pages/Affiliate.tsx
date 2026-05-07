/**
 * Affiliate Program — 4-tab dashboard.
 * Wires to /api/monetization/affiliate/* endpoints.
 */
import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Link } from 'react-router-dom';
import { affiliateApi } from '../hooks/useApi';
import { useStore } from '../store';
import { PageHeader } from '../components/PageHeader';
import { CrossLinkBar } from '../components/CrossLinkBar';
import { EmptyState } from '../components/EmptyState';
import { ErrorBanner } from '../components/ErrorBanner';
import { Spinner } from '../components/Spinner';
import { useToast } from '../components/Toast';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

interface AffiliateMetrics {
  total_referrals: number; converted_referrals: number; total_revenue: number;
  total_commissions: number; pending_commissions: number; conversion_rate: number;
  monthly_breakdown?: { month: string; commissions: number; referrals: number }[];
}
interface AffiliateAccount {
  affiliate_id: string; code: string; level: 'bronze'|'silver'|'gold'|'platinum';
  commission_rate: number; status: string; payment_method?: string; payout_email?: string;
}
interface Referral {
  referral_id: string; referred_user_id: string; referred_username?: string;
  status: 'pending'|'converted'|'paid'|'expired'; created_at: string;
  converted_at?: string; commission_amount?: number; plan?: string;
}
interface Commission {
  commission_id: string; referral_id: string; amount: number;
  status: 'pending'|'paid'|'cancelled'; period: string; paid_at?: string;
}
interface LeaderboardEntry {
  rank: number; affiliate_id: string; code: string; level: string;
  total_commissions: number; converted_referrals: number; username?: string;
}
type Tab = 'overview'|'referrals'|'commissions'|'leaderboard';

const LEVEL_COLORS: Record<string,string> = { bronze:'#cd7f32', silver:'#94a3b8', gold:'#f59e0b', platinum:'#a78bfa' };
const LEVEL_RATES: Record<string,string>  = { bronze:'10%', silver:'15%', gold:'20%', platinum:'25%' };
const LEVEL_THRESH: Record<string,string> = { bronze:'Starting tier', silver:'5+ conversions', gold:'15+ conversions', platinum:'30+ conversions' };
const fmt = (n:number,d=2) => n.toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});
const fmtUSD = (n:number) => '$'+fmt(n);
function extractErr(err:unknown,fb:string):string {
  const d=(err as {response?:{data?:{detail?:string}}})?.response?.data?.detail;
  return d??(err instanceof Error?err.message:fb);
}
function StatusBadge({status}:{status:string}) {
  const map:Record<string,{bg:string;color:string}> = {
    pending:{bg:'#1e3a5f',color:'#60a5fa'}, converted:{bg:'#14532d',color:'#4ade80'},
    paid:{bg:'#1a2e1a',color:'#22c55e'}, expired:{bg:'#2d1b1b',color:'#f87171'},
    cancelled:{bg:'#2d1b1b',color:'#f87171'}, active:{bg:'#14532d',color:'#4ade80'},
  };
  const c=map[status]??{bg:'#1e293b',color:'#94a3b8'};
  return <span style={{fontSize:11,fontWeight:700,padding:'2px 8px',borderRadius:4,textTransform:'uppercase',letterSpacing:'0.04em',background:c.bg,color:c.color}}>{status}</span>;
}

const MetricTile:React.FC<{label:string;value:string;sub?:string;color?:string}> = ({label,value,sub,color}) => (
  <div className="bg-[#1e293b] border border-[#334155] rounded-xl p-4 flex-1 min-w-[140px]">
    <div className="text-2xl font-extrabold text-slate-100 mb-1" style={color?{color}:{}}>{value}</div>
    <div className="text-[11px] text-slate-500 uppercase tracking-wider">{label}</div>
    {sub && <div className="text-xs text-slate-400 mt-1">{sub}</div>}
  </div>
);

const ReferralLink:React.FC<{code:string;onCopy:()=>void;copied:boolean}> = ({code,onCopy,copied}) => {
  const url = `${window.location.origin}/?ref=${code}`;
  return (
    <div className="bg-[#1e293b] border border-[#334155] rounded-xl p-4 mb-6">
      <div className="text-[11px] text-slate-500 uppercase tracking-wider mb-2">Your referral link</div>
      <div className="flex items-center gap-3 flex-wrap">
        <code className="flex-1 bg-[#0f172a] border border-[#475569] rounded-lg px-3 py-2 text-[13px] text-blue-300 break-all font-mono">{url}</code>
        <button onClick={onCopy} className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm font-semibold transition-colors shrink-0">
          {copied ? '✅ Copied' : 'Copy link'}
        </button>
      </div>
      <div className="text-xs text-slate-500 mt-2">
        Code: <strong className="text-slate-400">{code}</strong>
      </div>
    </div>
  );
};

const SignupGate:React.FC<{onSignup:()=>void;loading:boolean}> = ({onSignup,loading}) => (
  <div className="max-w-2xl">
    <div className="bg-[#1e293b] border border-[#334155] rounded-xl p-8">
      <h2 className="text-xl font-bold text-slate-100 mb-3">Earn by referring traders</h2>
      <p className="text-slate-400 text-sm leading-relaxed mb-6">
        Share your referral link and earn recurring commissions on every subscription your referrals purchase.
        Commissions range from <strong className="text-slate-200">10% (Bronze)</strong> to <strong className="text-purple-400">25% (Platinum)</strong>.
      </p>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
        {Object.entries(LEVEL_RATES).map(([level,rate]) => (
          <div key={level} className="bg-[#0f172a] rounded-lg p-3 text-center border" style={{borderColor:LEVEL_COLORS[level]+'55'}}>
            <div className="text-sm font-bold capitalize mb-1" style={{color:LEVEL_COLORS[level]}}>{level}</div>
            <div className="text-2xl font-extrabold text-slate-100">{rate}</div>
            <div className="text-[10px] text-slate-500 mt-1">{LEVEL_THRESH[level]}</div>
          </div>
        ))}
      </div>
      <button onClick={onSignup} disabled={loading}
        className="px-6 py-2.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-60 text-white rounded-lg text-sm font-semibold transition-colors flex items-center gap-2">
        {loading && <Spinner size="sm" />}
        {loading ? 'Joining…' : 'Join the affiliate program'}
      </button>
    </div>
  </div>
);

const Affiliate: React.FC = () => {
  const toast = useToast();
  const user = useStore(s => s.user);
  const userId = user?.id ?? '';

  const [account, setAccount]         = useState<AffiliateAccount|null>(null);
  const [metrics, setMetrics]         = useState<AffiliateMetrics|null>(null);
  const [referrals, setReferrals]     = useState<Referral[]>([]);
  const [commissions, setCommissions] = useState<Commission[]>([]);
  const [leaderboard, setLeaderboard] = useState<LeaderboardEntry[]>([]);
  const [loading, setLoading]         = useState(true);
  const [apiError, setApiError]       = useState<string|null>(null);
  const [subErrors, setSubErrors]     = useState<Record<string,string>>({});
  const [copied, setCopied]           = useState(false);
  const [signupLoading, setSignupLoading] = useState(false);
  const [activeTab, setActiveTab]     = useState<Tab>('overview');
  const [withdrawAmt, setWithdrawAmt] = useState('');
  const [withdrawing, setWithdrawing] = useState(false);
  const [withdrawMsg, setWithdrawMsg] = useState('');
  const [payoutEmail, setPayoutEmail] = useState('');
  const [savingPayment, setSavingPayment] = useState(false);

  const mountedRef = useRef(true);
  const copyTimerRef = useRef<ReturnType<typeof setTimeout>|null>(null);
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; if (copyTimerRef.current) clearTimeout(copyTimerRef.current); }; }, []);

  const loadData = useCallback(async () => {
    if (!userId) return;
    setLoading(true); setApiError(null); setSubErrors({});
    try {
      const res = await affiliateApi.account(userId);
      if (!mountedRef.current) return;
      const data = res.data as { has_affiliate_account: boolean; affiliate: AffiliateAccount; metrics: AffiliateMetrics };
      if (data.has_affiliate_account) {
        setAccount(data.affiliate);
        setMetrics(data.metrics);
        setPayoutEmail(data.affiliate.payout_email ?? '');
        const affId = data.affiliate.affiliate_id;
        const [rRes, cRes, lRes] = await Promise.allSettled([
          affiliateApi.referrals(affId),
          affiliateApi.commissions(affId),
          affiliateApi.leaderboard({ limit: 20 }),
        ]);
        if (!mountedRef.current) return;
        if (rRes.status === 'fulfilled') {
          const rd = rRes.value.data as { referrals?: Referral[] } | Referral[];
          setReferrals(Array.isArray(rd) ? rd : (rd.referrals ?? []));
        } else setSubErrors(p => ({ ...p, referrals: extractErr(rRes.reason, 'Failed to load referrals') }));
        if (cRes.status === 'fulfilled') {
          const cd = cRes.value.data as { commissions?: Commission[] } | Commission[];
          setCommissions(Array.isArray(cd) ? cd : (cd.commissions ?? []));
        } else setSubErrors(p => ({ ...p, commissions: extractErr(cRes.reason, 'Failed to load commissions') }));
        if (lRes.status === 'fulfilled') {
          const ld = lRes.value.data as { leaderboard?: LeaderboardEntry[] } | LeaderboardEntry[];
          setLeaderboard(Array.isArray(ld) ? ld : (ld.leaderboard ?? []));
        } else setSubErrors(p => ({ ...p, leaderboard: extractErr(lRes.reason, 'Failed to load leaderboard') }));
      } else {
        affiliateApi.leaderboard({ limit: 20 })
          .then(r => { if (!mountedRef.current) return; const ld = r.data as { leaderboard?: LeaderboardEntry[] } | LeaderboardEntry[]; setLeaderboard(Array.isArray(ld) ? ld : (ld.leaderboard ?? [])); })
          .catch(() => {});
      }
    } catch (err) {
      if (!mountedRef.current) return;
      setApiError(extractErr(err, 'Failed to load affiliate data.'));
    } finally { if (mountedRef.current) setLoading(false); }
  }, [userId]);

  useEffect(() => { loadData(); }, [loadData]);

  const handleSignup = async () => {
    if (!userId) return;
    setSignupLoading(true);
    try { await affiliateApi.signup({ user_id: userId }); await loadData(); toast.success('Welcome to the affiliate program!'); }
    catch (err) { setApiError(extractErr(err, 'Signup failed.')); }
    finally { setSignupLoading(false); }
  };

  const handleWithdraw = async () => {
    if (!account || !withdrawAmt) return;
    const amount = parseFloat(withdrawAmt);
    if (isNaN(amount) || amount <= 0) { setWithdrawMsg('Enter a valid amount.'); return; }
    setWithdrawing(true); setWithdrawMsg('');
    try {
      await affiliateApi.withdraw(account.affiliate_id, amount);
      setWithdrawMsg(`Withdrawal of ${fmtUSD(amount)} requested.`);
      setWithdrawAmt(''); await loadData();
    } catch (err) { setWithdrawMsg(extractErr(err, 'Withdrawal failed.')); }
    finally { setWithdrawing(false); }
  };

  const handleSavePayment = async () => {
    if (!account || !payoutEmail.trim()) return;
    setSavingPayment(true);
    try {
      await affiliateApi.updatePayment(account.affiliate_id, { payout_email: payoutEmail.trim(), method: 'bank_transfer' });
      toast.success('Payment method saved.');
    } catch (err) { toast.error(extractErr(err, 'Failed to save payment method.')); }
    finally { setSavingPayment(false); }
  };

  const copyLink = () => {
    if (!account) return;
    const url = `${window.location.origin}/?ref=${account.code}`;
    navigator.clipboard.writeText(url)
      .then(() => { setCopied(true); toast.success('Referral link copied!'); if (copyTimerRef.current) clearTimeout(copyTimerRef.current); copyTimerRef.current = setTimeout(() => setCopied(false), 2500); })
      .catch(() => toast.error('Failed to copy link.'));
  };

  const CROSS_LINKS = [
    { label: 'Leaderboard', href: '/leaderboard', icon: '🏆', color: '#f59e0b' },
    { label: 'Marketplace', href: '/marketplace', icon: '🛒', color: '#a78bfa' },
    { label: 'Copy Trading', href: '/copy-trading', icon: '🔁', color: '#60a5fa' },
    { label: 'Wallet', href: '/wallet', icon: '💳', color: '#4ade80' },
    { label: 'Performance', href: '/performance', icon: '📊', color: '#06b6d4' },
    { label: 'Pricing', href: '/pricing', icon: '💰', color: '#f97316' },
  ];

  if (!userId) return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <PageHeader title="Affiliate Program" icon="🤝" subtitle="Earn recurring commissions by referring traders"
        breadcrumbs={[{ label: 'Dashboard', href: '/dashboard' }, { label: 'Affiliate' }]} />
      <EmptyState icon="🔒" title="Sign in required" description="Please log in to view your affiliate dashboard." />
    </div>
  );

  if (loading) return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <PageHeader title="Affiliate Program" icon="🤝" subtitle="Earn recurring commissions by referring traders"
        breadcrumbs={[{ label: 'Dashboard', href: '/dashboard' }, { label: 'Affiliate' }]} />
      <div className="flex items-center gap-3 text-slate-500 py-12 justify-center"><Spinner size="sm" /> Loading affiliate data…</div>
    </div>
  );

  if (apiError) return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <PageHeader title="Affiliate Program" icon="🤝" subtitle="Earn recurring commissions by referring traders"
        breadcrumbs={[{ label: 'Dashboard', href: '/dashboard' }, { label: 'Affiliate' }]} />
      <ErrorBanner message={apiError} onDismiss={loadData} />
    </div>
  );

  if (!account) return (
    <div className="max-w-4xl mx-auto px-4 py-8 text-slate-100">
      <PageHeader title="Affiliate Program" icon="🤝" subtitle="Earn recurring commissions by referring traders"
        breadcrumbs={[{ label: 'Dashboard', href: '/dashboard' }, { label: 'Affiliate' }]}
        actions={
          <div className="flex gap-2">
            <Link to="/leaderboard" className="px-3 py-1.5 rounded-lg text-xs font-semibold no-underline" style={{ background: 'rgba(245,158,11,0.1)', border: '1px solid rgba(245,158,11,0.3)', color: '#f59e0b' }}>🏆 Leaderboard</Link>
            <Link to="/pricing" className="px-3 py-1.5 rounded-lg text-xs font-semibold no-underline" style={{ background: 'rgba(59,130,246,0.1)', border: '1px solid rgba(59,130,246,0.3)', color: '#60a5fa' }}>💰 Pricing</Link>
          </div>
        }
      />
      <SignupGate onSignup={handleSignup} loading={signupLoading} />
      {leaderboard.length > 0 && (
        <div className="mt-8 bg-[#1e293b] border border-[#334155] rounded-xl p-6">
          <h3 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-4">Top Affiliates</h3>
          <div className="space-y-2">
            {leaderboard.slice(0, 5).map(e => (
              <div key={e.affiliate_id} className="flex items-center gap-4 py-2 border-b border-[#1e293b] last:border-0">
                <span className="text-slate-500 text-sm w-6 text-right">{e.rank}</span>
                <span className="text-sm font-semibold text-slate-200 flex-1">{e.username ?? e.code}</span>
                <span className="text-xs capitalize px-2 py-0.5 rounded" style={{ background: LEVEL_COLORS[e.level] + '22', color: LEVEL_COLORS[e.level] }}>{e.level}</span>
                <span className="text-sm font-bold text-green-400">{fmtUSD(e.total_commissions)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      <CrossLinkBar links={CROSS_LINKS} title="Related" style={{ marginTop: 24 }} />
    </div>
  );

  const referralLink = `${window.location.origin}/?ref=${account.code}`;
  const monthlyData = metrics?.monthly_breakdown ?? [];

  return (
    <div className="max-w-4xl mx-auto px-4 py-8 text-slate-100">
      <PageHeader
        title="Affiliate Program"
        icon="🤝"
        subtitle="Earn recurring commissions by referring traders"
        breadcrumbs={[{ label: 'Dashboard', href: '/dashboard' }, { label: 'Affiliate' }]}
        badge={
          <span className="text-[11px] font-bold px-2.5 py-0.5 rounded-full uppercase tracking-wider"
            style={{ background: LEVEL_COLORS[account.level] + '22', color: LEVEL_COLORS[account.level], border: `1px solid ${LEVEL_COLORS[account.level]}55` }}>
            {account.level}
          </span>
        }
        actions={
          <div className="flex gap-2 flex-wrap">
            <Link to="/leaderboard" className="px-3 py-1.5 rounded-lg text-xs font-semibold no-underline border border-[#334155] text-slate-400 hover:text-slate-200 transition-colors">🏆 Leaderboard</Link>
            <Link to="/wallet" className="px-3 py-1.5 rounded-lg text-xs font-semibold no-underline border border-[#334155] text-slate-400 hover:text-slate-200 transition-colors">💳 Wallet</Link>
            <button onClick={loadData} className="px-3 py-1.5 rounded-lg text-xs border border-[#334155] text-slate-400 hover:text-slate-200 transition-colors bg-transparent cursor-pointer">↻ Refresh</button>
          </div>
        }
      />

      <ReferralLink code={account.code} onCopy={copyLink} copied={copied} />

      {/* Account info strip */}
      <div className="flex flex-wrap gap-4 mb-6 text-sm text-slate-400">
        <span>Commission rate: <strong className="text-slate-200">{(account.commission_rate * 100).toFixed(0)}%</strong></span>
        <span>Status: <StatusBadge status={account.status} /></span>
        <span>Level: <strong style={{ color: LEVEL_COLORS[account.level] }} className="capitalize">{account.level}</strong></span>
      </div>

      {/* Tabs */}
      <div className="flex gap-0 border-b border-[#1e293b] mb-6">
        {(['overview', 'referrals', 'commissions', 'leaderboard'] as Tab[]).map(tab => (
          <button key={tab} onClick={() => setActiveTab(tab)}
            className="px-5 py-2.5 text-sm font-medium bg-transparent border-none cursor-pointer transition-colors capitalize"
            style={{ color: activeTab === tab ? '#3b82f6' : '#64748b', borderBottom: `2px solid ${activeTab === tab ? '#3b82f6' : 'transparent'}`, fontWeight: activeTab === tab ? 600 : 400 }}>
            {tab}
          </button>
        ))}
      </div>

      {/* ── OVERVIEW TAB ── */}
      {activeTab === 'overview' && metrics && (
        <div className="space-y-6">
          <div className="flex flex-wrap gap-3">
            <MetricTile label="Total Referrals" value={String(metrics.total_referrals)} />
            <MetricTile label="Converted" value={String(metrics.converted_referrals)} sub={`${fmt(metrics.conversion_rate, 1)}% rate`} color="#4ade80" />
            <MetricTile label="Total Earned" value={fmtUSD(metrics.total_commissions)} color="#4ade80" />
            <MetricTile label="Pending Payout" value={fmtUSD(metrics.pending_commissions)} sub="Paid 1st of month" />
          </div>

          {monthlyData.length > 0 && (
            <div className="bg-[#1e293b] border border-[#334155] rounded-xl p-5">
              <h3 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-4">Monthly Commissions</h3>
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={monthlyData} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis dataKey="month" tick={{ fill: '#64748b', fontSize: 11 }} />
                  <YAxis tick={{ fill: '#64748b', fontSize: 11 }} />
                  <Tooltip contentStyle={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8 }} formatter={(v: number) => [fmtUSD(v), 'Commissions']} />
                  <Bar dataKey="commissions" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Withdraw */}
          <div className="bg-[#1e293b] border border-[#334155] rounded-xl p-5">
            <h3 className="text-base font-semibold text-slate-200 mb-1">Request Withdrawal</h3>
            <p className="text-xs text-slate-500 mb-4">Minimum withdrawal: <strong className="text-slate-400">$50.00</strong></p>
            <div className="flex gap-3 items-center flex-wrap">
              <input type="number" min="0" step="0.01" value={withdrawAmt} onChange={e => setWithdrawAmt(e.target.value)}
                placeholder="Amount (USD)"
                className="bg-[#0f172a] border border-[#334155] rounded-lg px-3 py-2 text-sm text-slate-100 outline-none w-44" />
              <button onClick={handleWithdraw} disabled={withdrawing || !withdrawAmt}
                className="px-5 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-60 text-white rounded-lg text-sm font-semibold transition-colors flex items-center gap-2">
                {withdrawing && <Spinner size="sm" />}
                {withdrawing ? 'Processing…' : 'Withdraw'}
              </button>
            </div>
            {withdrawMsg && (
              <div className={`mt-3 text-xs px-3 py-2 rounded-lg ${withdrawMsg.includes('requested') ? 'bg-green-950 border border-green-800 text-green-400' : 'bg-red-950 border border-red-800 text-red-400'}`}>
                {withdrawMsg}
              </div>
            )}
          </div>

          {/* Payment method */}
          <div className="bg-[#1e293b] border border-[#334155] rounded-xl p-5">
            <h3 className="text-base font-semibold text-slate-200 mb-1">Payout Settings</h3>
            <p className="text-xs text-slate-500 mb-4">Email address for commission payouts (bank transfer / PayPal).</p>
            <div className="flex gap-3 items-center flex-wrap">
              <input type="email" value={payoutEmail} onChange={e => setPayoutEmail(e.target.value)}
                placeholder="payout@example.com"
                className="bg-[#0f172a] border border-[#334155] rounded-lg px-3 py-2 text-sm text-slate-100 outline-none w-64" />
              <button onClick={handleSavePayment} disabled={savingPayment || !payoutEmail.trim()}
                className="px-5 py-2 bg-slate-700 hover:bg-slate-600 disabled:opacity-60 text-slate-200 rounded-lg text-sm font-semibold transition-colors flex items-center gap-2">
                {savingPayment && <Spinner size="sm" />}
                {savingPayment ? 'Saving…' : 'Save'}
              </button>
            </div>
          </div>

          {/* How it works */}
          <div className="bg-[#1e293b] border border-[#334155] rounded-xl p-5">
            <h3 className="text-base font-semibold text-slate-200 mb-3">How commissions work</h3>
            <ul className="text-sm text-slate-400 space-y-2 list-disc list-inside">
              <li>Share your referral link — signups are tracked for 30 days via cookie.</li>
              <li>When a referral subscribes to any paid plan, you earn a recurring commission.</li>
              <li>Commissions are paid on the 1st of each month to your registered payout email.</li>
              <li>Reach Silver (5+ conversions), Gold (15+), Platinum (30+) for higher rates.</li>
            </ul>
          </div>
        </div>
      )}

      {/* ── REFERRALS TAB ── */}
      {activeTab === 'referrals' && (
        <div className="bg-[#1e293b] border border-[#334155] rounded-xl p-5">
          <h3 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-4">Referral History</h3>
          {subErrors.referrals && <ErrorBanner message={subErrors.referrals} style={{ marginBottom: 12 }} />}
          {referrals.length === 0 ? (
            <EmptyState icon="👥" title="No referrals yet" description="Share your referral link to start earning commissions." />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[#334155]">
                    <th className="text-left py-2 px-3 text-[11px] text-slate-500 uppercase tracking-wider font-semibold">User</th>
                    <th className="text-left py-2 px-3 text-[11px] text-slate-500 uppercase tracking-wider font-semibold">Status</th>
                    <th className="text-left py-2 px-3 text-[11px] text-slate-500 uppercase tracking-wider font-semibold">Plan</th>
                    <th className="text-left py-2 px-3 text-[11px] text-slate-500 uppercase tracking-wider font-semibold">Commission</th>
                    <th className="text-left py-2 px-3 text-[11px] text-slate-500 uppercase tracking-wider font-semibold">Date</th>
                  </tr>
                </thead>
                <tbody>
                  {referrals.map(r => (
                    <tr key={r.referral_id} className="border-b border-[#0f172a] hover:bg-[#0f172a] transition-colors">
                      <td className="py-2.5 px-3 text-slate-300">{r.referred_username ?? r.referred_user_id.slice(0, 8) + '…'}</td>
                      <td className="py-2.5 px-3"><StatusBadge status={r.status} /></td>
                      <td className="py-2.5 px-3 text-slate-400 capitalize">{r.plan ?? '—'}</td>
                      <td className="py-2.5 px-3 text-green-400 font-semibold">{r.commission_amount != null ? fmtUSD(r.commission_amount) : '—'}</td>
                      <td className="py-2.5 px-3 text-slate-500 text-xs">{new Date(r.created_at).toLocaleDateString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ── COMMISSIONS TAB ── */}
      {activeTab === 'commissions' && (
        <div className="bg-[#1e293b] border border-[#334155] rounded-xl p-5">
          <h3 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-4">Commission Ledger</h3>
          {subErrors.commissions && <ErrorBanner message={subErrors.commissions} style={{ marginBottom: 12 }} />}
          {commissions.length === 0 ? (
            <EmptyState icon="💰" title="No commissions yet" description="Commissions appear here once your referrals subscribe to a paid plan." />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[#334155]">
                    <th className="text-left py-2 px-3 text-[11px] text-slate-500 uppercase tracking-wider font-semibold">Period</th>
                    <th className="text-left py-2 px-3 text-[11px] text-slate-500 uppercase tracking-wider font-semibold">Amount</th>
                    <th className="text-left py-2 px-3 text-[11px] text-slate-500 uppercase tracking-wider font-semibold">Status</th>
                    <th className="text-left py-2 px-3 text-[11px] text-slate-500 uppercase tracking-wider font-semibold">Paid At</th>
                  </tr>
                </thead>
                <tbody>
                  {commissions.map(c => (
                    <tr key={c.commission_id} className="border-b border-[#0f172a] hover:bg-[#0f172a] transition-colors">
                      <td className="py-2.5 px-3 text-slate-300">{c.period}</td>
                      <td className="py-2.5 px-3 text-green-400 font-bold">{fmtUSD(c.amount)}</td>
                      <td className="py-2.5 px-3"><StatusBadge status={c.status} /></td>
                      <td className="py-2.5 px-3 text-slate-500 text-xs">{c.paid_at ? new Date(c.paid_at).toLocaleDateString() : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ── LEADERBOARD TAB ── */}
      {activeTab === 'leaderboard' && (
        <div className="bg-[#1e293b] border border-[#334155] rounded-xl p-5">
          <h3 className="text-sm font-semibold text-slate-400 uppercase tracking-wider mb-4">Top Affiliates</h3>
          {subErrors.leaderboard && <ErrorBanner message={subErrors.leaderboard} style={{ marginBottom: 12 }} />}
          {leaderboard.length === 0 ? (
            <EmptyState icon="🏆" title="Leaderboard loading" description="Top affiliates will appear here once data is available." />
          ) : (
            <div className="space-y-1">
              {leaderboard.map(e => (
                <div key={e.affiliate_id}
                  className={`flex items-center gap-4 px-4 py-3 rounded-lg transition-colors ${e.affiliate_id === account.affiliate_id ? 'bg-blue-950 border border-blue-800' : 'hover:bg-[#0f172a]'}`}>
                  <span className="text-slate-500 text-sm w-6 text-right font-mono">{e.rank}</span>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold text-slate-200 truncate">
                      {e.username ?? e.code}
                      {e.affiliate_id === account.affiliate_id && <span className="ml-2 text-[10px] text-blue-400 font-bold">YOU</span>}
                    </div>
                    <div className="text-xs text-slate-500">{e.converted_referrals} conversions</div>
                  </div>
                  <span className="text-xs capitalize px-2 py-0.5 rounded-full font-semibold"
                    style={{ background: LEVEL_COLORS[e.level] + '22', color: LEVEL_COLORS[e.level] }}>
                    {e.level}
                  </span>
                  <span className="text-sm font-bold text-green-400 tabular-nums">{fmtUSD(e.total_commissions)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <CrossLinkBar links={CROSS_LINKS} title="Related" style={{ marginTop: 32 }} />
    </div>
  );
};

export default Affiliate;
