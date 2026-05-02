/**
 * LandingPage.tsx
 * Public marketing page — no auth required.
 * Features: animated hero, live price ticker (WebSocket), smooth-scroll nav,
 * interactive pricing toggle (wired to /api/pricing/plans), animated counters,
 * scroll-reveal sections, SEO meta tags, live signal strip, platform stats bar.
 */

import React, {
  useState,
  useEffect,
  useRef,
  useCallback,
  useMemo,
} from 'react';

import { motion, AnimatePresence, useInView, useMotionValue, useSpring } from 'framer-motion';
import {
  TrendingUp, TrendingDown, Zap, Shield, BarChart2, Bell,
  Globe, CreditCard, Users, ChevronRight, Check, Star,
  ArrowRight, Activity, Brain, Lock, Cpu,
  Menu, X, ExternalLink, Eye, Newspaper,
} from 'lucide-react';

// ── Helpers ───────────────────────────────────────────────────────────────────

// ── Types ─────────────────────────────────────────────────────────────────────

interface TickerItem {
  symbol: string;
  bid: number;
  ask: number;
  change_pct: number;
}

interface Feature {
  icon: React.ReactNode;
  title: string;
  desc: string;
  accent: string;
}

/** Shape returned by GET /api/pricing/plans */
interface ApiPlan {
  id: string;
  name: string;
  tagline: string;
  /** Flat monthly price in USD (e.g. 1800 = $1,800/mo) */
  price_usd_monthly: number;
  /** Total annual price in USD (e.g. 18000 = $18,000/yr = $1,500/mo) */
  price_usd_annual: number;
  annual_savings_pct: number;
  commission_rate: number;
  commission_label: string;
  badge: string | null;
  cta: string;
  cta_href: string;
  highlights: string[];
  features: Record<string, boolean>;
  limits: Record<string, number>;
}

interface Step {
  n: number;
  title: string;
  desc: string;
  icon: React.ReactNode;
}

interface Testimonial {
  stars: number;
  text: string;
  author: string;
  role: string;
  avatar: string;
}

// ── Static data ───────────────────────────────────────────────────────────────

const FEATURES: Feature[] = [
  {
    icon: <Brain size={22} />, accent: '#00d4ff',
    title: 'AI Signal Engine',
    desc: 'LSTM, XGBoost, and Random Forest models trained on OHLCV + macro data (DXY, US yields, CPI) generate directional signals with confidence scores.',
  },
  {
    icon: <BarChart2 size={22} />, accent: '#a855f7',
    title: 'Strategy Marketplace',
    desc: 'Browse, subscribe to, and deploy community strategies. Publish your own and earn recurring commissions.',
  },
  {
    icon: <Shield size={22} />, accent: '#00ff88',
    title: 'Institutional Risk Mgmt',
    desc: 'Per-trade position sizing, daily loss limits, max drawdown circuit breakers, and a kill switch — all configurable without code.',
  },
  {
    icon: <Activity size={22} />, accent: '#ffb800',
    title: 'Backtesting + PDF Reports',
    desc: 'Run historical simulations with look-ahead bias prevention. Export results as a PDF report with one click.',
  },
  {
    icon: <Bell size={22} />, accent: '#ff3b5c',
    title: 'Multi-Channel Alerts',
    desc: 'Trade notifications via Discord, Slack, Telegram, or email. Configure exactly which events trigger alerts.',
  },
  {
    icon: <Globe size={22} />, accent: '#06b6d4',
    title: 'Macro Data Integration',
    desc: 'Live DXY, 10Y/2Y yield spread, and CPI from FRED feed directly into the ML feature matrix.',
  },
  {
    icon: <CreditCard size={22} />, accent: '#f59e0b',
    title: 'Crypto Payments',
    desc: 'Subscribe with Bitcoin, Ethereum, or USDT (TRC20/ERC20/BEP20). No card required.',
  },
  {
    icon: <Users size={22} />, accent: '#ec4899',
    title: 'Affiliate Program',
    desc: 'Earn 10–25% recurring commissions by referring traders. Bronze to Platinum tiers.',
  },
  {
    icon: <Cpu size={22} />, accent: '#8b5cf6',
    title: 'Mobile Ready',
    desc: 'Responsive dashboard works on any device. Monitor positions and manage risk from anywhere.',
  },
];

// PLANS is loaded from /api/pricing/plans — see usePricingPlans() below.

const STEPS: Step[] = [
  { n: 1, icon: <Lock size={18} />, title: 'Connect your broker', desc: 'Link your OANDA practice or live account. Start with paper trading — no real money at risk.' },
  { n: 2, icon: <BarChart2 size={18} />, title: 'Choose a strategy', desc: 'Pick from 9 built-in strategies or browse the marketplace. Backtest before going live.' },
  { n: 3, icon: <Shield size={18} />, title: 'Configure risk', desc: 'Set position size limits, daily loss caps, and drawdown thresholds. The kill switch activates automatically.' },
  { n: 4, icon: <Zap size={18} />, title: 'Go live', desc: 'After 30 days of validated paper trading, activate live execution with one command.' },
];

const TESTIMONIALS: Testimonial[] = [
  { stars: 5, avatar: 'AM', author: 'Alex M.', role: 'Prop trader, London', text: '"The macro feature integration is what sets HOPEFX apart. Having DXY and yield data feeding directly into the gold model is something I\'d normally build myself."' },
  { stars: 5, avatar: 'SK', author: 'Sarah K.', role: 'Retail forex trader', text: '"Set up paper trading in under 10 minutes. The risk management defaults are sensible — I didn\'t have to tune anything to get started safely."' },
  { stars: 4, avatar: 'JT', author: 'James T.', role: 'Quantitative analyst', text: '"The backtest PDF reports are a game changer for presenting results to my fund. Clean, professional, and generated in seconds."' },
];

const NAV_LINKS = [
  ['#features',     'Features'],
  ['#how-it-works', 'How it works'],
  ['#pricing',      'Pricing'],
  ['/marketplace',  'Marketplace'],
  ['/geopolitical', 'Geo Risk'],
  ['/status',       'Status'],
  ['/docs',         'Docs'],
] as const;

const HERO_STATS = [
  { value: 9, suffix: '+', label: 'Built-in strategies' },
  { value: 99.9, suffix: '%', label: 'Uptime SLA' },
  { value: 50, suffix: 'ms', label: 'Signal latency', prefix: '<' },
  { value: 1, suffix: '', label: 'OANDA integration', display: 'OANDA' },
] as const;

// ── Live ticker hook ──────────────────────────────────────────────────────────
// Connects to /ws/public (no auth required) for real-time price ticks.
// The Vite dev server proxies /ws → ws://localhost:8000 so the same URL works
// in both dev (port 5173) and production (same origin).
// Falls back to polling /api/data-layer/tick when WebSocket is unavailable.

const PUBLIC_SYMBOLS = ['XAU_USD', 'EUR_USD', 'GBP_USD', 'USD_JPY', 'BTC_USD', 'XAG_USD'];

/** Build the correct WebSocket URL regardless of protocol or Gitpod tunnel host. */
function buildWsUrl(path: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}${path}`;
}

function useLiveTicker() {
  const [ticks, setTicks] = useState<Record<string, TickerItem>>({});
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const retryDelay = useRef(2000);
  const unmounted = useRef(false);
  const wsConnected = useRef(false);

  const connect = useCallback(() => {
    if (unmounted.current) return;
    const url = buildWsUrl('/ws/public');
    try {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        retryDelay.current = 2000;
        wsConnected.current = true;
        ws.send(JSON.stringify({ type: 'subscribe', channels: ['prices'] }));
      };

      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data as string);
          if (msg.type === 'price_tick' && msg.data) {
            const d = msg.data as TickerItem;
            setTicks(prev => ({ ...prev, [d.symbol]: d }));
          }
        } catch { /* ignore malformed frames */ }
      };

      ws.onclose = () => {
        wsConnected.current = false;
        if (unmounted.current) return;
        retryRef.current = setTimeout(() => {
          retryDelay.current = Math.min(retryDelay.current * 1.5, 30_000);
          connect();
        }, retryDelay.current);
      };

      ws.onerror = () => ws.close();
    } catch { /* WS constructor threw — polling fallback handles data */ }
  }, []);

  // Polling fallback — fetches real ticks from data-layer API every 3 s.
  // Runs in parallel with WS; WS ticks take precedence (they overwrite the
  // same state key) but polling ensures data even when WS is unavailable.
  useEffect(() => {
    let pollInterval: ReturnType<typeof setInterval> | null = null;

    const pollSymbol = async (symbol: string) => {
      try {
        const res = await fetch(`/api/data-layer/tick?symbol=${encodeURIComponent(symbol)}`);
        if (!res.ok) return;
        const data = await res.json() as {
          symbol: string; bid: number; ask: number; mid?: number; change_pct?: number;
        };
        // Only update from poll if WS is not connected (avoid flicker)
        if (!wsConnected.current) {
          setTicks(prev => ({
            ...prev,
            [data.symbol]: {
              symbol: data.symbol,
              bid: data.bid,
              ask: data.ask,
              change_pct: data.change_pct ?? 0,
            },
          }));
        }
      } catch { /* network unavailable on public page */ }
    };

    connect();
    // Poll all public symbols on first load
    PUBLIC_SYMBOLS.forEach(s => pollSymbol(s));
    pollInterval = setInterval(() => PUBLIC_SYMBOLS.forEach(s => pollSymbol(s)), 3_000);

    return () => {
      unmounted.current = true;
      if (retryRef.current) clearTimeout(retryRef.current);
      if (pollInterval) clearInterval(pollInterval);
      wsRef.current?.close();
    };
  }, [connect]);

  return ticks;
}

// ── Pricing plans hook ────────────────────────────────────────────────────────
// Fetches the canonical plan catalogue from /api/pricing/plans (public, no auth).
// The API returns price_usd_monthly (flat monthly fee) and price_usd_annual
// (total annual cost). Per-month equivalent when billed annually = annual / 10
// (2 months free ≈ 17% off, so 10 months paid).

function usePricingPlans(annual: boolean) {
  const [plans, setPlans] = useState<ApiPlan[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);

    const deadlineId = setTimeout(() => {
      if (!cancelled) { cancelled = true; setError(true); setLoading(false); }
    }, 8_000);

    const load = async () => {
      try {
        const cycle = annual ? 'annual' : 'monthly';
        const res = await fetch(`/api/pricing/plans?billing_cycle=${cycle}`);
        if (!res.ok || cancelled) { clearTimeout(deadlineId); setError(true); setLoading(false); return; }
        const data = await res.json() as { plans: ApiPlan[] };
        if (!cancelled) {
          clearTimeout(deadlineId);
          setPlans(data.plans ?? []);
          setLoading(false);
        }
      } catch {
        clearTimeout(deadlineId);
        if (!cancelled) { setError(true); setLoading(false); }
      }
    };

    load();
    return () => { cancelled = true; clearTimeout(deadlineId); };
  }, [annual]);

  return { plans, loading, error };
}

// ── Animated counter ──────────────────────────────────────────────────────────

function AnimatedCounter({
  target, suffix = '', prefix = '', decimals = 0, display,
}: {
  target: number; suffix?: string; prefix?: string; decimals?: number; display?: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true, margin: '-60px' });
  const mv = useMotionValue(0);
  const spring = useSpring(mv, { stiffness: 60, damping: 20 });
  const [rendered, setRendered] = useState('0');

  useEffect(() => {
    if (inView) mv.set(target);
  }, [inView, mv, target]);

  useEffect(() => {
    return spring.on('change', (v) => {
      if (display) { setRendered(display); return; }
      setRendered(v.toFixed(decimals));
    });
  }, [spring, decimals, display]);

  return (
    <span ref={ref}>
      {prefix}{rendered}{suffix}
    </span>
  );
}

// ── Scroll-reveal wrapper ─────────────────────────────────────────────────────

const fadeUp = {
  hidden: { opacity: 0, y: 32 },
  visible: (i = 0) => ({
    opacity: 1, y: 0,
    transition: { duration: 0.55, delay: i * 0.08, ease: [0.22, 1, 0.36, 1] as [number, number, number, number] },
  }),
};

function Reveal({
  children, delay = 0, className,
}: {
  children: React.ReactNode; delay?: number; className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, margin: '-40px' });
  return (
    <motion.div
      ref={ref}
      className={className}
      variants={fadeUp}
      initial="hidden"
      animate={inView ? 'visible' : 'hidden'}
      custom={delay}
    >
      {children}
    </motion.div>
  );
}

// ── Ticker bar ────────────────────────────────────────────────────────────────

function TickerBar({ ticks }: { ticks: Record<string, TickerItem> }) {
  const items = useMemo(() => {
    const base = PUBLIC_SYMBOLS.map(sym => ticks[sym] ?? null).filter(Boolean) as TickerItem[];
    // Duplicate for seamless loop
    return [...base, ...base];
  }, [ticks]);

  // Show placeholder slots while waiting for first tick data
  if (items.length === 0) {
    return (
      <div className="w-full overflow-hidden border-b border-terminal-border bg-terminal-surface/60 backdrop-blur-sm">
        <div className="flex gap-0 whitespace-nowrap">
          {PUBLIC_SYMBOLS.map(sym => (
            <div
              key={sym}
              className="inline-flex items-center gap-2 px-6 py-2 border-r border-terminal-border/40 shrink-0"
            >
              <span className="text-xs font-mono font-semibold text-slate-500 tracking-wide">
                {sym.replace('_', '/')}
              </span>
              <span className="w-14 h-3 rounded bg-terminal-border/60 animate-pulse" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="w-full overflow-hidden border-b border-terminal-border bg-terminal-surface/60 backdrop-blur-sm">
      <div
        className="ticker-track flex gap-0 whitespace-nowrap"
        style={{ animation: 'tickerScroll 28s linear infinite' }}
      >
        {items.map((item, i) => {
          const up = item.change_pct >= 0;
          return (
            <div
              key={`${item.symbol}-${i}`}
              className="inline-flex items-center gap-2 px-6 py-2 border-r border-terminal-border/40 shrink-0"
            >
              <span className="text-xs font-mono font-semibold text-slate-300 tracking-wide">
                {item.symbol.replace('_', '/')}
              </span>
              <span className={`text-xs font-mono tabular-nums font-bold ${up ? 'text-bull' : 'text-bear'}`}>
                {item.bid.toFixed(item.symbol.includes('JPY') ? 3 : item.symbol.includes('XAU') || item.symbol.includes('BTC') ? 2 : 5)}
              </span>
              <span className={`inline-flex items-center gap-0.5 text-2xs font-mono ${up ? 'text-bull' : 'text-bear'}`}>
                {up ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
                {up ? '+' : ''}{item.change_pct.toFixed(2)}%
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Navbar ────────────────────────────────────────────────────────────────────

function Navbar({ scrolled }: { scrolled: boolean }) {
  const [mobileOpen, setMobileOpen] = useState(false);

  const handleSmoothScroll = (e: React.MouseEvent<HTMLAnchorElement>, href: string) => {
    if (!href.startsWith('#')) return;
    e.preventDefault();
    const el = document.querySelector(href) as HTMLElement | null;
    if (el) {
      const top = el.getBoundingClientRect().top + window.scrollY - 64; // 64px navbar offset
      window.scrollTo({ top, behavior: 'smooth' });
    }
    setMobileOpen(false);
  };

  return (
    <motion.nav
      className={`fixed top-0 left-0 right-0 z-50 transition-all duration-300 ${
        scrolled
          ? 'bg-terminal-bg/95 backdrop-blur-xl border-b border-terminal-border shadow-terminal'
          : 'bg-transparent'
      }`}
      initial={{ y: -80 }}
      animate={{ y: 0 }}
      transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
    >
      <div className="max-w-7xl mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">
        {/* Logo */}
        <a href="/" className="flex items-center gap-2 shrink-0">
          <div className="w-7 h-7 rounded-lg bg-neon-blue/20 border border-neon-blue/40 flex items-center justify-center">
            <Activity size={14} className="text-neon-blue" />
          </div>
          <span className="text-lg font-bold tracking-tight text-slate-100">
            HOPE<span className="text-neon-blue">FX</span>
          </span>
        </a>

        {/* Desktop links */}
        <div className="hidden md:flex items-center gap-6">
          {NAV_LINKS.map(([href, label]) => (
            <a
              key={href}
              href={href}
              onClick={(e) => handleSmoothScroll(e, href)}
              className="text-sm text-slate-400 hover:text-slate-100 transition-colors duration-150 font-medium"
            >
              {label}
            </a>
          ))}
        </div>

        {/* Desktop CTA */}
        <div className="hidden md:flex items-center gap-3">
          <a href="/login" className="text-sm font-semibold text-slate-300 hover:text-white transition-colors px-3 py-1.5">
            Log in
          </a>
          <a
            href="/register"
            className="inline-flex items-center gap-1.5 text-sm font-semibold bg-neon-blue text-terminal-bg px-4 py-2 rounded-lg hover:bg-neon-blue/90 transition-all duration-150 shadow-neon-blue"
          >
            Start free trial <ArrowRight size={14} />
          </a>
        </div>

        {/* Mobile hamburger */}
        <button
          className="md:hidden p-2 text-slate-400 hover:text-white"
          onClick={() => setMobileOpen(v => !v)}
          aria-label="Toggle menu"
        >
          {mobileOpen ? <X size={20} /> : <Menu size={20} />}
        </button>
      </div>

      {/* Mobile menu */}
      <AnimatePresence>
        {mobileOpen && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="md:hidden bg-terminal-surface border-b border-terminal-border overflow-hidden"
          >
            <div className="px-4 py-4 flex flex-col gap-3">
              {NAV_LINKS.map(([href, label]) => (
                <a
                  key={href}
                  href={href}
                  onClick={(e) => handleSmoothScroll(e, href)}
                  className="text-sm text-slate-300 hover:text-white py-1.5 font-medium"
                >
                  {label}
                </a>
              ))}
              <div className="pt-2 border-t border-terminal-border flex flex-col gap-2">
                <a href="/login" className="text-sm font-semibold text-slate-300 py-2 text-center border border-terminal-border rounded-lg">Log in</a>
                <a href="/register" className="text-sm font-semibold bg-neon-blue text-terminal-bg py-2 text-center rounded-lg">Start free trial</a>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.nav>
  );
}

// ── Hero ──────────────────────────────────────────────────────────────────────

function Hero() {
  return (
    <section className="relative min-h-screen flex flex-col items-center justify-center text-center px-4 pt-24 pb-16 overflow-hidden">
      {/* Background grid */}
      <div className="absolute inset-0 bg-grid-terminal opacity-60 pointer-events-none" />
      {/* Radial glow */}
      <div className="absolute inset-0 pointer-events-none">
        <div className="absolute top-1/3 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] rounded-full bg-neon-blue/5 blur-3xl" />
        <div className="absolute top-1/2 left-1/4 w-[300px] h-[300px] rounded-full bg-neon-purple/5 blur-3xl" />
      </div>

      <div className="relative z-10 max-w-4xl mx-auto">
        {/* Badge */}
        <motion.div
          initial={{ opacity: 0, scale: 0.85 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.5, delay: 0.1 }}
          className="inline-flex items-center gap-2 bg-neon-blue/10 border border-neon-blue/30 text-neon-blue text-xs font-semibold px-4 py-1.5 rounded-full mb-8 tracking-wide"
        >
          <span className="w-1.5 h-1.5 rounded-full bg-neon-blue animate-pulse-fast" />
          AI-Powered Trading Platform
        </motion.div>

        {/* Headline */}
        <motion.h1
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.65, delay: 0.2, ease: [0.22, 1, 0.36, 1] }}
          className="text-5xl sm:text-6xl lg:text-7xl font-extrabold tracking-tight text-slate-100 leading-[1.08] mb-6"
        >
          Trade{' '}
          <span className="text-transparent bg-clip-text bg-gradient-to-r from-neon-amber to-yellow-300">
            gold & forex
          </span>
          <br />
          with institutional-grade AI
        </motion.h1>

        {/* Sub */}
        <motion.p
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.35 }}
          className="text-lg text-slate-400 max-w-2xl mx-auto mb-10 leading-relaxed"
        >
          HOPEFX combines machine learning, macro data feeds, and automated risk management
          to execute strategies that adapt to market conditions in real time.
        </motion.p>

        {/* CTA buttons */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.48 }}
          className="flex flex-wrap items-center justify-center gap-4 mb-16"
        >
          <a
            href="/register"
            className="inline-flex items-center gap-2 bg-neon-blue text-terminal-bg font-bold text-base px-7 py-3.5 rounded-xl hover:bg-neon-blue/90 transition-all duration-150 shadow-neon-blue hover:shadow-lg hover:-translate-y-0.5"
          >
            Start free trial <ArrowRight size={16} />
          </a>
          <a
            href="#how-it-works"
            onClick={(e) => {
              e.preventDefault();
              const el = document.querySelector('#how-it-works') as HTMLElement | null;
              if (el) window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - 64, behavior: 'smooth' });
            }}
            className="inline-flex items-center gap-2 border border-terminal-border text-slate-300 font-semibold text-base px-7 py-3.5 rounded-xl hover:border-slate-500 hover:text-white transition-all duration-150"
          >
            See how it works <ChevronRight size={16} />
          </a>
        </motion.div>

        {/* Stats row */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.6, delay: 0.6 }}
          className="grid grid-cols-2 sm:grid-cols-4 gap-6 max-w-2xl mx-auto"
        >
          {HERO_STATS.map((stat) => (
            <div key={stat.label} className="text-center">
              <div className="text-3xl font-extrabold text-slate-100 font-mono tabular-nums">
                <AnimatedCounter
                  target={stat.value}
                  suffix={stat.suffix}
                  prefix={'prefix' in stat ? stat.prefix : ''}
                  decimals={stat.value % 1 !== 0 ? 1 : 0}
                  display={'display' in stat ? stat.display : undefined}
                />
              </div>
              <div className="text-xs text-slate-500 mt-1">{stat.label}</div>
            </div>
          ))}
        </motion.div>
      </div>

      {/* Scroll indicator */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 1.2 }}
        className="absolute bottom-8 left-1/2 -translate-x-1/2 flex flex-col items-center gap-1 text-slate-600"
      >
        <span className="text-2xs uppercase tracking-widest">Scroll</span>
        <motion.div
          animate={{ y: [0, 6, 0] }}
          transition={{ repeat: Infinity, duration: 1.4, ease: 'easeInOut' }}
        >
          <ChevronRight size={14} className="rotate-90" />
        </motion.div>
      </motion.div>
    </section>
  );
}

// ── Features ──────────────────────────────────────────────────────────────────

function FeaturesSection() {
  const [hovered, setHovered] = useState<string | null>(null);

  return (
    <section id="features" className="py-24 px-4">
      <div className="max-w-6xl mx-auto">
        <Reveal>
          <p className="text-xs font-bold text-neon-blue uppercase tracking-widest mb-3">Features</p>
          <h2 className="text-4xl font-extrabold text-slate-100 tracking-tight mb-4">
            Everything you need to trade smarter
          </h2>
          <p className="text-slate-400 text-base max-w-xl mb-14">
            From signal generation to execution, HOPEFX handles the full trading lifecycle.
          </p>
        </Reveal>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
          {FEATURES.map((f, i) => (
            <Reveal key={f.title} delay={i * 0.5}>
              <motion.div
                className="relative bg-terminal-surface border border-terminal-border rounded-xl p-6 cursor-default overflow-hidden group"
                onHoverStart={() => setHovered(f.title)}
                onHoverEnd={() => setHovered(null)}
                whileHover={{ y: -4, transition: { duration: 0.2 } }}
              >
                {/* Accent glow on hover */}
                <motion.div
                  className="absolute inset-0 rounded-xl opacity-0 group-hover:opacity-100 transition-opacity duration-300 pointer-events-none"
                  style={{ background: `radial-gradient(ellipse at top left, ${f.accent}12 0%, transparent 60%)` }}
                />
                {/* Border glow */}
                <motion.div
                  className="absolute inset-0 rounded-xl border transition-all duration-300 pointer-events-none"
                  style={{ borderColor: hovered === f.title ? `${f.accent}50` : 'transparent' }}
                />

                <div
                  className="w-10 h-10 rounded-lg flex items-center justify-center mb-4"
                  style={{ background: `${f.accent}18`, color: f.accent }}
                >
                  {f.icon}
                </div>
                <h3 className="text-sm font-bold text-slate-100 mb-2">{f.title}</h3>
                <p className="text-sm text-slate-400 leading-relaxed">{f.desc}</p>
              </motion.div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

// ── How It Works ──────────────────────────────────────────────────────────────

function HowItWorksSection() {
  return (
    <section id="how-it-works" className="py-24 px-4 bg-terminal-surface/40">
      <div className="max-w-6xl mx-auto">
        <Reveal>
          <p className="text-xs font-bold text-neon-blue uppercase tracking-widest mb-3">How it works</p>
          <h2 className="text-4xl font-extrabold text-slate-100 tracking-tight mb-4">
            From setup to live trading in minutes
          </h2>
          <p className="text-slate-400 text-base max-w-xl mb-16">
            No coding required. Connect your broker, choose a strategy, and let the AI handle execution.
          </p>
        </Reveal>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-8 relative">
          {/* Connector line (desktop) */}
          <div className="hidden lg:block absolute top-8 left-[12.5%] right-[12.5%] h-px bg-gradient-to-r from-transparent via-terminal-border to-transparent" />

          {STEPS.map((step, i) => (
            <Reveal key={step.n} delay={i * 0.6}>
              <div className="flex flex-col items-center text-center relative">
                <motion.div
                  className="w-16 h-16 rounded-2xl bg-terminal-surface border border-terminal-border flex items-center justify-center mb-5 relative z-10"
                  whileHover={{ scale: 1.08, borderColor: '#00d4ff' }}
                  transition={{ duration: 0.2 }}
                >
                  <div className="text-neon-blue">{step.icon}</div>
                  <span className="absolute -top-2 -right-2 w-5 h-5 rounded-full bg-neon-blue text-terminal-bg text-2xs font-extrabold flex items-center justify-center">
                    {step.n}
                  </span>
                </motion.div>
                <h3 className="text-sm font-bold text-slate-100 mb-2">{step.title}</h3>
                <p className="text-sm text-slate-400 leading-relaxed">{step.desc}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

// ── Pricing ───────────────────────────────────────────────────────────────────

function PricingSection() {
  const [annual, setAnnual] = useState(false);
  const { plans, loading, error } = usePricingPlans(annual);

  /**
   * Display price per month.
   * Monthly billing: price_usd_monthly (e.g. 1800 → "$1,800")
   * Annual billing:  price_usd_annual / 12 — effective per-month rate when billed annually
   *                  (e.g. 18000 / 12 = 1500 → "$1,500/mo, billed $18,000/yr — save 17%")
   * Free tier:       always $0 → "Free"
   */
  const displayPrice = (plan: ApiPlan): string => {
    if (plan.price_usd_monthly === 0) return 'Free';
    const perMonth = annual && plan.price_usd_annual > 0
      ? Math.round(plan.price_usd_annual / 12)
      : plan.price_usd_monthly;
    return `$${perMonth.toLocaleString()}`;
  };

  const savingsPct = plans[1]?.annual_savings_pct ?? 17;

  return (
    <section id="pricing" className="py-24 px-4">
      <div className="max-w-7xl mx-auto">
        <Reveal>
          <p className="text-xs font-bold text-neon-blue uppercase tracking-widest mb-3">Pricing</p>
          <h2 className="text-4xl font-extrabold text-slate-100 tracking-tight mb-4">
            Simple, transparent pricing
          </h2>
          <p className="text-slate-400 text-base max-w-xl mb-8">
            All plans include a 14-day free trial. No card required to start.
          </p>
        </Reveal>

        {/* Toggle */}
        <Reveal delay={0.5}>
          <div className="flex items-center gap-3 mb-12">
            <span className={`text-sm font-medium ${!annual ? 'text-slate-100' : 'text-slate-500'}`}>Monthly</span>
            <button
              onClick={() => setAnnual(v => !v)}
              className={`relative w-11 h-6 rounded-full transition-colors duration-200 ${annual ? 'bg-neon-blue' : 'bg-terminal-border'}`}
              aria-label="Toggle annual billing"
            >
              <motion.span
                className="absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white shadow"
                animate={{ x: annual ? 20 : 0 }}
                transition={{ type: 'spring', stiffness: 400, damping: 30 }}
              />
            </button>
            <span className={`text-sm font-medium ${annual ? 'text-slate-100' : 'text-slate-500'}`}>
              Annual
              <span className="ml-2 text-2xs font-bold text-neon-green bg-neon-green/10 border border-neon-green/30 px-2 py-0.5 rounded-full">
                Save {savingsPct}%
              </span>
            </span>
          </div>
        </Reveal>

        {/* Error state */}
        {error && !loading && plans.length === 0 && (
          <div className="text-center py-12 text-slate-500 text-sm">
            Unable to load pricing. <a href="/pricing" className="text-neon-blue underline">View full pricing page</a>
          </div>
        )}

        {/* Skeleton while loading */}
        {loading && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-6">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="rounded-2xl bg-terminal-surface border border-terminal-border p-7 animate-pulse">
                <div className="h-4 w-24 bg-terminal-border rounded mb-4" />
                <div className="h-10 w-20 bg-terminal-border rounded mb-6" />
                <div className="space-y-2.5 mb-7">
                  {Array.from({ length: 5 }).map((_, j) => (
                    <div key={j} className="h-3 bg-terminal-border/60 rounded w-full" />
                  ))}
                </div>
                <div className="h-10 bg-terminal-border rounded-xl" />
              </div>
            ))}
          </div>
        )}

        {/* Plan cards */}
        {!loading && plans.length > 0 && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-6">
            {plans.map((plan, i) => {
              const featured = plan.badge === 'Most popular';
              return (
                <Reveal key={plan.id} delay={i * 0.15}>
                  <motion.div
                    className={`relative rounded-2xl p-7 flex flex-col h-full ${
                      featured
                        ? 'bg-gradient-to-b from-neon-blue/10 to-terminal-surface border-2 border-neon-blue/50 shadow-neon-blue'
                        : 'bg-terminal-surface border border-terminal-border'
                    }`}
                    whileHover={{ y: -4 }}
                    transition={{ duration: 0.2 }}
                  >
                    {plan.badge && (
                      <div className="absolute -top-3.5 left-1/2 -translate-x-1/2 bg-neon-blue text-terminal-bg text-2xs font-extrabold px-4 py-1 rounded-full whitespace-nowrap tracking-wide">
                        {plan.badge}
                      </div>
                    )}

                    <div className="mb-6">
                      <h3 className="text-base font-bold text-slate-100 mb-1">{plan.name}</h3>
                      <p className="text-xs text-slate-500 mb-3 leading-snug">{plan.tagline}</p>
                      <div className="flex items-end gap-1">
                        <AnimatePresence mode="wait">
                          <motion.span
                            key={annual ? 'annual' : 'monthly'}
                            initial={{ opacity: 0, y: -8 }}
                            animate={{ opacity: 1, y: 0 }}
                            exit={{ opacity: 0, y: 8 }}
                            transition={{ duration: 0.18 }}
                            className="text-4xl font-extrabold text-slate-100 font-mono tabular-nums"
                          >
                            {displayPrice(plan)}
                          </motion.span>
                        </AnimatePresence>
                        {plan.price_usd_monthly > 0 && (
                          <span className="text-sm text-slate-500 mb-1.5">/mo</span>
                        )}
                      </div>
                      {annual && plan.price_usd_annual > 0 && (
                        <p className="text-2xs text-slate-500 mt-1">
                          Billed ${plan.price_usd_annual.toLocaleString()}/yr — save {plan.annual_savings_pct}%
                        </p>
                      )}
                      {plan.commission_label && (
                        <p className="text-2xs text-slate-600 mt-1">{plan.commission_label}</p>
                      )}
                    </div>

                    <ul className="flex-1 space-y-2.5 mb-7">
                      {plan.highlights.map(f => (
                        <li key={f} className="flex items-start gap-2.5 text-sm text-slate-300">
                          <Check size={14} className="text-neon-green mt-0.5 shrink-0" />
                          {f}
                        </li>
                      ))}
                    </ul>

                    <a
                      href={plan.cta_href}
                      className={`w-full text-center text-sm font-bold py-3 rounded-xl transition-all duration-150 ${
                        featured
                          ? 'bg-neon-blue text-terminal-bg hover:bg-neon-blue/90 shadow-neon-blue'
                          : 'border border-terminal-border text-slate-300 hover:border-slate-500 hover:text-white'
                      }`}
                    >
                      {plan.cta}
                    </a>
                  </motion.div>
                </Reveal>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}

// ── Testimonials ──────────────────────────────────────────────────────────────

function TestimonialsSection() {
  return (
    <section className="py-24 px-4 bg-terminal-surface/40">
      <div className="max-w-5xl mx-auto">
        <Reveal>
          <p className="text-xs font-bold text-neon-blue uppercase tracking-widest mb-3">Testimonials</p>
          <h2 className="text-4xl font-extrabold text-slate-100 tracking-tight mb-14">
            Trusted by traders worldwide
          </h2>
        </Reveal>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {TESTIMONIALS.map((t, i) => (
            <Reveal key={t.author} delay={i * 0.6}>
              <motion.div
                className="bg-terminal-surface border border-terminal-border rounded-xl p-6 flex flex-col h-full"
                whileHover={{ y: -3 }}
                transition={{ duration: 0.2 }}
              >
                {/* Stars */}
                <div className="flex gap-0.5 mb-4">
                  {Array.from({ length: 5 }).map((_, si) => (
                    <Star
                      key={si}
                      size={13}
                      className={si < t.stars ? 'text-neon-amber fill-neon-amber' : 'text-slate-600'}
                    />
                  ))}
                </div>

                <p className="text-sm text-slate-300 leading-relaxed italic flex-1 mb-5">{t.text}</p>

                <div className="flex items-center gap-3">
                  <div className="w-9 h-9 rounded-full bg-neon-blue/20 border border-neon-blue/30 flex items-center justify-center text-xs font-bold text-neon-blue shrink-0">
                    {t.avatar}
                  </div>
                  <div>
                    <div className="text-sm font-semibold text-slate-200">{t.author}</div>
                    <div className="text-xs text-slate-500">{t.role}</div>
                  </div>
                </div>
              </motion.div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  );
}

// ── CTA Band ──────────────────────────────────────────────────────────────────

function CTABand() {
  return (
    <section className="py-24 px-4 relative overflow-hidden">
      <div className="absolute inset-0 bg-gradient-to-br from-neon-blue/8 via-transparent to-neon-purple/8 pointer-events-none" />
      <div className="absolute inset-0 bg-grid-terminal opacity-40 pointer-events-none" />
      <Reveal>
        <div className="relative max-w-3xl mx-auto text-center">
          <div className="inline-flex items-center gap-2 bg-neon-amber/10 border border-neon-amber/30 text-neon-amber text-xs font-semibold px-4 py-1.5 rounded-full mb-6 tracking-wide">
            <span className="w-1.5 h-1.5 rounded-full bg-neon-amber animate-pulse-fast" />
            Limited Elite spots available
          </div>
          <h2 className="text-4xl font-extrabold text-slate-100 tracking-tight mb-4">
            Start trading smarter today
          </h2>
          <p className="text-slate-400 text-base mb-8 max-w-xl mx-auto">
            14-day free trial on all plans. No credit card required. Cancel anytime.
            Paper trading is free forever.
          </p>
          <div className="flex flex-wrap items-center justify-center gap-4">
            <a
              href="/register"
              className="inline-flex items-center gap-2 bg-neon-green text-terminal-bg font-bold text-base px-8 py-4 rounded-xl hover:bg-neon-green/90 transition-all duration-150 shadow-neon-green hover:-translate-y-0.5"
            >
              Create free account <ArrowRight size={16} />
            </a>
            <a
              href="/register?plan=elite"
              className="inline-flex items-center gap-2 border border-neon-amber/50 text-neon-amber font-bold text-base px-8 py-4 rounded-xl hover:bg-neon-amber/10 transition-all duration-150 hover:-translate-y-0.5"
            >
              Unlock Elite <Eye size={16} />
            </a>
          </div>
        </div>
      </Reveal>
    </section>
  );
}

// ── Footer ────────────────────────────────────────────────────────────────────

function Footer() {
  const currentYear = new Date().getFullYear();

  const handleAnchorScroll = (e: React.MouseEvent<HTMLAnchorElement>, href: string) => {
    if (!href.startsWith('#')) return;
    e.preventDefault();
    const el = document.querySelector(href) as HTMLElement | null;
    if (el) window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - 64, behavior: 'smooth' });
  };

  return (
    <footer className="bg-terminal-surface border-t border-terminal-border px-4 pt-14 pb-8">
      <div className="max-w-6xl mx-auto">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-10 mb-12">
          {/* Brand */}
          <div className="col-span-2 md:col-span-1">
            <a href="/" className="flex items-center gap-2 mb-3 w-fit">
              <div className="w-7 h-7 rounded-lg bg-neon-blue/20 border border-neon-blue/40 flex items-center justify-center">
                <Activity size={14} className="text-neon-blue" />
              </div>
              <span className="text-lg font-bold text-slate-100">
                HOPE<span className="text-neon-blue">FX</span>
              </span>
            </a>
            <p className="text-xs text-slate-500 leading-relaxed max-w-[220px]">
              AI-powered gold and forex trading platform. Institutional-grade tools for independent traders.
            </p>
            <div className="flex items-center gap-2 mt-4">
              <span className="w-1.5 h-1.5 rounded-full bg-bull animate-pulse-fast" />
              <span className="text-2xs text-slate-500">Systems operational</span>
            </div>
          </div>

          {/* Product */}
          <div>
            <p className="text-xs font-bold text-slate-300 uppercase tracking-widest mb-4">Product</p>
            {([
              ['#features',      'Features'],
              ['#pricing',       'Pricing'],
              ['/marketplace',   'Marketplace'],
              ['/geopolitical',  'Geopolitical Risk'],
              ['/nuclear',       'AI Dashboard'],
              ['/news',          'Market News'],
            ] as [string, string][]).map(([h, l]) => (
              <a
                key={l}
                href={h}
                onClick={(e) => handleAnchorScroll(e, h)}
                className="flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-300 transition-colors mb-2.5"
              >
                {l === 'Market News' && <Newspaper size={11} className="shrink-0" />}
                {l}
              </a>
            ))}
          </div>

          {/* Company */}
          <div>
            <p className="text-xs font-bold text-slate-300 uppercase tracking-widest mb-4">Company</p>
            {([
              ['/pricing',    'Pricing'],
              ['/affiliate',  'Affiliate program'],
              ['/status',     'System status'],
              ['/docs',       'Documentation'],
              ['/terms',      'Terms of service'],
              ['/privacy',    'Legal'],
            ] as [string, string][]).map(([h, l]) => (
              <a key={l} href={h} className="block text-sm text-slate-500 hover:text-slate-300 transition-colors mb-2.5">{l}</a>
            ))}
          </div>

          {/* Support */}
          <div>
            <p className="text-xs font-bold text-slate-300 uppercase tracking-widest mb-4">Support</p>
            {([
              ['mailto:support@hopefx.io', 'Contact support'],
              ['/docs',                    'Documentation'],
              ['/journal',                 'Trade journal'],
              ['/risk-calc',               'Risk calculator'],
              ['/onboarding',              'Getting started'],
            ] as [string, string][]).map(([h, l]) => (
              <a key={l} href={h} className="flex items-center gap-1 text-sm text-slate-500 hover:text-slate-300 transition-colors mb-2.5">
                {l} {h.startsWith('mailto:') && <ExternalLink size={10} />}
              </a>
            ))}
          </div>
        </div>

        {/* Bottom bar */}
        <div className="border-t border-terminal-border pt-6 flex flex-col sm:flex-row items-center justify-between gap-3">
          <span className="text-xs text-slate-600">
            © {currentYear} HOPEFX. All rights reserved.
          </span>
          <div className="flex gap-4">
            {([
              ['/terms',   'Terms'],
              ['/privacy', 'Privacy'],
              ['/docs',    'Docs'],
              ['/status',  'Status'],
            ] as [string, string][]).map(([h, l]) => (
              <a key={l} href={h} className="text-xs text-slate-600 hover:text-slate-400 transition-colors">{l}</a>
            ))}
          </div>
        </div>

        <p className="text-2xs text-slate-700 mt-4 leading-relaxed max-w-4xl">
          RISK DISCLAIMER: Trading foreign exchange and commodities on margin carries a high level of risk
          and may not be suitable for all investors. Past performance is not indicative of future results.
          HOPEFX does not provide financial advice. Paper trading is simulated — no real funds are at risk.
        </p>
      </div>
    </footer>
  );
}

// ── Live signal feed strip ────────────────────────────────────────────────────
// Polls /api/signals/latest (real endpoint, no mocks) and shows a scrolling strip.

interface SignalItem {
  symbol: string;
  direction: 'long' | 'short' | 'neutral';
  confidence: number;
  strategy: string;
  timestamp: string;
}

function useLatestSignals() {
  const [signals, setSignals] = useState<SignalItem[]>([]);

  useEffect(() => {
    let cancelled = false;

    const fetch_ = async () => {
      try {
        const res = await fetch('/api/signals/latest');
        if (!res.ok || cancelled) return;
        const data = await res.json() as { signals?: SignalItem[] } | SignalItem[];
        const list = Array.isArray(data) ? data : (data.signals ?? []);
        if (!cancelled) setSignals(list.slice(0, 8));
      } catch { /* network unavailable on public page */ }
    };

    fetch_();
    const id = setInterval(fetch_, 15_000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  return signals;
}

function SignalStrip() {
  const signals = useLatestSignals();

  // Show a muted placeholder strip while signals are loading or unavailable
  if (signals.length === 0) {
    return (
      <div className="w-full overflow-hidden bg-terminal-raised border-y border-terminal-border py-2">
        <div className="flex gap-0 whitespace-nowrap">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="inline-flex items-center gap-2 px-5 border-r border-terminal-border/30 shrink-0">
              <span className="w-14 h-2.5 rounded bg-terminal-border/50 animate-pulse" />
              <span className="w-8 h-2.5 rounded bg-terminal-border/40 animate-pulse" />
              <span className="w-8 h-2.5 rounded bg-terminal-border/30 animate-pulse" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="w-full overflow-hidden bg-terminal-raised border-y border-terminal-border py-2">
      <div className="ticker-track flex gap-0 whitespace-nowrap" style={{ animation: 'tickerScroll 40s linear infinite' }}>
        {[...signals, ...signals].map((sig, i) => {
          const up = sig.direction === 'long';
          const neutral = sig.direction === 'neutral';
          return (
            <div key={i} className="inline-flex items-center gap-2 px-5 border-r border-terminal-border/30 shrink-0">
              <span className="text-2xs font-mono font-semibold text-slate-400 uppercase tracking-wide">
                {sig.symbol?.replace('_', '/')}
              </span>
              <span className={`text-2xs font-bold uppercase ${neutral ? 'text-slate-400' : up ? 'text-bull' : 'text-bear'}`}>
                {sig.direction}
              </span>
              <span className="text-2xs text-slate-500 font-mono">
                {(sig.confidence * 100).toFixed(0)}%
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Live platform stats bar ───────────────────────────────────────────────────
// Fetches real performance summary from /api/performance/public.
// win_rate is returned as a percentage (e.g. 62.5) by the backend.

interface PlatformStats {
  total_trades?: number;
  /** Win rate as a percentage 0–100 */
  win_rate?: number | null;
  avg_return_pct?: number | null;
  sharpe?: number | null;
  max_drawdown_pct?: number;
  start_date?: string;
  note?: string;
}

function usePlatformStats() {
  const [stats, setStats] = useState<PlatformStats | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const res = await fetch('/api/performance/public');
        if (!res.ok || cancelled) { setError(true); return; }
        const data = await res.json() as PlatformStats;
        if (!cancelled) setStats(data);
      } catch { if (!cancelled) setError(true); }
    };
    load();
    return () => { cancelled = true; };
  }, []);

  return { stats, error };
}

function PlatformStatsBar() {
  const { stats, error } = usePlatformStats();

  // Skeleton while loading
  if (!stats && !error) {
    return (
      <div className="w-full bg-terminal-surface/60 border-b border-terminal-border">
        <div className="max-w-6xl mx-auto px-4 py-3 flex flex-wrap items-center justify-center gap-8">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="flex items-center gap-2">
              <span className="w-16 h-2.5 rounded bg-terminal-border/50 animate-pulse" />
              <span className="w-10 h-2.5 rounded bg-terminal-border/40 animate-pulse" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  // Hide bar entirely if the API is unavailable (don't show stale/empty data)
  if (!stats) return null;

  // win_rate from backend is already a percentage (e.g. 62.5), not 0–1
  const items = [
    { label: 'Total trades',  value: stats.total_trades != null ? stats.total_trades.toLocaleString() : '—' },
    { label: 'Win rate',      value: stats.win_rate != null ? `${stats.win_rate.toFixed(1)}%` : '—' },
    { label: 'Avg return',    value: stats.avg_return_pct != null ? `${stats.avg_return_pct > 0 ? '+' : ''}${stats.avg_return_pct.toFixed(2)}%` : '—' },
    { label: 'Max drawdown',  value: stats.max_drawdown_pct != null ? `${stats.max_drawdown_pct.toFixed(1)}%` : '—' },
    ...(stats.sharpe != null ? [{ label: 'Sharpe', value: stats.sharpe.toFixed(2) }] : []),
  ];

  return (
    <div className="w-full bg-terminal-surface/60 border-b border-terminal-border">
      <div className="max-w-6xl mx-auto px-4 py-3 flex flex-wrap items-center justify-center gap-8">
        {items.map(item => (
          <div key={item.label} className="flex items-center gap-2">
            <span className="text-xs text-slate-500">{item.label}</span>
            <span className="text-xs font-mono font-bold text-slate-200 tabular-nums">{item.value}</span>
          </div>
        ))}
        <div className="flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-bull animate-pulse-fast" />
          <span className="text-2xs text-slate-500">Live data</span>
        </div>
      </div>
    </div>
  );
}

// ── Main LandingPage ──────────────────────────────────────────────────────────

const LandingPage: React.FC = () => {
  const [scrolled, setScrolled] = useState(false);
  const ticks = useLiveTicker();

  // SEO — set document title and meta tags for the landing page
  useEffect(() => {
    const prev = document.title;
    document.title = 'HOPEFX — AI-Powered Gold & Forex Trading Platform';

    const setMeta = (name: string, content: string, prop = false) => {
      const attr = prop ? 'property' : 'name';
      let el = document.querySelector(`meta[${attr}="${name}"]`) as HTMLMetaElement | null;
      if (!el) {
        el = document.createElement('meta');
        el.setAttribute(attr, name);
        document.head.appendChild(el);
      }
      el.setAttribute('content', content);
    };

    setMeta('description', 'HOPEFX combines machine learning, macro data feeds, and automated risk management to execute gold and forex strategies that adapt to market conditions in real time.');
    setMeta('keywords', 'AI trading, forex trading, gold trading, XAU/USD, algorithmic trading, automated trading, machine learning, risk management');
    setMeta('og:title', 'HOPEFX — AI-Powered Gold & Forex Trading Platform', true);
    setMeta('og:description', 'Institutional-grade AI trading tools for independent traders. LSTM, XGBoost, and macro data integration.', true);
    setMeta('og:type', 'website', true);
    setMeta('twitter:card', 'summary_large_image');
    setMeta('twitter:title', 'HOPEFX — AI-Powered Trading');
    setMeta('twitter:description', 'Trade gold & forex with institutional-grade AI. 14-day free trial.');

    return () => { document.title = prev; };
  }, []);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 40);
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  return (
    <div className="landing-root min-h-screen bg-terminal-bg text-slate-200 font-sans antialiased">

      {/* Sticky nav */}
      <Navbar scrolled={scrolled} />

      {/* Live ticker — top of page, below nav */}
      <div className="pt-16">
        <TickerBar ticks={ticks} />
        <PlatformStatsBar />
      </div>

      {/* Hero */}
      <Hero />

      {/* Signal strip between hero and features */}
      <SignalStrip />

      {/* Features */}
      <FeaturesSection />

      {/* How it works */}
      <HowItWorksSection />

      {/* Pricing */}
      <PricingSection />

      {/* Testimonials */}
      <TestimonialsSection />

      {/* CTA */}
      <CTABand />

      {/* Footer */}
      <Footer />
    </div>
  );
};

export default LandingPage;
