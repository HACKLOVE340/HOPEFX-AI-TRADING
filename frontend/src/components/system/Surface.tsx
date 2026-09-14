/**
 * Surface — the one card in the system.
 *
 * Every colour, size, radius and shadow here comes from a token in
 * `src/index.css`, so a Surface is correct in dark, in light, and inside a
 * `data-surface="ai"` region without knowing which it is in. That is the whole
 * point of the layer: 8,006 inline literals across 201 files exist because
 * there was no component that could be trusted to get this right.
 *
 * `tone` spends border, fill and shadow BY ROLE rather than stamping one of
 * each on every block. A page with eight identical cards has no hierarchy;
 * lift the one that needs lifting and let the rest recede.
 */

import React from 'react';

export type SurfaceTone = 'default' | 'raised' | 'quiet' | 'accent';

const TONE: Record<SurfaceTone, string> = {
  // Ordinary panel: the resting state of nearly everything.
  default: 'bg-surface border border-edge shadow-e1',
  // Lifted: the one object on the screen that is being acted on.
  raised: 'bg-raised border border-edge-strong shadow-e2',
  // Receded: present, not competing. No shadow, hairline edge.
  quiet: 'bg-transparent border border-hairline',
  // Selected or primary: the accent earns its place once per screen.
  accent: 'bg-surface border border-accent shadow-e2',
};

interface SurfaceProps {
  children: React.ReactNode;
  tone?: SurfaceTone;
  className?: string;
  /** Renders a header band when given. */
  title?: React.ReactNode;
  /** Right-aligned secondary text in the header band. */
  aside?: React.ReactNode;
  /** Header id, so a region can be labelled by its own title. */
  titleId?: string;
  as?: 'section' | 'div' | 'article';
}

export const Surface: React.FC<SurfaceProps> = ({
  children,
  tone = 'default',
  className = '',
  title,
  aside,
  titleId,
  as: Tag = 'section',
}) => (
  <Tag className={`rounded-md2 overflow-hidden ${TONE[tone]} ${className}`}>
    {title !== undefined && (
      <div className="flex flex-wrap items-baseline justify-between gap-s3 border-b border-hairline px-card py-s3">
        <h2 id={titleId} className="text-label font-semibold uppercase text-dim">
          {title}
        </h2>
        {aside !== undefined && (
          <span className="font-mono text-micro tabular-nums text-faint">{aside}</span>
        )}
      </div>
    )}
    {children}
  </Tag>
);

/** Padded body for a Surface whose content is not a table. */
export const SurfaceBody: React.FC<{ children: React.ReactNode; className?: string }> = ({
  children,
  className = '',
}) => <div className={`p-card ${className}`}>{children}</div>;
