/**
 * CryptoCheckout — crypto payment flow for plan upgrades.
 *
 * Wires to:
 *   GET  /api/billing/plans                    — live plan catalogue
 *   GET  /api/payments/crypto/rates            — live USD exchange rates
 *   POST /api/payments/crypto/address          — generate deposit address
 *   GET  /api/payments/crypto/status/{id}      — real confirmation polling
 *   GET  /api/billing/payments/flutterwave/status
 *   POST /api/billing/payments/flutterwave/init
 *
 * Fixes vs previous version:
 *   - Rates response shape: backend returns { rates: { BTC: { usd_per_coin } } }
 *     — now correctly parsed instead of treating flat keys as rates.
 *   - Confirmation polling: replaced setInterval counter with real
 *     GET /api/payments/crypto/status/{id} polling every 5 s.
 *   - Plan pre-selection: reads ?plan= and ?billing= from URL search params.
 *   - Plan list: fetched from /api/billing/plans at runtime; hardcoded
 *     constants are fallback-only while the request is in-flight.
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Link, useSearchParams, useNavigate } from 'react-router-dom';
import { api } from '../hooks/useApi';
import { useStore, selectUser } from '../store';
import { PageHeader } from '../components/PageHeader';
import { CrossLinkBar } from '../components/CrossLinkBar';
import { PLAN_COLORS } from '../lib/subscription';
import { extractApiError } from '../lib/utils';

// ── Types ─────────────────────────────────────────────────────────────────────

type CryptoOption = 'BTC' | 'ETH' | 'USDT';
type USDTNetwork  = 'TRC20' | 'ERC20' | 'BEP20';
type CheckoutStep = 'select' | 'address' | 'confirming' | 'complete';

interface Plan {
  id: string;
  name: string;
  price_usd: number;
  price_usd_monthly?: number;
  features: string[];
}

interface DepositAddress {
  payment_id: string;
  address: string;
  qr_code: string;
  network: string;
  min_deposit: number;
  confirmations_required: number;
  amount_crypto: number;
  expires_at: string;
  rate_usd?: number;
}

interface PaymentStatus {
  payment_id: string;
  status: 'pending' | 'confirming' | 'complete' | 'expired' | 'failed';
  confirmations: number;
  confirmations_required: number;
  currency: string;
  amount_crypto: number;
  tx_hash?: string | null;
}
// ── Constants ─────────────────────────────────────────────────────────────────

/** Fallback plan list used only while /api/billing/plans is loading. */
const FALLBACK_PLANS: Plan[] = [
  { id: 'starter',      name: 'Starter',      price_usd: 1800,  features: ['3 strategies', '1 broker', 'Live trading'] },
  { id: 'professional', name: 'Professional', price_usd: 4500,  features: ['7 strategies', '3 brokers', 'AI signals', 'Backtesting'] },
  { id: 'enterprise',   name: 'Enterprise',   price_usd: 7500,  features: ['Unlimited strategies', 'All brokers', 'White-label'] },
  { id: 'elite',        name: 'Elite',        price_usd: 10000, features: ['Everything in Enterprise', 'Dedicated support'] },
];

const CRYPTO_META: Record<CryptoOption, { name: string; color: string; icon: string; networks?: USDTNetwork[] }> = {
  BTC:  { name: 'Bitcoin',  color: '#f7931a', icon: '₿' },
  ETH:  { name: 'Ethereum', color: '#627eea', icon: 'Ξ' },
  USDT: { name: 'Tether',   color: '#26a17b', icon: '₮', networks: ['TRC20', 'ERC20', 'BEP20'] },
};

const POLL_INTERVAL_MS = 5000;

// ── Helpers ───────────────────────────────────────────────────────────────────

const fmt = (n: number, d = 2) =>
  n.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });

const fmtCrypto = (amount: number, currency: CryptoOption) => {
  const decimals = currency === 'BTC' ? 8 : currency === 'ETH' ? 6 : 2;
  return amount.toFixed(decimals) + ' ' + currency;
};

function buildQRUrl(text: string): string {
  return (
    'https://api.qrserver.com/v1/create-qr-code/?size=180x180&data=' +
    encodeURIComponent(text) +
    '&bgcolor=1e293b&color=f1f5f9&margin=10'
  );
}



async function copyToClipboard(text: string): Promise<void> {
  if (navigator.clipboard) {
    await navigator.clipboard.writeText(text);
  } else {
    const ta = document.createElement('textarea');
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
  }
}

/**
 * Parse the rates response from /api/payments/crypto/rates.
 * Backend returns: { rates: { BTC: { usd_per_coin: N }, ETH: { usd_per_coin: N }, ... } }
 * or flat: { BTC: N, ETH: N, ... }
 */
function parseRates(data: unknown): Record<CryptoOption, number> {
  const d = data as Record<string, unknown>;
  // Nested shape: { rates: { BTC: { usd_per_coin: N } } }
  if (d.rates && typeof d.rates === 'object') {
    const r = d.rates as Record<string, { usd_per_coin?: number } | number>;
    const get = (k: string): number => {
      const v = r[k];
      if (typeof v === 'number') return v;
      if (v && typeof v === 'object' && 'usd_per_coin' in v) return (v as { usd_per_coin: number }).usd_per_coin;
      return 0;
    };
    return { BTC: get('BTC'), ETH: get('ETH'), USDT: get('USDT') || 1 };
  }
  // Flat shape: { BTC: N, ETH: N, USDT: N }
  const get = (k: string): number => {
    const v = d[k] ?? d[k.toLowerCase()];
    return typeof v === 'number' ? v : 0;
  };
  return { BTC: get('BTC'), ETH: get('ETH'), USDT: get('USDT') || 1 };
}
// ── Sub-components ────────────────────────────────────────────────────────────

const PlanCard: React.FC<{ plan: Plan; selected: boolean; onSelect: () => void }> = ({
  plan, selected, onSelect,
}) => {
  const accent = PLAN_COLORS[plan.id as keyof typeof PLAN_COLORS] ?? '#475569';
  return (
    <div onClick={onSelect} style={{
      background: selected ? '#1e3a5f' : '#1e293b',
      border: '2px solid ' + (selected ? accent : '#334155'),
      borderRadius: 12, padding: '16px 14px', cursor: 'pointer',
      transition: 'border-color 0.15s, background 0.15s',
    }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: accent,
        textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 4 }}>
        {plan.name}
      </div>
      <div style={{ fontSize: 22, fontWeight: 800, color: '#f1f5f9', marginBottom: 8 }}>
        ${plan.price_usd.toLocaleString()}
        <span style={{ fontSize: 12, color: '#64748b', fontWeight: 400 }}>/mo</span>
      </div>
      <ul style={{ margin: 0, padding: '0 0 0 14px', fontSize: 12, color: '#94a3b8', lineHeight: 1.7 }}>
        {plan.features.slice(0, 3).map(f => <li key={f}>{f}</li>)}
      </ul>
      {selected && (
        <div style={{ marginTop: 8, fontSize: 11, fontWeight: 700, color: accent }}>✓ Selected</div>
      )}
    </div>
  );
};

const CryptoButton: React.FC<{ currency: CryptoOption; selected: boolean; onSelect: () => void }> = ({
  currency, selected, onSelect,
}) => {
  const meta = CRYPTO_META[currency];
  return (
    <button onClick={onSelect} style={{
      display: 'flex', alignItems: 'center', gap: 10, padding: '12px 16px',
      border: '2px solid ' + (selected ? meta.color : '#334155'),
      background: selected ? meta.color + '18' : '#1e293b',
      borderRadius: 10, cursor: 'pointer', flex: 1, minWidth: 100,
    }}>
      <span style={{ fontSize: 22, color: meta.color }}>{meta.icon}</span>
      <div style={{ textAlign: 'left' }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: '#e2e8f0' }}>{meta.name}</div>
        <div style={{ fontSize: 11, color: '#64748b' }}>{currency}</div>
      </div>
    </button>
  );
};

/** Countdown timer that re-renders every second. */
const ExpiryCountdown: React.FC<{ expiresAt: string }> = ({ expiresAt }) => {
  const [remaining, setRemaining] = useState(0);
  useEffect(() => {
    const tick = () => {
      const ms = new Date(expiresAt).getTime() - Date.now();
      setRemaining(Math.max(0, Math.floor(ms / 1000)));
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [expiresAt]);
  const mins = Math.floor(remaining / 60);
  const secs = remaining % 60;
  const urgent = remaining < 300;
  return (
    <span style={{ color: urgent ? '#ef4444' : '#f1f5f9', fontWeight: 700 }}>
      {mins}:{secs.toString().padStart(2, '0')}
    </span>
  );
};
// ── Main component ────────────────────────────────────────────────────────────

const CryptoCheckout: React.FC = () => {
  const currentUser   = useStore(selectUser);
  const navigate      = useNavigate();
  const [searchParams] = useSearchParams();

  // URL params: ?plan=starter&billing=monthly
  const urlPlanId  = searchParams.get('plan') ?? '';
  const urlBilling = searchParams.get('billing') ?? 'monthly';

  const [plans, setPlans]                   = useState<Plan[]>(FALLBACK_PLANS);
  const [plansLoading, setPlansLoading]     = useState(true);
  const [step, setStep]                     = useState<CheckoutStep>('select');
  const [selectedPlan, setSelectedPlan]     = useState<Plan>(
    FALLBACK_PLANS.find(p => p.id === urlPlanId) ?? FALLBACK_PLANS[0]
  );
  const [selectedCrypto, setSelectedCrypto] = useState<CryptoOption>('BTC');
  const [usdtNetwork, setUsdtNetwork]       = useState<USDTNetwork>('TRC20');
  const [depositInfo, setDepositInfo]       = useState<DepositAddress | null>(null);
  const [loadingAddress, setLoadingAddress] = useState(false);
  const [addressError, setAddressError]     = useState<string | null>(null);
  const [copied, setCopied]                 = useState(false);
  const [qrError, setQrError]               = useState(false);
  const [paymentStatus, setPaymentStatus]   = useState<PaymentStatus | null>(null);
  const [liveRates, setLiveRates]           = useState<Record<CryptoOption, number>>({ BTC: 0, ETH: 0, USDT: 1 });
  const [ratesErr, setRatesErr]             = useState<string | null>(null);
  const [showFlutterwave, setShowFlutterwave] = useState(false);
  const [flwLoading, setFlwLoading]         = useState(false);
  const [flwEnabled, setFlwEnabled]         = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Fetch live plans from API
  useEffect(() => {
    api.get<{ plans: Array<{ id: string; name: string; price_usd_monthly: number; highlights?: string[]; features?: string[] }> }>('/billing/plans')
      .then(r => {
        const fetched: Plan[] = (r.data.plans ?? []).map(p => ({
          id: p.id,
          name: p.name,
          price_usd: p.price_usd_monthly ?? 0,
          features: p.highlights ?? p.features ?? [],
        })).filter(p => p.id !== 'free');
        if (fetched.length > 0) {
          setPlans(fetched);
          // Re-apply URL plan selection against live data
          const match = fetched.find(p => p.id === urlPlanId);
          if (match) setSelectedPlan(match);
          else setSelectedPlan(fetched[0]);
        }
      })
      .catch(() => {
        // Keep FALLBACK_PLANS; apply URL selection
        const match = FALLBACK_PLANS.find(p => p.id === urlPlanId);
        if (match) setSelectedPlan(match);
      })
      .finally(() => setPlansLoading(false));
  }, [urlPlanId]);

  // Fetch live rates + Flutterwave status + geo
  useEffect(() => {
    api.get('/payments/crypto/rates')
      .then(r => setLiveRates(parseRates(r.data)))
      .catch(() => setRatesErr('Live rates unavailable — crypto amounts cannot be calculated.'));

    api.get<{ enabled: boolean }>('/billing/payments/flutterwave/status')
      .then(r => setFlwEnabled(r.data.enabled))
      .catch(() => {});

    fetch('https://ipapi.co/json/')
      .then(r => r.json())
      .then((d: { continent_code?: string }) => { if (d.continent_code === 'AF') setShowFlutterwave(true); })
      .catch(() => {});
  }, []);

  // Cleanup polling on unmount
  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  const fetchDepositAddress = useCallback(async () => {
    setLoadingAddress(true);
    setAddressError(null);
    setQrError(false);
    try {
      const network = selectedCrypto === 'USDT' ? usdtNetwork : undefined;
      const res = await api.post<DepositAddress>('/payments/crypto/address', {
        currency: selectedCrypto,
        network,
        plan_id: selectedPlan.id,
        amount_usd: selectedPlan.price_usd,
        user_id: currentUser?.id ?? '',
      });
      setDepositInfo(res.data);
      setStep('address');
    } catch (err) {
      setAddressError(extractApiError(err, 'Failed to generate deposit address. Please try again.'));
    } finally {
      setLoadingAddress(false);
    }
  }, [selectedCrypto, usdtNetwork, selectedPlan, currentUser]);

  /** Start real polling against GET /api/payments/crypto/status/{id} */
  const startPolling = useCallback((paymentId: string) => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const res = await api.get<PaymentStatus>('/payments/crypto/status/' + paymentId);
        setPaymentStatus(res.data);
        if (res.data.status === 'complete') {
          clearInterval(pollRef.current!);
          pollRef.current = null;
          setStep('complete');
        } else if (res.data.status === 'expired' || res.data.status === 'failed') {
          clearInterval(pollRef.current!);
          pollRef.current = null;
          setAddressError('Payment ' + res.data.status + '. Please start a new checkout.');
          setStep('select');
        }
      } catch {
        // Non-fatal — keep polling
      }
    }, POLL_INTERVAL_MS);
  }, []);

  const handleConfirmSent = () => {
    if (!depositInfo) return;
    setStep('confirming');
    setPaymentStatus(null);
    startPolling(depositInfo.payment_id);
  };

  const handleFlutterwavePay = async () => {
    setFlwLoading(true);
    try {
      const res = await api.post<{ payment_link: string }>('/billing/payments/flutterwave/init', {
        amount: selectedPlan.price_usd, currency: 'USD', plan: selectedPlan.id,
      });
      window.location.href = res.data.payment_link;
    } catch (err) {
      alert(extractApiError(err, 'Flutterwave payment init failed. Please try crypto payment.'));
    } finally {
      setFlwLoading(false);
    }
  };

  const copyAddress = async () => {
    if (!depositInfo) return;
    await copyToClipboard(depositInfo.address);
    setCopied(true);
    setTimeout(() => setCopied(false), 2500);
  };

  const meta = CRYPTO_META[selectedCrypto];
  const cryptoAmount = liveRates[selectedCrypto] > 0
    ? selectedPlan.price_usd / liveRates[selectedCrypto]
    : null;

  const breadcrumbs = [
    { label: 'Dashboard', href: '/dashboard' },
    { label: 'Upgrade', href: '/upgrade' },
    { label: 'Checkout' },
  ];
  // ── Step: Select ───────────────────────────────────────────────────────────
  if (step === 'select') {
    return (
      <div className="page-content">
        <PageHeader title="Crypto Checkout" subtitle="Pay with Bitcoin, Ethereum, or USDT — no card required."
          breadcrumbs={breadcrumbs}
          actions={<Link to="/upgrade" style={st.headerLink}>← All Plans</Link>}
        />
        {ratesErr && <div style={st.warnBox}>{ratesErr}</div>}
        {addressError && <div style={st.errorBox}>{addressError}</div>}

        <section style={st.section}>
          <h2 style={st.sectionTitle}>1. Choose a plan</h2>
          {plansLoading ? (
            <div style={{ color: '#64748b', fontSize: 14 }}>Loading plans…</div>
          ) : (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12 }}>
              {plans.map(p => (
                <PlanCard key={p.id} plan={p} selected={selectedPlan.id === p.id}
                  onSelect={() => setSelectedPlan(p)} />
              ))}
            </div>
          )}
        </section>

        <section style={st.section}>
          <h2 style={st.sectionTitle}>2. Choose cryptocurrency</h2>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            {(Object.keys(CRYPTO_META) as CryptoOption[]).map(c => (
              <CryptoButton key={c} currency={c} selected={selectedCrypto === c}
                onSelect={() => setSelectedCrypto(c)} />
            ))}
          </div>
          {selectedCrypto === 'USDT' && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 13, color: '#64748b' }}>Network:</span>
              {(['TRC20', 'ERC20', 'BEP20'] as USDTNetwork[]).map(n => (
                <button key={n} onClick={() => setUsdtNetwork(n)} style={{
                  padding: '5px 14px', borderRadius: 6, fontSize: 12, cursor: 'pointer',
                  background: usdtNetwork === n ? '#26a17b22' : 'transparent',
                  border: '1px solid ' + (usdtNetwork === n ? '#26a17b' : '#334155'),
                  color: usdtNetwork === n ? '#26a17b' : '#94a3b8',
                }}>{n}</button>
              ))}
            </div>
          )}
        </section>

        {showFlutterwave && flwEnabled && (
          <div style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 12,
            padding: '20px 24px', marginBottom: 20 }}>
            <div style={{ fontWeight: 600, color: '#f8fafc', marginBottom: 6 }}>Pay with Flutterwave</div>
            <p style={{ fontSize: 13, color: '#94a3b8', margin: '0 0 12px' }}>
              Recommended for West &amp; Central Africa — card, bank transfer, mobile money.
            </p>
            <button onClick={handleFlutterwavePay} disabled={flwLoading} style={{
              ...st.proceedBtn, background: '#f5a623', opacity: flwLoading ? 0.7 : 1,
            }}>
              {flwLoading ? 'Redirecting…' : 'Pay $' + selectedPlan.price_usd.toLocaleString() + ' with Flutterwave →'}
            </button>
          </div>
        )}

        <div style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 12,
          padding: '16px 20px', display: 'flex', alignItems: 'center',
          justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <span style={{ fontWeight: 700, color: '#f1f5f9' }}>{selectedPlan.name}</span>
            <span style={{ color: '#64748b' }}> — ${selectedPlan.price_usd.toLocaleString()}/mo</span>
            {cryptoAmount !== null && (
              <span style={{ color: '#94a3b8', fontSize: 13 }}>
                {' '}≈ {fmtCrypto(cryptoAmount, selectedCrypto)}
              </span>
            )}
          </div>
          <button onClick={fetchDepositAddress} disabled={loadingAddress} style={{
            ...st.proceedBtn, opacity: loadingAddress ? 0.7 : 1,
          }}>
            {loadingAddress ? 'Generating address…' : 'Pay with ' + meta.name + ' →'}
          </button>
        </div>

        <CrossLinkBar title="Related" style={{ marginTop: 24 }} links={[
          { label: '💳 Wallet',       href: '/wallet',   color: '#60a5fa' },
          { label: '💎 Pricing',      href: '/pricing',  color: '#a78bfa' },
          { label: '⚙️ Settings',    href: '/settings', color: '#34d399' },
          { label: '📊 Dashboard',   href: '/dashboard',color: '#fbbf24' },
        ]}/>
      </div>
    );
  }

  // ── Step: Address ───────────────────────────────────────────────────────────
  if (step === 'address' && depositInfo) {
    return (
      <div className="page-content">
        <PageHeader title="Send Payment" breadcrumbs={breadcrumbs}
          actions={<button onClick={() => setStep('select')} style={st.backBtn}>← Back</button>}
        />
        <div style={st.card}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 20 }}>
            <span style={{ color: meta.color, fontSize: 32 }}>{meta.icon}</span>
            <div>
              <div style={{ fontSize: 13, color: '#64748b' }}>Send exactly</div>
              <div style={{ fontSize: 28, fontWeight: 800, color: '#f8fafc' }}>
                {fmtCrypto(depositInfo.amount_crypto, selectedCrypto)}
              </div>
              <div style={{ fontSize: 13, color: '#64748b' }}>
                ≈ ${fmt(selectedPlan.price_usd)} · {depositInfo.network.toUpperCase()} network
              </div>
            </div>
          </div>

          {/* QR code */}
          <div style={{ display: 'flex', justifyContent: 'center', margin: '16px 0' }}>
            {!qrError ? (
              <img src={buildQRUrl(depositInfo.address)} alt="Payment QR code"
                style={{ width: 180, height: 180, borderRadius: 8, display: 'block' }}
                onError={() => setQrError(true)} />
            ) : (
              <div style={{ width: 180, height: 180, background: '#0f172a', border: '1px solid #334155',
                borderRadius: 8, display: 'flex', flexDirection: 'column', alignItems: 'center',
                justifyContent: 'center', gap: 8 }}>
                <span style={{ fontSize: 32 }}>📷</span>
                <div style={{ fontSize: 11, color: '#64748b', textAlign: 'center', padding: '0 12px' }}>
                  QR unavailable — copy address below
                </div>
              </div>
            )}
          </div>

          {/* Address */}
          <div style={{ background: '#0f172a', border: '1px solid #334155', borderRadius: 8,
            padding: '12px 14px', marginBottom: 14 }}>
            <div style={{ fontSize: 11, color: '#475569', marginBottom: 6 }}>Deposit address</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <code style={{ flex: 1, fontSize: 12, color: '#94a3b8', wordBreak: 'break-all',
                lineHeight: 1.5 }}>{depositInfo.address}</code>
              <button onClick={copyAddress} style={{ ...st.copyBtn, flexShrink: 0 }}>
                {copied ? '✅' : 'Copy'}
              </button>
            </div>
          </div>

          <div style={{ background: '#451a03', border: '1px solid #92400e', borderRadius: 8,
            padding: '10px 14px', fontSize: 13, color: '#fbbf24', marginBottom: 14 }}>
            ⚠️ Send only <strong>{selectedCrypto}</strong> on the{' '}
            <strong>{depositInfo.network.toUpperCase()}</strong> network.
            Sending a different asset will result in permanent loss.
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13,
            color: '#64748b', marginBottom: 20 }}>
            <span>Confirmations required: <strong style={{ color: '#f8fafc' }}>{depositInfo.confirmations_required}</strong></span>
            <span>Expires in: <ExpiryCountdown expiresAt={depositInfo.expires_at} /></span>
          </div>

          <button onClick={handleConfirmSent} style={st.proceedBtn}>
            I've sent the payment →
          </button>
        </div>
      </div>
    );
  }

  // ── Step: Confirming ────────────────────────────────────────────────────────
  if (step === 'confirming' && depositInfo) {
    const required = depositInfo.confirmations_required;
    const confirmed = paymentStatus?.confirmations ?? 0;
    const pct = Math.min(100, required > 0 ? (confirmed / required) * 100 : 0);
    return (
      <div className="page-content">
        <PageHeader title="Confirming Payment" breadcrumbs={breadcrumbs} />
        <div style={{ ...st.card, textAlign: 'center', padding: '40px 32px' }}>
          <div style={{ fontSize: 48, marginBottom: 16 }}>⏳</div>
          <div style={{ fontSize: 18, fontWeight: 600, color: '#f8fafc', marginBottom: 8 }}>
            Waiting for blockchain confirmations
          </div>
          <div style={{ color: '#64748b', marginBottom: 24 }}>
            {confirmed} / {required} confirmations
            {paymentStatus?.tx_hash && (
              <div style={{ fontSize: 12, marginTop: 6, wordBreak: 'break-all' }}>
                TX: {paymentStatus.tx_hash}
              </div>
            )}
          </div>
          <div style={{ width: '100%', height: 8, background: '#1e293b', borderRadius: 4,
            overflow: 'hidden', marginBottom: 16 }}>
            <div style={{ height: '100%', borderRadius: 4, background: meta.color,
              width: pct + '%', transition: 'width 0.5s ease' }} />
          </div>
          <div style={{ fontSize: 13, color: '#64748b' }}>
            This typically takes {selectedCrypto === 'BTC' ? '30–60 minutes' : '2–5 minutes'}.
            This page polls automatically every {POLL_INTERVAL_MS / 1000} seconds.
          </div>
        </div>
      </div>
    );
  }

  // ── Step: Complete ──────────────────────────────────────────────────────────
  if (step === 'complete') {
    return (
      <div className="page-content">
        <PageHeader title="Payment Confirmed" breadcrumbs={breadcrumbs} />
        <div style={{ ...st.card, textAlign: 'center', padding: '48px 32px' }}>
          <div style={{ fontSize: 56, marginBottom: 16 }}>✅</div>
          <h2 style={{ fontSize: 24, fontWeight: 700, color: '#f8fafc', marginBottom: 8 }}>
            Payment confirmed!
          </h2>
          <p style={{ color: '#94a3b8', marginBottom: 28 }}>
            Your <strong style={{ color: '#f8fafc' }}>{selectedPlan.name}</strong> subscription is now active.
          </p>
          <div style={{ display: 'flex', gap: 12, justifyContent: 'center', flexWrap: 'wrap' }}>
            <Link to="/dashboard" style={{ ...st.proceedBtn, textDecoration: 'none', display: 'inline-block' }}>
              Go to Dashboard →
            </Link>
            <Link to="/settings" style={{ ...st.proceedBtn, background: '#334155',
              textDecoration: 'none', display: 'inline-block' }}>
              Account Settings
            </Link>
          </div>
        </div>
      </div>
    );
  }

  // Fallback: step='address' or 'confirming' but depositInfo not yet set
  // (can occur during the React batch-render between setDepositInfo + setStep)
  return (
    <div className="page-content">
      <PageHeader
        title={step === 'confirming' ? 'Confirming Payment' : 'Send Payment'}
        breadcrumbs={breadcrumbs}
        actions={
          <button onClick={() => { setStep('select'); setAddressError(null); }} style={st.backBtn}>
            ← Back
          </button>
        }
      />
      <div style={{ ...st.card, textAlign: 'center', padding: '40px 32px' }}>
        {addressError ? (
          <>
            <div style={{ fontSize: 32, marginBottom: 12 }}>⚠️</div>
            <div style={{ fontSize: 15, fontWeight: 600, color: '#f87171', marginBottom: 8 }}>
              Failed to generate deposit address
            </div>
            <div style={{ fontSize: 13, color: '#94a3b8', marginBottom: 20 }}>{addressError}</div>
            <button
              onClick={() => { setAddressError(null); setStep('select'); }}
              style={st.backBtn}
            >
              ← Back to Plan Selection
            </button>
          </>
        ) : (
          <>
            <div style={{
              width: 36, height: 36,
              border: '3px solid #1e293b', borderTopColor: '#3b82f6',
              borderRadius: '50%', animation: 'spin 0.7s linear infinite',
              margin: '0 auto 16px',
            }} />
            <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
            <div style={{ color: '#64748b', fontSize: 14 }}>
              {loadingAddress ? 'Generating deposit address…' : 'Loading payment details…'}
            </div>
          </>
        )}
      </div>
    </div>
  );
};

// ── Styles ────────────────────────────────────────────────────────────────────

const st: Record<string, React.CSSProperties> = {
  page:       { maxWidth: 800, margin: '0 auto', padding: '24px 16px', color: '#f1f5f9' },
  section:    { marginBottom: 28 },
  sectionTitle: { fontSize: 15, fontWeight: 700, color: '#e2e8f0', margin: '0 0 12px' },
  card:       { background: '#1e293b', border: '1px solid #334155', borderRadius: 12, padding: 24, marginBottom: 16 },
  proceedBtn: { padding: '12px 24px', background: '#3b82f6', color: '#fff', border: 'none',
    borderRadius: 8, fontSize: 14, fontWeight: 700, cursor: 'pointer' },
  backBtn:    { background: 'none', border: '1px solid #334155', borderRadius: 6,
    color: '#94a3b8', fontSize: 13, padding: '6px 14px', cursor: 'pointer' },
  copyBtn:    { background: '#334155', border: 'none', borderRadius: 6,
    color: '#e2e8f0', fontSize: 12, padding: '5px 12px', cursor: 'pointer' },
  headerLink: { fontSize: 13, color: '#64748b', textDecoration: 'none',
    padding: '6px 14px', border: '1px solid #334155', borderRadius: 6 },
  warnBox:    { background: '#451a03', border: '1px solid #92400e', borderRadius: 8,
    padding: '10px 14px', color: '#fbbf24', fontSize: 13, marginBottom: 16 },
  errorBox:   { background: '#450a0a', border: '1px solid #7f1d1d', borderRadius: 8,
    padding: '10px 14px', color: '#f87171', fontSize: 13, marginBottom: 16 },
};

export default CryptoCheckout;
