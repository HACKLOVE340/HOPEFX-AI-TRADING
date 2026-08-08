/**
 * components/ui/LiveFeedNotice.tsx
 *
 * The socket half of the F1-01 story (audit F1-02).
 *
 * `<StaleDataNotice>` says "I asked for this and the request failed". This says
 * something different and, per S9-01, more likely: the connection is fine and
 * nothing is coming down it. There is no error to catch, so a page has to be
 * told to look — and when it looks, it must say what it found, because a page
 * whose numbers have quietly stopped moving reads exactly like one whose
 * numbers are simply not changing.
 *
 * `aria-live="polite"` for the same reason as StaleDataNotice: important, not an
 * emergency, and an assertive region interrupts a screen-reader user mid-word.
 */

import React from 'react';

export function LiveFeedNotice({
  live,
  what = 'live updates',
  className = '',
}: {
  /** Whether the live feed is actually delivering. See `selectFeedLive`. */
  live: boolean;
  /** What has stopped updating, in words a user recognises ("alerts"). */
  what?: string;
  className?: string;
}) {
  if (live) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="live-feed-notice"
      className={
        'flex items-start gap-2 px-3 py-2 rounded border text-[12px] ' +
        'bg-[#ffb800]/10 border-[#ffb800]/30 text-[#ffb800] ' +
        className
      }
    >
      <span aria-hidden="true">⚠</span>
      <span>
        The live feed isn&apos;t delivering — {what} are not arriving right now.
        Anything below is the last thing we received and may have moved since.
      </span>
    </div>
  );
}

export default LiveFeedNotice;
