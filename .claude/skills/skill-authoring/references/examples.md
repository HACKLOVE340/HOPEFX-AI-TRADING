# Examples

## Good Frontmatter Example

```yaml
---
name: risk-gate-review
description: Reviews changes to the pre-trade risk gate, VaR/CVaR sizing, Kelly sizing, and the kill switch in `risk/manager.py`. This skill should be used when a change adds, relaxes, reorders, or bypasses a risk check, changes position-size limits or drawdown thresholds, or touches the kill-switch trip or reset path.
---
```

Why it works:

- The opening phrase clearly defines the surface the skill owns
- The trigger sentence states when the skill should activate
- The keyword mix covers the module, the concepts, and the concrete actions that should trigger it

## Weak Frontmatter Example

```yaml
---
name: the-best-skill-for-all-risk-and-trading-work
description: A powerful skill for many different trading tasks.
---
```

What is weak about it:

- The name is too long and unstable
- The description is broad and vague, so it triggers on unrelated work
- The trigger boundary is unclear

## Better Rewrite

```yaml
---
name: risk-gate-review
description: Reviews changes to the pre-trade risk gate and kill switch. This skill should be used when a change touches `risk/manager.py`, position sizing, drawdown or exposure limits, or the kill-switch trip and reset path.
---
```

## Good Structure Example

A strong structure for a complex skill usually looks like this:

- `SKILL.md` for entry point and routing
- `references/` for deeper methodology
- `assets/` for reusable templates or sample materials
- `scripts/` for executable helper capabilities

## Bad Structure Example

Common structural problems:

- A single `SKILL.md` contains everything
- Many files exist but there is no routing
- Rules, examples, templates, and FAQ are mixed together

## Example Evaluation Prompts

### Should-Trigger

1. Help me write a new skill for guiding agents to document MCP tools.
2. This skill description is not activating reliably. Rewrite it to improve trigger quality.
3. I need to split a large `SKILL.md` into a main file and references. Design the structure.

### Should-Not-Trigger

1. Help me make this README sound more polished and persuasive.
2. Help me implement a new MCP tool.
3. Help me improve the visual design of this React page.
