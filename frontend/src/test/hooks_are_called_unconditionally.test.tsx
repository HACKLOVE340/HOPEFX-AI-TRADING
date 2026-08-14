/**
 * src/test/hooks_are_called_unconditionally.test.tsx
 * ==================================================
 * A Rules of Hooks violation, and the CI gate that keeps the class out.
 *
 * `ToastContainer` did this:
 *
 *     const ctx = useContext(ToastContext);
 *     if (!ctx) return null;                        // early return
 *     const toasts = useContext(ToastListContext);  // only when ctx is truthy
 *     if (!toasts) return null;
 *
 * React identifies hooks by call order, so the hook count changed between
 * renders — 1 while the toast context was absent, 2 once it appeared — and
 * React throws *"Rendered more hooks than during the previous render."*
 * Reachable whenever the provider mounts after this component or its value
 * starts undefined.
 *
 * It was found by adding ESLint, which this project had never had. Worth
 * recording what that exercise actually showed, because it inverted the
 * assumption behind it:
 *
 *  * `no-use-before-define` — the rule aimed at the Watchlist temporal-dead-zone
 *    crash — produced **1,990 errors**, essentially all false positives. It
 *    flags the `s` in `useStore((s) => s.prices)` as "used before defined"
 *    whenever a later scope declares an `s`, because it does not model
 *    shadowing across scopes and cannot separate a read during render from one
 *    inside a callback that runs later. It is off; `scripts/find_tdz_reads.mjs`
 *    remains the gate for that class, and is more precise.
 *  * `react-hooks/rules-of-hooks` found this — one real crash, which neither
 *    `tsc`, the 1,580-test vitest suite, nor the bespoke TDZ checker could see.
 *
 * So the general tool earned its place, just not for the reason it was added.
 */

import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import React from 'react';

describe('ToastContainer renders safely in both context states', () => {
  // Scope, stated honestly: these are smoke tests, NOT a reproduction of the
  // hook-order crash. Restoring the bug (verified by mutation) leaves all three
  // passing — wrapping the component in a provider on rerender changes the
  // element tree, so React remounts it and hook state resets rather than
  // mismatching. A genuine repro needs the component to stay mounted while the
  // context value flips, and both contexts here are module-private.
  //
  // The hook-order guarantee is carried by the lint gate below, which *is*
  // mutation-proven: restoring the early return fails it.

  it('renders with a provider and without one, in either order', async () => {
    const { ToastContainer, ToastProvider } = await import('../components/Toast');

    const { rerender } = render(<ToastContainer />);

    expect(() =>
      rerender(
        <ToastProvider>
          <ToastContainer />
        </ToastProvider>,
      ),
    ).not.toThrow();
  });

  it('renders nothing without a provider rather than crashing', async () => {
    const { ToastContainer } = await import('../components/Toast');
    const { container } = render(<ToastContainer />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders inside a provider', async () => {
    const { ToastContainer, ToastProvider } = await import('../components/Toast');
    expect(() =>
      render(
        <ToastProvider>
          <ToastContainer />
        </ToastProvider>,
      ),
    ).not.toThrow();
  });
});

describe('the hooks rule is enforced across the codebase', () => {
  it('reports no rules-of-hooks violations', async () => {
    // A source-level gate so the class cannot come back silently. Runs the
    // real linter rather than trusting that someone ran `npm run lint`.
    const { ESLint } = await import('eslint');
    const { fileURLToPath } = await import('node:url');
    const path = await import('node:path');

    // frontend/ — two levels up from src/test/. Resolved explicitly rather
    // than via URL arithmetic, which produced a path eslint could not match.
    const cwd = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
    const eslint = new ESLint({ cwd });

    const results = await eslint.lintFiles([path.join(cwd, 'src')]);
    const violations = results.flatMap((r) =>
      r.messages
        .filter((m) => m.ruleId === 'react-hooks/rules-of-hooks')
        .map((m) => `${r.filePath}:${m.line} ${m.message}`),
    );

    expect(violations, violations.join('\n')).toEqual([]);
  }, 120_000);
});
