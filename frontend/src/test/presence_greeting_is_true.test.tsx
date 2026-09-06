/**
 * The greeting must not go stale.
 *
 * Caught in the browser, not in a test. The panel greeted at mount with
 * "Nothing needs you", the AI Core summary then arrived reporting no reachable
 * vendor, and the caption changed to "I cannot answer" — while the transcript
 * still held the earlier line. The AI was on record saying something that had
 * stopped being true, beside a caption contradicting it.
 *
 * §5: "Never claim to have completed work that has not actually been
 * completed." The same rule applies to claiming a state nobody has checked.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { render } from '@testing-library/react';
import { PresencePanel } from '../components/ai/PresencePanel';
import { useStore } from '../store';

beforeEach(() => {
  useStore.setState({ wsStatus: 'connected', feedStale: false, aiJobs: {} });
});

describe('greeting', () => {
  it('says nothing until the inputs are real', () => {
    const { container } = render(<PresencePanel providersReachable={undefined} ready={false} />);
    // A greeting composed from defaults is a sentence about a system nobody has
    // looked at yet.
    expect(container.textContent).not.toMatch(/HOPEFX:/);
  });

  it('greets with what is actually true once they arrive', () => {
    const { container } = render(<PresencePanel providersReachable={0} ready />);
    expect(container.textContent).toMatch(/cannot answer/);
    expect(container.textContent).not.toMatch(/Nothing needs you/);
  });

  it('greets normally when everything is healthy', () => {
    const { container } = render(<PresencePanel providersReachable={3} ready />);
    expect(container.textContent).toMatch(/Nothing needs you/);
  });
});
