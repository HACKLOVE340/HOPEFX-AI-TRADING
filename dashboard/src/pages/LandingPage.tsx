import React from 'react';

// ── Types ─────────────────────────────────────────────────────────────────────

interface Feature {
  icon: string;
  title: string;
  desc: string;
}

interface Plan {
  name: string;
  price: number;
  features: string[];
  featured?: boolean;
  cta: string;
  href: string;
}

// ── Data ──────────────────────────────────────────────────────────────────────

const FEATURES: Feature[] = [
  { icon: '🧠', title: 'AI Signal Engine',           desc: 'LSTM, XGBoost, and Random Forest models trained on OHLCV + macro data (DXY, US yields, CPI) generate directional signals with confidence scores.' },
  { icon: '📊', title: 'Strategy Marketplace',       desc: 'Browse, subscribe to, and deploy community strategies. Publish your own and earn recurring commissions.' },
  { icon: '🛡️', title: 'Institutional Risk Mgmt',   desc: 'Per-trade position sizing, daily loss limits, max drawdown circuit breakers, and a kill switch — all configurable without code.' },
  { icon: '📈', title: 'Backtesting + PDF Reports',  desc: 'Run historical simulations with look-ahead bias prevention. Export results as a PDF report with one click.' },
  { icon: '🔔', title: 'Multi-Channel Alerts',       desc: 'Trade notifications via Discord, Slack, Telegram, or email. Configure exactly which events trigger alerts.' },
  { icon: '🌐', title: 'Macro Data Integration',     desc: 'Live DXY, 10Y/2Y yield spread, and CPI from FRED feed directly into the ML feature matrix.' },
  { icon: '💳', title: 'Crypto Payments',            desc: 'Subscribe with Bitcoin, Ethereum, or USDT (TRC20/ERC20/BEP20). No card required.' },
  { icon: '🤝', title: 'Affiliate Program',          desc: 'Earn 10–25% recurring commissions by referring traders. Bronze to Platinum tiers.' },
  { icon: '📱', title: 'Mobile Ready',               desc: 'Responsive dashboard works on any device. Monitor positions and manage risk from anywhere.' },
];

const PLANS: Plan[] = [
  {
    name: 'Starter', price: 29,
    features: ['1 active strategy', '5 symbols', 'Paper trading', 'Basic backtesting', 'Email alerts'],
    cta: 'Get started', href: '/register?plan=starter',
  },
  {
    name: 'Pro', price: 79, featured: true,
    features: ['10 active strategies', '20 symbols', 'Live trading', 'Full backtesting + PDF reports', 'Discord / Slack / Telegram alerts', 'Marketplace access', 'Crypto payments'],
    cta: 'Start free trial', href: '/register?plan=pro',
  },
  {
    name: 'Elite', price: 199,
    features: ['Unlimited strategies', 'All symbols', 'Priority support', 'API access', 'White-label option', 'Affiliate program', 'Custom integrations'],
    cta: 'Contact sales', href: '/register?plan=elite',
  },
];

const STEPS = [
  { n: 1, title: 'Connect your broker',  desc: 'Link your OANDA practice or live account. Start with paper trading — no real money at risk.' },
  { n: 2, title: 'Choose a strategy',    desc: 'Pick from 9 built-in strategies or browse the marketplace. Backtest before going live.' },
  { n: 3, title: 'Configure risk',       desc: 'Set position size limits, daily loss caps, and drawdown thresholds. The kill switch activates automatically.' },
  { n: 4, title: 'Go live',              desc: 'After 30 days of validated paper trading, activate live execution with one command.' },
];

const TESTIMONIALS = [
  { stars: 5, text: '"The macro feature integration is what sets HOPEFX apart. Having DXY and yield data feeding directly into the gold model is something I\'d normally build myself."', author: 'Alex M.', role: 'Prop trader, London' },
  { stars: 5, text: '"Set up paper trading in under 10 minutes. The risk management defaults are sensible — I didn\'t have to tune anything to get started safely."', author: 'Sarah K.', role: 'Retail forex trader' },
  { stars: 4, text: '"The backtest PDF reports are a game changer for presenting results to my fund. Clean, professional, and generated in seconds."', author: 'James T.', role: 'Quantitative analyst' },
];

// ── Sub-components ────────────────────────────────────────────────────────────

const SectionLabel: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div style={s.sectionLabel}>{children}</div>
);

const SectionHeading: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <h2 style={s.sectionHeading}>{children}</h2>
);

const Btn: React.FC<{ href: string; variant?: 'primary' | 'ghost' | 'green'; size?: 'lg'; children: React.ReactNode }> = ({
  href, variant = 'primary', size, children,
}) => (
  <a
    href={href}
    style={{
      ...s.btn,
      ...(variant === 'primary' ? s.btnPrimary : variant === 'green' ? s.btnGreen : s.btnGhost),
      ...(size === 'lg' ? s.btnLg : {}),
    }}
  >
    {children}
  </a>
);

// ── Main component ────────────────────────────────────────────────────────────

const LandingPage: React.FC = () => (
  <div style={s.page}>

    {/* ── Nav ── */}
    <nav style={s.nav}>
      <div style={s.logo}>HOPE<span style={{ color: '#3b82f6' }}>FX</span></div>
      <div style={s.navLinks}>
        {[['#features', 'Features'], ['#how-it-works', 'How it works'], ['#pricing', 'Pricing'], ['/docs/', 'Docs'], ['/status', 'Status']].map(([href, label]) => (
          <a key={href} href={href} style={s.navLink}>{label}</a>
        ))}
      </div>
      <div style={s.navCta}>
        <Btn href="/login" variant="ghost">Log in</Btn>
        <Btn href="/register">Start free trial</Btn>
      </div>
    </nav>

    {/* ── Hero ── */}
    <div style={s.hero}>
      <div style={s.heroBadge}><span>🤖</span> AI-Powered Trading</div>
      <h1 style={s.heroH1}>
        Trade <span style={{ color: '#f59e0b' }}>gold & forex</span><br />
        with institutional-grade AI
      </h1>
      <p style={s.heroP}>
        HOPEFX combines machine learning, macro data feeds, and automated risk management
        to execute strategies that adapt to market conditions in real time.
      </p>
      <div style={s.heroCta}>
        <Btn href="/register" size="lg">Start free trial</Btn>
        <Btn href="#how-it-works" variant="ghost" size="lg">See how it works</Btn>
      </div>
      <div style={s.heroStats}>
        {[['9+', 'Built-in strategies'], ['99.9%', 'Uptime SLA'], ['<50ms', 'Signal latency'], ['OANDA', 'Broker integration']].map(([v, l]) => (
          <div key={l} style={{ textAlign: 'center' }}>
            <div style={s.heroStatValue}>{v}</div>
            <div style={s.heroStatLabel}>{l}</div>
          </div>
        ))}
      </div>
    </div>

    {/* ── Features ── */}
    <section id="features" style={s.section}>
      <SectionLabel>Features</SectionLabel>
      <SectionHeading>Everything you need to trade smarter</SectionHeading>
      <p style={s.sectionSub}>From signal generation to execution, HOPEFX handles the full trading lifecycle.</p>
      <div style={s.featuresGrid}>
        {FEATURES.map(f => (
          <div key={f.title} style={s.featureCard}>
            <div style={s.featureIcon}>{f.icon}</div>
            <div style={s.featureTitle}>{f.title}</div>
            <div style={s.featureDesc}>{f.desc}</div>
          </div>
        ))}
      </div>
    </section>

    {/* ── How it works ── */}
    <section id="how-it-works" style={s.section}>
      <SectionLabel>How it works</SectionLabel>
      <SectionHeading>From setup to live trading in minutes</SectionHeading>
      <p style={s.sectionSub}>No coding required. Connect your broker, choose a strategy, and let the AI handle execution.</p>
      <div style={s.stepsGrid}>
        {STEPS.map(step => (
          <div key={step.n} style={s.step}>
            <div style={s.stepNum}>{step.n}</div>
            <div style={s.stepTitle}>{step.title}</div>
            <div style={s.stepDesc}>{step.desc}</div>
          </div>
        ))}
      </div>
    </section>

    {/* ── Pricing ── */}
    <section id="pricing" style={s.section}>
      <SectionLabel>Pricing</SectionLabel>
      <SectionHeading>Simple, transparent pricing</SectionHeading>
      <p style={s.sectionSub}>All plans include a 14-day free trial. No card required to start.</p>
      <div style={s.pricingGrid}>
        {PLANS.map(plan => (
          <div key={plan.name} style={{ ...s.pricingCard, ...(plan.featured ? s.pricingFeatured : {}) }}>
            {plan.featured && <div style={s.featuredBadge}>Most popular</div>}
            <div style={s.planName}>{plan.name}</div>
            <div style={s.planPrice}>${plan.price}<span style={s.planPer}>/mo</span></div>
            <ul style={s.planFeatures}>
              {plan.features.map(f => <li key={f} style={s.planFeatureItem}>✓ {f}</li>)}
            </ul>
            <Btn href={plan.href} variant={plan.featured ? 'primary' : 'ghost'}>
              {plan.cta}
            </Btn>
          </div>
        ))}
      </div>
    </section>

    {/* ── Testimonials ── */}
    <section style={s.section}>
      <SectionLabel>Testimonials</SectionLabel>
      <SectionHeading>Trusted by traders worldwide</SectionHeading>
      <div style={s.testimonialsGrid}>
        {TESTIMONIALS.map(t => (
          <div key={t.author} style={s.testimonialCard}>
            <div style={s.stars}>{'★'.repeat(t.stars)}{'☆'.repeat(5 - t.stars)}</div>
            <p style={s.testimonialText}>{t.text}</p>
            <div style={s.testimonialAuthor}>{t.author}</div>
            <div style={s.testimonialRole}>{t.role}</div>
          </div>
        ))}
      </div>
    </section>

    {/* ── CTA band ── */}
    <div style={s.ctaBand}>
      <h2 style={s.ctaH2}>Start trading smarter today</h2>
      <p style={s.ctaP}>14-day free trial. No credit card required. Cancel anytime.</p>
      <Btn href="/register" variant="green" size="lg">Create free account</Btn>
    </div>

    {/* ── Footer ── */}
    <footer style={s.footer}>
      <div style={s.footerGrid}>
        <div>
          <div style={s.logo}>HOPE<span style={{ color: '#3b82f6' }}>FX</span></div>
          <p style={s.footerBrandP}>AI-powered gold and forex trading platform. Institutional-grade tools for independent traders.</p>
        </div>
        <div>
          <div style={s.footerColTitle}>Product</div>
          {[['#features', 'Features'], ['#pricing', 'Pricing'], ['/marketplace', 'Marketplace'], ['/docs/', 'Documentation']].map(([h, l]) => (
            <a key={l} href={h} style={s.footerLink}>{l}</a>
          ))}
        </div>
        <div>
          <div style={s.footerColTitle}>Company</div>
          {[['/affiliate', 'Affiliate program'], ['/status', 'System status'], ['/security', 'Security']].map(([h, l]) => (
            <a key={l} href={h} style={s.footerLink}>{l}</a>
          ))}
        </div>
        <div>
          <div style={s.footerColTitle}>Support</div>
          {[['/docs/FAQ.md', 'FAQ'], ['/docs/API.md', 'API reference'], ['mailto:support@hopefx.io', 'Contact']].map(([h, l]) => (
            <a key={l} href={h} style={s.footerLink}>{l}</a>
          ))}
        </div>
      </div>
      <div style={s.footerBottom}>
        <span>© 2024 HOPEFX. All rights reserved.</span>
        <span>
          <a href="/privacy" style={s.footerLegal}>Privacy</a>
          <a href="/terms" style={s.footerLegal}>Terms</a>
        </span>
      </div>
      <p style={s.disclaimer}>
        RISK DISCLAIMER: Trading foreign exchange and commodities on margin carries a high level of risk and may not be suitable for all investors.
        Past performance is not indicative of future results. HOPEFX does not provide financial advice.
      </p>
    </footer>
  </div>
);

// ── Styles ────────────────────────────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  page: { background: '#0f172a', color: '#f1f5f9', fontFamily: 'system-ui, -apple-system, sans-serif', minHeight: '100vh' },
  nav: { position: 'sticky', top: 0, zIndex: 100, background: 'rgba(15,23,42,0.92)', backdropFilter: 'blur(12px)', borderBottom: '1px solid #334155', padding: '0 32px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', height: 60 },
  logo: { fontSize: 20, fontWeight: 800, color: '#f8fafc', letterSpacing: -0.5 },
  navLinks: { display: 'flex', gap: 28 },
  navLink: { color: '#94a3b8', textDecoration: 'none', fontSize: 14, fontWeight: 500 },
  navCta: { display: 'flex', gap: 10 },
  btn: { padding: '9px 20px', borderRadius: 7, fontSize: 14, fontWeight: 600, cursor: 'pointer', textDecoration: 'none', display: 'inline-block', transition: 'opacity 0.15s' },
  btnPrimary: { background: '#3b82f6', border: 'none', color: '#fff' },
  btnGhost: { background: 'transparent', border: '1px solid #334155', color: '#f1f5f9' },
  btnGreen: { background: '#22c55e', border: 'none', color: '#fff' },
  btnLg: { padding: '14px 32px', fontSize: 16, borderRadius: 9 },
  hero: { textAlign: 'center', padding: '100px 32px 80px', maxWidth: 860, margin: '0 auto' },
  heroBadge: { display: 'inline-flex', alignItems: 'center', gap: 8, background: '#1e3a5f', border: '1px solid #3b82f6', color: '#60a5fa', fontSize: 13, fontWeight: 600, padding: '5px 14px', borderRadius: 20, marginBottom: 24 },
  heroH1: { fontSize: 'clamp(36px, 6vw, 64px)' as any, fontWeight: 800, lineHeight: 1.1, letterSpacing: -1.5, color: '#f8fafc', marginBottom: 20 },
  heroP: { fontSize: 18, color: '#94a3b8', maxWidth: 580, margin: '0 auto 36px', lineHeight: 1.7 },
  heroCta: { display: 'flex', gap: 12, justifyContent: 'center', flexWrap: 'wrap' },
  heroStats: { display: 'flex', justifyContent: 'center', gap: 48, marginTop: 56, flexWrap: 'wrap' },
  heroStatValue: { fontSize: 32, fontWeight: 800, color: '#f8fafc' },
  heroStatLabel: { fontSize: 13, color: '#64748b', marginTop: 2 },
  section: { padding: '80px 32px', maxWidth: 1100, margin: '0 auto' },
  sectionLabel: { fontSize: 12, fontWeight: 700, color: '#3b82f6', textTransform: 'uppercase', letterSpacing: 1.5, marginBottom: 10 },
  sectionHeading: { fontSize: 'clamp(24px, 4vw, 38px)' as any, fontWeight: 800, color: '#f8fafc', letterSpacing: -0.5, marginBottom: 12 },
  sectionSub: { fontSize: 16, color: '#94a3b8', maxWidth: 560, marginBottom: 40 },
  featuresGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 20 },
  featureCard: { background: '#1e293b', border: '1px solid #334155', borderRadius: 12, padding: 24 },
  featureIcon: { fontSize: 28, marginBottom: 12 },
  featureTitle: { fontSize: 16, fontWeight: 700, color: '#f8fafc', marginBottom: 8 },
  featureDesc: { fontSize: 14, color: '#94a3b8', lineHeight: 1.6 },
  stepsGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 24 },
  step: { textAlign: 'center' },
  stepNum: { width: 44, height: 44, borderRadius: '50%', background: '#3b82f6', color: '#fff', fontSize: 18, fontWeight: 800, display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 14px' },
  stepTitle: { fontSize: 15, fontWeight: 700, color: '#f8fafc', marginBottom: 6 },
  stepDesc: { fontSize: 13, color: '#94a3b8' },
  pricingGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 20 },
  pricingCard: { background: '#1e293b', border: '1px solid #334155', borderRadius: 14, padding: '28px 24px', position: 'relative' },
  pricingFeatured: { borderColor: '#3b82f6', background: '#1e3a5f' },
  featuredBadge: { position: 'absolute', top: -12, left: '50%', transform: 'translateX(-50%)', background: '#3b82f6', color: '#fff', fontSize: 11, fontWeight: 700, padding: '3px 14px', borderRadius: 20, whiteSpace: 'nowrap' },
  planName: { fontSize: 16, fontWeight: 700, color: '#f8fafc', marginBottom: 6 },
  planPrice: { fontSize: 36, fontWeight: 800, color: '#f8fafc' },
  planPer: { fontSize: 14, fontWeight: 400, color: '#64748b' },
  planFeatures: { listStyle: 'none', margin: '16px 0 24px', padding: 0 },
  planFeatureItem: { fontSize: 14, color: '#94a3b8', padding: '5px 0' },
  testimonialsGrid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 20 },
  testimonialCard: { background: '#1e293b', border: '1px solid #334155', borderRadius: 12, padding: 22 },
  stars: { color: '#f59e0b', fontSize: 14, marginBottom: 10 },
  testimonialText: { fontSize: 14, color: '#94a3b8', lineHeight: 1.7, marginBottom: 14, fontStyle: 'italic' },
  testimonialAuthor: { fontSize: 13, fontWeight: 600, color: '#e2e8f0' },
  testimonialRole: { fontSize: 12, color: '#64748b' },
  ctaBand: { background: 'linear-gradient(135deg, #1e3a5f 0%, #1e293b 100%)', borderTop: '1px solid #334155', borderBottom: '1px solid #334155', textAlign: 'center', padding: '72px 32px' },
  ctaH2: { fontSize: 36, fontWeight: 800, color: '#f8fafc', marginBottom: 12 },
  ctaP: { fontSize: 16, color: '#94a3b8', marginBottom: 28 },
  footer: { background: '#1e293b', borderTop: '1px solid #334155', padding: '40px 32px 24px' },
  footerGrid: { display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1fr', gap: 32, maxWidth: 1100, margin: '0 auto 32px' },
  footerBrandP: { fontSize: 13, color: '#64748b', marginTop: 10, maxWidth: 260, lineHeight: 1.6 },
  footerColTitle: { fontSize: 13, fontWeight: 700, color: '#e2e8f0', marginBottom: 12 },
  footerLink: { display: 'block', fontSize: 13, color: '#64748b', textDecoration: 'none', marginBottom: 8 },
  footerBottom: { maxWidth: 1100, margin: '0 auto', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderTop: '1px solid #334155', paddingTop: 20, fontSize: 12, color: '#64748b' },
  footerLegal: { color: 'inherit', textDecoration: 'none', marginLeft: 16 },
  disclaimer: { fontSize: 11, color: '#475569', maxWidth: 1100, margin: '16px auto 0', lineHeight: 1.5 },
};

export default LandingPage;
