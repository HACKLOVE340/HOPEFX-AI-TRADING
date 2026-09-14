/**
 * A 403 from an admin-only endpoint is an answer, not an outage.
 *
 * `PresenceAnywhereMount` is mounted for EVERY authenticated user —
 * `{isAuth && <PresenceAnywhereMount />}` in App.tsx — and on mount it fetches
 * `/api/ai-core/capabilities/app`. That endpoint is `Depends(_viewer)`, and
 * `_VIEWER_ROLE = "admin"` (api/ai_core.py:51). So for every non-admin user, on
 * every page, the request is refused by design.
 *
 * The component treated the refusal as a load failure and rendered
 *
 *     "I could not load what I am allowed to do here (Error: HTTP 403)."
 *
 * in amber, permanently, to a user for whom nothing was broken. Measured in
 * Chromium signed in as a trader: /api/auth/me returned 200 over the same
 * cookie, so this was not a credential problem — the platform answered, and the
 * answer was "not you".
 *
 * The component's own docstring gives the rule this keeps: "a surface it could
 * not load is reported as unloaded, not as an empty one." A 403 IS loaded — the
 * platform stated the surface visible to this user, and it is empty. A timeout
 * or a 500 is not, and must still be reported. That is the distinction these
 * two tests hold apart; without the second one, "swallow the error" would pass.
 */
import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { PresenceAnywhereMount } from '../hub/PresenceAnywhereMount';

const mountWith = async (init: { ok: boolean; status: number }) => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({ ...init, json: async () => ({ capabilities: [] }) }),
  );
  await act(async () => {
    render(
      <MemoryRouter>
        <PresenceAnywhereMount />
      </MemoryRouter>,
    );
  });
  // "What I can read here" lives behind the collapsed panel. Asserting on the
  // closed overlay found the message in NEITHER case, so the 403 test passed
  // while measuring nothing — the shape this repository calls a control that
  // cannot fail. Open it, and assert the panel actually opened.
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: /open assistant/i })); });
  expect(screen.getByText(/what i can read here/i)).toBeTruthy();
};

afterEach(() => vi.unstubAllGlobals());

describe('the presence overlay tells a refusal from an outage', () => {
  it('says nothing is wrong when the platform refuses an admin-only surface', async () => {
    await mountWith({ ok: false, status: 403 });
    expect(screen.queryByText(/could not load what I am allowed to do/i)).toBeNull();
    // and says the true thing instead
    expect(screen.getByText(/nothing on this page is exposed to me/i)).toBeTruthy();
  });

  it('still reports a surface it genuinely could not load', async () => {
    await mountWith({ ok: false, status: 500 });
    expect(screen.queryByText(/could not load what I am allowed to do/i)).not.toBeNull();
  });
});
