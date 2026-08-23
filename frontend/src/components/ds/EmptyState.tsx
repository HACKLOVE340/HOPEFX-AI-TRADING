/**
 * ds/EmptyState.tsx — the standard "nothing here yet" panel.
 *
 * Modelled on /walk-forward, which the audit found to be the one page that
 * gets this right (F195): it states what is missing, why, what to do, and
 * gives the route to do it.
 *
 * The failures it replaces:
 *   - /correlation showed a blank card after a ~20s request while the server
 *     had sent a plain-English explanation the UI discarded (F189).
 *   - /news renders "SENTIMENT 0.0" as a measurement when the sentiment engine
 *     is not running (F194).
 *
 * Hence `serverNote`: when the API explains itself, show the server's words.
 * An empty screen is an invitation to act, never a dead end.
 */

import React from 'react';
import { Link } from 'react-router-dom';
import type { LucideIcon } from 'lucide-react';
import { Inbox } from 'lucide-react';

export interface EmptyStateProps {
  /** What is missing, as a statement. Not "No data" — say what data. */
  title: string;
  /** Why it is missing, in the user's terms. */
  description?: string;
  /**
   * Verbatim explanation from the API. Several endpoints in this platform
   * return one and the UI used to throw it away — it is usually more specific
   * than anything written here.
   */
  serverNote?: string | null;
  icon?: LucideIcon;
  /** The route that resolves the emptiness. Label it with the action. */
  action?: { label: string; to?: string; onClick?: () => void };
  secondaryAction?: { label: string; to?: string; onClick?: () => void };
  compact?: boolean;
}

const btnBase =
  'inline-flex min-h-[44px] items-center justify-center gap-1.5 rounded-lg px-4 ' +
  'text-[13px] font-semibold cursor-pointer transition-colors duration-150 ' +
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 ' +
  'focus-visible:ring-offset-2 focus-visible:ring-offset-[#0d1421]';

const Btn: React.FC<{ a: NonNullable<EmptyStateProps['action']>; primary?: boolean }> = ({ a, primary }) => {
  const cls = `${btnBase} ${primary
    ? 'bg-sky-500/15 text-sky-300 ring-1 ring-inset ring-sky-500/40 hover:bg-sky-500/25'
    : 'text-slate-400 ring-1 ring-inset ring-[#1e2d3d] hover:bg-[#141c2b] hover:text-slate-200'}`;
  return a.to
    ? <Link to={a.to} className={cls}>{a.label}</Link>
    : <button type="button" onClick={a.onClick} className={cls}>{a.label}</button>;
};

export const EmptyState: React.FC<EmptyStateProps> = ({
  title, description, serverNote, icon: Icon = Inbox, action, secondaryAction, compact,
}) => (
  <div
    className={`flex flex-col items-center justify-center text-center
                ${compact ? 'gap-2 px-4 py-8' : 'gap-3 px-6 py-14'}`}
  >
    <span
      aria-hidden
      className="grid h-11 w-11 place-items-center rounded-full bg-[#111827]
                 text-slate-600 ring-1 ring-inset ring-[#1e2d3d]"
    >
      <Icon size={19} strokeWidth={1.5} />
    </span>
    <p className="text-[14px] font-semibold text-slate-300">{title}</p>
    {description && (
      <p className="max-w-[52ch] text-[12.5px] leading-relaxed text-slate-500">{description}</p>
    )}
    {serverNote && (
      <p className="max-w-[62ch] rounded-lg bg-[#0b1220] px-3 py-2 text-left text-[12px]
                    leading-relaxed text-slate-400 ring-1 ring-inset ring-[#1e2d3d]">
        {serverNote}
      </p>
    )}
    {(action || secondaryAction) && (
      <div className="mt-1 flex flex-wrap items-center justify-center gap-2">
        {action && <Btn a={action} primary />}
        {secondaryAction && <Btn a={secondaryAction} />}
      </div>
    )}
  </div>
);
