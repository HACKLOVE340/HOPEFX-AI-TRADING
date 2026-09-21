/**
 * The flag that decides what the AI Core page opens on.
 *
 * Decision D2, revised: the presence lives inside the existing page rather than
 * beside it. A flag that only works in one position is not a flag, so both
 * positions are pinned here — and the "off" case matters more, because it is
 * what protects every operator who has not opted in.
 */

import { describe, it, expect, afterEach } from 'vitest';
import { hubEnabled } from '../hub/flag';

afterEach(() => {
  delete (import.meta.env as Record<string, unknown>).VITE_HUB_ENABLED;
});

describe('the presence flag', () => {
  it('is off unless it is switched on', () => {
    delete (import.meta.env as Record<string, unknown>).VITE_HUB_ENABLED;
    expect(hubEnabled()).toBe(false);
  });

  it('is on for the literal string true', () => {
    (import.meta.env as Record<string, unknown>).VITE_HUB_ENABLED = 'true';
    expect(hubEnabled()).toBe(true);
  });

  it.each(['false', '0', '', 'yes-please', 'TRUE ', '1'])('treats %o as off', (value) => {
    // A typo must fail toward the status board, which works today.
    (import.meta.env as Record<string, unknown>).VITE_HUB_ENABLED = value;
    expect(hubEnabled()).toBe(false);
  });
});
