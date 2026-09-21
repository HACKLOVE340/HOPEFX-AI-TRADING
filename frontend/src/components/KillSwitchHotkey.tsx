/**
 * components/KillSwitchHotkey.tsx
 *
 * Shift+K halts trading from anywhere in the app (audit S10-04).
 *
 * The backlog recorded "no keyboard-shortcut affordance … for the kill switch".
 * Auditing where the switch could actually be thrown made the gap sharper than
 * the entry suggested: every trigger lives in **Settings** (`TradingSection`,
 * `AdminSettingsSection`) or the **superadmin** panel. A trader watching a
 * position run against them had to navigate away from the trading screen to
 * halt trading — at exactly the moment navigating away is the worst thing to
 * ask of them.
 *
 * Design decisions, because this is the most destructive control in the product:
 *
 * * **A modifier, not a bare letter.** "Halt all trading" must not be one stray
 *   keystroke away. `useHotkeys` also refuses to fire from inside a field or
 *   while a dialog is open.
 * * **It still asks.** The shortcut opens the same confirmation a button would.
 *   A shortcut is an accelerator for reaching a control, never a way around the
 *   guard on it — and the confirmation states what will happen in words, per
 *   S10-03.
 * * **The failure is reported honestly.** `describeSubmitFailure` (F2-01): a
 *   timeout on the halt request means we do not know whether trading stopped,
 *   and telling an operator it failed when it may have succeeded is how they
 *   end up fighting the system during an incident.
 *
 * Rendered once, inside `ConfirmDialogProvider`, from `App.tsx`.
 */

import { useCallback } from 'react';
import { useHotkeys } from '../hooks/useHotkeys';
import { useConfirm } from './ConfirmDialog';
import { useToast } from './Toast';
import { tradingApi } from '../hooks/useApi';
import { describeSubmitFailure } from '../lib/utils';

export function KillSwitchHotkey() {
  const confirm = useConfirm();
  const toast = useToast();

  const halt = useCallback(async () => {
    const ok = await confirm({
      title: 'Halt all trading?',
      description:
        'This activates the kill switch. New orders are refused and the engine ' +
        'stops trading immediately.\n\n' +
        'It does NOT close your open positions — you keep the exposure you have ' +
        'and must close it yourself.',
      confirmLabel: 'Halt trading',
      variant: 'danger',
    });
    if (!ok) return;

    try {
      await tradingApi.emergencyStop();
      toast.warning('Kill switch activated — trading halted. Open positions are unchanged.');
    } catch (e: unknown) {
      const outcome = describeSubmitFailure(e, 'halt');
      toast.error(outcome.message);
    }
  }, [confirm, toast]);

  useHotkeys({ 'shift+k': () => void halt() });

  return null;
}

export default KillSwitchHotkey;
