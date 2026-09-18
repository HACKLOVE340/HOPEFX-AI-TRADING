# AI Core — spec intake and audit cross-reference

**Status: RECORDED, NOT STARTED.** Nothing in this document has been built or
changed. It exists so the AI Core work enters the same backlog as the 187 audit
findings and gets fixed in one pass rather than as a parallel stream.

**Source:** "HOPEFX AI Core — Full Build Spec" supplied 2026-08-23.
**Figma:** https://www.figma.com/design/TmdTVOynTywweydCaWlEWg
(per the spec's own Section 10, **out of date** — it holds six nodes from the
original draft, including "Growth & Business" which no longer exists as a
department. It needs a rebuild, not an addition.)

The spec is not restated here. What follows is what the audit adds to it.

---

## 1. The part that matters most: this spec's central promise is this codebase's signature defect

The architecture spine states:

> "Every department can *recommend*. Nothing places a trade, deploys code,
> rotates a credential, or changes a setting without passing through the
> superadmin approval queue. A kill switch halts every agent instantly."

That is the correct design. It is also, precisely, the thing this codebase has
repeatedly failed to actually do. The most repeated defect across 187 findings
is **a control that exists, is described accurately in documentation, and is
never invoked** — or one that reports success for work that did not happen:

| Finding | The control | What it actually does |
|---|---|---|
| **F176** | `scripts/invariant_coverage.py` prints `FULL COVERAGE ✅` | Counts hardcoded `True` literals. Cannot fail. |
| **F214** | Phase-3 paper-trading gate | `phase3_ready()` is computed once — into a health dict. Gates nothing. |
| **F204** | Creator payout | Marks `PAID` and zeroes the balance when the Stripe package is absent. No transfer. |
| **F219** | Push notification | Returns `True` with FCM off and zero tokens. Default deployment. |
| **F177** | `invariants/` | 362 predicates written, ~31 reachable from production. |
| **F233** | Feature-importance `method` field | Reports `feature_importances` while returning 30 identical values. |

**Consequence for the AI Core:** an approval queue that is designed but
enforced only by convention will fail in exactly this way, and it will fail
silently. The spec already says the right thing in the AI-layer hardening
section — *"per-agent permission scoping enforced at the tool layer, not just
prompted — so a compromised agent can't call an action outside its scope even
if tricked."* That sentence should be treated as the **load-bearing
requirement of the entire build**, not one bullet among many.

**Concrete acceptance criterion to adopt now, before any of it is written:**
a test that constructs an agent, calls an action outside its scope directly
(bypassing the prompt), and **fails the build if the call succeeds**. Same for
the approval queue: a test that executes a proposal without an approval record
and fails if anything moves. Without those, this spec describes F176 at a
larger scale.

---

## 2. Three spec components inherit an existing broken dependency

These are not objections to the design. They are prerequisites the spec does
not currently know about.

### 2a. "A kill switch halts every agent instantly" → blocked by **F139**
`deployments/k8s/` has no RBAC file and no `serviceAccountName`, so the
ConfigMap patch that propagates the kill switch across pods is **denied**. A
second manifest set (`k8s/kill-switch-rbac.yaml`) has it. Whichever
`kubectl apply` ran last decides whether the kill switch crosses pods at all.
An AI kill switch built on top of this inherits it and will appear to work in
single-pod testing.

**Order:** fix F139 before the AI kill switch is wired, or the AI layer ships
with a decorative emergency stop.

### 2b. "Sandbox — agents run code without touching production" → blocked by **F130** and **F184**
The platform already has a component that writes code to the running system —
`security/self_healer.py` — and both of its safety properties are broken:
* **F130** — patch signing is off and `HEAL_PATCH_SIGNING_KEY` is set nowhere.
* **F184** — `_run_tests()` returns `True` on `FileNotFoundError`, so "could
  not run tests" is recorded as "tests passed" on the gate that admits a patch.

The AI Core sandbox is the same capability with more autonomy. Building it
before these are fixed means shipping a second, larger unsigned code-execution
path.

### 2c. "Evals as a hard gate before sandbox → live" → undermined by **F221/F222**
The spec is right that this must be a gate, not an intention. But the platform
already has a coverage gate, and:
* **F221** — `.coveragerc [run] source` measures **34% of the application**
  (127,878 of 367,949 LOC). `api/` (61k), `monetization/`, `payments/`,
  `security/`, `invariants/` are not measured at all, and the `omit` list
  removes `risk/manager.py` and the decision engine from inside the packages
  that are.
* **F222** — 13 critical modules are never named in any test, including
  `revenue_split.py` and `payments/crypto/address_generator.py`.

A new eval harness added to this measurement culture will inherit the blind
spot. **The eval gate must state what it does not cover**, or it becomes the
next F176.

---

## 3. Where the spec is already ahead of the codebase

Recording these so the review is fair and the good decisions are not lost:

* **The Bitter Lesson exception is correct and should not be softened.**
  Hard-coding drawdown limits and prop-firm rules against model reasoning is
  the right call. The audit supports it: **F94** found regime detection never
  runs, leaving every position sized at 0.5× via a default nobody notices —
  which is what happens when a risk parameter depends on an inference path
  that can silently stop working.
* **Prompt-injection defence framed as "live news and user content are
  untrusted data, not instructions"** is exactly right, and matches **F80**:
  the existing nuclear wordmap matches by bare substring, so a headline
  containing "coupon" scores severity 7 and triggers hedge mode. Untrusted
  text already reaches a control path in this platform today.
* **"Knows everything isn't real — has live access to the feeds you wire up"**
  is the honesty this audit has spent 187 findings arguing for.
* **Section 3's own net assessment** (5 of 9 concepts need real work) is an
  accurate self-appraisal, not a sales document. That is unusual and worth
  keeping.

---

## 4. Superadmin surface ≠ user surface

Carried in from the instruction that preceded this spec: **the hive chat page
needs a superadmin surface distinct from the user surface.** The spec covers
the AI Core page; it does not cover hive chat. Both are recorded here.

The requirement is a **capability split, not a styling split.** The audit's
relevant precedent:

* `/observability` is `adminOnly` at the route level, and that is the right
  mechanism — but **F198** showed route-level assumptions failing in practice
  (`/kyc` and `/mobile` return raw JSON 404 on direct navigation because an API
  router squats the path). Role gating that is only enforced in the SPA is not
  enforced.
* **F209** showed two pages diverging in content while sharing a name and a
  feature gate — the same gate (`featureKey: 'dashboard'`) served two very
  different surfaces for two years without anyone noticing.

**Acceptance criteria to adopt for both hive chat and AI Core:**
1. Every superadmin-only capability is enforced **server-side**, and there is a
   test that a `trader`-role token receives 403 from each such endpoint.
2. A direct `GET` on every superadmin route returns the SPA, not a JSON 404
   (the probe that found F198 — cheap, and it already exists).
3. The two surfaces are separate components, not one component with
   `if (isSuperAdmin)` branches, so a rendering bug cannot leak an admin
   control into the user view.

**Still needed from you:** the hive chat details themselves — what a user does
on that page versus what a superadmin does. Not yet supplied.

**Criterion 1 is now enforced** (`tests/unit/test_superadmin_capabilities_are_server_enforced.py`).
Verified rather than assumed: all **220** endpoints under `api/superadmin/`
already carry a server-side role dependency, and the seven nuclear controls —
halt, resume, hedge activate/deactivate, risk override — additionally require a
TOTP-verified token through `require_superadmin_2fa`. The test exists so the
221st cannot ship without one; it was proved to catch an unguarded endpoint by
adding one and watching it fail.

A first pass reported those seven nuclear endpoints as *unguarded*. They are the
most strictly guarded in the package — they reach the base dependency through a
wrapper, which a narrower pattern did not see. Trace reachability before
assigning severity.

---

## 5. Item 6 — the exposed superadmin credential

The spec lists this as unresolved and higher priority than everything else in
its own list. Agreed, and it should sit above the AI Core work entirely.

**What I checked (read-only), and what I found:**
* `k8s/k8s-secrets.yaml` — committed, but uses `<BASE64…>` placeholders.
* `.env.example` / `.env.production.example` — `ADMIN_USER_IDS` is empty;
  entries read as templates.
* `.secrets.baseline` — 26 files carry entries flagged by `detect-secrets` and
  since baselined. Baselined means *reviewed and accepted*, not *proven safe*;
  it is worth re-reading that list rather than trusting the acceptance.

**History now scanned — nothing found.**
`scripts/scan_git_history_for_secrets.py` walks every object reachable from
every ref (**4,301 unique text blobs across 194 commits**) against 13 patterns
that have no legitimate placeholder form: AWS key id, GitHub PAT, Slack token,
Stripe live/test key, OpenAI and Anthropic keys, private-key blocks, three-part
JWTs, Google API keys, SendGrid keys, OANDA tokens, Telegram bot tokens.
**Zero matches.**

A second, filtered pass over credential-shaped assignments and basic-auth URLs
returned only placeholders (`user:pass` in docstrings), `${VAR}` interpolations
and test fixtures — one literally named `sk-ant-VERY-SECRET-KEY-do-not-leak`.
The eight "Basic Auth Credentials" entries in `.secrets.baseline` were read
individually: all documentation placeholders.

**What that establishes, precisely:** no credential of a recognised format has
ever been committed to *this repository*. It does **not** mean the credential is
safe. The exposure may have been a screenshot, a chat, a `.env` on the VPS, or
another repository — and **rotation is the fix regardless**, because removing a
secret from history does not un-leak it: anyone who cloned or forked has it.

**Still needed from you:** where the exposure was seen, if it was not here.

The scanner is re-runnable and honours the repository's existing
`pragma: allowlist secret` marker, so it cannot drift from `detect-secrets`.

Related and already logged: **F180-F183** — `security/encryption.py` and
`security/vault.py` are two unreferenced `SecureVault` classes whose
`rotate_key()` **destroys every stored credential and returns `True`**. If any
rotation tooling is written for this credential, it must not use those.
**Now disarmed (F262):** `security/encryption.py::rotate_key` raises
`NotImplementedError` naming `config/vault.py` instead of silently orphaning
every ciphertext. `security/vault.py::rotate_keys` needed no change — its
docstring already tells callers they must re-encrypt. The
live vault is `config/vault.py`, which is correct.

---

## 6. Smaller notes worth not losing

* **"Customizable settings"** — the spec flags this as dropped from later
  drafts and belonging back in (theme, department visibility, notification
  thresholds, default autonomy per department), distinct from the per-action
  autonomy dial. Recorded. Note the existing `/settings` surface has 16
  sections behind a shared `ui.tsx`, so this has somewhere to live.
* **VPS sizing (Section 8)** — 7B–8B is the realistic local tier without a GPU
  upgrade. Confirm actual specs before committing. Related: **F98/F178** —
  there are two ConfigMaps named `hopefx-config` with contradictory safety
  values, so "what is actually deployed" is not currently a settled question.
  Settle that before adding a local model service to it.
* **Figma Starter rate limit** — a real constraint on iteration. The spec's
  own recommendation (confirm department names *before* rebuilding) is right.
* **Playwright** — available and already in use in this repo for the audit
  harness; the spec's note that it is unavailable applies to the chat
  interface, not here.

---

## 7. What I recommend, in order — not started

1. **Rotate the credential** (spec item 6). Above everything.
2. **F95 — CI has not run on `main` for 30+ pushes.** Nothing above or below
   is verified until this is green. Owner-blocked; Actions billing.
3. **F139, F130, F184** — the three prerequisites in Section 2. Small, and they
   unblock the kill switch and sandbox.
4. **Adopt the two acceptance tests in Section 1** before writing agent code —
   scope-bypass and approval-bypass must fail the build. **DONE** —
   `enforce_agent_action` (a new `agent_action` enforcement kind) plus
   `tests/unit/test_agent_actions_are_enforced_not_prompted.py`. See F260: every
   predicate already existed and none was reachable.
5. **Confirm the six Business Operations department names** (spec item 2), then
   rebuild Figma once.
6. Then the AI Gateway / MCP bus / cache / guardrails plumbing (spec item 1).

The money findings (**F203/F204/F208** — payouts destroying money, balances in
RAM) are not in this list because they are a separate track, but they remain
the highest-severity open items in the audit and are not superseded by this
spec.
