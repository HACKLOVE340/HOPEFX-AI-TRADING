/**
 * components/ui/withPanelGuard.tsx
 * HOC that wraps any panel with PanelErrorBoundary + React.Suspense + PanelSkeleton.
 * Use this on every lazy-loaded or data-fetching panel so a single panel crash
 * or loading state never affects the rest of the dashboard.
 *
 * Usage:
 *   export default withPanelGuard(MyPanel, 'My Panel');
 */

import React, { Suspense } from 'react';
import { PanelErrorBoundary } from './PanelErrorBoundary';
import { PanelSkeleton } from './Skeleton';

export function withPanelGuard<P extends object>(
  Component: React.ComponentType<P>,
  title?: string,
  skeletonRows = 4,
): React.FC<P> {
  const Guarded: React.FC<P> = (props) => (
    <PanelErrorBoundary title={title}>
      <Suspense fallback={<PanelSkeleton rows={skeletonRows} />}>
        <Component {...props} />
      </Suspense>
    </PanelErrorBoundary>
  );
  Guarded.displayName = `withPanelGuard(${title ?? Component.displayName ?? Component.name})`;
  return Guarded;
}
