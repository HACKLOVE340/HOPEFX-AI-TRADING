/**
 * F187 regression — dashboard metrics must be drill-downs, not a readout.
 *
 * The dashboard rendered 104 numbers and exactly ONE was clickable. A trader
 * seeing a win rate, a drawdown or an open P&L could not reach the trades,
 * the equity curve or the positions behind it. `/trade` (60 of 71 clickable)
 * was the only page in the product that did this properly.
 *
 * These tests pin the contract of the shared tile: it links when given a
 * destination, stays inert when not, and meets the interaction rules that
 * make a link usable (accessible name carrying the value, 44px target,
 * visible focus ring, colour-only hover).
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import fs from 'node:fs';
import path from 'node:path';
import { MetricTile } from '../components/ui/MetricTile';

const wrap = (ui: React.ReactNode) => render(<MemoryRouter>{ui}</MemoryRouter>);
const SRC = path.resolve(__dirname, '..');
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), 'utf-8');

describe('F187 — MetricTile drill-down contract', () => {
  it('renders a link when given a destination', () => {
    wrap(<MetricTile label="Win Rate" value="62.5%" to="/journal" toHint="the trades behind it" />);
    const link = screen.getByRole('link');
    expect(link).toHaveAttribute('href', '/journal');
  });

  it('names the metric AND its value in the accessible name', () => {
    // "Win Rate" alone tells a screen-reader user nothing about the number
    // they are activating, nor where it leads.
    wrap(<MetricTile label="Win Rate" value="62.5%" to="/journal" toHint="the trades behind it" />);
    const link = screen.getByRole('link');
    const name = link.getAttribute('aria-label') ?? '';
    expect(name).toContain('Win Rate');
    expect(name).toContain('62.5%');
    expect(name).toContain('the trades behind it');
  });

  it('stays an inert div with no destination', () => {
    // A tile that leads nowhere must not become an empty tab stop.
    const { container } = wrap(<MetricTile label="Spread" value="0.3" />);
    expect(container.querySelector('a')).toBeNull();
    expect(screen.queryByRole('link')).toBeNull();
  });

  it('meets the touch-target, cursor and focus-ring rules', () => {
    wrap(<MetricTile label="Equity" value="$100,000" to="/portfolio" toHint="Portfolio" />);
    const cls = screen.getByRole('link').className;
    expect(cls).toMatch(/min-h-\[44px\]/);        // 44x44 minimum target
    expect(cls).toMatch(/cursor-pointer/);
    expect(cls).toMatch(/focus-visible:ring-2/);  // keyboard users get an affordance
  });

  it('hovers with colour only, never a transform', () => {
    // A scale/translate on a tile inside a flex row nudges every neighbour on
    // each mouse-over.
    const cls = wrap(
      <MetricTile label="Equity" value="$1" to="/portfolio" />,
    ).container.querySelector('a')!.className;
    expect(cls).toMatch(/hover:bg-/);
    expect(cls).not.toMatch(/hover:scale|hover:translate/);
  });
});

describe('F187 — the dashboard panels are actually wired', () => {
  const panels: Array<[string, number]> = [
    ['components/terminal/AccountBar.tsx', 10],
    ['components/panels/RiskDashboard.tsx', 4],
    ['components/panels/MLModelPanel.tsx', 6],
    ['components/charts/EquityCurveChart.tsx', 9],
  ];

  it.each(panels)('%s wires at least %i tiles', (file, min) => {
    const hits = (read(file).match(/\bto="\//g) ?? []).length;
    expect(hits).toBeGreaterThanOrEqual(min);
  });

  it('every wired destination is a real route', () => {
    const routes = new Set(
      (read('App.tsx').match(/path="\/[a-z0-9-]*"/g) ?? [])
        .map((m) => m.slice(6, -1)),
    );
    for (const [file] of panels) {
      for (const m of read(file).matchAll(/toHint="[^"]*"|to="(\/[a-z0-9-]+)"/g)) {
        if (m[1]) expect(routes.has(m[1]), `${file} -> ${m[1]} is not a declared route`).toBe(true);
      }
    }
  });

  it('link copy does not repeat the verb ("open open positions")', () => {
    for (const [file] of panels) {
      for (const m of read(file).matchAll(/toHint="([^"]*)"/g)) {
        const hint = m[1] ?? '';
        expect(hint.toLowerCase().startsWith('open '), `${file}: "${hint}"`).toBe(false);
      }
    }
  });
});
