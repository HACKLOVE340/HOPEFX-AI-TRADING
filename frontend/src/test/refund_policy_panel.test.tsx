/**
 * The refund policy control in the superadmin financial section.
 *
 * This setting decides where a creator's money comes from when a settled sale is
 * refunded, so the control has to do more than store a string. What is pinned
 * here is what the operator can actually see and do: the three options and their
 * consequences must be readable, the current one must be identifiable without
 * relying on colour, Save must be inert until something changed, and a rejected
 * save must say so rather than appearing to have worked.
 *
 * It also exists because passing `tsc` and `vite build` does not prove a panel
 * is reachable — earlier in this audit a block of JSX compiled cleanly while
 * landing inside the wrong component and rendering nowhere.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';

const OPTIONS = [
  {
    value: 'deduct_next_payout',
    label: 'Deduct from next payout',
    description: "Withhold the refunded amount from the creator's next payout.",
    recommended: 'true',
  },
  {
    value: 'allow_negative_balance',
    label: 'Debit immediately, allow negative',
    description: "Debit the creator's balance now, even into the negative.",
    recommended: 'false',
  },
  {
    value: 'platform_absorbs',
    label: 'Platform absorbs the loss',
    description: 'Refund the buyer in full from platform funds.',
    recommended: 'false',
  },
];

const refundPolicy = vi.fn();
const setRefundPolicy = vi.fn();

vi.mock('../hooks/useApi', () => ({
  superadminApi: {
    revenueStats: vi.fn().mockResolvedValue({ data: {} }),
    paymentHistory: vi.fn().mockResolvedValue({ data: { payments: [] } }),
    subscriptionStats: vi.fn().mockResolvedValue({ data: {} }),
    affiliateStats: vi.fn().mockResolvedValue({ data: {} }),
    chargebacks: vi.fn().mockResolvedValue({ data: { chargebacks: [] } }),
    taxReports: vi.fn().mockResolvedValue({ data: { reports: [] } }),
    reconciliationRecords: vi.fn().mockResolvedValue({ data: { records: [] } }),
    refundPayment: vi.fn().mockResolvedValue({ data: {} }),
    refundPolicy: (...a: unknown[]) => refundPolicy(...a),
    setRefundPolicy: (...a: unknown[]) => setRefundPolicy(...a),
  },
}));

vi.mock('../hooks/usePolling', () => ({ usePolling: vi.fn() }));

import FinancialSection from '../pages/superadmin/FinancialSection';

async function openPolicyTab() {
  render(<FinancialSection />);
  fireEvent.click(screen.getByText('Refund Policy'));
  await waitFor(() => expect(refundPolicy).toHaveBeenCalled());
}

describe('refund policy panel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    refundPolicy.mockResolvedValue({
      data: { policy: 'deduct_next_payout', options: OPTIONS, note: 'Applies to new refunds only.' },
    });
    setRefundPolicy.mockResolvedValue({ data: { policy: 'platform_absorbs' } });
  });

  it('is reachable and renders every option with what it does to money', async () => {
    await openPolicyTab();

    for (const opt of OPTIONS) {
      expect(await screen.findByText(opt.label)).toBeTruthy();
      // The consequence, not just the name — an operator picking where money
      // goes must be able to read what each choice does.
      expect(screen.getByText(opt.description)).toBeTruthy();
    }
  });

  it('offers the three policies as one exclusive radio group', async () => {
    await openPolicyTab();

    const radios = await screen.findAllByRole('radio');
    expect(radios).toHaveLength(3);
    // One name => selecting one deselects the others. Three separate checkboxes
    // would let an operator pick two mutually exclusive money policies.
    expect(new Set(radios.map(r => (r as HTMLInputElement).name)).size).toBe(1);
    expect(radios.filter(r => (r as HTMLInputElement).checked)).toHaveLength(1);
  });

  it('marks the current policy in words, not only in colour', async () => {
    await openPolicyTab();
    expect(await screen.findByText('Current')).toBeTruthy();
    expect(screen.getByText('Recommended')).toBeTruthy();
  });

  it('leaves Save inert until something actually changed', async () => {
    await openPolicyTab();

    const save = (await screen.findByText('Save policy')).closest('button')!;
    expect(save.disabled).toBe(true);

    fireEvent.click(screen.getByRole('radio', { name: /platform absorbs/i }));
    await waitFor(() => expect(save.disabled).toBe(false));
  });

  it('sends the selected policy and reports that it applies to new refunds only', async () => {
    await openPolicyTab();

    fireEvent.click(screen.getByRole('radio', { name: /platform absorbs/i }));
    fireEvent.click((await screen.findByText('Save policy')).closest('button')!);

    await waitFor(() => expect(setRefundPolicy).toHaveBeenCalledWith('platform_absorbs'));
    // Assert the status region specifically: the standing note carries similar
    // wording, and matching on text alone would pass without a save confirmation.
    const status = await screen.findByRole('status');
    expect(status.textContent).toMatch(/saved/i);
    expect(status.textContent).toMatch(/new refunds only/i);
  });

  it('does not pretend a rejected save worked', async () => {
    setRefundPolicy.mockRejectedValue({
      response: { data: { detail: 'Configuration store unavailable — refund policy not changed.' } },
    });
    await openPolicyTab();

    fireEvent.click(screen.getByRole('radio', { name: /platform absorbs/i }));
    fireEvent.click((await screen.findByText('Save policy')).closest('button')!);

    // The server's reason, verbatim, in an assertive region.
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('not changed');
    // And the selection snaps back, so the UI never shows a policy the platform
    // is not actually using.
    await waitFor(() => {
      const checked = screen.getAllByRole('radio').find(r => (r as HTMLInputElement).checked) as HTMLInputElement;
      expect(checked.value).toBe('deduct_next_payout');
    });
  });
});
