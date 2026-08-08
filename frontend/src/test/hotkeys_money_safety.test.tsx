/**
 * S10-04 (rest) — keyboard shortcuts on a capital-committing surface.
 *
 * The backlog recorded "no keyboard-shortcut affordance for order entry or for
 * the kill switch". The kill switch is the sharper half: its only triggers live
 * in Settings and the superadmin panel, so a trader watching a position go
 * against them has to navigate away from the trading screen to halt trading.
 *
 * These tests are mostly about what a shortcut layer must **refuse** to do,
 * because on this surface the failure modes cost money:
 *
 *   - firing while the user is typing (`b` for "buy" inside the quantity field
 *     would arm a direction on a keystroke meant as text);
 *   - firing while a confirmation is open, reaching past the question;
 *   - reaching a destructive action without its confirmation.
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, act, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { useHotkeys, eventToBinding, isTypingTarget } from '../hooks/useHotkeys';
import { ConfirmDialogProvider, useConfirm } from '../components/ConfirmDialog';

describe('eventToBinding — S10-04', () => {
  const ev = (init: Partial<KeyboardEvent>) => new KeyboardEvent('keydown', init as never);

  it('renders a bare key', () => {
    expect(eventToBinding(ev({ key: 'b' }))).toBe('b');
  });

  it('is case-insensitive', () => {
    expect(eventToBinding(ev({ key: 'B' }))).toBe('b');
  });

  it('names shift', () => {
    expect(eventToBinding(ev({ key: 'K', shiftKey: true }))).toBe('shift+k');
  });

  it('normalises ctrl and meta to one "mod"', () => {
    expect(eventToBinding(ev({ key: 'enter', ctrlKey: true }))).toBe('mod+enter');
    expect(eventToBinding(ev({ key: 'enter', metaKey: true }))).toBe('mod+enter');
  });
});

describe('isTypingTarget — S10-04', () => {
  it.each(['input', 'textarea', 'select'])('%s is a typing target', (tag) => {
    expect(isTypingTarget(document.createElement(tag))).toBe(true);
  });

  it('a button is not', () => {
    expect(isTypingTarget(document.createElement('button'))).toBe(false);
  });

  it('a contenteditable div is', () => {
    const d = document.createElement('div');
    Object.defineProperty(d, 'isContentEditable', { value: true });
    expect(isTypingTarget(d)).toBe(true);
  });

  it('null is not', () => {
    expect(isTypingTarget(null)).toBe(false);
  });
});

const Harness: React.FC<{ onBuy: () => void; enabled?: boolean }> = ({ onBuy, enabled }) => {
  useHotkeys({ b: onBuy }, enabled ?? true);
  return <input aria-label="quantity" />;
};

describe('useHotkeys refuses to fire when it must not — S10-04', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('fires on a bare key outside a field', async () => {
    const onBuy = vi.fn();
    render(<Harness onBuy={onBuy} />);
    await userEvent.keyboard('b');
    expect(onBuy).toHaveBeenCalledTimes(1);
  });

  it('does NOT fire while the user is typing in a field', async () => {
    // The one that would arm an order direction from a keystroke meant as text.
    const onBuy = vi.fn();
    render(<Harness onBuy={onBuy} />);
    await userEvent.click(screen.getByLabelText('quantity'));
    await userEvent.keyboard('b');
    expect(onBuy).not.toHaveBeenCalled();
  });

  it('does NOT fire while a dialog is open', async () => {
    const onBuy = vi.fn();
    render(
      <>
        <div role="dialog">Confirm something?</div>
        <Harness onBuy={onBuy} />
      </>,
    );
    await userEvent.keyboard('b');
    expect(onBuy).not.toHaveBeenCalled();
  });

  it('does not fire when disabled', async () => {
    const onBuy = vi.fn();
    render(<Harness onBuy={onBuy} enabled={false} />);
    await userEvent.keyboard('b');
    expect(onBuy).not.toHaveBeenCalled();
  });

  it('unbinds on unmount', async () => {
    const onBuy = vi.fn();
    const { unmount } = render(<Harness onBuy={onBuy} />);
    unmount();
    await userEvent.keyboard('b');
    expect(onBuy).not.toHaveBeenCalled();
  });

  it('ignores a key with a modifier when the binding has none', async () => {
    const onBuy = vi.fn();
    render(<Harness onBuy={onBuy} />);
    await userEvent.keyboard('{Shift>}b{/Shift}');
    expect(onBuy).not.toHaveBeenCalled();
  });
});

// ── The destructive binding still asks ───────────────────────────────────────

const KillHarness: React.FC<{ onHalt: () => void }> = ({ onHalt }) => {
  const confirm = useConfirm();
  useHotkeys({
    'shift+k': async () => {
      const ok = await confirm({
        title: 'Halt all trading?',
        confirmLabel: 'Halt trading',
        variant: 'danger',
      });
      if (ok) onHalt();
    },
  });
  return <div>trading surface</div>;
};

describe('a destructive shortcut does not bypass its confirmation — S10-04', () => {
  it('opens the confirmation rather than acting', async () => {
    const onHalt = vi.fn();
    render(<ConfirmDialogProvider><KillHarness onHalt={onHalt} /></ConfirmDialogProvider>);

    await userEvent.keyboard('{Shift>}K{/Shift}');
    await screen.findByText('Halt all trading?');
    expect(onHalt, 'the shortcut halted trading without asking').not.toHaveBeenCalled();
  });

  it('acts only once confirmed', async () => {
    const onHalt = vi.fn();
    render(<ConfirmDialogProvider><KillHarness onHalt={onHalt} /></ConfirmDialogProvider>);

    await userEvent.keyboard('{Shift>}K{/Shift}');
    await screen.findByText('Halt all trading?');
    await userEvent.click(screen.getByRole('button', { name: /halt trading/i }));
    await waitFor(() => expect(onHalt).toHaveBeenCalledTimes(1));
  });

  it('does nothing when cancelled', async () => {
    const onHalt = vi.fn();
    render(<ConfirmDialogProvider><KillHarness onHalt={onHalt} /></ConfirmDialogProvider>);

    await userEvent.keyboard('{Shift>}K{/Shift}');
    await screen.findByText('Halt all trading?');
    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByText('Halt all trading?')).toBeNull());
    expect(onHalt).not.toHaveBeenCalled();
  });

  it('a bare "k" does nothing — the destructive binding needs its modifier', async () => {
    const onHalt = vi.fn();
    render(<ConfirmDialogProvider><KillHarness onHalt={onHalt} /></ConfirmDialogProvider>);
    await userEvent.keyboard('k');
    await act(async () => {});
    expect(screen.queryByText('Halt all trading?')).toBeNull();
    expect(onHalt).not.toHaveBeenCalled();
  });
});
