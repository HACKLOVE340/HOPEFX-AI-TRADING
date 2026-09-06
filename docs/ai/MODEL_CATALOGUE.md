# Model catalogue

Every model this platform may route to, with the date a human last checked that
it still exists, is still supported, and is still the right choice for its role.

**Why this file exists.** The committed chain defaults named `gpt-4o` and
`claude-3-5-sonnet-20241022` — two 2024 models — in September 2026, and nothing
noticed. They were hard-coded in a module, so going stale was silent and fixing
it needed a redeploy (audit D8). Good defaults today are not a fix for that.
A check that notices when they rot is.

`tests/unit/test_model_catalogue_freshness.py` asserts two things, and CI runs
it on every push:

1. **Every model in `ai/gateway/chain.py::DEFAULT_CHAINS` appears in the table
   below, under the same provider.** A default the catalogue has never heard of
   is a default nobody reviewed.
2. **Every `reviewed_on` is within 180 days.** The row goes stale on a
   schedule, and the build says so, rather than a person having to remember.

**How to review.** Open the vendor's current model list, confirm the identifier
still resolves and is not deprecated, confirm the role assignment still makes
sense against what has shipped since, then update `reviewed_on` in the same
commit as any change to `DEFAULT_CHAINS`. Bumping the date without doing the
check is the one thing that makes this file worse than nothing.

Identifiers are **data, not code**: a superadmin edits the live chain in AI
settings, and the table below records what the committed defaults are — not a
limit on what may be configured.

## Catalogue

| Model | Provider | Role | Position | reviewed_on | Notes |
|---|---|---|---|---|---|
| `claude-opus-5` | anthropic | reasoning | primary | 2026-09-05 | Strongest reasoning tier available to this platform; carries the decisions where being wrong costs money. |
| `gpt-5.5` | openai | reasoning | fallback 1 | 2026-09-05 | Deliberately a **different vendor** from the primary. A cheaper model in the primary's own family shares that vendor's control plane, auth and status page, so both legs fail together in the incident the fallback exists for. |
| `gemini-3.1-pro` | google | reasoning | fallback 2 | 2026-09-05 | Third vendor. Reached only when two others are down; its job is to keep the platform answering, not to match the primary. |
| `claude-sonnet-5` | anthropic | fast | primary | 2026-09-05 | The high-volume tier: classification, extraction, summarisation. |
| `claude-haiku-4-5-20251001` | anthropic | fast | fallback 1 | 2026-09-05 | Same vendor on purpose here — a `fast` outage degrades throughput, not correctness, so latency wins over vendor diversity. |
| `gemini-3.5-flash` | google | fast | fallback 2 | 2026-09-05 | Cross-vendor leg for the `fast` role. |
| `gemini-3.5-flash` | google | vision | primary | 2026-09-05 | Chart and screenshot reading. |
| `claude-opus-5` | anthropic | vision | fallback 1 | 2026-09-05 | Vision-capable fallback; more expensive, so it is not the primary for a high-volume role. |
| `text-embedding-3-large` | openai | embedding | primary | 2026-09-05 | Changing this **invalidates every stored vector**: embeddings from two models are not comparable. Re-index before switching, never after. |
| `gemini-embedding` | google | embedding | fallback 1 | 2026-09-05 | Same warning applies; a fallback that silently writes vectors from a second model into one index produces a corrupt index, so the embedding role should be pinned in production rather than allowed to fall through. |
| `llama3` | ollama | reasoning (local, opt-in) | not in the default chain | 2026-09-05 | Local inference is **optional, off by default, and never a primary leg**. Capability drops sharply against every row above; it exists for a deployment that must not egress prompts, and the UI has to say so. `OLLAMA_MODEL` overrides the identifier; `OLLAMA_BASE_URL` is what makes the provider reachable at all. |

## Not routed to

Recorded so a future reviewer does not have to re-derive the decision:

| Model | Why not |
|---|---|
| `gpt-4o`, `claude-3-5-sonnet-20241022` | The 2024 defaults D8 found still committed in 2026. Superseded on every axis; kept here only as the reason this file exists. |
| Any model chosen for price alone | The `reasoning` role decides trades. A cheaper model that is wrong more often is not cheaper. |
