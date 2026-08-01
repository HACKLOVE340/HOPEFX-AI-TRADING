/**
 * Onboarding page — unit tests
 *
 * Covers:
 * - Renders all 5 steps
 * - Step navigation (Next / Back)
 * - Broker selection
 * - Risk level selection
 * - Prop firm selection
 * - Backtest step (run + error)
 * - Paper trading step (start + error)
 * - Skip button navigates to /dashboard
 * - Finish button navigates to /dashboard
 * - localStorage persistence
 * - canAdvance gating per step
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';

// ── Mocks ─────────────────────────────────────────────────────────────────────

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return { ...actual, useNavigate: () => mockNavigate };
});

const mockApiPost = vi.fn();
vi.mock('../hooks/useApi', () => ({
  api: {
    post: (...args: unknown[]) => mockApiPost(...args),
    get:  vi.fn().mockResolvedValue({ data: {} }),
    defaults: { baseURL: '/api', timeout: 15000, headers: { 'Content-Type': 'application/json' } },
    interceptors: {
      request:  { handlers: [{}], use: vi.fn() },
      response: { handlers: [{}], use: vi.fn() },
    },
  },
  tradingApi:     { positions: vi.fn().mockResolvedValue({ data: [] }) },
  authApi:        { login: vi.fn(), logout: vi.fn(), me: vi.fn() },
  backtestApi:    { run: vi.fn(), results: vi.fn(), list: vi.fn() },
  mlApi:          { accuracy: vi.fn().mockResolvedValue({ data: {} }) },
  performanceApi: { summary: vi.fn().mockResolvedValue({ data: {} }) },
  signalsApi:     { active: vi.fn().mockResolvedValue({ data: [] }) },
}));

// ── Helpers ───────────────────────────────────────────────────────────────────

const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });

async function renderOnboarding(initialStep = 0) {
  localStorage.setItem('hopefx_onboarding_step', String(initialStep));
  const Onboarding = (await import('../pages/Onboarding')).default;
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/onboarding']}>
        <Routes>
          <Route path="*" element={<Onboarding />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('Onboarding — Step 1: Broker', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  afterEach(() => {
    localStorage.clear();
  });

  it('renders without crashing', async () => {
    await renderOnboarding();
    expect(document.body).toBeTruthy();
  });

  it('renders HOPEFX Setup heading', async () => {
    await renderOnboarding();
    expect(screen.getByText('HOPEFX Setup')).toBeInTheDocument();
  });

  it('renders step counter "Step 1 of 5"', async () => {
    await renderOnboarding();
    expect(screen.getByText(/step 1 of 5/i)).toBeInTheDocument();
  });

  it('renders step indicator with 5 nodes', async () => {
    await renderOnboarding();
    // Step indicator renders 5 circles
    const stepNodes = document.querySelectorAll('[style*="border-radius: 50%"]');
    expect(stepNodes.length).toBeGreaterThanOrEqual(5);
  });

  it('renders "Connect your broker" heading', async () => {
    await renderOnboarding();
    expect(screen.getByText('Connect your broker')).toBeInTheDocument();
  });

  it('renders OANDA broker option', async () => {
    await renderOnboarding();
    expect(screen.getByText('OANDA')).toBeInTheDocument();
  });

  it('renders Alpaca broker option', async () => {
    await renderOnboarding();
    expect(screen.getByText('Alpaca')).toBeInTheDocument();
  });

  it('renders Paper Trading broker option', async () => {
    await renderOnboarding();
    expect(screen.getByText('Paper Trading')).toBeInTheDocument();
  });

  it('renders Skip button', async () => {
    await renderOnboarding();
    expect(screen.getByText(/skip/i)).toBeInTheDocument();
  });

  it('renders Back button (disabled on step 1)', async () => {
    await renderOnboarding();
    const backBtn = screen.getByText(/back/i);
    expect(backBtn).toBeInTheDocument();
    expect(backBtn).toBeDisabled();
  });

  it('renders Next button', async () => {
    await renderOnboarding();
    expect(screen.getByText(/next/i)).toBeInTheDocument();
  });

  it('Next button is disabled before broker selection', async () => {
    await renderOnboarding();
    const nextBtn = screen.getByText(/next/i);
    expect(nextBtn).toBeDisabled();
  });

  it('selecting OANDA enables Next button', async () => {
    await renderOnboarding();
    fireEvent.click(screen.getByText('OANDA'));
    const nextBtn = screen.getByText(/next/i);
    expect(nextBtn).not.toBeDisabled();
  });

  it('selecting Alpaca enables Next button', async () => {
    await renderOnboarding();
    fireEvent.click(screen.getByText('Alpaca'));
    expect(screen.getByText(/next/i)).not.toBeDisabled();
  });

  it('selecting Paper Trading enables Next button', async () => {
    await renderOnboarding();
    fireEvent.click(screen.getByText('Paper Trading'));
    expect(screen.getByText(/next/i)).not.toBeDisabled();
  });

  it('points OANDA users at Settings, not at a .env file', async () => {
    // A hosted customer has no filesystem and no .env — the old copy told them
    // to add BROKER_OANDA_TOKEN to a file they cannot reach.
    await renderOnboarding();
    fireEvent.click(screen.getByText('OANDA'));
    const link = screen.getByRole('link', { name: /settings.*broker/i });
    expect(link).toHaveAttribute('href', '/settings?tab=broker');
    expect(screen.queryByText(/BROKER_OANDA_TOKEN/)).not.toBeInTheDocument();
  });

  it('Skip navigates to /dashboard', async () => {
    await renderOnboarding();
    fireEvent.click(screen.getByText(/skip/i));
    expect(mockNavigate).toHaveBeenCalledWith('/dashboard');
  });

  it('Skip records completion and clears the wizard state', async () => {
    // Completion used to be recorded by writing the string 'done' into the STEP
    // key. The next visit read that back through parseInt, got NaN, and matched
    // no step — so finishing onboarding was what produced the blank wizard.
    await renderOnboarding();
    fireEvent.click(screen.getByText(/skip/i));
    expect(localStorage.getItem('hopefx_onboarding_complete')).toBeTruthy();
    expect(localStorage.getItem('hopefx_onboarding_step')).toBeNull();
    expect(localStorage.getItem('hopefx_onboarding_answers')).toBeNull();
  });

  it('renders a usable first step when the saved value is not a number', async () => {
    localStorage.setItem('hopefx_onboarding_step', 'done');
    await renderOnboarding();
    // Step 1 of 5, not an empty shell.
    expect(screen.getByText(/step 1 of/i)).toBeInTheDocument();
  });
});

describe('Onboarding — Step 2: Risk Level', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it('advances to step 2 after broker selection', async () => {
    await renderOnboarding();
    fireEvent.click(screen.getByText('Paper Trading'));
    fireEvent.click(screen.getByText(/next/i));
    expect(screen.getByText('Set your risk level')).toBeInTheDocument();
  });

  it('renders step counter "Step 2 of 5"', async () => {
    await renderOnboarding();
    fireEvent.click(screen.getByText('Paper Trading'));
    fireEvent.click(screen.getByText(/next/i));
    expect(screen.getByText(/step 2 of 5/i)).toBeInTheDocument();
  });

  it('renders Conservative option', async () => {
    await renderOnboarding();
    fireEvent.click(screen.getByText('Paper Trading'));
    fireEvent.click(screen.getByText(/next/i));
    expect(screen.getByText('Conservative')).toBeInTheDocument();
  });

  it('renders Moderate option', async () => {
    await renderOnboarding();
    fireEvent.click(screen.getByText('Paper Trading'));
    fireEvent.click(screen.getByText(/next/i));
    expect(screen.getByText('Moderate')).toBeInTheDocument();
  });

  it('renders Aggressive option', async () => {
    await renderOnboarding();
    fireEvent.click(screen.getByText('Paper Trading'));
    fireEvent.click(screen.getByText(/next/i));
    expect(screen.getByText('Aggressive')).toBeInTheDocument();
  });

  it('Next is disabled before risk selection', async () => {
    await renderOnboarding();
    fireEvent.click(screen.getByText('Paper Trading'));
    fireEvent.click(screen.getByText(/next/i));
    expect(screen.getByText(/next/i)).toBeDisabled();
  });

  it('selecting Moderate enables Next', async () => {
    await renderOnboarding();
    fireEvent.click(screen.getByText('Paper Trading'));
    fireEvent.click(screen.getByText(/next/i));
    fireEvent.click(screen.getByText('Moderate'));
    expect(screen.getByText(/next/i)).not.toBeDisabled();
  });

  it('Back button returns to step 1', async () => {
    await renderOnboarding();
    fireEvent.click(screen.getByText('Paper Trading'));
    fireEvent.click(screen.getByText(/next/i));
    fireEvent.click(screen.getByText(/back/i));
    expect(screen.getByText('Connect your broker')).toBeInTheDocument();
  });
});

describe('Onboarding — Step 3: Prop Firm', () => {
  async function goToStep3() {
    const result = await renderOnboarding();
    fireEvent.click(screen.getByText('Paper Trading'));
    fireEvent.click(screen.getByText(/next/i));
    fireEvent.click(screen.getByText('Moderate'));
    fireEvent.click(screen.getByText(/next/i));
    return result;
  }

  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it('renders Prop firm rules heading', async () => {
    await goToStep3();
    expect(screen.getByText('Prop firm rules')).toBeInTheDocument();
  });

  it('renders FTMO option', async () => {
    await goToStep3();
    expect(screen.getByText('FTMO')).toBeInTheDocument();
  });

  it('renders The5ers option', async () => {
    await goToStep3();
    expect(screen.getByText('The5ers')).toBeInTheDocument();
  });

  it('renders No Prop Firm option', async () => {
    await goToStep3();
    expect(screen.getByText('No Prop Firm')).toBeInTheDocument();
  });

  it('Next is disabled before prop firm selection', async () => {
    await goToStep3();
    expect(screen.getByText(/next/i)).toBeDisabled();
  });

  it('selecting FTMO enables Next', async () => {
    await goToStep3();
    fireEvent.click(screen.getByText('FTMO'));
    expect(screen.getByText(/next/i)).not.toBeDisabled();
  });

  it('selecting No Prop Firm enables Next', async () => {
    await goToStep3();
    fireEvent.click(screen.getByText('No Prop Firm'));
    expect(screen.getByText(/next/i)).not.toBeDisabled();
  });
});

describe('Onboarding — Step 4: Backtest', () => {
  async function goToStep4() {
    await renderOnboarding();
    fireEvent.click(screen.getByText('Paper Trading'));
    fireEvent.click(screen.getByText(/next/i));
    fireEvent.click(screen.getByText('Moderate'));
    fireEvent.click(screen.getByText(/next/i));
    fireEvent.click(screen.getByText('No Prop Firm'));
    fireEvent.click(screen.getByText(/next/i));
  }

  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it('renders Run your first backtest heading', async () => {
    await goToStep4();
    expect(screen.getByText('Run your first backtest')).toBeInTheDocument();
  });

  it('renders Run Backtest button', async () => {
    await goToStep4();
    expect(screen.getByText(/run backtest/i)).toBeInTheDocument();
  });

  it('Next is disabled before backtest completes', async () => {
    await goToStep4();
    expect(screen.getByText(/next/i)).toBeDisabled();
  });

  it('runs backtest and shows results on success', async () => {
    mockApiPost.mockResolvedValueOnce({
      data: { total_return: 12.5, total_trades: 47, win_rate: 63 },
    });
    await goToStep4();
    fireEvent.click(screen.getByText(/run backtest/i));
    await waitFor(() => {
      expect(screen.getByText(/backtest complete/i)).toBeInTheDocument();
    });
    expect(screen.getByText('12.5%')).toBeInTheDocument();
    expect(screen.getByText('47')).toBeInTheDocument();
    expect(screen.getByText('63%')).toBeInTheDocument();
  });

  it('enables Next after successful backtest', async () => {
    mockApiPost.mockResolvedValueOnce({
      data: { total_return: 8.2, total_trades: 30, win_rate: 55 },
    });
    await goToStep4();
    fireEvent.click(screen.getByText(/run backtest/i));
    await waitFor(() => {
      expect(screen.getByText(/backtest complete/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/next/i)).not.toBeDisabled();
  });

  it('shows error message when backtest API fails', async () => {
    mockApiPost.mockRejectedValueOnce(new Error('Backtest service unavailable'));
    await goToStep4();
    fireEvent.click(screen.getByText(/run backtest/i));
    await waitFor(() => {
      expect(screen.getByText(/backtest service unavailable/i)).toBeInTheDocument();
    });
  });

  it('shows loading state while backtest runs', async () => {
    let resolve: (v: unknown) => void;
    mockApiPost.mockReturnValueOnce(new Promise((r) => { resolve = r; }));
    await goToStep4();
    fireEvent.click(screen.getByText(/run backtest/i));
    expect(screen.getByText(/running backtest/i)).toBeInTheDocument();
    act(() => resolve!({ data: { total_return: 5, total_trades: 10, win_rate: 50 } }));
  });
});

describe('Onboarding — Step 5: Paper Trading', () => {
  async function goToStep5() {
    mockApiPost.mockResolvedValueOnce({
      data: { total_return: 10, total_trades: 40, win_rate: 60 },
    });
    await renderOnboarding();
    fireEvent.click(screen.getByText('Paper Trading'));
    fireEvent.click(screen.getByText(/next/i));
    fireEvent.click(screen.getByText('Moderate'));
    fireEvent.click(screen.getByText(/next/i));
    fireEvent.click(screen.getByText('No Prop Firm'));
    fireEvent.click(screen.getByText(/next/i));
    fireEvent.click(screen.getByText(/run backtest/i));
    await waitFor(() => screen.getByText(/backtest complete/i));
    fireEvent.click(screen.getByText(/next/i));
  }

  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it('renders Start paper trading heading', async () => {
    await goToStep5();
    expect(screen.getByText('Start paper trading')).toBeInTheDocument();
  });

  it('renders Launch Paper Trading button', async () => {
    await goToStep5();
    expect(screen.getByText(/launch paper trading/i)).toBeInTheDocument();
  });

  it('renders Go to Dashboard button after paper start', async () => {
    mockApiPost.mockResolvedValueOnce({ data: { status: 'started' } });
    await goToStep5();
    fireEvent.click(screen.getByText(/launch paper trading/i));
    await waitFor(() => {
      expect(screen.getByText(/paper trading active/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/go to dashboard/i)).toBeInTheDocument();
  });

  it('navigates to /dashboard on finish', async () => {
    mockApiPost.mockResolvedValueOnce({ data: { status: 'started' } });
    await goToStep5();
    fireEvent.click(screen.getByText(/launch paper trading/i));
    await waitFor(() => screen.getByText(/go to dashboard/i));
    fireEvent.click(screen.getByText(/go to dashboard/i));
    expect(mockNavigate).toHaveBeenCalledWith('/dashboard');
  });

  it('shows error when paper trading API fails', async () => {
    // First call: backtest succeeds; second call: paper start fails
    mockApiPost
      .mockResolvedValueOnce({ data: { total_return: 10, total_trades: 40, win_rate: 60 } })
      .mockRejectedValueOnce(new Error('Trading service offline'));
    await renderOnboarding();
    fireEvent.click(screen.getByText('Paper Trading'));
    fireEvent.click(screen.getByText(/next/i));
    fireEvent.click(screen.getByText('Moderate'));
    fireEvent.click(screen.getByText(/next/i));
    fireEvent.click(screen.getByText('No Prop Firm'));
    fireEvent.click(screen.getByText(/next/i));
    fireEvent.click(screen.getByText(/run backtest/i));
    await waitFor(() => screen.getByText(/backtest complete/i));
    fireEvent.click(screen.getByText(/next/i));
    fireEvent.click(screen.getByText(/launch paper trading/i));
    await waitFor(() => {
      expect(screen.getByText(/trading service offline/i)).toBeInTheDocument();
    });
  });
});

describe('Onboarding — localStorage persistence', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it('resumes from saved step', async () => {
    localStorage.setItem('hopefx_onboarding_step', '2');
    await renderOnboarding(2);
    expect(screen.getByText('Prop firm rules')).toBeInTheDocument();
  });

  it('saves step to localStorage on Next', async () => {
    await renderOnboarding();
    fireEvent.click(screen.getByText('Paper Trading'));
    fireEvent.click(screen.getByText(/next/i));
    expect(localStorage.getItem('hopefx_onboarding_step')).toBe('1');
  });

  it('saves step to localStorage on Back', async () => {
    localStorage.setItem('hopefx_onboarding_step', '2');
    await renderOnboarding(2);
    fireEvent.click(screen.getByText(/back/i));
    expect(localStorage.getItem('hopefx_onboarding_step')).toBe('1');
  });
});
