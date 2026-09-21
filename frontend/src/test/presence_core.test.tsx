/**
 * The presence on screen.
 *
 * The canvas is decorative — it is `aria-hidden`, and everything it expresses is
 * also expressed in text. That is not a concession to accessibility; it is the
 * same rule the rest of this codebase follows, that colour and motion are never
 * the only carrier of meaning (§27), and it is what makes the presence usable
 * with the sound off, with a screen reader, or with reduced motion on.
 *
 * The caption is load-bearing for a second reason: it is the same sentence the
 * AI speaks. One string, three consumers — spoken audio, visible caption,
 * screen-reader announcement — so they cannot drift apart.
 */

import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { PresenceCore } from '../hub/PresenceCore';
import { PRESENCE_STATES, derivePresence, type PresenceInputs } from '../hub/presence';

const calm: PresenceInputs = {
  wsStatus: 'connected', feedStale: false, micOpen: false, speaking: false,
  jobsRunning: 0, jobsQueued: 0, riskHeadroom: 0.68, alert: null, providersReachable: 3,
};

describe('everything the canvas says is also said in text', () => {
  it('shows the reason as a caption', () => {
    render(<PresenceCore presence={derivePresence(calm)} />);
    expect(screen.getByText(/Nothing needs you/)).toBeTruthy();
  });

  it('announces state changes politely rather than interrupting', () => {
    render(<PresenceCore presence={derivePresence(calm)} />);
    const live = screen.getByRole('status');
    expect(live.getAttribute('aria-live')).toBe('polite');
  });

  it('hides the canvas from assistive technology', () => {
    // It is decoration. The text beside it is the real content.
    const { container } = render(<PresenceCore presence={derivePresence(calm)} />);
    const canvas = container.querySelector('canvas');
    expect(canvas).toBeTruthy();
    expect(canvas?.getAttribute('aria-hidden')).toBe('true');
  });

  it('names the state in words, never only in colour', () => {
    render(<PresenceCore presence={derivePresence({ ...calm, feedStale: true })} />);
    expect(screen.getByText(/degraded/i)).toBeTruthy();
  });

  it('gives the whole presence an accessible name', () => {
    render(<PresenceCore presence={derivePresence(calm)} />);
    expect(screen.getByLabelText(/presence/i)).toBeTruthy();
  });
});

describe('every state the machine can produce, renders', () => {
  it.each(PRESENCE_STATES)('renders %s without crashing and labels it', (state) => {
    const presence = { state, reason: `reason for ${state}`, tone: 'ok' as const, intensity: 0.5, headroomKnown: true };
    render(<PresenceCore presence={presence} />);
    expect(screen.getByText(`reason for ${state}`)).toBeTruthy();
  });
});

describe('risk headroom', () => {
  it('shows the headroom when it is known', () => {
    render(<PresenceCore presence={derivePresence(calm)} />);
    expect(screen.getByText('68%')).toBeTruthy();
  });

  it('says unknown rather than drawing a full ring for a number nobody has', () => {
    render(<PresenceCore presence={derivePresence({ ...calm, riskHeadroom: null })} />);
    expect(screen.queryByText('100%')).toBeNull();
    expect(screen.getByText('Not measured')).toBeTruthy();
    expect(screen.getByText('—')).toBeTruthy();
  });
});

describe('reduced motion', () => {
  it('keeps the numbers when the animation is off', () => {
    // The failure mode to avoid: reduced motion removing the animation AND the
    // information the animation was carrying.
    render(<PresenceCore presence={derivePresence(calm)} reducedMotion />);
    expect(screen.getByText('68%')).toBeTruthy();
    expect(screen.getByText(/Nothing needs you/)).toBeTruthy();
  });
});
