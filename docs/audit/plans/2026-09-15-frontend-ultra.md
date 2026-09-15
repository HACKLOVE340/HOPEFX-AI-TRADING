# HOPEFX Ultra Front-End Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement
> this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every page show more, route better and feel like a professional
trading instrument — without removing anything that is on screen today.

**Architecture:** Three layers, in order. (1) A token layer that already exists
and now carries a gold-anchored palette and a user-chosen density. (2) A set of
page *enrichment rules* applied per page archetype, so improvement is a rule
rather than 74 opinions. (3) Three new surfaces built on backend APIs that are
already shipped and currently have no UI at all.

**Tech Stack:** React 18 + TypeScript + Vite, Tailwind over CSS custom
properties, Zustand, TanStack Query, lucide-react, Vitest + Testing Library,
Playwright for runtime proof.

**Spec:** This document is both spec and plan. The design decisions in §2 were
approved by the owner on 2026-09-15 against two prototypes:
`claude.ai/artifact/XPEztmcXuS7XLgxaYWjRGK` (palette) and
`claude.ai/artifact/51F1drxYhU8BFZfCFhc2pq` (all 66 destinations).

---

## Global Constraints

Copied verbatim from the owner's instructions and `CLAUDE.md`. Every task
inherits these.

1. **Nothing is removed.** No page loses a section, a control, a figure or a
   route. Every task is additive or a replacement-in-place. A task that deletes
   user-visible content is a failed task, not a trade-off.
2. **Never weaken a risk gate, kill switch, or staleness/drift check.**
3. **Every fix ships with a test that fails on the pre-fix tree.** Run it against
   the old code and watch it fail.
4. **Prove by execution, not by reading.** Reproduce in a browser before and
   after.
5. **Do not commit with `--no-verify`.** `pre-commit run --all-files` is the gate.
6. **Documentation ships with every push.** If a figure changes, the document
   that states it changes in the same commit.
7. Density tiers are `comfortable` | `promax` | `ultra`. Ultra is the default.
8. Motion budget: **one orchestrated entrance per view, plus state-change
   signalling.** Data never animates while it is being read.
9. Colour comes from tokens. No new hex literal in a component — the ratchet
   (`scripts/frontend_colour_ratchet.py`) blocks it.
10. No emoji as an icon. Lucide only (`scripts/frontend_emoji_ratchet.py`).

---

## Part 0 — The measured baseline

Counted from source on 2026-09-15 by `node /tmp/pageaudit.mjs`, over the 74
page components the router mounts. This is what "how each page was designed"
actually looks like, rather than an impression.

| Finding | Count | What it means |
|---|---:|---|
| Routed page components | 74 | |
| **Call no API at all** | **26** | Of these, ~7 are static by nature (legal, docs, landing, 404, onboarding, mobile shell). **The other ~19 are data pages with no data** — this is why pages "don't show anything". |
| Under 150 LOC | 6 | `AIAssistant` (52), `SystemReliability` (83), `NuclearDashboardPage` (96), `Hub` (115), `NewsSentiment` (117), `Transparency` (139) |
| On `PageShell` | 49 of 63 | 14 still off the standard frame |
| Destinations with no description | 8 → **0** | Fixed 2026-09-15; the gap was `/dashboard /trade /portfolio /watchlist /alerts /terminal /journal /settings` |

**The single most important number is 26.** A page that renders a heading and
nothing else is not a design problem, it is an empty page. Enrichment rules
(§3) are worthless applied to a page with no data behind it, so Task 6 wires
data *before* Task 7 dresses it.

### Backend already built, no UI

Found by grepping the router registry against frontend consumers:

| API | Endpoints | Frontend consumer |
|---|---|---|
| `api/community_chat.py` | `/api/chat/rooms`, `/rooms/{id}/messages`, **plus a WebSocket router** | **none** |
| `api/news_feed.py` | `/feed`, `/nuclear-score`, `/calendar` | `NewsSentiment` only (117 LOC) |
| `api/social_feed.py` | `/{id}/react`, `/comment`, `/opt-in` | `SocialFeed` only |

The AI room and the community news wall are therefore **mostly a front-end
job**. That is why they are in this plan rather than in a backlog: the
expensive half is done.

---

## Part 1 — What is already landed

Committed on `claude/add-new-skills-lys862` before this plan:

- `f5daf6da` — voice no longer reads Markdown aloud (`speechText`)
- `37c0c758` — four test failures, three older than the change that exposed them
- `6200ccad` — three audited defects (chat history isolation, model age, agent deadline)

Uncommitted, complete, tests green (these become **Task 1**):

- Instrument palette in `index.css`, both themes, every pair contrast-measured
- `AppBackground` tokenised — light mode no longer shows a dark ground
- Density default flipped to `ultra`, `ULTRA` list kept as a precedence rule
- Support launcher: Lucide icons, no emoji
- Sidebar claims a lane so the presence panel stops covering the navigation
- The 8 missing nav descriptions written

---

## Part 2 — Design decisions (locked)

### 2.1 Palette — "Instrument"

Gold-anchored, because the platform trades gold. Every pair measured with the
WCAG formula before it reached a screen: **22 pairs per theme, 0 below target**,
against 686 light-mode failures in the palette it replaces.

| Role | Dark | Light |
|---|---|---|
| ground / surface / raised | `#05070d` / `#0a0e18` / `#0f1523` | `#f6f7fa` / `#ffffff` / `#ffffff` |
| text-strong / text / dim | `#f7f9fc` / `#dbe3ee` / `#93a1b5` | `#0b1220` / `#1f2937` / `#4a5768` |
| accent | `#f0b429` | `#8a5a00` |
| gain / loss | `#3ddc97` / `#ff5c6c` | `#047857` / `#b91c1c` |

Semantic colour (gain/loss/warn) is separate from the accent, so nothing reads
as profit merely by being the brand colour.

### 2.2 Density — user-controlled, Ultra default

**Owner decision, 2026-09-15.** The three tiers already exist in `index.css` and
are already stamped on every route by `PageSurface`. The change is to let the
person choose, defaulting to Ultra.

Resolution order, highest first:
1. `ULTRA` route list — data surfaces are always dense (order books, ledgers,
   audit trails). A user preference cannot loosen these; seeing three more rows
   of open risk is not a taste question.
2. The user's stored preference.
3. `COMFORTABLE` route list — prose pages.
4. Default: `ultra`.

### 2.3 Motion — precision, plus an ambient layer

**Owner decision, 2026-09-15.** Two parts, deliberately separated so the second
can be switched off without touching the first.

**Precision (always on):**
- One orchestrated entrance per view — 160 ms, `ease-out`, 8 px rise, staggered
  by 25 ms across at most the first row. Never on data rows.
- Tick flash on price change: 400 ms background wash, gain/loss tinted.
- Confirmation on a state change that matters — order accepted, order refused,
  gate tripped.
- Skeletons that match the final layout exactly, so nothing jumps on arrival.

**Ambient (on by default, one switch in Settings → Appearance):**
- The `AppBackground` aurora, already present, now theme-aware.
- An idle "breathing" pulse on the AI room presence when models are active.

**What does not animate, ever:** a number while it is being read, a table row on
hover, anything behind `prefers-reduced-motion: reduce`.

Grounded in the UX guidance the tools returned: *"Animate 1-2 key elements per
view maximum"* (severity High) and *"Check prefers-reduced-motion"* (High).
Animating everything is how a terminal becomes unreadable; this is how it
becomes alive.

### 2.4 Elevation — the round-edge rule

The owner's note — *"some of the round edge to be transparent"* — is correct and
becomes a rule:

> Border, fill, radius and shadow each say **"this is a separate object."**
> Spend them by role, not by habit.

- **Two radii only:** `6px` for objects that sit on the page, `99px` for pills.
- **Border only where an object truly separates.** A tile inside a card does not
  get its own border — it gets a hairline, or nothing.
- **No nested cards.** A card inside a card is one border too many; the inner
  one becomes a plain region on the parent's fill.
- **Shadow is for things that float** (menus, popovers, the presence). Never on a
  static card.

### 2.5 Optical density beats small type

Real pro-max density comes from removing chrome, not from shrinking text. 12 px
body inside three nested borders is *less* dense than 13 px with none. When a
page needs to fit more: remove the border, then the padding, then the redundant
label — and only then consider the type scale.

---

## Part 3 — Page enrichment rules

Applied by archetype so improvement is a rule, not 74 opinions. **Every rule is
additive.** Nothing currently on a page is removed by any of them.

| Archetype | Pages | What gets ADDED |
|---|---|---|
| **Data surface** | Trade, Portfolio, Positions, PnL, TCA, Journal, Watchlist, Leaderboard, Audit | A summary rail above the table (4-6 figures); column sort + sticky header; a sparkline column; row → detail routing; empty state that names the next action |
| **Analytical** | Performance, Correlation, WalkForward, Backtest, ABTesting, Indicators | A "what changed since last look" strip; period selector; an export; one chart gains an emphasised endpoint and an area fill |
| **Operational** | Observability, Reliability, Security, AutoHeal, MLOps, SuperAdmin | Live status tiles with a severity stripe; last-fired timestamps; a link to the runbook for anything red |
| **Account** | Profile, Wallet, Billing, KYC, SubAccounts, Settings | Progressive disclosure — summary row, expand for detail; state chips (Verified / Pending / Action needed) |
| **Reading** | Docs, Academy, Terms, Privacy, Onboarding | Comfortable density; a table of contents; reading progress; "next" at the foot |
| **Hub** | AI, Analytics, Community, Account, Operations | Already good. Add: recent destinations, a count badge per card, and the plan fence (done) |

**Routing rule:** every list row that represents an entity routes to that
entity's detail page. Today several tables render a row that is not a link —
`PositionDetail` exists and almost nothing routes to it.

---

## Part 4 — The three new surfaces

### 4.1 The AI Room (on `/ai-assistant`)

Owner's words: *"a side that shows AI active there communicating… a small
surface that displays like a room where AIs are discussing about market."*

`AIAssistant` is 52 lines — a wrapper around `<AIChat>`. It gains a right rail
(bottom sheet under 900 px) showing the models that are working, what each is
looking at, and their last line. It is a **read-only window onto real activity**:
it renders what `ai/gateway` and `ai/ledger/decisions.py` already record, and it
shows "standing by" when nothing is running rather than inventing chatter.

### 4.2 The Community Room (on `/community`)

Built on `api/community_chat.py`, which ships rooms, messages and a WebSocket and
has **no UI at all** today. Real people and AI participants in the same room,
AI messages clearly badged as such — never passed off as a person.

### 4.3 Live News (inside Community)

Built on `api/news_feed.py` (`/feed`, `/nuclear-score`, `/calendar`). A live wall
where each item can be tagged by the AI with its read, and discussed in the room
beside it. The AI's tag is an opinion with a model name on it, not a fact.

---

## Part 5 — Tasks

### Task 1: Land the foundation already built — **DONE, commit `e9f00a0a`**

**Files:**
- Modify: `frontend/src/index.css` (palette + ground tokens, both themes)
- Modify: `frontend/src/components/AppBackground.tsx`
- Modify: `frontend/src/components/system/PageSurface.tsx`
- Modify: `frontend/src/components/sidebar/Sidebar.tsx`, `src/hub/floatingLanes.ts`
- Modify: `frontend/src/components/ai/AISupportWidget.tsx`
- Modify: `frontend/src/components/sidebar/navDescriptions.ts`
- Test: the_ground_follows_the_theme.test.ts — to be created, `the_dense_default_and_the_named_pages.test.ts`,
  `the_presence_clears_the_sidebar.test.ts` (all written, all green)

**Interfaces:**
- Produces: `SIDEBAR_LANE` from `hub/floatingLanes`; ground tokens
  `--ground-base|mid|deep`, `--ground-glow-a..d`, `--ground-grid`,
  `--ground-vignette[-strong]`, `--orb-*`, `--spark-*`.

- [ ] **Step 1: Run the three new suites** — `npx vitest run src/test/the_ground_follows_the_theme.test.ts src/test/the_dense_default_and_the_named_pages.test.ts src/test/the_presence_clears_the_sidebar.test.ts` — Expected: 12 passed.
- [ ] **Step 2: Run the full frontend suite** — `npx vitest run` — Expected: 0 failed.
- [ ] **Step 3: Prove light mode in a browser.** Drive `/ai` at 1440x900 with `colorScheme: 'light'` and assert the computed background of `.app-shell-scroller`'s ground layer is light, not `#0a1424`. Record the before/after values in the commit.
- [ ] **Step 4: Run the ratchets** — `python scripts/frontend_colour_ratchet.py --check && python scripts/frontend_emoji_ratchet.py --check` — Expected: both at or below baseline. Adopt if lower.
- [ ] **Step 5: Commit** with the measured before/after in the message.

---

### Task 2: Density becomes a user choice — **DONE, commits `c2811c06` and `b86d8478`**

> Landed with one finding the plan did not anticipate: the control was DEAD.
> `data-density` reached 29 class usages against 2,871 inline sizes, so making
> it settable changed almost nothing. `scripts/frontend_size_codemod.py`
> converted 763 of them; 2,108 remain and need per-bucket decisions. Tracked as
> DENSITY-CANNOT-REACH in the correction register. See
> `docs/audit/FRONTEND_HANDOVER.md` before starting Task 3.

**Files:**
- Create: frontend/src/lib/densityPref.ts — to be created
- Modify: `frontend/src/components/system/PageSurface.tsx`
- Modify: `frontend/src/pages/settings/AppearanceSection.tsx`
- Test: frontend/src/test/density_is_the_users_choice.test.ts — to be created

**Interfaces:**
- Consumes: `Density` from `components/system/PageSurface`.
- Produces: `getDensityPref(): Density | null`, `setDensityPref(d: Density | null): void`,
  `useDensityPref(): [Density | null, (d: Density | null) => void]`,
  and `densityFor(pathname: string, pref?: Density | null): Density`.

- [ ] **Step 1: Write the failing test**

```ts
import { describe, it, expect, beforeEach } from 'vitest';
import { densityFor } from '../components/system/PageSurface';
import { getDensityPref, setDensityPref } from '../lib/densityPref';

beforeEach(() => localStorage.clear());

describe('density preference', () => {
  it('defaults to ultra when the user has not chosen', () => {
    expect(getDensityPref()).toBeNull();
    expect(densityFor('/notifications', null)).toBe('ultra');
  });

  it('honours the choice on an ordinary page', () => {
    expect(densityFor('/notifications', 'comfortable')).toBe('comfortable');
  });

  it('never loosens a data surface below ultra', () => {
    // Seeing three more rows of open risk is not a taste question.
    expect(densityFor('/portfolio', 'comfortable')).toBe('ultra');
    expect(densityFor('/pnl', 'promax')).toBe('ultra');
  });

  it('round-trips through storage and survives a broken store', () => {
    setDensityPref('promax');
    expect(getDensityPref()).toBe('promax');
    setDensityPref(null);
    expect(getDensityPref()).toBeNull();
  });
});
```

- [ ] **Step 2: Run it and watch it fail** — `npx vitest run src/test/density_is_the_users_choice.test.ts` — Expected: FAIL, `Cannot find module '../lib/densityPref'`.

- [ ] **Step 3: Write `densityPref.ts`**

```ts
/**
 * densityPref — how tight the person wants the interface.
 *
 * The three tiers already existed and were chosen per route. This lets the
 * person choose, defaulting to `ultra`. It cannot loosen a data surface: the
 * ULTRA list in PageSurface still wins, because a looser order book is a worse
 * order book whatever anyone prefers.
 *
 * Mirrors the shape of `voicePrefs.ts` — localStorage plus a custom event, so
 * two tabs agree.
 */
import { useCallback, useEffect, useState } from 'react';
import type { Density } from '../components/system/PageSurface';

const KEY = 'hopefx.density';
const EVENT = 'hopefx:density';
const VALID: readonly Density[] = ['comfortable', 'promax', 'ultra'];

export function getDensityPref(): Density | null {
  try {
    const raw = localStorage.getItem(KEY);
    return VALID.includes(raw as Density) ? (raw as Density) : null;
  } catch {
    return null; // private mode, blocked storage — the default still works
  }
}

export function setDensityPref(density: Density | null): void {
  try {
    if (density === null) localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, density);
  } catch { /* ignore */ }
  try {
    window.dispatchEvent(new CustomEvent(EVENT, { detail: density }));
  } catch { /* SSR */ }
}

export function useDensityPref(): [Density | null, (d: Density | null) => void] {
  const [pref, setPref] = useState<Density | null>(getDensityPref);
  useEffect(() => {
    const onCustom = (e: Event) => setPref(((e as CustomEvent).detail ?? null) as Density | null);
    const onStorage = (e: StorageEvent) => { if (e.key === KEY) setPref(getDensityPref()); };
    window.addEventListener(EVENT, onCustom);
    window.addEventListener('storage', onStorage);
    return () => {
      window.removeEventListener(EVENT, onCustom);
      window.removeEventListener('storage', onStorage);
    };
  }, []);
  return [pref, useCallback((d: Density | null) => setDensityPref(d), [])];
}
```

- [ ] **Step 4: Teach `densityFor` about the preference**

```ts
export function densityFor(pathname: string, pref: Density | null = null): Density {
  // ULTRA first: a data surface stays dense whatever anyone prefers.
  if (match(pathname, ULTRA)) return 'ultra';
  if (pref) return pref;
  if (match(pathname, COMFORTABLE)) return 'comfortable';
  if (match(pathname, PROMAX)) return 'promax';
  return 'ultra';
}
```

- [ ] **Step 5: Read the preference in `PageSurface`** — call `useDensityPref()` and pass it into `densityFor(pathname, pref)` at the `data-density` stamp.

- [ ] **Step 6: Add the control to Settings → Appearance** — a three-way segmented control labelled *Comfortable / Pro / Ultra*, plus *Use the page default*, each with `aria-pressed`, and a one-line description saying data surfaces stay dense.

- [ ] **Step 7: Run the tests** — `npx vitest run src/test/density_is_the_users_choice.test.ts` — Expected: 4 passed. Then `npx vitest run` — Expected: 0 failed.

- [ ] **Step 8: Commit.**

---

### Task 3: The motion layer — **NOT STARTED**

**Files:**
- Create: frontend/src/styles/motion.css — to be created (imported by `index.css`)
- Create: frontend/src/lib/motionPref.ts — to be created
- Modify: `frontend/src/components/system/PageShell.tsx` (entrance)
- Test: frontend/src/test/motion_is_budgeted.test.ts — to be created

**Interfaces:**
- Produces: classes `.enter`, `.enter-stagger`, `.tick-flash-up`, `.tick-flash-down`;
  `getAmbient(): boolean`, `setAmbient(on: boolean): void`.

- [ ] **Step 1: Write the failing test**

```ts
import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const css = fs.readFileSync(path.resolve(__dirname, '../styles/motion.css'), 'utf8');

describe('the motion budget', () => {
  it('every animation is inside a reduced-motion guard', () => {
    expect(css).toContain('@media (prefers-reduced-motion: reduce)');
  });

  it('entrances are short enough not to be waited on', () => {
    const durations = [...css.matchAll(/animation:[^;]*?(\d+)ms/g)].map((m) => Number(m[1]));
    expect(durations.length).toBeGreaterThan(0);
    expect(Math.max(...durations), 'an entrance longer than 400ms is a delay').toBeLessThanOrEqual(400);
  });

  it('uses ease-out for entering, never linear', () => {
    expect(css).toContain('ease-out');
    expect(css).not.toMatch(/animation:[^;]*\blinear\b/);
  });
});
```

- [ ] **Step 2: Run it and watch it fail** — Expected: FAIL, no such file.

- [ ] **Step 3: Write `motion.css`** — `.enter` (160 ms, `ease-out`, `translateY(8px)` → 0, `opacity` 0 → 1), `.enter-stagger > *` with `animation-delay: calc(var(--i, 0) * 25ms)`, `.tick-flash-up/down` (400 ms background wash from `--gain`/`--loss` at 18% to transparent), and a closing `@media (prefers-reduced-motion: reduce) { * { animation: none !important; transition: none !important } }`.

- [ ] **Step 4: Apply the entrance in `PageShell`** — add `enter` to the content column. One element, one entrance, per the budget.

- [ ] **Step 5: Run the test** — Expected: 3 passed.

- [ ] **Step 6: Prove it in a browser** — drive three routes and confirm the entrance runs once and no data row animates. Record it.

- [ ] **Step 7: Commit.**

---

### Task 4: The elevation rule, enforced — **NOT STARTED**

**Files:**
- Create: frontend/src/test/elevation_is_spent_by_role.test.ts — to be created
- Modify: `frontend/src/index.css` (radius tokens)

**Interfaces:**
- Produces: `--radius-object: 6px`, `--radius-pill: 99px`.

- [ ] **Step 1: Write the failing test** — assert `index.css` declares exactly two radius tokens, and that no component file nests a bordered card directly inside a bordered card (scan for `border` + `borderRadius` within one JSX parent chain in the five worst offenders found by the audit).
- [ ] **Step 2: Run it, watch it fail.**
- [ ] **Step 3: Add the two tokens; point existing radii at them via the codemod** — `python scripts/frontend_token_codemod.py --check` first, then `--apply`.
- [ ] **Step 4: Run the test and the colour ratchet.**
- [ ] **Step 5: Commit.**

---

### Task 5: Finish the PageShell migration (14 pages) — **NOT STARTED**

**Files:** the 14 named by `python scripts/frontend_page_shell_ratchet.py --check`.

- [ ] **Step 1: List them** — run the ratchet, record the names.
- [ ] **Step 2: For each, migrate by AST range replacement** — the tool and its rules are in the session scratchpad (`shellify.mjs`); the rules it encodes are: default export only, own returns only, refuse on a second render branch, refuse if an `<h1>` would remain, lift `PageHeader`, move `RelatedPages` onto `related`.
- [ ] **Step 3: After each batch, `npx tsc --noEmit && npx vitest run`.**
- [ ] **Step 4: Drive each migrated route in a browser** — one `h1`, footer present, fills the scroller, no new console errors against a control run.
- [ ] **Step 5: Adopt the ratchet and commit.**

---

### Task 6: Wire the 19 data pages that call no API — **NOT STARTED**

> Re-measured 2026-09-15: **11** routed pages call no API, not 19, and four of
> them (DocsPage, PrivacyPolicy, TermsAndRiskDisclosure, NotFound) are correctly
> static and must stay that way. Five are worth wiring. See the handover.

**Files:** the 19 identified in Part 0, one commit per page.

**This task comes before enrichment.** Dressing a page with no data produces a
prettier empty page.

- [ ] **Step 1: For each page, name the endpoint it should read** — from `api/` and `useApi.ts`. If none exists, record it as a backend gap in `docs/ai/MASTER_OUTSTANDING.md` rather than inventing a client for it.
- [ ] **Step 2: Write the failing test** — render the page with a mocked API returning one row; assert the row reaches the screen.
- [ ] **Step 3: Wire the query** — TanStack Query, with the three states the repo requires: loading (skeleton matching final layout), empty (names the next action), error (says what failed and how to retry).
- [ ] **Step 4: Run the test; drive the route in a browser.**
- [ ] **Step 5: Commit per page** so a bad wiring is one revert.

---

### Task 7: Apply the enrichment rules by archetype — **NOT STARTED**

**Files:** per the table in Part 3, one commit per archetype.

- [ ] **Step 1: Write the test for the archetype rule** — e.g. for data surfaces, assert the summary rail renders the same figure count the table's columns imply, and that every entity row is a link.
- [ ] **Step 2: Run it, watch it fail.**
- [ ] **Step 3: Implement for the first page in the archetype.**
- [ ] **Step 4: Assert nothing was removed** — snapshot the rendered text content before and after; the after-set must be a superset. This is the constraint-1 gate and it is mechanical:

```ts
const before = new Set(renderBefore().textContent!.split(/\s{2,}/).filter(Boolean));
const after  = new Set(renderAfter().textContent!.split(/\s{2,}/).filter(Boolean));
const lost = [...before].filter((t) => !after.has(t));
expect(lost, `these disappeared from the page: ${lost.join(' | ')}`).toEqual([]);
```

- [ ] **Step 5: Roll to the rest of the archetype; commit per archetype.**

---

### Task 8: The AI Room — **NOT STARTED**

**Files:**
- Create: frontend/src/components/ai/AIRoom.tsx — to be created
- Create: frontend/src/hooks/useAIRoom.ts — to be created
- Modify: `frontend/src/pages/AIAssistant.tsx` (52 → a two-column shell; the existing `<AIChat>` is untouched and keeps its full width under 900 px)
- Test: frontend/src/test/the_ai_room_shows_only_real_activity.test.tsx — to be created

**Interfaces:**
- Produces: `useAIRoom(): { participants: Participant[]; standingBy: boolean; reason: string }`
  where `Participant = { id: string; model: string; department: string; looking_at: string; last_line: string; at: string }`.

- [ ] **Step 1: Write the failing test**

```tsx
it('says standing by rather than inventing chatter', async () => {
  aiCoreApi.summary.mockResolvedValue({ data: { calls_recorded: 0 } });
  render(<AIRoom />);
  expect(await screen.findByText(/standing by/i)).toBeTruthy();
  expect(screen.queryByRole('listitem')).toBeNull();
});

it('renders one row per model that actually ran', async () => {
  aiCoreApi.summary.mockResolvedValue({ data: { calls_recorded: 2, participants: [
    { id: 'a', model: 'claude-opus-5', department: 'research_intelligence',
      looking_at: 'XAUUSD 4h', last_line: 'Range holds until the London fix.', at: '14:02' },
    { id: 'b', model: 'llama3.2:3b', department: 'news_intelligence',
      looking_at: 'CPI print', last_line: 'Consensus 3.1%.', at: '14:03' },
  ] } });
  render(<AIRoom />);
  expect(await screen.findAllByRole('listitem')).toHaveLength(2);
  expect(screen.getByText(/claude-opus-5/)).toBeTruthy();
});

it('never labels a model as a person', async () => {
  // Every participant row carries a model badge. An AI line that could be
  // mistaken for a human one is the failure this test exists for.
  render(<AIRoom />);
  const rows = await screen.findAllByRole('listitem');
  rows.forEach((r) => expect(r.textContent).toMatch(/AI|model/i));
});
```

- [ ] **Step 2: Run it, watch it fail.**
- [ ] **Step 3: Write `useAIRoom`** reading `aiCoreApi.summary()` and `ai/ledger` decisions; return `standingBy: true` with a reason whenever nothing ran. **No placeholder participants, ever.**
- [ ] **Step 4: Write `AIRoom.tsx`** — a list, each row: model badge, department, what it is looking at, its last line, a timestamp. Idle pulse only when `standingBy === false` and only if ambient motion is on.
- [ ] **Step 5: Add it to `AIAssistant.tsx` as a right rail**, bottom sheet under 900 px. The existing chat is not moved or shrunk on mobile.
- [ ] **Step 6: Run the tests; drive `/ai-assistant` in a browser at 1440 and 390.**
- [ ] **Step 7: Commit.**

---

### Task 9: The Community Room — **NOT STARTED**

**Files:**
- Create: frontend/src/hooks/useCommunityRooms.ts — to be created (the missing client for `api/community_chat.py`)
- Create: frontend/src/components/community/RoomList.tsx — to be created, `RoomThread.tsx`
- Modify: `frontend/src/pages/Hub.tsx` — community hub gains the room
- Test: frontend/src/test/the_community_room_badges_its_ai.test.tsx — to be created

**Interfaces:**
- Consumes: `/api/chat/rooms`, `/api/chat/rooms/{id}/messages`, the WS router.
- Produces: `useCommunityRooms()`, `useRoomThread(roomId)`.

- [ ] **Step 1: Write the failing test** — a room with one human and one AI message; assert the AI message carries a visible badge and an accessible name containing "AI", and that the human's does not.
- [ ] **Step 2: Run it, watch it fail.**
- [ ] **Step 3: Write the client** — REST for history, WebSocket for live, reconnect with backoff, and an explicit "reconnecting" state rather than silent staleness.
- [ ] **Step 4: Write the components.** An AI line is always badged. Never render an AI message as a person.
- [ ] **Step 5: Run the tests; drive the route; confirm a live message arrives over the socket.**
- [ ] **Step 6: Commit.**

---

### Task 10: Live News inside Community — **NOT STARTED**

**Files:**
- Create: frontend/src/components/community/NewsWall.tsx — to be created
- Modify: `frontend/src/hooks/useApi.ts` — add the `/feed`, `/nuclear-score`, `/calendar` calls if absent
- Test: frontend/src/test/the_news_wall_attributes_its_reads.test.tsx — to be created

- [ ] **Step 1: Write the failing test** — a news item with an AI tag must show the model name next to the tag; an item with no tag must show the item and no tag, never a blank chip.
- [ ] **Step 2: Run it, watch it fail.**
- [ ] **Step 3: Build the wall** — item, source, time, impact from `/nuclear-score`, and the AI's read as an attributed opinion. "Discuss" routes into the room thread for that item.
- [ ] **Step 4: Run the tests; drive it.**
- [ ] **Step 5: Commit.**

---

### Task 11: Prove the whole thing, then document it — **NOT STARTED**

- [ ] **Step 1: Drive all 93 routes** at 1440 and 390, capturing console errors, failed requests, unnamed controls and duplicate ids. Expected: no regressions against the control run.
- [ ] **Step 2: Re-measure contrast** in both themes across the driven routes. Expected: 0 failures.
- [ ] **Step 3: Run every gate** — `npx tsc --noEmit`, `npx eslint src/`, `npx vitest run`, `pytest -m "not slow and not e2e"`, `pre-commit run --all-files`.
- [ ] **Step 4: Update the documents the work made stale** — `CLAUDE.md` routing table, `ARCHITECTURE.md`, `docs/ai/MASTER_OUTSTANDING.md`, and the correction register with a probe per finding.
- [ ] **Step 5: Final commit and push.**

---

## Self-review

**Spec coverage.** Palette §2.1 → Task 1. Density §2.2 → Task 2. Motion §2.3 →
Task 3. Elevation §2.4 → Task 4. Optical density §2.5 → Tasks 4 and 7. Page
enrichment Part 3 → Tasks 6 and 7. AI Room §4.1 → Task 8. Community Room §4.2 →
Task 9. Live News §4.3 → Task 10. "Nothing removed" → the superset assertion in
Task 7 Step 4, applied to every enrichment commit. "Some pages don't show" →
Task 6, which is the 26-with-no-API finding and is sequenced before dressing.

**Placeholder scan.** No TBDs. Task 5 and Task 6 iterate over lists produced by
a named command rather than a typed list, because those lists are measured at
execution time and a typed copy would be stale by Task 7 — the command is given
in the step.

**Type consistency.** `Density` is imported from `components/system/PageSurface`
in both `densityPref.ts` and the test. `densityFor` takes
`(pathname: string, pref?: Density | null)` in Tasks 2 and 5 alike.
`Participant` is defined once, in Task 8's Interfaces block, and used by the
Task 8 tests.

**Risk.** Task 6 is the largest and the one most likely to find that an endpoint
does not exist. Its Step 1 says to record a backend gap rather than invent a
client — that is the honest failure mode, and it keeps the plan from silently
turning into backend work nobody scheduled.
