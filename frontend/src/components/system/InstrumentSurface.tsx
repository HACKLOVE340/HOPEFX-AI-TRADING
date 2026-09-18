/**
 * InstrumentSurface — the AI pages' ground.
 *
 * Wraps a page in `data-surface="ai"`, which swaps the palette underneath it
 * to the instrument set in `index.css`: a cooler, deeper ground, faintly
 * luminous hairlines, an instrument cyan accent, and a violet reserved for
 * model and inference state so "the model did this" never has to borrow the
 * interaction colour.
 *
 * The reference is a scientific instrument, not an arcade. What makes the
 * difference is restraint: a plotting field at 32px, drawn from the hairline
 * token so it moves with the palette instead of being a second literal, and a
 * single cool light falling from the top. Everything else — type, spacing,
 * elevation — stays exactly as it is on the rest of the platform, because a
 * page that changes its typography as well as its colour stops reading as the
 * same product.
 *
 * It stays dark under both themes on purpose, the way Xcode, Logic and Final
 * Cut keep a dark working canvas in Light. This is where plotted output and
 * live inference are read.
 *
 * What it must never touch: --bull, --bear, --gain and --loss keep their
 * platform meanings here, and service health has its own --ok / --degraded /
 * --failed so a control plane going red never reads as a price falling.
 * `design_tokens.test.ts` fails if the scoped block reaches the money tokens.
 */

import React from 'react';

export const InstrumentSurface: React.FC<{
  children: React.ReactNode;
  className?: string;
}> = ({ children, className = '' }) => (
  <div
    data-surface="ai"
    className={`relative min-h-full bg-base text-ink ${className}`}
  >
    {/* The plotting field. Fixed so the grid reads as the surface the content
        sits on rather than as a texture scrolling with it, and low enough in
        contrast that it never competes with a figure. */}
    <div
      aria-hidden
      className="pointer-events-none fixed inset-0 opacity-70"
      style={{ backgroundImage: 'var(--ai-grid)' }}
    />
    {/* One cool light from the top edge — the instrument's own illumination.
        A single source, not a gradient wash: the page should look lit, not
        painted. */}
    <div
      aria-hidden
      className="pointer-events-none fixed inset-x-0 top-0 h-64"
      style={{
        background:
          'radial-gradient(120% 100% at 50% 0%, var(--accent-soft) 0%, transparent 62%)',
      }}
    />
    <div className="relative">{children}</div>
  </div>
);
