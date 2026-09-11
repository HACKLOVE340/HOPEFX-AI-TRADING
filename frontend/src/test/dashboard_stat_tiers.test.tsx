/**
 * The stat row has three weights, and the weight says what kind of number it is.
 *
 * All eight tiles carried identical styling — same fill, same border, same
 * radius, same 18px figure — so nothing led the row and the eye had no reason
 * to start anywhere. The reference the owner brought does the opposite:
 * saturation and size carry the hierarchy, and the most important figure is the
 * most saturated thing on the screen.
 *
 * The tier encodes something true rather than decorating:
 *
 *   1  equity        the figure the screen exists to show
 *   2  money         balance and the two P&L tiles
 *   3  statistics    derived from closed trades, meaningless without them
 *
 * That last group is the one the same commit taught to render "—" when there
 * are no trades behind it, so its lighter weight and its em-dash are saying the
 * same thing.
 */

import React from 'react';
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const read = (relative: string): string =>
  readFileSync(join(dirname(fileURLToPath(import.meta.url)), '..', relative), 'utf8');

const dashboard = () => read('pages/Dashboard.tsx');
const css = () => read('index.css');

describe('every tile declares what kind of number it holds', () => {
  it('equity leads the row', () => {
    expect(dashboard()).toMatch(/label="Equity"[\s\S]{0,160}tier=\{1\}/);
  });

  it('balance and both P&L tiles are money', () => {
    const source = dashboard();
    for (const label of ['Balance', 'Daily P&L', 'Total P&L']) {
      expect(source).toMatch(new RegExp(`label="${label.replace('&', '&')}"[\\s\\S]{0,200}tier=\\{2\\}`));
    }
  });

  it('the four derived statistics step back', () => {
    const source = dashboard();
    for (const label of ['Win Rate', 'Sharpe', 'Account DD', 'Open Trades']) {
      expect(source).toMatch(new RegExp(`label="${label}"[\\s\\S]{0,200}tier=\\{3\\}`));
    }
  });

  it('no tile is left without one', () => {
    const source = dashboard();
    const row = source.slice(source.indexOf('<div style={s.statsGrid}>'), source.indexOf('Live Equity Curve'));
    const tiles = row.match(/<StatCard/g) ?? [];
    const tiers = row.match(/tier=\{[123]\}/g) ?? [];
    expect(tiles.length).toBe(8);
    expect(tiers.length).toBe(tiles.length);
  });
});

describe('the weight is carried by fill and size, not a second accent', () => {
  const block = () => css().slice(css().indexOf('.stat-tile {'));

  it('tier 1 is lifted onto the raised surface', () => {
    expect(block()).toMatch(/\.stat-tile\[data-tier="1"\][\s\S]{0,200}background: var\(--raised\)/);
  });

  it('tier 1 is given room, not just colour', () => {
    expect(block()).toMatch(/\.stat-tile\[data-tier="1"\][\s\S]{0,200}grid-column: span 2/);
    expect(block()).toMatch(/\.stat-tile\[data-tier="1"\] \.stat-tile-value \{ font-size: 24px/);
  });

  it('tier 3 recedes to a transparent fill and a quieter edge', () => {
    expect(block()).toMatch(/\.stat-tile\[data-tier="3"\][\s\S]{0,200}background: transparent/);
    expect(block()).toMatch(/\.stat-tile\[data-tier="3"\][\s\S]{0,200}border-color: var\(--hairline\)/);
  });

  it('tier 3 figures are smaller than the money above them', () => {
    expect(block()).toMatch(/\.stat-tile\[data-tier="3"\] \.stat-tile-value \{ font-size: 15px/);
  });

  it('the accent appears once, as an edge on the leading tile', () => {
    const matches = block().match(/var\(--accent\)/g) ?? [];
    expect(matches.length).toBe(1);
  });
});

describe('the tiles take their colours from tokens', () => {
  it('gain and loss read the money tokens', () => {
    const block = css().slice(css().indexOf('.stat-tile {'));
    expect(block).toContain('.stat-tile-value[data-tone="gain"] { color: var(--gain); }');
    expect(block).toContain('.stat-tile-value[data-tone="loss"] { color: var(--loss); }');
  });

  it('the eight new tokens are declared before anything uses them', () => {
    const source = css();
    const rootEnd = source.indexOf('}', source.indexOf(':root {'));
    const root = source.slice(0, rootEnd);
    for (const token of [
      '--text-strong', '--text-dim', '--hairline',
      '--surface-hover', '--link', '--gain', '--loss', '--warn',
    ]) {
      expect(root).toContain(token);
    }
  });

  it('the stat card no longer carries colours of its own', () => {
    const source = dashboard();
    const card = source.slice(source.indexOf('const StatCard'), source.indexOf('// ─── Price ticker'));
    expect(card.match(/#[0-9a-fA-F]{3,8}\b/g)).toBeNull();
  });

  it('figures line up in their columns', () => {
    // A stat row where the digits jog left and right as values change reads as
    // noisier than it is.
    const block = css().slice(css().indexOf('.stat-tile-value {'));
    expect(block).toContain('font-variant-numeric: tabular-nums');
  });
});
