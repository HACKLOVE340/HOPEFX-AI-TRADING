# Dependabot remediation — 2026-07-27

Response to the 11 Dependabot alerts across `frontend/`, `dashboard/`, and
`mobile-app/`. Every fixable alert is fixed; the unfixable one (react-router,
no published patch) is analysed and mitigated where the app is actually exposed.

## Result by package

| Package | Alerts | Action | Status |
|---|---|---|---|
| brace-expansion | #306, #307, #326 | `overrides: "5.0.8"` in all three package.json | **Fixed** |
| postcss | #304 | frontend bumped `^8.5.14 → ^8.5.18` (resolves 8.5.23) | **Fixed** |
| @babel/core | #309 | dashboard `overrides: "7.29.7"` | **Fixed** |
| react-router / react-router-dom | #305, #320, #321, #322, #323, #325 | no published fix — see below | **Mitigated / N/A** |

Audit counts after remediation: frontend **11 → 2**, dashboard **11 → 2**,
mobile-app **54 → 0**. The remaining 2 in frontend/dashboard are react-router.

`brace-expansion@5.0.8` was the leaf of a large transitive chain (minimatch →
glob → jake/ejs/workbox/jest/the entire Expo+RN toolchain), so the single
override cleared dozens of downstream audit findings — 54 → 0 in mobile-app.

## react-router: why it isn't "fixed", and why most of it doesn't apply

The latest published `react-router-dom` is **7.18.1** — the version the frontend
already runs. There is **no forward-patched release**; npm's only suggested
"fix" is a downgrade to 7.11.0 (seven minors back), which would risk breaking a
production trading app for advisories that are largely inapplicable here.

This app is a **client-side SPA** (`BrowserRouter`, Vite, no SSR, no React
Server Components — verified: zero `renderToString`/`StaticRouter`/RSC usage).
Against that architecture:

- **#325 RSC CSRF, #321 RSCErrorHandler XSS, #320 SSR-hydration constructor
  injection, RSC portion of #305** — require React Server Components or SSR.
  **Not applicable**; those code paths do not execute in this app.
- **#323 DoS via inefficient route matching** — route matching runs in the
  user's own browser for a CSR SPA, so worst case is a self-inflicted tab hang,
  not a server outage. Severity is far lower than the server-side rating.
- **#322 open redirect via backslash in `<Link>`/`useNavigate`** — this one
  **is** exploitable in a SPA and this app had the surface: the login page
  redirects to a user-controlled `?next=` param. **Mitigated in code below.**

### Open-redirect mitigation (independent of react-router)

`Login.tsx` resolved its post-auth destination from `?next=` and passed it
straight to `navigate()`. `?next=//evil.com` or the backslash bypass
(`/\evil.com`) would have redirected off-site after login. Added
`isSafeRedirectPath()` (in `lib/utils.ts`): a destination is accepted only if it
is a single-leading-slash, same-origin path with no `//`, no backslash, and no
embedded scheme. Applied in `Login.resolveDestination`. This closes the
open-redirect regardless of when react-router ships a patch. Covered by unit
tests including the exact CVE-2025-68470 backslash payloads.

## Follow-up

Watch for a react-router-dom **7.18.2+** (or a 7.x backport) that clears the
DoS/redirect advisories, then drop the version pin. Until then the app is not
meaningfully exposed: the RSC/SSR advisories don't apply, the DoS is
client-side, and the open redirect is now guarded in application code.

## Verification

- `npm audit`: frontend 2 (react-router only), dashboard 2 (react-router only),
  mobile-app 0.
- frontend `tsc --noEmit` + `vite build` clean; vitest **1143/1143** (4 new
  redirect-guard tests + 5 symbol tests over the prior 1134).
- dashboard `tsc && vite build` clean (rebuilt `dist/` reverted — deploy
  regenerates it; only lockfiles are committed).
- Committed changes are limited to the six `package.json`/`package-lock.json`
  files plus the login open-redirect guard and its tests.
