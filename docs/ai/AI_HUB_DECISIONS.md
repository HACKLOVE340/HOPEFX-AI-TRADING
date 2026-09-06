# AI Hub — decisions of record

Decisions taken against **AI Hub Institutional Master Architecture &
Implementation Specification v1.0**. Recorded here rather than left in chat,
because §30 requires each phase to report what was decided and why, and a
decision nobody can find is a decision that gets re-litigated.

Add to this file; do not rewrite it. A superseded decision keeps its entry and
gains a note.

---

## D1 — The five capabilities §3 says exist but do not

**Decided: build them. There is no second prototype to merge.**

§3 lists these as existing and therefore to be preserved: particle field,
cognitive stream, neural engine, sleep monitor, GPU monitoring. An audit of the
whole repository — not only the frontend — found none of them.

What *does* exist, and is preserved rather than rebuilt: the holographic stage
(`frontend/src/index.css:230-239` — two counter-rotating orbital rings, a
scan-line overlay, a projection glow, a 3D perspective and a reduced-motion
guard), the multi-display console (`useAICommandCenter.ts`, six live sources
with degraded-source tracking), the camera (`VisualIntelligenceWorkspaces.tsx`),
voice (`hooks/useVoice.ts`), and real model/spend/drift telemetry.

The five absent capabilities are registered in `ai/hub/capabilities.py` with a
note recording the discrepancy, so they cannot be silently dropped:

| Capability id | Lands in |
|---|---|
| `presence.particle_field` | Phase 1 |
| `legacy.cognitive_stream` | Phase 2 |
| `legacy.neural_engine` | Phase 4 |
| `legacy.sleep_monitor` | Phase 4 |
| `telemetry.host` | Phase 4 |

---

## D2 — Where the Hub lives

**Decided: a new route the login lands on. The 85 existing routes stay.**

§4 forbids a permanent dashboard as the primary interface. The minimum change
that satisfies it without deleting anything is to move the front door, not to
remove the rooms behind it.

* The Hub becomes the post-login destination.
* Every existing route stays reachable and unchanged.
* Existing pages become *surfaces the Hub can summon* (§8) as well as routes.
* The change ships behind a feature flag, per §30-I, so the previous landing
  page is one flag away for the life of the rollout.

Nothing is deleted. `AICore` in particular is preserved as the governance and
observability surface — §29 requires that agent workflows be auditable, and that
page is where an operator reads the audit.

---

## D3 — Voice

**Decided: the AI gets its own consistent voice. Local synthesis first,
a hosted provider as the upgrade.**

The high-quality path already exists and is wired: `api/voice.py` serves
`POST /api/voice/tts` and `/stt` behind auth and a quota, with ElevenLabs or
OpenAI for synthesis and Whisper for recognition, and `useVoice.ts` already
probes `/voice/status` and falls back to Web Speech when no key is configured.
So this is a configuration decision, not a build.

The reason for choosing is **identity, not fidelity**. Web Speech uses whatever
voice the operating system provides, so the AI currently sounds like a different
person on every machine and has no voice of its own. A single synthesis source
gives it one.

The second reason is **privacy**. This assistant reads balances, positions and
risk limits aloud. Local synthesis means those sentences never leave the host.

| Route | Cost | Identity | Where the text goes |
|---|---|---|---|
| Local neural TTS on the VPS | free after setup | one voice, consistent everywhere | nowhere |
| ElevenLabs (`ELEVENLABS_API_KEY`) | metered | a chosen or cloned voice id | the vendor |
| OpenAI (`OPENAI_API_KEY`) | metered, cheaper | six presets | the vendor |

Local first; the hosted providers stay one environment variable away and the
code path is already written. Neither blocks Phase 0, and both land in Phase 1.

Open: whether the VPS can run a neural TTS model at acceptable latency.
`scripts/vps_capability_report.py` answers that and has not been run against the
production host.
