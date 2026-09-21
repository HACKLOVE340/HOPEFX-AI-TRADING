# What is left on the AI Core, and what still needs fixing

**Written 2026-09-06, measured not asserted.** Every count below came from
running a query against the tree, and each query is shown so it can be re-run.

This document exists because I reported the AI Core as "complete" and it is not.
What was built is the **engine** — spec §3's nine engineering concepts. What the
spec also describes — §4's department directory, §5 generative media, §6's
capability list, §7 skill tiers, §8 local model sizing — is untouched. And three
of the seven subsystems that *were* built have **no production caller**, which
is this audit's signature defect reproduced by the work meant to fix it.

---

## 1. The correction: three built subsystems are dead code today

```
grep -rn "<symbol>" --include=*.py . | grep -v ".venv|tests/|^./ai/"
```

| Subsystem | Production callers | Honest status |
|---|---:|---|
| **Gateway** — chain, budget, audit, adapters, guardrails | **4** | Load-bearing. `api/brain.py` ×2, `brain/llm_agent.py`, `security/llm_wrapper.py` (and `security/self_healer.py` through the last). Every model call in the repository goes through it, asserted by `tests/unit/test_no_model_call_bypasses_the_gateway.py`. |
| **Evals gate** | 1 | Bound to canary promotion in `api/safe_agent_platform.py`. **But `set_eval_report` has zero callers**, so `_EVAL_REPORT` is always `None` and the gate always refuses `no_eval_report`. Fail-closed, which is the right direction — and it means canary promotion is currently *impossible*, not merely gated. The eval **runner** is the missing piece. |
| **Response cache** | **0** | `install_shared_cache()` is called by nothing. The cache is correct and tested; no deployment installs one, so every call still reaches a provider. |
| **Tool bus** | **0** | `ToolBus(...)` is constructed nowhere in production and **no tool is registered on it**. It gates on `ToolPermissionRegistry.review` *and* `enforce_agent_action` — 16 constitutional predicates whose first production caller this was meant to be. Today it is still zero. |
| **Sandbox** | **0** | Nothing runs code through `ai/sandbox/`. `marketplace_submission`'s static filter is the only thing standing in front of submitted strategy code, and that filter says in its own docstring it is not containment. |

**This is the same finding class as D1–D8.** A control that exists, is
documented, is tested, and is never invoked. I wrote three of them and reported
them as done. The tests prove the units work; they do not prove anything runs.

### What closing it takes

| Gap | Work |
|---|---|
| Cache unused | Call `install_shared_cache()` in `core/startup_factories.py` and pass it into the four `GatewayClient(...)` sites. Small. Needs a decision on TTL and whether the tool-state key is wired to anything real. |
| Tool bus unused | Register the first real tool. The natural candidates are the read-only ones: `run_backtest()`, `score_regime()`, `check_drawdown()`. Until one is registered, `enforce_agent_action` still has no production caller. |
| Sandbox unused | Route `marketplace_submission`'s approved code and `brain/llm_agent`'s generated strategies through `ai.sandbox.run()` before either is trusted. This is the one with real security value. |
| Evals gate can never pass | Write the eval **runner**: a suite of cases, a runner that calls the gateway, and the call to `set_eval_report()`. Without it the gate is a permanent "no". |

---

## 2. The spec's §4–§8: not started

My plan's own self-review said so ("Not covered here, deliberately"), but the
summary I gave did not. Measured: **zero** of the department agents exist.

```
grep -rn "Compliance Guard|Execution Agent|Model Analyst|Research Scout|
         Code Auditor|Deploy Sentinel|Broker Liaison|Risk Monitor" --include=*.py .
→ no matches
```

| Spec § | What it describes | Built? |
|---|---|---|
| **§4 Cluster A** — Trading Core | 4 departments × (agent, actions, memory, awareness): Markets & Execution, Risk & Compliance, Research & Intelligence, Platform Engineering | **No.** No agent, no action registry, no per-department memory, no awareness triggers. |
| **§4 Cluster B** — Business Operations | 6 departments × 6 skills each (Design, Marketing, Social, Corporate Finance, Legal, Client & Ops) | **No.** Names confirmed by the owner; nothing implemented. |
| **§5** Generative media | 3D avatar + TTS/viseme, image generation, video (phase 2), live news | **No.** Blocked on §8 for the self-hosted path. |
| **§6** Master capability list | ~25 capabilities | **Partially.** Guardrails, failure resilience, governance, observability and permission scoping are real. Deep reasoning, adaptive behaviour, multi-modal, plugin architecture, data residency are not. |
| **§7** Skill tiers | Plug-ins / Skills / MCP servers | **Tier 2 only**, and only as `.claude/skills/` for *development*, not as runtime agent skills. |
| **§8** Local model sizing | Pick a tier from real VPS specs | **Blocked on you.** `scripts/vps_capability_report.py` exists and must be run on the VPS. |

**The dependency that matters:** §4's departments are the thing that makes the
tool bus, the sandbox and the eval runner load-bearing. Building the departments
*is* what gives those three subsystems their production callers. Doing §4 first
closes §1's gaps as a side effect; doing §1's gaps first is busywork that §4
would rewrite.

---

## 3. Owner-blocked, unchanged

| # | Item | What is needed from you |
|---|---|---|
| 1 | **Rotate the exposed superadmin credential** — spec §12.6, "higher priority than everything above" | Where the exposure was seen. It is **not in this repository**: 4,301 blobs across all 194 commits, 13 patterns, zero matches. Rotation is still the fix; removing a secret from history does not un-leak it. |
| 2 | **VPS RAM/VRAM report** (§8, and §5 depends on it) | Run `scripts/vps_capability_report.py` on the VPS and paste the output. |
| 3 | **CodeQL: 2 critical / 12 high** | The rule ID, file and line from the Security tab. Unchanged across all 25 commits today, so nothing new was introduced — 3 of the 14 are attributable to the v0 merge. |
| 4 | **Two model artefacts fail integrity and do not load** | Which artefacts are canonical. |
| 5 | **Vercel** — `v0-new-project-8ud36nesln3` | Disconnect the integration. It is a scratch project hitting a free-tier daily deploy limit; not our code, and it will stay red until it is disconnected. |
| 6 | **Vendor accounts** for the model chain | Which of Anthropic / OpenAI / Google are contracted. A leg with no key is skipped, so an unconfigured chain silently has fewer legs than it appears to. |
| 7 | **Budget ceilings** | Per operator and global, per month. Defaults are $25 / $250, chosen conservatively, not by you. |
| 8 | **OANDA venue verification** | The adapter has never run against the venue. |

---

## 4. Audit items still open (non-AI)

| # | Item | Severity |
|---|---|---|
| 3 | F218 — re-measured: tables covered; 8 *columns* were not | ~~HIGH~~ **fixed** |
| 9 | Coverage measures 38.6% of the application | MEDIUM |
| 10 | `execution/` omissions, with measured debt | MEDIUM |
| 11 | F223 — 75 metric-named files, 1,125 assertion-free tests | HIGH |
| 21 | F216/F217 — the `data/` ↔ `data_layer/` boundary is undocumented | MEDIUM |
| 22 | `REMEDIATION_PLAN.md` is stale | MEDIUM |

Closed: 3 (schema drift), 4 (money columns), 5 (**8 of 8** modules),
6 (crypto currency), 12 (coverage gate), 24 (dependency scan).

---

## 5. Recommended order

1. **The three owner decisions that cost nothing to make** — Paystack FX rate,
   `TickQuality.UNKNOWN`, Stripe hardening. Being fixed now.
2. **§4 Cluster A — Trading Core departments.** Four departments, each with a
   real action registry on the tool bus. This is what turns the bus, the
   sandbox and the eval runner from tested code into running code, and it is
   the half of §4 that touches money and therefore matters most.
3. **The eval runner**, once departments give it something to evaluate.
4. **§4 Cluster B — Business Operations.** Six departments, no money path,
   safe to build after A.
5. **§5 generative media**, only once the VPS report (owner item 2) lands.
