/**
 * F4 — routing, guards, and authorization.
 *
 * docs/FRONTEND_AUDIT_PLAYBOOK.md slice F4. The question it emphasises:
 *
 *   > "a guard that renders children while loading leaks data for a frame"
 *
 * The four guards are `AuthGuard`, `AdminGuard`, `SuperAdminGuard` and
 * `SubscriptionGate`, composed in `App.tsx` through three helpers —
 * `gated()`, `adminOnly()`, `superAdminOnly()` — each of which wraps the inner
 * guard in `AuthGuard`. Three of the four are only safe *because* of that
 * nesting, and nothing enforced it:
 *
 *   SuperAdminGuard   `if (!user) return <spinner/>`   → a logged-out visitor
 *   SubscriptionGate  `if (!user) return <spinner/>`      sees a spinner that
 *                                                          never resolves
 *   AdminGuard        `if (isAuth && !user)` → spinner  → but with `isAuth`
 *                                                          false and a persisted
 *                                                          user it falls through
 *                                                          to the role check
 *
 * None of those is reachable through `App.tsx` today. They are one careless
 * `<AdminGuard>` away from being reachable, so the composition is pinned here
 * rather than left as a property of how someone happened to write the routes.
 *
 * The route/page reconciliation came back clean and is recorded rather than
 * tested: 70 lazy route components, every one resolving to a real file, and no
 * top-level page in `src/pages` without a route.
 */

import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

import { useStore } from '../store';
import AdminGuard from '../components/AdminGuard';
import SuperAdminGuard from '../components/SuperAdminGuard';
import SubscriptionGate from '../components/SubscriptionGate';

const SECRET = 'PROTECTED-CONTENT';

const at = (path: string, ui: React.ReactElement) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/login" element={<div>LOGIN PAGE</div>} />
        <Route path="*" element={ui} />
      </Routes>
    </MemoryRouter>,
  );

const loggedOut = () =>
  useStore.setState({ isAuthenticated: false, user: null, token: null } as never);

const as = (role: string, plan = 'free') =>
  useStore.setState({
    isAuthenticated: true,
    token: 'tok',
    user: { id: 'u1', email: 'a@b.c', role, plan } as never,
    plan,
  } as never);

describe('guards never render protected content to a logged-out visitor — F4', () => {
  beforeEach(() => { loggedOut(); vi.restoreAllMocks(); });

  it('AdminGuard does not render children', async () => {
    at('/admin', <AdminGuard><div>{SECRET}</div></AdminGuard>);
    await waitFor(() => expect(screen.queryByText(SECRET)).toBeNull());
  });

  it('SuperAdminGuard does not render children', async () => {
    at('/master-control', <SuperAdminGuard><div>{SECRET}</div></SuperAdminGuard>);
    await waitFor(() => expect(screen.queryByText(SECRET)).toBeNull());
  });

  it('SubscriptionGate does not render children', async () => {
    at('/wallet', <SubscriptionGate featureKey="wallet"><div>{SECRET}</div></SubscriptionGate>);
    await waitFor(() => expect(screen.queryByText(SECRET)).toBeNull());
  });
});

describe('guards do not leak content while the role is still unknown — F4', () => {
  beforeEach(() => {
    // Authenticated, but /me has not come back yet: this is the frame the
    // playbook is asking about.
    useStore.setState({ isAuthenticated: true, token: 'tok', user: null } as never);
  });

  it('AdminGuard shows a spinner, not the page', () => {
    at('/admin', <AdminGuard><div>{SECRET}</div></AdminGuard>);
    expect(screen.queryByText(SECRET)).toBeNull();
  });

  it('SuperAdminGuard shows a spinner, not the page', () => {
    at('/master-control', <SuperAdminGuard><div>{SECRET}</div></SuperAdminGuard>);
    expect(screen.queryByText(SECRET)).toBeNull();
  });

  it('SubscriptionGate shows a spinner, not the upgrade wall or the page', () => {
    at('/wallet', <SubscriptionGate featureKey="wallet"><div>{SECRET}</div></SubscriptionGate>);
    expect(screen.queryByText(SECRET)).toBeNull();
    expect(screen.queryByText(/plan required/i)).toBeNull();
  });
});

describe('guards admit the right roles — F4', () => {
  it('AdminGuard admits an admin', () => {
    as('admin');
    at('/admin', <AdminGuard><div>{SECRET}</div></AdminGuard>);
    expect(screen.getByText(SECRET)).toBeTruthy();
  });

  it('AdminGuard refuses a trader', () => {
    as('trader');
    at('/admin', <AdminGuard><div>{SECRET}</div></AdminGuard>);
    expect(screen.queryByText(SECRET)).toBeNull();
    expect(screen.getByText(/admin access required/i)).toBeTruthy();
  });

  it('SuperAdminGuard refuses an admin', () => {
    as('admin');
    at('/master-control', <SuperAdminGuard><div>{SECRET}</div></SuperAdminGuard>);
    expect(screen.queryByText(SECRET)).toBeNull();
    expect(screen.getByText(/insufficient privilege/i)).toBeTruthy();
  });

  it('SuperAdminGuard admits a superadmin', () => {
    as('superadmin');
    at('/master-control', <SuperAdminGuard><div>{SECRET}</div></SuperAdminGuard>);
    expect(screen.getByText(SECRET)).toBeTruthy();
  });
});

// ── The composition in App.tsx is the thing keeping three of these safe ──────

describe('App.tsx wraps every privileged route in AuthGuard — F4', () => {
  const read = async () => {
    const fs = await import('node:fs');
    const path = await import('node:path');
    return fs.readFileSync(path.resolve(process.cwd(), 'src/App.tsx'), 'utf8');
  };

  it.each(['adminOnly', 'superAdminOnly', 'gated'])(
    '%s() nests its guard inside AuthGuard',
    async (helper) => {
      const src = await read();
      const body = src.slice(src.indexOf(`const ${helper} =`));
      const decl = body.slice(0, body.indexOf('\n);') + 3);
      expect(
        decl.includes('<AuthGuard>'),
        `${helper}() does not wrap in AuthGuard. AdminGuard, SuperAdminGuard and ` +
          `SubscriptionGate each assume a resolved session; without AuthGuard a ` +
          `logged-out visitor gets a spinner that never resolves, or worse (F4).`,
      ).toBe(true);
    },
  );

  it('every route element using a raw privileged guard goes through a helper', async () => {
    const src = await read();
    const routes = src.match(/<Route\b[^>]*?\/>/gs) ?? [];
    const raw = routes.filter(
      (r) => /<(AdminGuard|SuperAdminGuard|SubscriptionGate)\b/.test(r) && !/<AuthGuard\b/.test(r),
    );
    expect(raw, `privileged guard used without AuthGuard:\n${raw.join('\n')}`).toEqual([]);
  });
});

// ── F4-01 ────────────────────────────────────────────────────────────────────

/**
 * `/profile/:id` is the one account route declared with no guard at all:
 *
 *   App.tsx:606   <Route path="/profile"     element={wrap(gated('profile', <Profile />))} />
 *   App.tsx:607   <Route path="/profile/:id" element={wrap(<Profile />)} />
 *
 * Public viewing of *another* trader's profile is deliberate — `Leaderboard`
 * and `Marketplace` are public previews by the same design, and the comment at
 * App.tsx:588 says so. The defect is that `Profile` decides which view to show
 * from the URL:
 *
 *   Profile.tsx:32   const isOwn = !id || id === 'me' || id === currentUser?.id;
 *
 * So `/profile/me` resolves to `isOwn === true` — the full own-profile view,
 * edit controls included, calling `profileApi.get(undefined)` exactly as the
 * gated route does — at a URL carrying neither `AuthGuard` nor the `profile`
 * subscription gate.
 *
 * The subscription gate is enforced only on the client, so this is a complete
 * bypass of it: a user whose plan does not include `profile` types six extra
 * characters and gets the page. Whether data also reaches an anonymous visitor
 * depends on the server rejecting the call — which is the right place for that
 * check, and is not something the routing table gets to assume.
 */
describe('F4-01 — /profile/me must not bypass the gate on /profile', () => {
  const renderProfileAt = async (path: string) => {
    const { default: Profile } = await import('../pages/Profile');
    return render(
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          {/* Stands in for the real gated route, so a redirect to /profile is
              observable as "you were sent through the gate". */}
          <Route path="/profile" element={<div>GATED PROFILE ROUTE</div>} />
          <Route path="/profile/:id" element={<Profile />} />
        </Routes>
      </MemoryRouter>,
    );
  };

  beforeEach(() => as('user', 'free'));

  it('/profile/me redirects to the guarded route', async () => {
    await renderProfileAt('/profile/me');
    await waitFor(() => expect(screen.getByText('GATED PROFILE ROUTE')).toBeTruthy());
  });

  it("/profile/<own id> redirects to the guarded route", async () => {
    await renderProfileAt('/profile/u1');
    await waitFor(() => expect(screen.getByText('GATED PROFILE ROUTE')).toBeTruthy());
  });

  it('another trader\'s profile is still viewable at /profile/:id', async () => {
    // The public-preview behaviour is deliberate (App.tsx:588) and must survive.
    const { container } = await renderProfileAt('/profile/someone-else');
    expect(screen.queryByText('GATED PROFILE ROUTE')).toBeNull();
    expect(container.textContent ?? '').not.toBe('');
  });

  it('does not spend a request on a view it is about to replace', async () => {
    // The fetch that would have run is the own-profile call the gated route
    // makes — the exact thing this route must not be able to reach.
    const get = vi.fn(async () => ({ data: {} }));
    vi.resetModules();
    vi.doMock('../hooks/useApi', async () => {
      const actual = await vi.importActual<Record<string, unknown>>('../hooks/useApi');
      return { ...actual, profileApi: { ...(actual.profileApi as object), get } };
    });
    const { default: Profile } = await import('../pages/Profile');
    const { useStore: freshStore } = await import('../store');
    freshStore.setState({
      isAuthenticated: true, token: 'tok',
      user: { id: 'u1', email: 'a@b.c', role: 'user', plan: 'free' },
    } as never);

    render(
      <MemoryRouter initialEntries={['/profile/me']}>
        <Routes>
          <Route path="/profile" element={<div>GATED PROFILE ROUTE</div>} />
          <Route path="/profile/:id" element={<Profile />} />
        </Routes>
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByText('GATED PROFILE ROUTE')).toBeTruthy());
    expect(get).not.toHaveBeenCalled();
  });
});
