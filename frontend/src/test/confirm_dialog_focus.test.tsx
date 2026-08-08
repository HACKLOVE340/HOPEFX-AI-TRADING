/**
 * F8-01 — the confirmation that guards every destructive action is not focus-trapped.
 *
 * docs/FRONTEND_AUDIT_PLAYBOOK.md slice F8: *"Are modals and confirm dialogs
 * focus-trapped and escapable? … can any destructive control be triggered by an
 * accidental Enter on a focused element?"* — money paths reported separately.
 *
 * `ConfirmDialog` declares `role="dialog"` and `aria-modal="true"`, and its
 * backdrop is `position: fixed; inset: 0; zIndex: 10000`, so the **mouse** is
 * blocked. The keyboard is not:
 *
 *   - focus is never moved into the dialog, so it stays on whatever was focused
 *     behind it — for `OrderEntryForm`, the submit button the user just pressed;
 *   - Tab walks straight out of the dialog into the page behind it, which
 *     `aria-modal="true"` tells a screen reader is inert. The markup and the
 *     behaviour disagree, and the screen-reader user gets the worse of the two;
 *   - Enter on that still-focused submit button re-submits the form *behind* the
 *     confirmation.
 *
 * That last one is why this is filed under the money path rather than as general
 * accessibility. It is the mechanism behind F2-02: a second submit while the
 * dialog is open displaced the first confirmation's resolver. F2-02 fixed the
 * consequence — a promise that never settled — and this fixes the cause.
 *
 * Escape already works and is left as it is.
 */

import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen, act, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { ConfirmDialogProvider, useConfirm } from '../components/ConfirmDialog';

const Harness: React.FC = () => {
  const confirm = useConfirm();
  return (
    <div>
      <button id="behind" onClick={() => void confirm({ title: 'Close everything?' })}>
        Close all
      </button>
      <input id="other" />
    </div>
  );
};

const open = async () => {
  render(<ConfirmDialogProvider><Harness /></ConfirmDialogProvider>);
  const trigger = screen.getByRole('button', { name: /close all/i });
  trigger.focus();
  await userEvent.click(trigger);
  await screen.findByText('Close everything?');
  return trigger;
};

describe('ConfirmDialog focus behaviour — F8-01', () => {
  it('moves focus into the dialog when it opens', async () => {
    const trigger = await open();
    await waitFor(() => {
      const dialog = screen.getByRole('dialog');
      expect(
        dialog.contains(document.activeElement),
        'focus stayed on the control behind the dialog, so Enter re-triggers it',
      ).toBe(true);
    });
    expect(document.activeElement).not.toBe(trigger);
  });

  it('does not leave focus on the destructive trigger', async () => {
    const trigger = await open();
    expect(document.activeElement).not.toBe(trigger);
  });

  it('keeps Tab inside the dialog', async () => {
    await open();
    const dialog = screen.getByRole('dialog');
    for (let i = 0; i < 6; i++) {
      await userEvent.tab();
      expect(
        dialog.contains(document.activeElement),
        `Tab ${i + 1} escaped a dialog marked aria-modal="true"`,
      ).toBe(true);
    }
  });

  it('keeps Shift+Tab inside the dialog', async () => {
    await open();
    const dialog = screen.getByRole('dialog');
    for (let i = 0; i < 4; i++) {
      await userEvent.tab({ shift: true });
      expect(dialog.contains(document.activeElement)).toBe(true);
    }
  });

  it('is still escapable', async () => {
    await open();
    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByText('Close everything?')).toBeNull());
  });

  it('returns focus to the trigger when it closes', async () => {
    const trigger = await open();
    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  });

  it('can be confirmed by keyboard alone', async () => {
    // The whole money path must be operable without a mouse.
    render(<ConfirmDialogProvider><Harness /></ConfirmDialogProvider>);
    const trigger = screen.getByRole('button', { name: /close all/i });
    trigger.focus();
    await userEvent.keyboard('{Enter}');
    await screen.findByText('Close everything?');
    await userEvent.keyboard('{Enter}');
    await waitFor(() => expect(screen.queryByText('Close everything?')).toBeNull());
  });
});
