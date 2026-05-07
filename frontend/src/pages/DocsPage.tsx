/**
 * DocsPage.tsx
 * Public documentation hub — no auth required.
 *
 * Renders the platform documentation index with links to all major sections.
 * Content mirrors docs/index.md and docs/FAQ.md from the repository.
 * External GitHub doc links open in a new tab.
 */

import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { CrossLinkBar } from '../components/CrossLinkBar';
import {
  BookOpen, Zap, BarChart2, Brain, Shield, Globe,
  Code2, Settings, Users, ChevronRight, ExternalLink,
  Search, Activity,
} from 'lucide-react';

// ── Types ─────────────────────────────────────────────────────────────────────

interface DocSection {
  id: string;
  icon: React.ReactNode;
  title: string;
  color: string;
  entries: { label: string; href: string; external?: boolean }[];
}

// ── Doc sections ──────────────────────────────────────────────────────────────
// hrefs point to the GitHub-hosted markdown files so users always get the
// latest version without requiring a separate docs server.

const GITHUB_BASE =
  'https://github.com/HACKLOVE340/HOPEFX-AI-TRADING/blob/main/docs';

const SECTIONS: DocSection[] = [
  {
    id: 'getting-started',
    icon: <Zap size={18} />,
    title: 'Getting Started',
    color: '#00d4ff',
    entries: [
      { label: 'Installation',              href: `${GITHUB_BASE}/INSTALLATION.md`,              external: true },
      { label: 'Quick Start',               href: `${GITHUB_BASE}/QUICKSTART.md`,                external: true },
      { label: 'OANDA Paper Trading Setup', href: `${GITHUB_BASE}/oanda_paper_trading_setup.md`, external: true },
      { label: 'Setup Guide',               href: `${GITHUB_BASE}/SETUP_GUIDE.md`,               external: true },
      { label: 'Architecture Overview',     href: `${GITHUB_BASE}/architecture.md`,              external: true },
    ],
  },
  {
    id: 'trading',
    icon: <BarChart2 size={18} />,
    title: 'Trading & Strategies',
    color: '#a855f7',
    entries: [
      { label: 'Sample Strategies',     href: `${GITHUB_BASE}/SAMPLE_STRATEGIES.md`,      external: true },
      { label: 'Order Flow Guide',      href: `${GITHUB_BASE}/ORDER_FLOW_GUIDE.md`,        external: true },
      { label: 'Backtesting Guide',     href: `${GITHUB_BASE}/BACKTESTING_GUIDE.md`,       external: true },
      { label: 'Asset Diversification', href: `${GITHUB_BASE}/ASSET_DIVERSIFICATION.md`,   external: true },
      { label: 'Prop Firm Guide',       href: `${GITHUB_BASE}/PROP_FIRM_GUIDE.md`,         external: true },
    ],
  },
  {
    id: 'ml',
    icon: <Brain size={18} />,
    title: 'ML & AI',
    color: '#00ff88',
    entries: [
      { label: 'Model Performance', href: `${GITHUB_BASE}/model_performance.md`, external: true },
      { label: 'ML Guide',          href: `${GITHUB_BASE}/ML_GUIDE.md`,          external: true },
      { label: 'Architecture — ML', href: `${GITHUB_BASE}/architecture.md`,      external: true },
    ],
  },
  {
    id: 'risk',
    icon: <Shield size={18} />,
    title: 'Risk & Live Trading',
    color: '#ff3b5c',
    entries: [
      { label: 'Risk Management',  href: `${GITHUB_BASE}/RISK_MANAGEMENT.md`,  external: true },
      { label: 'Live Trading Gate', href: `${GITHUB_BASE}/live_trading_gate.md`, external: true },
      { label: 'Security',         href: `${GITHUB_BASE}/SECURITY.md`,          external: true },
    ],
  },
  {
    id: 'api',
    icon: <Code2 size={18} />,
    title: 'API & Integration',
    color: '#f59e0b',
    entries: [
      { label: 'API Reference',              href: `${GITHUB_BASE}/API_REFERENCE.md`,              external: true },
      { label: 'API Guide',                  href: `${GITHUB_BASE}/API_GUIDE.md`,                  external: true },
      { label: 'Mobile Guide',               href: `${GITHUB_BASE}/MOBILE_GUIDE.md`,               external: true },
      { label: 'World Monitor Integration',  href: `${GITHUB_BASE}/WORLD_MONITOR_INTEGRATION.md`,  external: true },
    ],
  },
  {
    id: 'ops',
    icon: <Settings size={18} />,
    title: 'Operations',
    color: '#06b6d4',
    entries: [
      { label: 'Deployment',     href: `${GITHUB_BASE}/DEPLOYMENT.md`,     external: true },
      { label: 'Grafana Setup',  href: `${GITHUB_BASE}/GRAFANA_SETUP.md`,  external: true },
      { label: 'Debugging',      href: `${GITHUB_BASE}/DEBUGGING.md`,      external: true },
      { label: 'Troubleshooting', href: `${GITHUB_BASE}/TROUBLESHOOTING.md`, external: true },
      { label: 'FAQ',            href: `${GITHUB_BASE}/FAQ.md`,            external: true },
    ],
  },
  {
    id: 'monetization',
    icon: <Globe size={18} />,
    title: 'Monetization & Community',
    color: '#ec4899',
    entries: [
      { label: 'Pricing & Plans',  href: '/pricing' },
      { label: 'Monetization',     href: `${GITHUB_BASE}/MONETIZATION.md`, external: true },
      { label: 'Community',        href: `${GITHUB_BASE}/COMMUNITY.md`,    external: true },
      { label: 'Contributing',     href: `${GITHUB_BASE}/CONTRIBUTING.md`, external: true },
      { label: 'Roadmap',          href: `${GITHUB_BASE}/roadmap.md`,      external: true },
    ],
  },
  {
    id: 'platform',
    icon: <Users size={18} />,
    title: 'Platform Status',
    color: '#8b5cf6',
    entries: [
      { label: 'System Status',  href: '/status' },
      { label: 'Terms of Service', href: '/terms' },
      { label: 'Privacy Policy', href: '/privacy' },
    ],
  },
];

// ── FAQ data ──────────────────────────────────────────────────────────────────
// Sourced from docs/FAQ.md — key questions only for the inline panel.

const FAQ_ITEMS: { q: string; a: string }[] = [
  {
    q: 'How much does HOPEFX cost?',
    a: 'Free plan is available indefinitely. Paid plans start at $1,800/mo (Starter), $4,500/mo (Professional), $7,500/mo (Enterprise), and $10,000/mo (Elite). Annual billing gives 2 months free (~17% off).',
  },
  {
    q: 'Is there a free trial?',
    a: 'The Free plan is available indefinitely with no credit card required. The Professional plan includes a 14-day free trial.',
  },
  {
    q: 'What brokers are supported?',
    a: 'OANDA (practice + live), Interactive Brokers, Alpaca, Binance, Bybit, MetaTrader 5, and 100+ exchanges via CCXT. Paper trading is built-in and requires no broker account.',
  },
  {
    q: 'What ML models power the signals?',
    a: 'XGBoost stacking ensemble with 176 features (66.4% OOS accuracy). Online learning via SGD + EWC updates the model hourly. LSTM and Random Forest are also available.',
  },
  {
    q: 'Can I self-host HOPEFX?',
    a: 'Yes. Under AGPL-3.0 you can self-host for personal trading. Commercial use or SaaS deployment requires a separate commercial license.',
  },
  {
    q: 'What payment methods are accepted?',
    a: 'Credit/debit cards via Stripe, bank transfers, Flutterwave, Paystack, and cryptocurrency (BTC, ETH, USDT TRC20/ERC20/BEP20).',
  },
];

// ── Components ────────────────────────────────────────────────────────────────

function FAQItem({ q, a }: { q: string; a: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="border border-terminal-border rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center justify-between px-5 py-4 text-left bg-terminal-surface hover:bg-terminal-raised transition-colors"
      >
        <span className="text-sm font-semibold text-slate-200">{q}</span>
        <ChevronRight
          size={16}
          className={`text-slate-500 shrink-0 transition-transform duration-200 ${open ? 'rotate-90' : ''}`}
        />
      </button>
      {open && (
        <div className="px-5 py-4 bg-terminal-bg border-t border-terminal-border">
          <p className="text-sm text-slate-400 leading-relaxed">{a}</p>
        </div>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

const DocsPage: React.FC = () => {
  const [query, setQuery] = useState('');

  const filtered = query.trim()
    ? SECTIONS.map(s => ({
        ...s,
        entries: s.entries.filter(e =>
          e.label.toLowerCase().includes(query.toLowerCase()) ||
          s.title.toLowerCase().includes(query.toLowerCase())
        ),
      })).filter(s => s.entries.length > 0)
    : SECTIONS;

  return (
    <div
      style={{
        minHeight: '100vh',
        background: 'var(--bg, #0f172a)',
        color: 'var(--text, #f1f5f9)',
        fontFamily: 'Inter, system-ui, -apple-system, sans-serif',
      }}
    >
      {/* Header */}
      <div
        style={{
          borderBottom: '1px solid #1e293b',
          background: '#0a0f1a',
          padding: '48px 24px 40px',
        }}
      >
        <div style={{ maxWidth: 900, margin: '0 auto' }}>
          {/* Breadcrumb */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 20 }}>
            <Link to="/home" style={{ color: '#475569', fontSize: 13, textDecoration: 'none' }}
              onMouseEnter={e => { (e.currentTarget as HTMLAnchorElement).style.color = '#94a3b8'; }}
              onMouseLeave={e => { (e.currentTarget as HTMLAnchorElement).style.color = '#475569'; }}
            >Home</Link>
            <ChevronRight size={12} style={{ color: '#334155' }} />
            <span style={{ color: '#94a3b8', fontSize: 13 }}>Documentation</span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
            <div style={{
              width: 40, height: 40, borderRadius: 10,
              background: '#00d4ff18', border: '1px solid #00d4ff40',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
              <BookOpen size={20} style={{ color: '#00d4ff' }} />
            </div>
            <h1 style={{ fontSize: 28, fontWeight: 800, letterSpacing: '-0.5px', margin: 0 }}>
              HOPE<span style={{ color: '#00d4ff' }}>FX</span> Documentation
            </h1>
          </div>

          <p style={{ color: '#64748b', fontSize: 15, margin: '0 0 28px', lineHeight: 1.6 }}>
            AI-powered gold and forex trading platform. Automated strategies, real-time signals,
            and institutional-grade risk management.
          </p>

          {/* System status badge */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 28 }}>
            <span style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              background: '#00ff8810', border: '1px solid #00ff8830',
              color: '#00ff88', fontSize: 12, fontWeight: 600,
              padding: '4px 12px', borderRadius: 20,
            }}>
              <Activity size={11} />
              ML model: 66.4% OOS accuracy · 108 API endpoints · 2,560+ tests
            </span>
          </div>

          {/* Search */}
          <div style={{ position: 'relative', maxWidth: 480 }}>
            <Search
              size={15}
              style={{
                position: 'absolute', left: 14, top: '50%',
                transform: 'translateY(-50%)', color: '#475569',
              }}
            />
            <input
              type="text"
              placeholder="Search documentation…"
              value={query}
              onChange={e => setQuery(e.target.value)}
              style={{
                width: '100%', boxSizing: 'border-box',
                background: '#0f172a', border: '1px solid #1e293b',
                borderRadius: 10, color: '#e2e8f0', fontSize: 14,
                padding: '10px 14px 10px 40px', outline: 'none',
              }}
            />
          </div>
        </div>
      </div>

      {/* Doc sections grid */}
      <div style={{ maxWidth: 900, margin: '0 auto', padding: '40px 24px' }}>
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
          gap: 20,
          marginBottom: 56,
        }}>
          {filtered.map(section => (
            <div
              key={section.id}
              style={{
                background: '#0f172a',
                border: '1px solid #1e293b',
                borderRadius: 14,
                padding: '20px 22px',
              }}
            >
              {/* Section header */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
                <div style={{
                  width: 34, height: 34, borderRadius: 8,
                  background: `${section.color}18`,
                  border: `1px solid ${section.color}30`,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  color: section.color, flexShrink: 0,
                }}>
                  {section.icon}
                </div>
                <span style={{ fontSize: 13, fontWeight: 700, color: '#e2e8f0' }}>
                  {section.title}
                </span>
              </div>

              {/* Links */}
              <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                {section.entries.map(entry => (
                  <li key={entry.label}>
                    <a
                      href={entry.href}
                      target={entry.external ? '_blank' : undefined}
                      rel={entry.external ? 'noopener noreferrer' : undefined}
                      style={{
                        display: 'flex', alignItems: 'center', gap: 6,
                        color: '#94a3b8', fontSize: 13, textDecoration: 'none',
                        padding: '5px 0',
                        transition: 'color 0.15s',
                      }}
                      onMouseOver={e => { (e.currentTarget as HTMLAnchorElement).style.color = '#e2e8f0'; }}
                      onMouseOut={e => { (e.currentTarget as HTMLAnchorElement).style.color = '#94a3b8'; }}
                    >
                      <ChevronRight size={12} style={{ color: '#334155', flexShrink: 0 }} />
                      {entry.label}
                      {entry.external && (
                        <ExternalLink size={10} style={{ color: '#334155', marginLeft: 'auto' }} />
                      )}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        {/* FAQ section */}
        <div style={{ marginBottom: 56 }}>
          <h2 style={{
            fontSize: 20, fontWeight: 700, color: '#f1f5f9',
            marginBottom: 20, letterSpacing: '-0.3px',
          }}>
            Frequently Asked Questions
          </h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {FAQ_ITEMS.map(item => (
              <FAQItem key={item.q} q={item.q} a={item.a} />
            ))}
          </div>
          <p style={{ marginTop: 16, fontSize: 13, color: '#475569' }}>
            More questions?{' '}
            <a
              href={`${GITHUB_BASE}/FAQ.md`}
              target="_blank"
              rel="noopener noreferrer"
              style={{ color: '#00d4ff', textDecoration: 'none' }}
            >
              Read the full FAQ on GitHub
            </a>
          </p>
        </div>

        {/* Quick navigation */}
        <CrossLinkBar title="Quick Links" style={{ marginBottom: 32 }} links={[
          { label: 'Dashboard',    href: '/dashboard',  icon: '📊', color: '#3b82f6' },
          { label: 'Trade',        href: '/trade',      icon: '⚡', color: '#4ade80' },
          { label: 'Pricing',      href: '/pricing',    icon: '💰', color: '#f59e0b' },
          { label: 'Status',       href: '/status',     icon: '🟢', color: '#22c55e' },
          { label: 'AI Strategy',  href: '/ai-strategy',icon: '🤖', color: '#a78bfa' },
          { label: 'Leaderboard',  href: '/leaderboard',icon: '🏆', color: '#fbbf24' },
        ]} />

        {/* Footer links */}
        <div style={{
          borderTop: '1px solid #1e293b',
          paddingTop: 28,
          display: 'flex',
          flexWrap: 'wrap',
          gap: 16,
          alignItems: 'center',
          justifyContent: 'space-between',
        }}>
          <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap' }}>
            {[
              { label: 'Pricing', to: '/pricing' },
              { label: 'Terms',   to: '/terms' },
              { label: 'Privacy', to: '/privacy' },
              { label: 'Status',  to: '/status' },
              { label: 'Home',    to: '/home' },
              { label: 'Trade',   to: '/trade' },
            ].map(l => (
              <Link
                key={l.label}
                to={l.to}
                style={{ color: '#475569', fontSize: 13, textDecoration: 'none' }}
                onMouseEnter={e => { (e.currentTarget as HTMLAnchorElement).style.color = '#94a3b8'; }}
                onMouseLeave={e => { (e.currentTarget as HTMLAnchorElement).style.color = '#475569'; }}
              >
                {l.label}
              </Link>
            ))}
          </div>
          <a
            href="https://github.com/HACKLOVE340/HOPEFX-AI-TRADING"
            target="_blank"
            rel="noopener noreferrer"
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              color: '#475569', fontSize: 13, textDecoration: 'none',
            }}
            onMouseOver={e => { (e.currentTarget as HTMLAnchorElement).style.color = '#94a3b8'; }}
            onMouseOut={e => { (e.currentTarget as HTMLAnchorElement).style.color = '#475569'; }}
          >
            <ExternalLink size={12} />
            View on GitHub
          </a>
        </div>
      </div>
    </div>
  );
};

export default DocsPage;
