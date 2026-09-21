/**
 * 64 switches on this platform had no accessible name.
 *
 * `pages/superadmin/ui.tsx` exports `Toggle`, used 64 times across every
 * Settings and Super Admin section. It renders:
 *
 *     <label>
 *       <div>{label}</div>
 *       <div role="switch" aria-checked={checked} tabIndex={0} … />
 *     </label>
 *
 * which LOOKS labelled and is not. A `<label>` implicitly labels only
 * *labelable* elements — input, select, textarea, button, meter, output,
 * progress. A `div[role="switch"]` is none of those, so the wrapper gives it
 * no accessible name at all: a screen reader announces "switch, off" with
 * nothing to say what it switches. On the Super Admin panel that includes
 * toggles that change how the platform trades.
 *
 * eslint had been reporting this for as long as the a11y debt list existed,
 * filed under "known limitations of one rule". Seventeen of that rule's
 * eighteen findings genuinely ARE its blind spot — a control correctly wrapped
 * in a `<label>`, or paired by `htmlFor`, which this rule cannot see because it
 * only looks DOWN into a control's own children. This one was the real defect
 * hiding among them, and it was found by checking each rather than by
 * accepting the label on the list.
 *
 * The name comes from `aria-labelledby` pointing at the element that already
 * renders the visible text — never a duplicated `aria-label` string, which is
 * free to drift away from what is on screen and then lies with confidence.
 */
import React from 'react';
import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, cleanup } from '@testing-library/react';

import { Toggle } from '../pages/superadmin/ui';

afterEach(() => cleanup());

describe('the switch says what it switches', () => {
  it('takes its accessible name from the visible label', () => {
    render(<Toggle label="Auto-heal enabled" checked={false} onChange={() => {}} />);
    expect(screen.getByRole('switch', { name: 'Auto-heal enabled' })).toBeTruthy();
  });

  it('names it with the SAME node the eye reads, not a copy of the string', () => {
    render(<Toggle label="Auto-heal enabled" checked={false} onChange={() => {}} />);
    const sw = screen.getByRole('switch');
    // An aria-label would pass the test above and still be free to drift.
    expect(sw.getAttribute('aria-label')).toBeNull();
    const id = sw.getAttribute('aria-labelledby');
    expect(id).toBeTruthy();
    expect(document.getElementById(id as string)?.textContent).toBe('Auto-heal enabled');
  });

  it('describes it from the visible description when there is one', () => {
    render(
      <Toggle
        label="Auto-heal enabled"
        description="Patches are applied without review"
        checked
        onChange={() => {}}
      />,
    );
    const sw = screen.getByRole('switch');
    const id = sw.getAttribute('aria-describedby');
    expect(id).toBeTruthy();
    expect(document.getElementById(id as string)?.textContent).toBe(
      'Patches are applied without review',
    );
  });

  it('claims no description when there is none to point at', () => {
    render(<Toggle label="Auto-heal enabled" checked={false} onChange={() => {}} />);
    expect(screen.getByRole('switch').getAttribute('aria-describedby')).toBeNull();
  });

  it('still reports its state', () => {
    render(<Toggle label="Kill switch" checked onChange={() => {}} />);
    expect(screen.getByRole('switch').getAttribute('aria-checked')).toBe('true');
  });

  it('tells assistive tech it is disabled, not only the tab order', () => {
    render(<Toggle label="Kill switch" checked={false} disabled onChange={() => {}} />);
    const sw = screen.getByRole('switch');
    expect(sw.getAttribute('aria-disabled')).toBe('true');
    expect(sw.getAttribute('tabindex')).toBe('-1');
  });

  it('is not marked disabled when it is not', () => {
    render(<Toggle label="Kill switch" checked={false} onChange={() => {}} />);
    expect(screen.getByRole('switch').getAttribute('aria-disabled')).toBeNull();
  });

  it('gives two toggles on one page two different label ids', () => {
    render(
      <>
        <Toggle label="First" checked={false} onChange={() => {}} />
        <Toggle label="Second" checked={false} onChange={() => {}} />
      </>,
    );
    const switches = screen.getAllByRole('switch');
    expect(switches).toHaveLength(2);
    const ids = switches.map((s) => s.getAttribute('aria-labelledby'));
    expect(new Set(ids).size).toBe(2);
    expect(screen.getByRole('switch', { name: 'First' })).toBeTruthy();
    expect(screen.getByRole('switch', { name: 'Second' })).toBeTruthy();
  });
});
