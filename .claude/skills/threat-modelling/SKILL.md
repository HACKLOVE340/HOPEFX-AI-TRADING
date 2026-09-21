---
name: threat-modelling
description: Threat model a HOPEFX surface end to end — identify threats with STRIDE, map the paths an attacker would actually take, bind each threat to a control that exists and runs, and turn what is left into security requirements and test cases. Use when adding or changing an authentication path, a money movement, an order route, an operator or superadmin action, an AI control-plane capability, or any externally reachable endpoint; when reviewing security design; and when asked to threat model, find defence gaps, or produce security requirements.
---

# Threat modelling

One workflow in four stages. It was four skills — `stride-analysis-patterns`,
`attack-tree-construction`, `threat-mitigation-mapping` and
`security-requirement-extraction` — each a thin router over a large reference
file. They are stages of a single activity, and splitting them meant the
routing layer had four ways to answer one question while the reference content
stayed where it was. The content is unchanged and lives under `references/`;
only the entry point merged.

## The four stages

| Stage | Question | Reference |
|---|---|---|
| 1. Identify | What can go wrong here? | `references/stride.md` |
| 2. Path | How would someone actually get there? | `references/attack-trees.md` |
| 3. Map | Which control stops it, and does that control run? | `references/mitigation-mapping.md` |
| 4. Require | What must be built and tested? | `references/security-requirements.md` |

Read the reference for the stage you are in. Do not read all four up front.

## The four trust boundaries in this platform

Name the boundary before applying STRIDE — a threat model without a boundary
produces a list that is true of every system and actionable for none.

| Boundary | Where it lives | What crossing it costs |
|---|---|---|
| **Order path** | `core/decision/HOPEFXDecisionEngine.py` → `risk/manager.py` → `execution/oms.py` → `brokers/` | A position opened, sized or routed against intent |
| **Money path** | `payments/`, `monetization/`, `api/billing.py`, `api/accounts.py` | Value created, destroyed or moved |
| **AI control plane** | `ai/`, `ml/inference_engine.py`, `ai/hub/capabilities.py`, `enforce_agent_action` | An agent acting outside its authorized scope |
| **Operator surfaces** | `api/superadmin/`, `api/settings_extended.py`, `auth/service.py` | A privileged action taken, or taken unattributably |

## Stage 3 is where this repository has actually been bitten

Mapping a threat to a named control is not the end of stage 3. **The control
must be traced to a call site that executes.** This platform's most common
defect is a control that exists, reads correctly, and never runs — see
`../hopefx-dead-controls/SKILL.md`. A threat model that maps a threat to a dead
control has documented a defence that is not there, and is worse than one that
records the threat as unmitigated, because it closes the item.

Two findings from threat-modelling this repository, both real, both found at
stage 3 rather than stage 1:

* **STRIDE-R, repudiation.** A superadmin action taken while the audit database
  was unreachable left a hash chain that still verified clean. The control
  existed; it verified its own memory rather than what was persisted. The
  threat was "an operator denies an action"; the mapped control was the chain;
  the chain could not fail.
* **STRIDE-D/S, denial of service and spoofing.** The change-password throttle
  failed open when its backing store was unreachable, and said so at `DEBUG`.
  Unlimited password attempts were served, and nothing in production logging
  recorded it.

Both are the same shape: the control was named correctly in the model and did
not run in the condition the threat describes. So at stage 3, for every mapped
control, answer two questions in writing:

1. Which call site invokes it, on the path the threat takes?
2. What happens to it when its dependency is down — does it refuse, or does it
   fail open and log quietly?

## Stage 4 output

A requirement that cannot fail a test is a wish. Each requirement leaves this
stage with a test that **injects the threat** and asserts the refusal — the
same standard as `docs/GATE_EVIDENCE.toml`, where a row counts as proven only
when it cites a test that introduces the defect. Where the control is an
invariant, `../hopefx-invariants/SKILL.md` governs the predicate's shape.

## Do's and don'ts

**Do** cover all six STRIDE categories — each reveals a different class, and
repudiation and elevation are the two most often skipped here. **Do** model the
dependency-down state explicitly; that is where both findings above lived.
**Do** treat a threat you cannot map to a running control as open, and record
it as open.

**Don't** stop at identification. **Don't** accept "the gate handles it"
without naming the call site. **Don't** widen or downgrade a control to close a
finding — that is weakening a risk gate, which `CLAUDE.md` forbids without
explicit instruction.

## Not for this skill

* Configuring the scanners that find code-level issues — `../sast-configuration/SKILL.md`.
* Card data handling specifically — `../pci-compliance/SKILL.md`.
* Cluster-level network and RBAC policy — `../k8s-security-policies/SKILL.md`.
* Proving a control can fail once you have one — `../hopefx-dead-controls/SKILL.md`.
