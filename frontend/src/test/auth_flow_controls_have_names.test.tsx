/**
 * Every control in the sign-in → register → profile flow has an accessible
 * name, asserted by rendering it rather than by reading the source.
 *
 * F172. `jsx-a11y/control-has-associated-label` measured 138 violations, and
 * clearing an entry from `a11y-debt.json` means the RULE went quiet — which is
 * not the same claim as "a screen reader now gets a name". The rule cannot
 * resolve `<label htmlFor="x">` to `<input id="x">` at all (it inspects one
 * element's own props and children, `mayHaveAccessibleLabel.js`), so it is
 * silent on correct code and, in the other direction, silent on a button whose
 * only child is `{cond ? '…' : '📷'}` — an expression container it assumes
 * renders a label, and which renders an emoji.
 *
 * So the lint ratchet and this file assert different things on purpose:
 *   - `a11y_debt_is_accurate.test.ts` — the debt list still describes the tree.
 *   - this file — the names actually resolve, in a DOM, for these three pages.
 *
 * The Profile edit form is the one that was really broken: three
 * `<label style={s.label}>Display Name</label>` bound to nothing, over inputs
 * with no id. jsdom's accessible-name computation is what proves it, and these
 * assertions fail on the pre-fix tree.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import { useStore } from '../store';

vi.mock('../hooks/useWebSocket', () => ({ useWebSocket: vi.fn(() => ({ send: vi.fn() })) }));

vi.mock('../hooks/useApi', () => ({
  authApi: {
    login: vi.fn().mockResolvedValue({ data: {} }),
    register: vi.fn().mockResolvedValue({ data: {} }),
    me: vi.fn().mockResolvedValue({ data: {} }),
  },
  profileApi: {
    get: vi.fn().mockResolvedValue({
      data: {
        user_id: 'u1', username: 'trader1', display_name: 'Trader One',
        bio: 'Test bio', avatar_url: null, country: 'United States',
        joined_at: '2024-01-01T00:00:00Z',
        followers_count: 5, following_count: 3, is_following: false,
        stats: {}, strategies: [], recent_signals: [],
      },
    }),
    update: vi.fn().mockResolvedValue({ data: {} }),
    uploadAvatar: vi.fn().mockResolvedValue({ data: {} }),
    follow: vi.fn().mockResolvedValue({ data: {} }),
    unfollow: vi.fn().mockResolvedValue({ data: {} }),
  },
}));

const makeQC = () =>
  new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });

function wrap(element: React.ReactElement, path = '/') {
  return render(
    <QueryClientProvider client={makeQC()}>
      <MemoryRouter initialEntries={[path]}>
        <Routes><Route path="*" element={element} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  useStore.setState({
    token: 'tok',  // pragma: allowlist secret — vitest store fixture, literal "tok"
    user: { id: 'u1', email: 'a@b.com', username: 'trader1', role: 'trader' },
    isAuthenticated: true,
  } as never);
});

/** Every rendered form control, with the name the accessibility tree gives it. */
function namelessControls(container: HTMLElement): string[] {
  const controls = container.querySelectorAll('input, textarea, select');
  const bad: string[] = [];
  controls.forEach((el) => {
    const c = el as HTMLInputElement;
    if (c.type === 'hidden') return;
    const labelled =
      c.getAttribute('aria-label')?.trim() ||
      (c.getAttribute('aria-labelledby') ?? '')
        .split(/\s+/)
        .filter(Boolean)
        .map((id) => container.ownerDocument.getElementById(id)?.textContent?.trim() ?? '')
        .join(' ')
        .trim() ||
      (c.id ? container.ownerDocument.querySelector(`label[for="${c.id}"]`)?.textContent?.trim() : '') ||
      c.closest('label')?.textContent?.trim();
    if (!labelled) bad.push(`<${c.tagName.toLowerCase()}${c.id ? ` id="${c.id}"` : ''}${c.name ? ` name="${c.name}"` : ''}>`);
  });
  return bad;
}

describe('auth flow — accessible names', () => {
  it('Login names every field', async () => {
    const Login = (await import('../pages/Login')).default;
    const { container } = wrap(<Login />);
    expect(screen.getByLabelText(/email or username/i)).toBeTruthy();
    expect(screen.getByLabelText(/^password$/i)).toBeTruthy();
    expect(namelessControls(container)).toEqual([]);
  });

  it('Register names every field', async () => {
    const Register = (await import('../pages/Register')).default;
    const { container } = wrap(<Register />);
    await waitFor(() => expect(screen.getByLabelText(/^email$/i)).toBeTruthy());
    expect(screen.getByLabelText(/^username$/i)).toBeTruthy();
    expect(screen.getByLabelText(/^password$/i)).toBeTruthy();
    expect(screen.getByLabelText(/confirm password/i)).toBeTruthy();
    expect(namelessControls(container)).toEqual([]);
  });

  it('Profile names the edit form and the avatar upload', async () => {
    const Profile = (await import('../pages/Profile')).default;
    const { container } = wrap(<Profile />);

    await waitFor(() => expect(screen.getByText('Edit Profile')).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: /edit profile/i }));

    // The three that were bound to nothing.
    await waitFor(() => expect(screen.getByLabelText(/display name/i)).toBeTruthy());
    expect(screen.getByLabelText(/^bio$/i)).toBeTruthy();
    expect(screen.getByLabelText(/^country$/i)).toBeTruthy();

    // The hidden file input, and the icon-only button that opens it — the
    // shape F172 is named after, and the one the lint rule cannot see.
    expect(screen.getByLabelText(/upload a new avatar image/i)).toBeTruthy();
    expect(screen.getByRole('button', { name: /change avatar/i })).toBeTruthy();

    expect(namelessControls(container)).toEqual([]);
  });
});
