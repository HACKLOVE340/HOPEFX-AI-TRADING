# Frontend Audit Playbook

How to get a complete, honest picture of what is wrong with the HOPEFX
frontend — the pages, the state layer, the design, and whether any of it is
actually verified.

Companion to `docs/AUDIT_PLAYBOOK.md` (backend/engine). This one is not a copy:
frontend defects fail differently, and the questions that find them are
different.

---

## The surface you are auditing

| | |
|---|---|
| Pages | 69 (`src/pages/`) |
| Routes declared | 86 (`App.tsx`) |
| `.tsx` / `.ts` | 205 / 62 |
| Lines | ~89,000 |
| Tests | 1,242 across 40 files |
| Panels with an ErrorBoundary | ~8 of 128 (`withPanelGuard`, `PanelErrorBoundary`) |
| Files with a loading state | 37 of 128 |
| Files with any `aria-` attribute | 29 of 128 |

86 routes against 69 page files is itself a question worth asking (F10).

---

## Read this before you ask anything

Round 3 already ran two frontend slices (S9 correctness, S10 design). They found
real defects — the frozen-price illusion (S9-01), the confidence percentage that
never decays (S9-02), the "No open positions" false negative (S9-03) — and the
first and third are fixed.

**But that round carried an explicit, recorded limitation:**

> *"The 'run it' clause of this slice — pointing the dev server at a stopped
> backend and at one returning 500s, and recording what each view actually does
> — was **not performed**. The findings above are from reading the code."*
> — `docs/HARDENING_BACKLOG.md`, S9-03 verification note

That is the single biggest gap. Everything below is ordered so the runtime pass
comes first, because it ranks every other finding by real impact instead of by
grep coverage.

**The second thing to know:** across this codebase, every critical defect found
so far *failed silently upward* — logs, alerts and UI all reported success while
nothing happened. The frontend's version of that is a screen that looks healthy
and is lying. Ask questions that force the UI to prove it is telling the truth,
not questions that ask whether it renders.

---

## The four rules that made the backend audit work

1. **One slice per session.** A prompt that says "audit the frontend" produces a
   list of opinions. A prompt that says "audit what every view does when the
   backend returns 500" produces defects.
2. **Ask for the failure, not the feature.** "Does the order form work?" gets
   yes. "What does the order form do when the price feed is 4 minutes stale?"
   gets the bug.
3. **Demand evidence, not assurance.** Require a file:line, a reproduction, or a
   screenshot for every claim. Reject "looks correct".
4. **Ask what was *not* checked.** Every report should end with its own
   limitations. The S9-03 note above is why this rule exists.

---

## The slices

Run them in this order. F1 first is not optional — it re-ranks everything else.

### F1 — The runtime failure matrix ← **start here**

The pass that was skipped. Nothing else you do is as valuable.

> Run the frontend against a backend in each of these states and record what
> every top-level route actually renders: (a) backend not running at all,
> (b) backend returning 500 on every `/api/*` call, (c) backend up but the
> WebSocket never connects, (d) WebSocket connects then goes silent mid-session,
> (e) auth token expired. For each route, tell me exactly what a user sees:
> real data, a loading state that never resolves, an empty state that implies a
> meaningful zero, a blank screen, or a crash. Rank by consequence — a view that
> shows "no positions" when it cannot reach the broker is worse than a chart
> that fails to load. Give me the list ordered by what could cost money.

Why it matters: `PositionsTable` rendered "📭 No open positions" whenever the
positions array was empty — including when the socket was down. It read
identically whether the trader was flat or the client had no idea. That is the
class of defect only the runtime pass finds cheaply.

### F2 — Money-committing surfaces

The screens where a click moves capital.

> Audit every surface that can commit or move money: `OrderEntryForm`,
> `PositionsTable` close/close-all, `VoiceTradingPanel`, `CryptoCheckout`,
> `Wallet`, `PricingPage`. For each: can it double-submit? Does it confirm with
> the actual numbers (symbol, side, size, entry, stop, max loss) or just "are
> you sure?" What does it do when the price it is quoting is stale? What happens
> if the request times out — does the user learn whether the order went through?
> Can a user submit against a price that has since moved? Show me the code path
> for each answer.

### F3 — State, freshness, and the store

> `src/store/index.ts` is the single source of truth for prices, positions and
> account. For every field in it: what writes it, what reads it, and what
> happens when it goes stale? Find fields that are written and never read
> (`lastHeartbeat` was one), and fields that are read as if fresh but never
> expire. Then check the React Query layer separately: what are the
> `staleTime`/`refetchInterval` settings, and is any money-bearing query
> configured to serve cached data indefinitely?

### F4 — Routing, guards, and authorization

> There are 86 route declarations and four guard components (`AuthGuard`,
> `AdminGuard`, `SuperAdminGuard`, `SubscriptionGate`). Build a table: every
> route, the guard(s) wrapping it, and the role it should require. Flag any
> admin/superadmin/billing route that is reachable without the matching guard,
> any guard that renders its children before the check resolves, and any route
> that is declared but has no page file (or vice versa). Then tell me what a
> logged-out user sees at each protected route — a redirect, a flash of
> protected content, or an error.

The "flash of protected content" question matters: a guard that renders children
while loading leaks data for a frame.

### F5 — Numbers, money, and precision

> Audit every place a price, size, P&L, percentage or currency value is
> formatted or computed in the frontend. Look for: floating-point arithmetic on
> money, `toFixed` rounding that hides a real difference, percentages computed
> from already-rounded inputs, gold quoted with FX decimal conventions, P&L
> whose sign can be wrong for shorts, and any value displayed without units.
> Cross-check the display against what the backend actually sends for the same
> field.

Backend precedent: gold's pip is $0.10 and a contract is 100 oz, not FX's 0.0001
and 100,000 — that exact confusion was a real backtesting defect (S3).

### F6 — Loading, empty, and error states, triaged by consequence

> ~21% of components under `components/` and `pages/` render an error branch;
> 37 of 128 have a loading state. Do not give me a blanket sweep. Triage by
> consequence: list the views where an empty or missing state could be misread
> as a *meaningful* value — positions, open orders, account equity, risk limits,
> alerts, KYC status — and for each, tell me whether "couldn't load" is
> distinguishable from "nothing here". Everything else is cosmetic; say so and
> move on.

### F7 — Design and information hierarchy for a trading surface

Not visual taste — the duties a capital-committing UI owes its operator.

> Review the trading surfaces against what an operator needs to act safely: is
> the most decision-relevant number the most prominent one? Can a user tell at a
> glance whether the system is live, degraded, or halted? Is destructive action
> (close all) visually distinct from routine action? Are red/green the only
> carriers of long/short and P&L sign — and what does that mean for a
> colour-blind trader? Is there anywhere the UI implies more precision or more
> certainty than the data supports? Give me specific screens and specific fixes.

### F8 — Accessibility and input safety

> Only 29 of 128 component/page files use any `aria-` attribute. Audit keyboard
> operability of the money paths first: can an order be placed, confirmed and
> cancelled by keyboard alone? Are modals and confirm dialogs focus-trapped and
> escapable? Is any control operable only by hover or mouse? Then check whether
> any *destructive* control can be triggered by an accidental Enter on a focused
> element. Report the money-path issues separately from the general ones.

### F9 — Performance and behaviour under live ticks

> The app receives a continuous tick stream. Find what re-renders on every tick
> that should not: components subscribing to the whole store instead of a
> selector, effects with unstable dependency arrays, charts rebuilding their
> full dataset per update. Then tell me what happens over a long session — do
> any arrays or maps in the store grow without bound (ticks, signals, alerts,
> log lines)? Measure, don't guess: give me a profile or a render count.

### F10 — Dead pages and duplication

> 86 routes, 69 page files. Reconcile them: which routes point at nothing, which
> pages are unreachable, and which pages are near-duplicates of each other
> (`Trade.tsx` / `Trading.tsx` / `TradingDashboard.tsx`, `Dashboard.tsx` /
> `EliteDashboard.tsx`, several `*Dashboard` variants). For each duplicate pair,
> tell me which one the router actually serves and whether a fix applied to one
> was applied to the other.

Backend precedent: **every** duplicated pair in this codebase had already
produced a confirmed defect (S13-01). Assume the same holds here.

### F11 — Do the 1,242 tests assert anything?

Run this last, because it tells you how much to trust everything else.

> There are 1,242 frontend tests across 40 files. Sample the ones covering the
> money paths and the guards, and tell me: how many assert on *rendered output*
> versus merely that a component mounted without throwing? How many mock the
> thing they claim to test? Are there tests that would still pass if the
> component rendered nothing? Show me the worst five, with the assertion that is
> missing.

Backend precedent: nine separate tests were found *asserting the defective
behaviour* — including one that required the positions panel to claim "no open
positions" while the socket was disconnected, and one that required a mock auth
service to approve every login. Do not assume a green suite means a working app.

---

## How to phrase a request so it produces defects

**Weak → strong:**

| Instead of | Ask |
|---|---|
| "Is the frontend good?" | "What does each route render when every `/api/*` call returns 500?" |
| "Check the order form" | "How does the order form behave when the quoted price is 4 minutes stale?" |
| "Are there accessibility issues?" | "Can an order be placed, confirmed and cancelled by keyboard alone?" |
| "Review the design" | "Where does the UI imply more certainty than the data supports?" |
| "Are the tests good?" | "Which money-path tests would still pass if the component rendered nothing?" |

**Always append one of these:**

- "Show me file:line for every claim."
- "Rank by what could cost money, not by how many files are affected."
- "End with what you did **not** check and why."

**And when a report comes back clean:** ask *"what would have to be true for this
to be wrong?"* That question is what turned "the SL/TP tests pass" into
"the stop-loss never reached the broker".

---

## Suggested order and cadence

1. **F1** — runtime failure matrix (re-ranks everything)
2. **F2**, **F4** — money surfaces and authorization
3. **F3**, **F5** — state freshness and number correctness
4. **F6**, **F11** — states triaged by consequence, then test quality
5. **F7**, **F8**, **F9**, **F10** — design, a11y, performance, dead code

One slice per session. Fix what F1–F4 find before running F5 onward — the fixes
change what the later slices see, and this round proved that fixing one defect
routinely unmasks another that was hiding behind it.
