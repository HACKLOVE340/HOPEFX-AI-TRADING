# Choosing the AI provider (Claude vs OpenAI)

HOPEFX's AI features — the chat assistant, the strategy-generation "brain", and
the security-analysis agent — run through **one** LLM layer (`brain/llm_agent.py`,
`brain/llm_wrapper`). You pick the provider with **environment variables only** —
there is **no code change** and no new integration to build. Both providers are
already implemented.

## The three variables

| Variable | What it does | Example |
|----------|--------------|---------|
| `LLM_BACKEND` | Which provider to use: `anthropic` (default) or `openai` | `openai` |
| `ANTHROPIC_API_KEY` | Claude key — required when `LLM_BACKEND=anthropic` | `sk-ant-...` |
| `OPENAI_API_KEY` | OpenAI key — required when `LLM_BACKEND=openai` | `sk-...` |
| `ANTHROPIC_MODEL` | (optional) Claude model | `claude-sonnet-4-5` |
| `OPENAI_MODEL` | (optional) OpenAI model | `o4-mini` / `gpt-4o` |

Set **one** provider and its matching key. The app reads these at startup.

## Use Claude (default)

In your server's `.env`:

```env
LLM_BACKEND=anthropic
ANTHROPIC_API_KEY=sk-ant-your-key
```

## Use OpenAI

In your server's `.env`:

```env
LLM_BACKEND=openai
OPENAI_API_KEY=sk-your-key
# optional: OPENAI_MODEL=gpt-4o
```

Then restart the app (`docker compose restart app`, or restart your process).

## 🔒 Security — read this

- **Never paste an API key into a chat, ticket, screenshot, or commit.** A key is
  full billable access to your account.
- The key lives **only** in `.env` on the server. `.env` is gitignored — it is
  never committed and is not overwritten by deploys, so it's the correct place.
- If a key was ever exposed, **revoke and regenerate it immediately**
  (Anthropic console / OpenAI dashboard).

## Where it's used in the code

- `brain/llm_agent.py` — provider selection + client construction
  (`LLM_BACKEND` → Anthropic Messages API or OpenAI Chat Completions).
- `api/chat.py`, `api/brain.py` — the endpoints the UI calls.
- The `.env.example` block (search `LLM_BACKEND`) documents every variable.
