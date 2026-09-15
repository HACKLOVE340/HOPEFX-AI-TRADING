# Frontend handover — the AI presence, density, and what is left

**Written 2026-09-15. Branch `claude/add-new-skills-lys862`.**

If you are picking this up, read this file, then run the commands in
[Measure first](#measure-first). Every number below is a snapshot; every number
those commands print is today's. Where they disagree, the command is right and
this document is stale — fix the document, per the standing rule in `CLAUDE.md`.

This is the **frontend / AI-presence** thread. It is not the whole programme.
For the rest see `docs/audit/CORRECTION_REGISTER.md` (97 findings, probed from
the code), `docs/ai/MASTER_OUTSTANDING.md` (owner decisions) and
`docs/audit/LANDING_PLAN.md` (how this branch reaches `main`).

---

## Measure first

```bash
python scripts/correction_register.py --check       # what is open, probed from the code
python scripts/frontend_page_shell_ratchet.py --check
python scripts/frontend_colour_ratchet.py --check
python scripts/frontend_emoji_ratchet.py --check
python scripts/frontend_size_codemod.py --check     # what density still cannot reach
cd frontend && npx tsc --noEmit && npm run lint && npx vitest run
```

Measured 2026-09-15, immediately before this document was written:

| Measure | Value |
|---|---|
| Correction register | 97 findings · OPEN 1 · PARTIAL 9 · OWNER 8 · FIXED 79 |
| Pages on the standard shell | 49 of 63 — **14 off** |
| Colour literals | 3,555 across 190 files |
| Emoji used as icons | 750 across 125 files |
| Inline `fontSize` the cascade cannot reach | 2,108 (was 2,871) |
| Numeric spacing utilities | 1,089 |
| Frontend tests | 172 files · 2,972 tests · all pass |
| eslint | 0 errors · 18 warnings (one a11y rule, known limitations) |

---

## What was built, and why it is shaped that way

Four commits on this branch, newest last.

### `e9f00a0a` — the presence gets a head, eleven faces, and a voice

**The head on every page was mute.** `PresenceAnywhere` rendered
`<PresenceCore presence={…} size={…} />` and passed no `utterance`, no
`speechProgress`, no `speaking`. So `mouthFor` ran with `speaking=false` on
every frame of every page and returned `{ openness: 0 }` — the mouth was painted
shut while the platform talked. Nothing was broken in `head.ts`; speech was
component state inside `useVoice`, and a head elsewhere in the tree had no way
to learn synthesis had started. That is the dead-control shape.

`hub/speechBus.ts` is the fix: a module store `useVoice` publishes to and
`useSpeech()` subscribes to. It normalises at the boundary — silence clears the
utterance and the progress together, a non-finite progress becomes null, speech
with no text is silence. **Null progress stays null all the way through**:
`mouthFor` reads null as "speaking, unmeasured" and holds a steady shape,
whereas zero would pin every head in the app to the first character of the
utterance.

**The head was an outline, and an outline has no orientation.**
`head.ts::headMesh` now builds a volumetric wireframe skull that yaws, pitches
and rolls, and hinges its mandible on the character being spoken.

**The head had one face.** `hub/headModes.ts` holds eleven — panicking,
refusing, worried, concerned, speaking, listening, mimicking, detection,
reaction, awareness, dormant — and **there is no `setMode`**. `chooseHeadMode`
reads the same measurements the presence machine reads and returns the mode
those signals justify, plus the sentence naming which measurement chose it and a
0..1 severity. A settable mood is a decorative live value with a face, which §22
already forbids in ring form.

Two of the modes are refusals, and they are the interesting ones:

* **`mimicking`** requires a live vision source, not a camera permission.
  Mirroring a face nobody measured is a fabricated claim about the operator.
* **`panicking`** requires a catastrophic measurement rather than a loud one. If
  an amber alert could reach it, it would be reached constantly, and an operator
  learns to ignore a face that is always alarmed.

`refusing` is a mode this codebase needed and did not have: `ai/ledger/decisions.py`
records refusals as first-class entries rather than failures, and the presence
had no way to show one, so a refusal looked like an error — which invites a retry.

`expressionFor` separates **meaning** from **motion**. Brow, eyelids, tilt and
pupil are the reading and reduced motion keeps every one of them; tremor,
breath, sweep and the scan are motion and reduced motion removes all of them.
Hiding a raised brow from the operator who asked for a still interface would be
an accessibility setting that removes information.

### `0d9a958e` — the head becomes a lit hologram with a face

Owner reference: a cyan holographic head, front-lit, with a recognisable face
and a neck. Three things were missing.

* **No face.** Every point sat at the profile radius, so straight on it was an
  egg with features painted on it. `faceRelief(u, v)` is the displacement —
  nose, brow ridge, sockets, cheeks, lips, philtrum, chin, temples — each a
  product of two Gaussians so it stays continuous, all multiplied by a window
  that reaches zero behind the ears.
* **No neck.** Its own geometry, outside the shell, so the jaw cannot drag it
  and the relief cannot reach it: a neck with cheekbones is not a neck.
* **No surface.** Contours cannot make a head solid — you see the back of the
  skull through the front however dense the wire gets, because nothing is
  filled. `headSurface` samples the same geometry as quads carrying a Lambert
  term, a Fresnel rim and a Blinn-Phong highlight.

**Why arithmetic and not a loaded mesh.** A `.glb` is bytes nobody can review in
a diff, needs a loader and a renderer this canvas does not have, and the head
must respond to measurements anyway — a jaw hinging on the character being
spoken, brows carrying a risk reading — which means driving vertices at runtime
either way. **If you are tempted to add three.js, read the "Not worth doing"
section below first.**

Four things were found by rendering rather than by reasoning, and each changed
the geometry: the first shaded render was a flat slab (relief too shallow to
tilt a normal); the second a teardrop (the profile closed to zero at both
poles); the third blocked into hard squares (canvas fills a quad with ONE
colour, so a tight specular exponent is aliasing, not a highlight); and the scan
band was twice wide enough to sit across the eyes like a blindfold.

**It was far too slow, and the first two fixes were wrong.** ~900 visible quads
× (one fill + one seam-stroke) = 108,000 draw calls per head per second. The
eleven-mode review page measured **3.1 FPS**. Removing the bloom and memoising
the geometry took it to 4.1 — because the geometry was never the cost. The
surface is now painted once per **pose** into an offscreen canvas and blitted
with a single `drawImage`. One 460px head: **44.8 FPS, 1 drawImage, 131 fills
per frame.**

Two things that cache had to get right, both learned the hard way:

* The memo key is **quantised**, because the pose is driven by a breath and a
  blink that jitter by fractions no pixel can show. Without rounding it would
  never hit while the head was merely alive.
* The cache is **per component**, not per module. With more than one head on
  screen a shared cache is worse than none, since each pose evicts the last —
  measured, a module-level cache left the review page exactly where it was.

**A test caught a real regression here.** Re-proportioning the head to the
reference (1.44 radii tall, was 1.3) broke `drops the chin as the mouth opens`:
a pure hinge moves a chin that far below the pivot mostly *backward*, and the
perspective divide shrank the retreating chin by more than the swing lowered it,
so `mouthOpenness` 1 drew a chin marginally **higher** than 0. The mandible now
translates as well as rotates, which is what a real one does past a small angle.
That assertion is exactly the one that would otherwise have been quietly relaxed.

### `c2811c06` — density becomes the person's choice, and is found to be dead

`lib/densityPref.ts` stores the choice; Settings → Appearance carries the
control. `densityFor(pathname, pref)` lets it override the route table in both
directions, with **one floor it cannot cross**: a data surface never loosens
below `ultra`, because how many rows of open risk fit on screen is not a taste
question.

Then the finding. Making a control settable is not the same as making it
effective, and shipping the first without checking the second would have been a
second dead control stacked on the first. **DENSITY-CANNOT-REACH (P2):**
`data-density` is stamped on every route and specified across three tiers, and
it reached **29** class usages against 2,871 inline `fontSize: <number>` and
1,089 numeric spacing utilities. A literal pixel is not in the cascade. *That is
why the interface did not feel dense at any setting — there was no density to
feel.*

What is alive was proven in a browser, not asserted: comfortable / promax /
ultra resolve to gap 16 / 10 / 7px, body 15 / 13 / 12px, card padding
20 / 14 / 10px.

**A test had to be rewritten.** The first version used jsdom's
`getComputedStyle`. The tiers live inside `@layer base`, which jsdom's CSSOM
drops entirely, so it returned empty strings — it would have passed against a
*broken* cascade, which is how a control stays dead. It now parses `index.css`
and asserts the tiers are monotonic and separated by a real margin rather than a
rounding one.

### `b86d8478` — 763 inline font sizes reach the token layer

`scripts/frontend_size_codemod.py`, built on `frontend_token_codemod.py`'s
proven rules and **importing** its span-finding and canvas exclusion rather than
copying them — two implementations of that hazard would drift, the second one
silently, in a chart nobody opened.

Every substitution is byte-identical at the default density, verified in
Chromium: all seven tokens match the literal they replaced at `promax`, and now
move at the other two tiers. 2,871 → 2,108.

Sizes **between** tokens are reported and never rewritten — 12px (×638), 11px
(×532), 10px (×255), 14px (×217) each need a decision per call site. Spacing is
out of scope for a stronger reason: `padding: 14` is byte-identical to
`--pad-card`, and 14px of padding might be a card, a row, a modal or a button.

**An injection survived all nineteen tests**, and the lesson generalises. The
test written for the pattern's anchor — `fontSize: 130` must not become
`var(--fs-body)0` — is protected by the **table**, not the pattern. The case the
anchor really guards is `fontSize: 13 + offset`, which an unanchored version
rewrites to `'var(--fs-body)' + offset`: a string concatenation that
type-checks, renders `var(--fs-body)4`, and is silent. If you write a codemod
here, injection-test it; the obvious reading of your own regex will be wrong.

**A gate fired and was not bypassed.** `check_secrets.sh` flagged eleven lines —
`smtp_password: ''`, `has_api_key: boolean`, `const ForgotPassword: React.FC`.
It matches credential *key names*, right for YAML and wrong for source; `.py`,
`.js`, `.ts` and `.sh` were already excluded for that reason and `.jsx`/`.tsx`
were missed, because `\.ts$` is anchored and does not match `.tsx`. The gap
survived because the hook is `types: [yaml], pass_filenames: false`, so it only
runs when a YAML file is staged. The exclusion is now consistent, and the
compensating control was **verified by injection**: a real AWS key planted in a
new `.tsx` was caught by `detect-secrets` at line 1.

---

## What is left, in the order I would do it

The plan is `docs/audit/plans/2026-09-15-frontend-ultra.md`; Tasks 1–2 are done,
Tasks 3–11 are not. This section is the *current* reading of them, which
supersedes the plan where they differ.

### 1. Finish what the codemod started — close DENSITY-CANNOT-REACH

**Why first:** everything the owner asked for about density is blocked behind
it, and the mechanism is already built and proven.

2,108 inline sizes remain. They are not all substitutable, and the work divides:

| Bucket | Count | What to do |
|---|---:|---|
| `fontSize: 12` | 638 | A decision, not a substitution. 12 sits between `--fs-label` (11.5) and `--fs-body` (13). Sample the call sites: if most are table cells, they are body text at the wrong size and should become `--fs-body`, which moves them 1px at the default. **That needs the owner's word**, because it changes what pages look like today. |
| `fontSize: 11` | 532 | Same question against `--fs-label` (11.5). |
| `fontSize: 10` / `9` | 350 | Probably `--fs-micro` (10.5). Same question. |
| `fontSize: 14`/`16`/`18`/`20`/`22`/`24` | 461 | Between `--fs-value` and `--fs-head`. The type scale may be missing a step; consider adding one rather than rounding 461 sites. |
| Numeric spacing (`p-4`, `gap-3`, …) | 1,089 | Needs a spacing scale decision first. `--pad-card` / `--pad-row` / `--gap-grid` exist; a fourth for buttons and a fifth for modals probably should. |

**Do not** rewrite a bucket to the nearest token without asking. The codemod's
whole safety argument is that nothing moves at the default density, and rounding
638 sites by 1px abandons it.

A **size ratchet** (mirroring `frontend_colour_ratchet.py`) would stop the count
growing while this is decided. It does not exist yet; the register's probe
measures the number but does not block on it.

### 2. The 14 pages still off the standard shell

`python scripts/frontend_page_shell_ratchet.py --check` names them:

```
AICore · Affiliate · CryptoCheckout · DocsPage · MLDashboard · NotificationsPage
NuclearDashboardPage · Profile · Settings · StatusPage · SuperAdminDashboard
Trading · TradingDashboard · WalkForward
```

These are the hard ones — the earlier 49 were the tractable ones. `AICore`,
`Trading` and `TradingDashboard` own their own full-bleed layouts and should
probably get a **fourth width** on `PageShell` rather than being forced into the
three that exist. `Settings` and `SuperAdminDashboard` are tab shells whose
children are the real pages.

**Method that worked for the first 49:** AST-range replacement, never text
slicing. A non-greedy regex cannot match nested JSX — `<PageHeader[\s\S]*?/>`
stops at the `/>` inside `actions={<button …/>}`, which produced 7 false
refusals before it was caught.

### 3. Pages that render but fetch nothing

Eleven routed pages call no API at all:

```
AIAssistant (51)   Hub (114)            NuclearDashboardPage (95)
SystemReliability (82)                  PositionDetail (274)
GeopoliticalRiskPage (549)              Settings (554)
DocsPage (429)     NotFound (169)       PrivacyPolicy (248)
TermsAndRiskDisclosure (429)
```

Four of those are **correct** and must stay that way: `DocsPage`,
`PrivacyPolicy`, `TermsAndRiskDisclosure` and `NotFound` are static by design.
`Settings` and `Hub` are shells whose children fetch.

The five worth wiring are `AIAssistant`, `NuclearDashboardPage`,
`SystemReliability`, `PositionDetail` and `GeopoliticalRiskPage` — each shows a
surface with no live data behind it. **Check before you wire:** the endpoint may
not exist. Adding a fetch to a 404 is worse than a static page, because it
produces an error state where there was none.

### 4. The three surfaces the owner asked for and nobody has built

From the owner's 2026-09-14 brief, still entirely unbuilt:

* **An AI room on `/ai-assistant`** — a panel showing the AIs that are actually
  active, discussing the market. The refusal rule matters more than the panel:
  it must show only real activity, and say "standing by" when there is none.
  Inventing a conversation is the exact defect this codebase keeps finding.
* **A community with AI participants** discussing sentiment and news, linked to
  that room. **`api/community_chat.py` already exists and is already consumed**
  — `pages/ChatPage.tsx` (296 lines, routed at `/chat`) uses `chatApi` and
  `openAuthenticatedWebSocket`. *An earlier note in this session claimed it had
  zero frontend consumers; that was wrong, and re-measuring is what corrected
  it.* So this is an extension of a live feature, not a greenfield build: AI
  participants need a **badge** so a human always knows who is a model.
* **Live news inside the community**, where an AI can tag an item and humans can
  reply in real time. Attribution is the hard part: which model tagged it, and
  on what evidence.

### 5. Motion, elevation, and the round-edge transparency the owner asked for

Plan Tasks 3 and 4, untouched. The owner asked specifically for "some of the
round edge to be transparent". There is no motion layer: transitions are
per-component inline strings, so there is no way to honour
`prefers-reduced-motion` in one place. `hub/a11yMotion.ts` exists and is the
right home.

---

## Not worth doing, and why — read before you "improve" these

**Do not replace the procedural head with three.js and a rigged model.** It
costs ~600KB plus model bytes and a WebGL renderer on the page that places
orders, and it does not remove any work: the head must still hinge its jaw on
the character being spoken and move its brows on risk headroom, which means
authoring morph targets and driving them at runtime. The current head is not
photoreal and will not become photoreal in canvas 2D — that limit is real and
was stated to the owner. If the owner later decides photoreal is worth the
dependency, scope it properly first; do not start it as a refactor.

**Do not make the head bloom with `shadowBlur`.** It is the most expensive
operation in the 2D context. At ~150 blurred fills per head per frame it took
the review page to 3.1 FPS. The rim is brightened by colour instead, which costs
nothing and is a difference nobody could point at.

**Do not add a second copy of the codemod's canvas exclusion.** Import it.

**Do not relax `drops the chin as the mouth opens`, or any assertion that goes
red under a re-proportioning.** It caught a real inversion. Three tests in this
session were found to be proving nothing and were rewritten rather than trusted.

**Do not raise a ratchet baseline to get past it.** Both frontend ratchets are
currently at their measured value with no slack.

---

## Traps this session actually fell into

Recorded because each cost real time and each is easy to repeat.

1. **A test that passes against the broken code proves nothing.** Three tests
   were rewritten for this in one session. Injection-test anything that guards
   a rule.
2. **jsdom is not a browser.** It has no canvas, and its CSSOM drops `@layer`
   entirely. Two tests were written against it that could not have failed.
3. **Detaching a DOM node does not stop its `requestAnimationFrame` loop.** A
   "one head" performance measurement was actually twelve heads still drawing,
   and the number was wrong by an order of magnitude.
4. **When a measurement looks alarming, suspect the measurement.** 3.1 FPS was
   real; "one head at 5.2 FPS" was not.
5. **Re-measure a claim before repeating it.** The "community chat has zero
   frontend consumers" note above was wrong and would have sent the next person
   building something that exists.
6. **A checker that reads prose is not reading code — except when it is meant
   to.** `frontend_colour_ratchet.py` counts a hex in a comment *deliberately*
   and documents why ("a literal written in a comment is a literal the next
   contributor copies"). I assumed it was the F255 defect and it was not;
   reading the script settled it in one command.

---

## Where things live

| What | Where |
|---|---|
| The presence, drawn | `frontend/src/hub/PresenceCore.tsx` |
| Its geometry and lighting | `frontend/src/hub/head.ts` |
| Which face it wears, and why | `frontend/src/hub/headModes.ts` |
| What the platform is saying, anywhere | `frontend/src/hub/speechBus.ts` |
| The presence on every page | `frontend/src/hub/PresenceAnywhere.tsx` |
| The AI Core plane | `frontend/src/hub/PresenceStage.tsx` · `components/ai/PresencePanel.tsx` |
| Layouts (focus/compare/split/timeline/war_room/presentation) | `frontend/src/hub/layout.ts` |
| Density tiers and palette | `frontend/src/index.css` · `components/system/PageSurface.tsx` |
| The density preference | `frontend/src/lib/densityPref.ts` |
| The size codemod | `scripts/frontend_size_codemod.py` |
| The colour codemod | `scripts/frontend_token_codemod.py` |
| The plan this came from | `docs/audit/plans/2026-09-15-frontend-ultra.md` |
