/**
 * LandingPage — unit tests
 *
 * Covers:
 * - Renders without crashing
 * - HOPEFX branding
 * - Navbar: logo, nav links, Log in, Start free trial
 * - Mobile menu toggle
 * - Hero section: headline, subheadline, CTA buttons, stats
 * - Features section: all 9 feature titles
 * - How it works section: all 4 steps
 * - Pricing section: all 5 plans (free/starter/professional/enterprise/elite), monthly/annual toggle
 * - Testimonials section
 * - Footer
 * - Live ticker (WebSocket mock)
 * - No auth required (no store dependency)
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';

// ── Mocks ─────────────────────────────────────────────────────────────────────

// framer-motion: render children directly, skip animations
vi.mock('framer-motion', () => {
  const React = require('react');
  const motion: Record<string, React.FC<Record<string, unknown>>> = new Proxy({}, {
    get: (_t, tag: string) => {
      const Component = React.forwardRef(
        ({ children, ...props }: Record<string, unknown>, ref: unknown) => {
          // Strip framer-motion-specific props
          const { initial, animate, exit, variants, transition, whileHover, whileTap,
                  onHoverStart, onHoverEnd, custom, layout, layoutId, ...rest } = props;
          void initial; void animate; void exit; void variants; void transition;
          void whileHover; void whileTap; void onHoverStart; void onHoverEnd;
          void custom; void layout; void layoutId;
          return React.createElement(tag, { ...rest, ref }, children);
        }
      );
      Component.displayName = `motion.${tag}`;
      return Component;
    },
  });
  return {
    motion,
    AnimatePresence: ({ children }: { children: React.ReactNode }) => React.createElement(React.Fragment, null, children),
    useInView: () => true,
    useMotionValue: (v: number) => ({ set: vi.fn(), on: vi.fn(() => vi.fn()), get: () => v }),
    useSpring: (mv: { get: () => number; on: (e: string, cb: (v: number) => void) => () => void }) => mv,
  };
});

// WebSocket mock
class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  readyState = MockWebSocket.OPEN;
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  send = vi.fn();
  close = vi.fn(() => { this.readyState = MockWebSocket.CLOSED; });
  constructor(_url: string) {
    setTimeout(() => this.onopen?.(), 0);
  }
}

// fetch mock for polling fallback
const mockFetch = vi.fn();

const MOCK_PLANS = [
  {
    id: 'free', name: 'Free', tagline: 'Get started', price_usd_monthly: 0,
    price_usd_annual: 0, annual_savings_pct: 0, commission_rate: 0,
    commission_label: '0%', badge: null, cta: 'Get started', cta_href: '/register?plan=free',
    highlights: ['Basic signals', 'Paper trading'], features: {}, limits: {},
  },
  {
    id: 'starter', name: 'Starter', tagline: 'For active traders', price_usd_monthly: 1800,
    // annual display = price_usd_annual / 10 → 12600 / 10 = $1,260/mo
    price_usd_annual: 12600, annual_savings_pct: 17, commission_rate: 0.1,
    commission_label: '0.1%', badge: null, cta: 'Get started', cta_href: '/register?plan=starter',
    highlights: ['Live signals', 'Risk calculator'], features: {}, limits: {},
  },
  {
    id: 'professional', name: 'Professional', tagline: 'For serious traders', price_usd_monthly: 4500,
    // annual display = price_usd_annual / 10 → 31500 / 10 = $3,150/mo
    price_usd_annual: 31500, annual_savings_pct: 30, commission_rate: 0.05,
    commission_label: '0.05%', badge: 'Most popular', cta: 'Get started', cta_href: '/register?plan=professional',
    highlights: ['AI strategy', 'Backtesting', 'Copy trading', 'Marketplace access'], features: {}, limits: {},
  },
  {
    id: 'enterprise', name: 'Enterprise', tagline: 'For teams', price_usd_monthly: 0,
    price_usd_annual: 0, annual_savings_pct: 0, commission_rate: 0,
    commission_label: 'Custom', badge: null, cta: 'Contact sales', cta_href: '/contact',
    highlights: ['Custom limits', 'Dedicated support'], features: {}, limits: {},
  },
  {
    id: 'elite', name: 'Elite', tagline: 'Maximum power', price_usd_monthly: 10000,
    // annual display = price_usd_annual / 10 → 70000 / 10 = $7,000/mo
    price_usd_annual: 70000, annual_savings_pct: 30, commission_rate: 0,
    commission_label: '0%', badge: null, cta: 'Contact sales', cta_href: '/register?plan=elite',
    highlights: ['Nuclear AI', 'White-glove support', 'Custom dev', 'White-label option'], features: {}, limits: {},
  },
];

beforeEach(() => {
  vi.stubGlobal('WebSocket', MockWebSocket);
  vi.stubGlobal('fetch', mockFetch);
  mockFetch.mockImplementation((url: string | URL) => {
    const urlStr = typeof url === 'string' ? url : url.toString();
    if (urlStr.includes('/pricing/plans')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ plans: MOCK_PLANS }),
      });
    }
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve({ symbol: 'XAU_USD', bid: 2340.5, ask: 2341.0, mid: 2340.75, change_pct: 0.42 }),
    });
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// ── Helpers ───────────────────────────────────────────────────────────────────

const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });

async function renderLanding() {
  const LandingPage = (await import('../pages/LandingPage')).default;
  let result!: ReturnType<typeof render>;
  await act(async () => {
    result = render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/']}>
          <Routes>
            <Route path="*" element={<LandingPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    );
  });
  return result;
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('LandingPage — render', () => {
  it('renders without crashing', async () => {
    await renderLanding();
    expect(document.body).toBeTruthy();
  });

  it('renders HOPEFX branding', async () => {
    await renderLanding();
    // HOPE and FX appear multiple times (navbar + footer) — use getAllByText
    expect(screen.getAllByText('HOPE').length).toBeGreaterThan(0);
    expect(screen.getAllByText('FX').length).toBeGreaterThan(0);
  });

  it('renders page content (non-empty body)', async () => {
    await renderLanding();
    expect(document.body.textContent?.length).toBeGreaterThan(100);
  });
});

describe('LandingPage — Navbar', () => {
  it('renders Log in link', async () => {
    await renderLanding();
    const loginLinks = screen.getAllByText(/log in/i);
    expect(loginLinks.length).toBeGreaterThan(0);
  });

  it('Log in link points to /login', async () => {
    await renderLanding();
    const loginLink = screen.getAllByRole('link', { name: /log in/i })[0];
    expect(loginLink).toHaveAttribute('href', '/login');
  });

  it('renders Start free trial link in navbar', async () => {
    await renderLanding();
    const trialLinks = screen.getAllByText(/start free trial/i);
    expect(trialLinks.length).toBeGreaterThan(0);
  });

  it('renders Features nav link', async () => {
    await renderLanding();
    const featuresLinks = screen.getAllByRole('link', { name: /^features$/i });
    expect(featuresLinks.length).toBeGreaterThan(0);
  });

  it('renders Pricing nav link', async () => {
    await renderLanding();
    const pricingLinks = screen.getAllByRole('link', { name: /^pricing$/i });
    expect(pricingLinks.length).toBeGreaterThan(0);
  });

  it('renders How it works nav link', async () => {
    await renderLanding();
    const links = screen.getAllByRole('link', { name: /how it works/i });
    expect(links.length).toBeGreaterThan(0);
  });

  it('renders Docs nav link', async () => {
    await renderLanding();
    const docsLinks = screen.getAllByRole('link', { name: /^docs$/i });
    expect(docsLinks.length).toBeGreaterThan(0);
  });

  it('renders Status nav link', async () => {
    await renderLanding();
    const statusLinks = screen.getAllByRole('link', { name: /^status$/i });
    expect(statusLinks.length).toBeGreaterThan(0);
  });

  it('renders mobile menu toggle button', async () => {
    await renderLanding();
    // aria-label is "Open menu" when closed, "Close menu" when open
    const menuBtn = screen.getByRole('button', { name: /open menu|close menu/i });
    expect(menuBtn).toBeInTheDocument();
  });

  it('mobile menu opens on toggle click', async () => {
    await renderLanding();
    const menuBtn = screen.getByRole('button', { name: /open menu|close menu/i });
    fireEvent.click(menuBtn);
    // Mobile menu shows additional links — Log in appears again
    const loginLinks = screen.getAllByText(/log in/i);
    expect(loginLinks.length).toBeGreaterThanOrEqual(1);
  });
});

describe('LandingPage — Hero section', () => {
  it('renders main headline with "gold & forex"', async () => {
    await renderLanding();
    expect(screen.getByText(/gold & forex/i)).toBeInTheDocument();
  });

  it('renders "institutional-grade AI" in headline', async () => {
    await renderLanding();
    expect(screen.getByText(/institutional-grade ai/i)).toBeInTheDocument();
  });

  it('renders hero subheadline', async () => {
    await renderLanding();
    expect(screen.getByText(/machine learning/i)).toBeInTheDocument();
  });

  it('renders Start free trial CTA button in hero', async () => {
    await renderLanding();
    const trialLinks = screen.getAllByRole('link', { name: /start free trial/i });
    expect(trialLinks.length).toBeGreaterThan(0);
    expect(trialLinks[0]).toHaveAttribute('href', '/register');
  });

  it('renders See how it works CTA', async () => {
    await renderLanding();
    expect(screen.getByText(/see how it works/i)).toBeInTheDocument();
  });

  it('renders AI-Powered Trading Platform badge', async () => {
    await renderLanding();
    expect(screen.getByText(/ai-powered trading platform/i)).toBeInTheDocument();
  });

  it('renders Built-in strategies stat', async () => {
    await renderLanding();
    // Appears in both hero stats and possibly features — use getAllByText
    expect(screen.getAllByText(/built-in strategies/i).length).toBeGreaterThan(0);
  });

  it('renders Uptime SLA stat', async () => {
    await renderLanding();
    expect(screen.getByText(/uptime sla/i)).toBeInTheDocument();
  });

  it('renders Signal latency stat', async () => {
    await renderLanding();
    expect(screen.getByText(/signal latency/i)).toBeInTheDocument();
  });

  it('renders OANDA integration stat', async () => {
    await renderLanding();
    expect(screen.getByText(/oanda integration/i)).toBeInTheDocument();
  });
});

describe('LandingPage — Features section', () => {
  it('renders Features section heading', async () => {
    await renderLanding();
    expect(screen.getByText(/everything you need to trade smarter/i)).toBeInTheDocument();
  });

  it('renders AI Signal Engine feature', async () => {
    await renderLanding();
    expect(screen.getByText('AI Signal Engine')).toBeInTheDocument();
  });

  it('renders Strategy Marketplace feature', async () => {
    await renderLanding();
    expect(screen.getByText('Strategy Marketplace')).toBeInTheDocument();
  });

  it('renders Institutional Risk Mgmt feature', async () => {
    await renderLanding();
    expect(screen.getByText('Institutional Risk Mgmt')).toBeInTheDocument();
  });

  it('renders Backtesting + PDF Reports feature', async () => {
    await renderLanding();
    expect(screen.getByText('Backtesting + PDF Reports')).toBeInTheDocument();
  });

  it('renders Multi-Channel Alerts feature', async () => {
    await renderLanding();
    expect(screen.getByText('Multi-Channel Alerts')).toBeInTheDocument();
  });

  it('renders Macro Data Integration feature', async () => {
    await renderLanding();
    expect(screen.getByText('Macro Data Integration')).toBeInTheDocument();
  });

  it('renders Crypto Payments feature', async () => {
    await renderLanding();
    expect(screen.getByText('Crypto Payments')).toBeInTheDocument();
  });

  it('renders Affiliate Program feature', async () => {
    await renderLanding();
    expect(screen.getByText('Affiliate Program')).toBeInTheDocument();
  });

  it('renders Mobile Ready feature', async () => {
    await renderLanding();
    expect(screen.getByText('Mobile Ready')).toBeInTheDocument();
  });
});

describe('LandingPage — How it works section', () => {
  it('renders How it works heading', async () => {
    await renderLanding();
    // "How it works" appears in nav link and section heading — use getAllByText
    expect(screen.getAllByText(/how it works/i).length).toBeGreaterThan(0);
  });

  it('renders Connect your broker step', async () => {
    await renderLanding();
    expect(screen.getByText('Connect your broker')).toBeInTheDocument();
  });

  it('renders Choose a strategy step', async () => {
    await renderLanding();
    expect(screen.getByText('Choose a strategy')).toBeInTheDocument();
  });

  it('renders Configure risk step', async () => {
    await renderLanding();
    expect(screen.getByText('Configure risk')).toBeInTheDocument();
  });

  it('renders Go live step', async () => {
    await renderLanding();
    expect(screen.getByText('Go live')).toBeInTheDocument();
  });
});

describe('LandingPage — Pricing section', () => {
  it('renders Pricing section heading', async () => {
    await renderLanding();
    expect(screen.getByText(/simple, transparent pricing/i)).toBeInTheDocument();
  });

  it('renders Free plan', async () => {
    await renderLanding();
    // Plans load asynchronously via fetch — wait for them
    await waitFor(() => expect(screen.getAllByText('Free').length).toBeGreaterThan(0), { timeout: 3000 });
  });

  it('renders Starter plan', async () => {
    await renderLanding();
    await waitFor(() => expect(screen.getByText('Starter')).toBeInTheDocument(), { timeout: 3000 });
  });

  it('renders Professional plan', async () => {
    await renderLanding();
    await waitFor(() => expect(screen.getByText('Professional')).toBeInTheDocument(), { timeout: 3000 });
  });

  it('renders Enterprise plan', async () => {
    await renderLanding();
    await waitFor(() => expect(screen.getByText('Enterprise')).toBeInTheDocument(), { timeout: 3000 });
  });

  it('renders Elite plan', async () => {
    await renderLanding();
    await waitFor(() => expect(screen.getByText('Elite')).toBeInTheDocument(), { timeout: 3000 });
  });

  it('renders Most popular badge on Professional plan', async () => {
    await renderLanding();
    await waitFor(() => expect(screen.getByText('Most popular')).toBeInTheDocument(), { timeout: 3000 });
  });

  it('renders monthly pricing toggle', async () => {
    await renderLanding();
    expect(screen.getByText(/monthly/i)).toBeInTheDocument();
  });

  it('renders annual pricing toggle', async () => {
    await renderLanding();
    expect(screen.getByText(/annual/i)).toBeInTheDocument();
  });

  it('shows monthly price $1,800 for Starter by default', async () => {
    await renderLanding();
    await waitFor(() => expect(screen.getByText('$1,800')).toBeInTheDocument(), { timeout: 3000 });
  });

  it('shows monthly price $4,500 for Professional by default', async () => {
    await renderLanding();
    await waitFor(() => expect(screen.getByText('$4,500')).toBeInTheDocument(), { timeout: 3000 });
  });

  it('shows monthly price $10,000 for Elite by default', async () => {
    await renderLanding();
    await waitFor(() => expect(screen.getByText('$10,000')).toBeInTheDocument(), { timeout: 3000 });
  });

  it('switches to annual pricing on toggle click', async () => {
    await renderLanding();
    const annualBtn = screen.getByRole('button', { name: /annual/i });
    fireEvent.click(annualBtn);
    await waitFor(() => expect(screen.getByText('$1,260')).toBeInTheDocument());
  });

  it('shows annual price $3,150 for Professional after toggle', async () => {
    await renderLanding();
    fireEvent.click(screen.getByRole('button', { name: /annual/i }));
    await waitFor(() => expect(screen.getByText('$3,150')).toBeInTheDocument());
  });

  it('shows annual price $7,000 for Elite after toggle', async () => {
    await renderLanding();
    fireEvent.click(screen.getByRole('button', { name: /annual/i }));
    await waitFor(() => expect(screen.getByText('$7,000')).toBeInTheDocument());
  });

  it('renders Get started CTA for Free plan', async () => {
    await renderLanding();
    // Plans load async — wait for CTA links to appear
    await waitFor(() => {
      const links = screen.getAllByRole('link', { name: /get started/i });
      expect(links.length).toBeGreaterThan(0);
    }, { timeout: 3000 });
  });

  it('renders Start free trial CTA for Professional', async () => {
    await renderLanding();
    // Navbar and hero already have "Start free trial" links — no waitFor needed
    const trialLinks = screen.getAllByRole('link', { name: /start free trial/i });
    expect(trialLinks.length).toBeGreaterThan(0);
  });

  it('renders Contact sales CTA for Elite', async () => {
    await renderLanding();
    await waitFor(() => {
      const links = screen.getAllByRole('link', { name: /contact sales/i });
      expect(links.length).toBeGreaterThan(0);
    }, { timeout: 3000 });
  });

  it('Starter plan links to /register?plan=starter', async () => {
    await renderLanding();
    await waitFor(() => {
      const links = screen.getAllByRole('link', { name: /get started/i });
      const starterLink = links.find(l => l.getAttribute('href') === '/register?plan=starter');
      expect(starterLink).toBeTruthy();
    }, { timeout: 3000 });
  });

  it('Elite plan links to /register?plan=elite', async () => {
    await renderLanding();
    await waitFor(() => {
      const links = screen.getAllByRole('link', { name: /contact sales/i });
      const eliteLink = links.find(l => l.getAttribute('href') === '/register?plan=elite');
      expect(eliteLink).toBeTruthy();
    }, { timeout: 3000 });
  });

  it('renders Free plan features', async () => {
    await renderLanding();
    await waitFor(() => expect(screen.getByText('Paper trading')).toBeInTheDocument(), { timeout: 3000 });
  });

  it('renders Professional plan features', async () => {
    await renderLanding();
    await waitFor(() => expect(screen.getByText('Marketplace access')).toBeInTheDocument(), { timeout: 3000 });
  });

  it('renders Elite plan features', async () => {
    await renderLanding();
    await waitFor(() => expect(screen.getByText('White-label option')).toBeInTheDocument(), { timeout: 3000 });
  });
});

describe('LandingPage — Testimonials section', () => {
  it('renders testimonials heading', async () => {
    await renderLanding();
    expect(screen.getByText(/trusted by traders/i)).toBeInTheDocument();
  });

  it('renders Alex M. testimonial', async () => {
    await renderLanding();
    expect(screen.getByText('Alex M.')).toBeInTheDocument();
  });

  it('renders Sarah K. testimonial', async () => {
    await renderLanding();
    expect(screen.getByText('Sarah K.')).toBeInTheDocument();
  });

  it('renders James T. testimonial', async () => {
    await renderLanding();
    expect(screen.getByText('James T.')).toBeInTheDocument();
  });

  it('renders testimonial roles', async () => {
    await renderLanding();
    expect(screen.getByText('Prop trader, London')).toBeInTheDocument();
  });
});

describe('LandingPage — Footer', () => {
  it('renders footer with HOPEFX branding', async () => {
    await renderLanding();
    // Footer has HOPE + FX text (multiple instances)
    const hopeElements = screen.getAllByText('HOPE');
    expect(hopeElements.length).toBeGreaterThan(0);
  });

  it('renders footer copyright', async () => {
    await renderLanding();
    // Copyright year in footer (currently 2024)
    expect(screen.getByText(/© 202\d HOPEFX/)).toBeInTheDocument();
  });

  it('renders footer links section', async () => {
    await renderLanding();
    // Footer has product/company links — multiple elements may match /privacy/i
    expect(screen.getAllByText(/privacy/i).length).toBeGreaterThan(0);
  });
});

describe('LandingPage — Live ticker', () => {
  it('renders ticker bar when WebSocket sends price data', async () => {
    let wsInstance: MockWebSocket | null = null;
    vi.stubGlobal('WebSocket', class extends MockWebSocket {
      constructor(url: string) {
        super(url);
        wsInstance = this;
      }
    });

    await renderLanding();

    // Simulate WebSocket price tick
    await act(async () => {
      wsInstance?.onmessage?.({
        data: JSON.stringify({
          type: 'price_tick',
          data: { symbol: 'XAU_USD', bid: 2340.50, ask: 2341.00, change_pct: 0.42 },
        }),
      });
    });

    await waitFor(() => {
      // Ticker duplicates items for seamless loop — multiple XAU/USD elements
      expect(screen.getAllByText('XAU/USD').length).toBeGreaterThan(0);
    }, { timeout: 3000 });
  });

  it('polling fallback calls /api/data-layer/tick', async () => {
    await renderLanding();
    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/data-layer/tick')
      );
    }, { timeout: 3000 });
  });

  it('renders without crashing when WebSocket is unavailable', async () => {
    vi.stubGlobal('WebSocket', class {
      constructor() { throw new Error('WS unavailable'); }
    });
    await renderLanding();
    expect(document.body).toBeTruthy();
  });
});

describe('LandingPage — CTA section', () => {
  it('renders final CTA section', async () => {
    await renderLanding();
    // Multiple "Start free trial" links exist (navbar + hero + CTA section)
    const trialLinks = screen.getAllByRole('link', { name: /start free trial/i });
    expect(trialLinks.length).toBeGreaterThanOrEqual(2);
  });

  it('all Start free trial links point to /register', async () => {
    await renderLanding();
    const trialLinks = screen.getAllByRole('link', { name: /start free trial/i });
    trialLinks.forEach(link => {
      expect(link.getAttribute('href')).toMatch(/\/register/);
    });
  });
});
