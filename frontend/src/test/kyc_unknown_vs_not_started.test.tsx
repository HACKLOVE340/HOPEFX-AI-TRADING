/**
 * F6-01 — a failed load must not manufacture a compliance state.
 *
 * docs/FRONTEND_AUDIT_PLAYBOOK.md slice F6 asks for the views where an empty or
 * missing state can be misread as a *meaningful* value, and names KYC status as
 * one of them.
 *
 * `KYCPage.tsx:149`
 *
 *     } catch {
 *       setError('Failed to load KYC status. Please refresh.');
 *       setKycState({ status: 'not_started', submitted_at: null,
 *                     reviewed_at: null, rejection_reason: null, documents: [] });
 *     }
 *
 * The error handler does not fall through to a default — it **constructs** a
 * status object and asserts `not_started`. The page then renders the full "Not
 * Started" card, puts the step indicator on step 1, and offers the document
 * upload form, all describing a compliance state nobody checked.
 *
 * There is an error banner above it, so the failure is technically visible. But
 * the page is simultaneously making a specific claim, and the two contradict
 * each other:
 *
 *   - a user whose documents are `under_review` is told they have not begun,
 *     and the obvious response is to upload everything again;
 *   - a user who is `approved` is told to start verifying;
 *   - a `rejected` user is not shown the rejection reason they came for.
 *
 * "We could not check" is the honest answer and it is a different answer from
 * "you have not started". This is the S10-01 empty-vs-unknown distinction on a
 * surface that gates withdrawals.
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const renderKyc = async (getImpl: () => Promise<unknown>) => {
  vi.resetModules();
  vi.doMock('../hooks/useApi', async () => {
    const actual = await vi.importActual<Record<string, unknown>>('../hooks/useApi');
    return {
      ...actual,
      kycApi: { ...(actual.kycApi as object), status: vi.fn(getImpl) },
    };
  });
  const { default: KYCPage } = await import('../pages/KYCPage');
  return render(<MemoryRouter><KYCPage /></MemoryRouter>);
};

const boom = async () => { throw new Error('network down'); };

describe('KYC status — F6-01', () => {
  beforeEach(() => vi.resetModules());

  it('shows the real status when the load succeeds', async () => {
    const { container } = await renderKyc(async () => ({
      data: { status: 'under_review', submitted_at: null, reviewed_at: null, rejection_reason: null, documents: [] },
    }));
    await waitFor(() => expect(container.textContent ?? '').toMatch(/under review/i));
  });

  it('does not claim "Not Started" when the status could not be loaded', async () => {
    const { container } = await renderKyc(boom);
    await waitFor(() => expect(container.textContent ?? '').toMatch(/failed to load|couldn|unable/i));

    expect(
      container.textContent ?? '',
      'a failed load renders the full "Not Started" card — telling a user whose ' +
        'documents are under review that they have not begun (F6-01)',
    ).not.toMatch(/not started/i);
  });

  it('says the status is unknown, in words', async () => {
    const { container } = await renderKyc(boom);
    await waitFor(() => expect(container.textContent ?? '').toMatch(/unknown|unavailable|could ?n[o']t|unable/i));
  });

  it('does not invite a re-upload it cannot know is needed', async () => {
    // Offering the upload form under a fabricated "Not Started" is how a user
    // who already submitted ends up submitting again.
    const { container } = await renderKyc(boom);
    await waitFor(() => expect(container.textContent ?? '').toMatch(/failed to load|unknown/i));
    expect(container.textContent ?? '').not.toMatch(/choose file/i);
  });

  it('still tells the user the load failed', async () => {
    const { container } = await renderKyc(boom);
    await waitFor(() => expect(container.textContent ?? '').toMatch(/failed to load/i));
  });

  it('an approved user is not told to start verifying', async () => {
    const { container } = await renderKyc(async () => ({
      data: { status: 'approved', submitted_at: null, reviewed_at: null, rejection_reason: null, documents: [] },
    }));
    await waitFor(() => expect(container.textContent ?? '').toMatch(/approved/i));
    expect(container.textContent ?? '').not.toMatch(/not started/i);
  });
});
