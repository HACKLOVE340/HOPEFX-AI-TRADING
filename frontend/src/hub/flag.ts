/**
 * hub/flag.ts — whether the AI Core page opens on the presence.
 *
 * Decision D2, revised: the Hub is not a new destination. It is what the
 * **existing** AI Core page opens on. Every tab that page already has —
 * Workbench, Overview, Model chain, Spend, Calls, Governance — stays exactly
 * where it was; what changes is which one you see first.
 *
 * That reading satisfies §4 ("the AI Core is the primary interface", not a
 * permanent dashboard) while deleting nothing at all, and it avoids the thing
 * the first attempt got wrong: a second AI screen beside the AI screen.
 *
 * Still behind a flag, per §30-I. Changing what a page opens on is a change to
 * what every operator sees first, and the status board must stay one variable
 * away for the life of the rollout.
 *
 * **Off unless the value is exactly `true`.** Not truthy, not "yes", not
 * "TRUE " with a trailing space: a typo in a deployment variable must fail
 * toward the behaviour that already works.
 */

export function hubEnabled(): boolean {
  return (import.meta.env.VITE_HUB_ENABLED as string | undefined) === 'true';
}
