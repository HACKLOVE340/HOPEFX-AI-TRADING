import React, { useState, useEffect, useCallback } from 'react';

// ── Types ─────────────────────────────────────────────────────────────────────

type CryptoOption = 'BTC' | 'ETH' | 'USDT';
type USDTNetwork = 'TRC20' | 'ERC20' | 'BEP20';
type CheckoutStep = 'select' | 'address' | 'confirming' | 'complete';

interface Plan {
  id: string;
  name: string;
  price_usd: number;
  features: string[];
}

interface DepositAddress {
  address: string;
  qr_code: string;
  network: string;
  min_deposit: number;
  confirmations_required: number;
  amount_crypto: number;
  expires_at: string;
}

// ── Constants ─────────────────────────────────────────────────────────────────

const CRYPTO_META: Record<CryptoOption, { name: string; color: string; icon: string; networks?: USDTNetwork[] }> = {
  BTC:  { name: 'Bitcoin',  color: '#f7931a', icon: '₿' },
  ETH:  { name: 'Ethereum', color: '#627eea', icon: 'Ξ' },
  USDT: { name: 'Tether',   color: '#26a17b', icon: '₮', networks: ['TRC20', 'ERC20', 'BEP20'] },
};

// ── Helpers ───────────────────────────────────────────────────────────────────

const fmt = (n: number, d = 2) =>
  n.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });

const fmtCrypto = (amount: number, currency: CryptoOption) => {
  const decimals = currency === 'BTC' ? 8 : currency === 'ETH' ? 6 : 2;
  return amount.toFixed(decimals) + ' ' + currency;
};

function buildQRDataURL(text: string): string {
  // Returns a placeholder SVG QR — in production use a real QR library
  const encoded = encodeURIComponent(text);
  return `https://api.qrserver.com/v1/create-qr-code/?size=180x180&data=${encoded}&bgcolor=1e293b&color=f1f5f9&margin=10`;
}

// ── Sub-components ────────────────────────────────────────────────────────────

const PlanCard: React.FC<{
  plan: Plan;
  selected: boolean;
  onSelect: () => void;
}> = ({ plan, selected, onSelect }) => (
  <div
    onClick={onSelect}
    style={{
      ...styles.planCard,
      borderColor: selected ? '#3b82f6' : '#334155',
      background: selected ? '#1e3a5f' : '#1e293b',
      cursor: 'pointer',
    }}
  >
    <div style={styles.planName}>{plan.name}</div>
    <div style={styles.planPrice}>${plan.price_usd}<span style={styles.planPer}>/mo</span></div>
    <ul style={styles.planFeatures}>
      {plan.features.map((f) => <li key={f}>{f}</li>)}
    </ul>
    {selected && <div style={styles.selectedMark}>✓ Selected</div>}
  </div>
);

const CryptoButton: React.FC<{
  currency: CryptoOption;
  selected: boolean;
  onSelect: () => void;
}> = ({ currency, selected, onSelect }) => {
  const meta = CRYPTO_META[currency];
  return (
    <button
      onClick={onSelect}
      style={{
        ...styles.cryptoBtn,
        borderColor: selected ? meta.color : '#334155',
        background: selected ? meta.color + '18' : '#1e293b',
      }}
    >
      <span style={{ ...styles.cryptoIcon, color: meta.color }}>{meta.icon}</span>
      <div>
        <div style={styles.cryptoName}>{meta.name}</div>
        <div style={styles.cryptoTicker}>{currency}</div>
      </div>
    </button>
  );
};

// ── Main component ────────────────────────────────────────────────────────────

interface CryptoCheckoutProps {
  /** Pre-select a plan by id */
  initialPlanId?: string;
}

const CryptoCheckout: React.FC<CryptoCheckoutProps> = ({ initialPlanId }) => {
  const [step, setStep] = useState<CheckoutStep>('select');
  const [plans, setPlans] = useState<Plan[]>([]);
  const [plansLoading, setPlansLoading] = useState(true);
  const [selectedPlan, setSelectedPlan] = useState<Plan | null>(null);
  const [liveRates, setLiveRates] = useState<Record<CryptoOption, number> | null>(null);
  const [selectedCrypto, setSelectedCrypto] = useState<CryptoOption>('BTC');
  const [usdtNetwork, setUsdtNetwork] = useState<USDTNetwork>('TRC20');
  const [depositInfo, setDepositInfo] = useState<DepositAddress | null>(null);
  const [loadingAddress, setLoadingAddress] = useState(false);
  const [copied, setCopied] = useState(false);
  const [confirmations, setConfirmations] = useState(0);
  const [pollingTimer, setPollingTimer] = useState<ReturnType<typeof setInterval> | null>(null);

  // Cleanup polling on unmount
  useEffect(() => () => { if (pollingTimer) clearInterval(pollingTimer); }, [pollingTimer]);

  useEffect(() => {
    fetch('/api/billing/plans')
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        if (d?.plans && d.plans.length > 0) {
          setPlans(d.plans);
          setSelectedPlan(d.plans.find((p: Plan) => p.id === initialPlanId) ?? d.plans[1] ?? d.plans[0]);
        }
      })
      .catch(() => {})
      .finally(() => setPlansLoading(false));
  }, [initialPlanId]);

  useEffect(() => {
    fetch('/api/crypto/rates')
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        if (d?.rates) {
          setLiveRates(d.rates);
        } else {
          setLiveRates({ BTC: 0, ETH: 0, USDT: 1.0 });
        }
      })
      .catch(() => setLiveRates({ BTC: 0, ETH: 0, USDT: 1.0 }));
  }, []);

  const fetchDepositAddress = useCallback(async () => {
    if (!selectedPlan) return;
    setLoadingAddress(true);
    try {
      const network = selectedCrypto === 'USDT' ? usdtNetwork : undefined;
      const res = await fetch('/api/payments/crypto/address', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          currency: selectedCrypto,
          network,
          plan_id: selectedPlan.id,
          amount_usd: selectedPlan.price_usd,
          user_id: 'demo_user',
        }),
      });

      if (res.ok) {
        const data = await res.json();
        setDepositInfo(data);
      } else {
        setDepositInfo(null);
      }
    } catch (_) {
      setDepositInfo(null);
    } finally {
      setLoadingAddress(false);
    }
  }, [selectedCrypto, usdtNetwork, selectedPlan]);

  const handleProceed = async () => {
    await fetchDepositAddress();
    setStep('address');
  };

  const handleConfirmSent = () => {
    setStep('confirming');
    setConfirmations(0);
    // Simulate confirmation polling
    let count = 0;
    const required = depositInfo?.confirmations_required ?? 3;
    const timer = setInterval(() => {
      count += 1;
      setConfirmations(count);
      if (count >= required) {
        clearInterval(timer);
        setStep('complete');
      }
    }, 2000);
    setPollingTimer(timer);
  };

  const copyAddress = () => {
    if (!depositInfo) return;
    navigator.clipboard.writeText(depositInfo.address).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    });
  };

  const meta = CRYPTO_META[selectedCrypto];

  // ── Step: Select plan + crypto ────────────────────────────────────────────
  if (step === 'select') {
    if (plansLoading) {
      return (
        <div style={styles.page}>
          <h1 style={styles.heading}>Crypto Checkout</h1>
          <p style={{ color: '#94a3b8' }}>Loading plans…</p>
        </div>
      );
    }

    return (
      <div style={styles.page}>
        <h1 style={styles.heading}>Crypto Checkout</h1>
        <p style={styles.subheading}>Pay with Bitcoin, Ethereum, or USDT — no card required.</p>

        <section style={styles.section}>
          <h2 style={styles.sectionTitle}>1. Choose a plan</h2>
          <div style={styles.planGrid}>
            {plans.map((p) => (
              <PlanCard
                key={p.id}
                plan={p}
                selected={selectedPlan?.id === p.id}
                onSelect={() => setSelectedPlan(p)}
              />
            ))}
          </div>
        </section>

        <section style={styles.section}>
          <h2 style={styles.sectionTitle}>2. Choose cryptocurrency</h2>
          <div style={styles.cryptoGrid}>
            {(Object.keys(CRYPTO_META) as CryptoOption[]).map((c) => (
              <CryptoButton
                key={c}
                currency={c}
                selected={selectedCrypto === c}
                onSelect={() => setSelectedCrypto(c)}
              />
            ))}
          </div>

          {selectedCrypto === 'USDT' && (
            <div style={styles.networkRow}>
              <span style={styles.networkLabel}>Network:</span>
              {(['TRC20', 'ERC20', 'BEP20'] as USDTNetwork[]).map((n) => (
                <button
                  key={n}
                  onClick={() => setUsdtNetwork(n)}
                  style={{
                    ...styles.networkBtn,
                    background: usdtNetwork === n ? '#26a17b22' : 'transparent',
                    borderColor: usdtNetwork === n ? '#26a17b' : '#334155',
                    color: usdtNetwork === n ? '#26a17b' : '#94a3b8',
                  }}
                >
                  {n}
                </button>
              ))}
            </div>
          )}
        </section>

        {selectedPlan && (
          <div style={styles.summaryBar}>
            <div>
              <span style={styles.summaryPlan}>{selectedPlan.name}</span>
              <span style={styles.summaryPrice}> — ${selectedPlan.price_usd}/mo</span>
              <span style={styles.summaryCrypto}>
                {liveRates
                  ? ` ≈ ${fmtCrypto(selectedPlan.price_usd * liveRates[selectedCrypto], selectedCrypto)}`
                  : ' ≈ …'}
              </span>
            </div>
            <button onClick={handleProceed} style={styles.proceedBtn}>
              {loadingAddress ? 'Generating address…' : `Pay with ${meta.name} →`}
            </button>
          </div>
        )}
      </div>
    );
  }

  // ── Step: Show deposit address ────────────────────────────────────────────
  if (step === 'address' && !depositInfo) {
    return (
      <div style={styles.page}>
        <button onClick={() => setStep('select')} style={styles.backBtn}>← Back</button>
        <h1 style={styles.heading}>Send Payment</h1>
        {loadingAddress ? (
          <p style={{ color: '#94a3b8' }}>Generating address…</p>
        ) : (
          <div style={styles.addressErrorBanner}>
            <span>❌ Could not generate deposit address. Please try again.</span>
            <button onClick={fetchDepositAddress} style={styles.proceedBtn}>Retry</button>
          </div>
        )}
      </div>
    );
  }

  if (step === 'address' && depositInfo) {
    const expiresIn = Math.max(0, Math.round((new Date(depositInfo.expires_at).getTime() - Date.now()) / 60000));
    return (
      <div style={styles.page}>
        <button onClick={() => setStep('select')} style={styles.backBtn}>← Back</button>
        <h1 style={styles.heading}>Send Payment</h1>

        <div style={styles.addressCard}>
          <div style={styles.addressHeader}>
            <span style={{ color: meta.color, fontSize: 28 }}>{meta.icon}</span>
            <div>
              <div style={styles.addressTitle}>Send exactly</div>
              <div style={{ fontSize: 26, fontWeight: 800, color: '#f8fafc' }}>
                {fmtCrypto(depositInfo.amount_crypto, selectedCrypto)}
              </div>
              <div style={{ fontSize: 13, color: '#64748b' }}>
                ≈ ${fmt(selectedPlan?.price_usd ?? 0)} · {depositInfo.network.toUpperCase()} network
              </div>
            </div>
          </div>

          <div style={styles.qrSection}>
            <img
              src={buildQRDataURL(depositInfo.address)}
              alt="Payment QR code"
              style={styles.qrImage}
            />
          </div>

          <div style={styles.addressBox}>
            <div style={styles.addressLabel}>Deposit address</div>
            <div style={styles.addressRow}>
              <code style={styles.addressText}>{depositInfo.address}</code>
              <button onClick={copyAddress} style={styles.copyBtn}>
                {copied ? '✅' : 'Copy'}
              </button>
            </div>
          </div>

          <div style={styles.warningBox}>
            ⚠️ Send only <strong>{selectedCrypto}</strong> on the <strong>{depositInfo.network.toUpperCase()}</strong> network.
            Sending a different asset will result in permanent loss.
          </div>

          <div style={styles.infoRow}>
            <span>Confirmations required: <strong style={{ color: '#f8fafc' }}>{depositInfo.confirmations_required}</strong></span>
            <span>Address expires in: <strong style={{ color: expiresIn < 5 ? '#ef4444' : '#f8fafc' }}>{expiresIn} min</strong></span>
          </div>

          <button onClick={handleConfirmSent} style={styles.confirmBtn}>
            I've sent the payment →
          </button>
        </div>
      </div>
    );
  }

  // ── Step: Waiting for confirmations ──────────────────────────────────────
  if (step === 'confirming' && depositInfo) {
    const required = depositInfo.confirmations_required;
    const pct = Math.min(100, (confirmations / required) * 100);
    return (
      <div style={styles.page}>
        <h1 style={styles.heading}>Confirming Payment</h1>
        <div style={styles.addressCard}>
          <div style={{ textAlign: 'center', padding: '24px 0' }}>
            <div style={{ fontSize: 48, marginBottom: 16 }}>⏳</div>
            <div style={{ fontSize: 18, fontWeight: 600, color: '#f8fafc', marginBottom: 8 }}>
              Waiting for blockchain confirmations
            </div>
            <div style={{ color: '#64748b', marginBottom: 24 }}>
              {confirmations} / {required} confirmations
            </div>
            <div style={styles.progressTrack}>
              <div style={{ ...styles.progressBar, width: `${pct}%`, background: meta.color }} />
            </div>
            <div style={{ fontSize: 13, color: '#64748b', marginTop: 12 }}>
              This typically takes {selectedCrypto === 'BTC' ? '30–60 minutes' : '2–5 minutes'}.
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ── Step: Complete ────────────────────────────────────────────────────────
  if (step === 'complete') {
    return (
      <div style={styles.page}>
        <div style={styles.successCard}>
          <div style={{ fontSize: 56, marginBottom: 16 }}>✅</div>
          <h2 style={{ fontSize: 24, fontWeight: 700, color: '#f8fafc', marginBottom: 8 }}>
            Payment confirmed!
          </h2>
          <p style={{ color: '#94a3b8', marginBottom: 24 }}>
            Your <strong style={{ color: '#f8fafc' }}>{selectedPlan?.name ?? 'selected'}</strong> subscription is now active.
          </p>
          <button onClick={() => setStep('select')} style={styles.proceedBtn}>
            Back to checkout
          </button>
        </div>
      </div>
    );
  }

  return null;
};

// ── Styles ────────────────────────────────────────────────────────────────────

const styles: Record<string, React.CSSProperties> = {
  page: {
    maxWidth: 760,
    margin: '0 auto',
    padding: '32px 16px',
    fontFamily: 'system-ui, -apple-system, sans-serif',
    color: '#f1f5f9',
    background: '#0f172a',
    minHeight: '100vh',
  },
  heading: { fontSize: 28, fontWeight: 700, marginBottom: 6, color: '#f8fafc' },
  subheading: { color: '#64748b', marginBottom: 32, fontSize: 15 },
  section: { marginBottom: 32 },
  sectionTitle: { fontSize: 16, fontWeight: 600, color: '#94a3b8', marginBottom: 14, textTransform: 'uppercase', letterSpacing: 0.5 },
  planGrid: { display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 },
  planCard: {
    border: '2px solid', borderRadius: 10, padding: '18px 16px',
    transition: 'border-color 0.15s, background 0.15s',
  },
  planName: { fontSize: 16, fontWeight: 700, color: '#e2e8f0', marginBottom: 6 },
  planPrice: { fontSize: 28, fontWeight: 800, color: '#f8fafc', marginBottom: 12 },
  planPer: { fontSize: 14, fontWeight: 400, color: '#64748b' },
  planFeatures: { listStyle: 'none', padding: 0, margin: 0, fontSize: 13, color: '#94a3b8', lineHeight: 1.8 },
  selectedMark: { marginTop: 12, fontSize: 13, color: '#3b82f6', fontWeight: 600 },
  cryptoGrid: { display: 'flex', gap: 12, flexWrap: 'wrap' },
  cryptoBtn: {
    display: 'flex', alignItems: 'center', gap: 12,
    padding: '14px 20px', border: '2px solid', borderRadius: 10,
    cursor: 'pointer', transition: 'all 0.15s', minWidth: 140,
  },
  cryptoIcon: { fontSize: 28, fontWeight: 700 },
  cryptoName: { fontSize: 14, fontWeight: 600, color: '#e2e8f0' },
  cryptoTicker: { fontSize: 12, color: '#64748b' },
  networkRow: { display: 'flex', alignItems: 'center', gap: 8, marginTop: 14 },
  networkLabel: { fontSize: 13, color: '#64748b' },
  networkBtn: {
    padding: '6px 14px', border: '1px solid', borderRadius: 6,
    fontSize: 12, fontWeight: 600, cursor: 'pointer', transition: 'all 0.15s',
  },
  summaryBar: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    background: '#1e293b', border: '1px solid #334155', borderRadius: 10,
    padding: '16px 20px', marginTop: 8,
  },
  summaryPlan: { fontSize: 16, fontWeight: 700, color: '#f8fafc' },
  summaryPrice: { fontSize: 15, color: '#94a3b8' },
  summaryCrypto: { fontSize: 14, color: '#60a5fa' },
  proceedBtn: {
    padding: '12px 24px', background: '#3b82f6', color: '#fff',
    border: 'none', borderRadius: 8, fontSize: 15, fontWeight: 600, cursor: 'pointer',
  },
  backBtn: {
    background: 'transparent', border: 'none', color: '#64748b',
    fontSize: 14, cursor: 'pointer', marginBottom: 20, padding: 0,
  },
  addressCard: {
    background: '#1e293b', border: '1px solid #334155', borderRadius: 12,
    padding: '28px 24px',
  },
  addressHeader: { display: 'flex', alignItems: 'center', gap: 16, marginBottom: 24 },
  addressTitle: { fontSize: 13, color: '#64748b', marginBottom: 4 },
  qrSection: { display: 'flex', justifyContent: 'center', marginBottom: 24 },
  qrImage: { width: 180, height: 180, borderRadius: 8, border: '1px solid #334155' },
  addressBox: {
    background: '#0f172a', border: '1px solid #334155', borderRadius: 8,
    padding: '12px 16px', marginBottom: 16,
  },
  addressLabel: { fontSize: 11, color: '#64748b', textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 8 },
  addressRow: { display: 'flex', alignItems: 'center', gap: 10 },
  addressText: {
    flex: 1, fontSize: 13, color: '#93c5fd', wordBreak: 'break-all',
    fontFamily: 'monospace',
  },
  copyBtn: {
    padding: '6px 14px', background: '#3b82f6', color: '#fff',
    border: 'none', borderRadius: 6, fontSize: 12, cursor: 'pointer', whiteSpace: 'nowrap',
  },
  warningBox: {
    background: '#2d1b1b', border: '1px solid #7f1d1d', borderRadius: 8,
    padding: '12px 16px', fontSize: 13, color: '#fca5a5', marginBottom: 16,
  },
  infoRow: {
    display: 'flex', justifyContent: 'space-between',
    fontSize: 13, color: '#64748b', marginBottom: 20,
  },
  confirmBtn: {
    width: '100%', padding: '14px', background: '#22c55e', color: '#fff',
    border: 'none', borderRadius: 8, fontSize: 15, fontWeight: 600, cursor: 'pointer',
  },
  progressTrack: {
    width: '100%', height: 8, background: '#1e293b', borderRadius: 4, overflow: 'hidden',
  },
  progressBar: { height: '100%', borderRadius: 4, transition: 'width 0.5s ease' },
  successCard: {
    background: '#1e293b', border: '1px solid #334155', borderRadius: 12,
    padding: '48px 32px', textAlign: 'center',
  },
  addressErrorBanner: {
    background: '#450a0a', border: '1px solid #dc262633', borderRadius: 10,
    padding: '16px 20px', color: '#f87171', display: 'flex',
    alignItems: 'center', justifyContent: 'space-between', gap: 16,
  },
};

export default CryptoCheckout;
