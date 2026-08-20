# Agent skills

Skills in this directory are discovered automatically by Claude Code. Each lives
in `<name>/SKILL.md`, with supporting material in `<name>/references/` and
`<name>/scripts/`.

Everything here is **vendored from an upstream project and adapted for HOPEFX**.
Adaptation is not optional: an unmodified skill points at another repository's
directories, CI, and conventions, and will confidently give wrong instructions.

---

## Installed

| Skill | Upstream | What it does |
|-------|----------|--------------|
| `ui-ux-pro-max` | [regutierrez/ui-ux-skill] | UI/UX design intelligence: a BM25 search over ~800 rows of styles, palettes, font pairings, chart types, UX guidelines, and per-stack best practices. Relevant here because `frontend/` is React 19 + Vite + Tailwind. |
| `codebase-audit` | [CloudBase-AI-Toolkit] | Full-codebase review, severity classification, issue filing, worktree-isolated fixes. |
| `pr-review-fix` | [CloudBase-AI-Toolkit] | Triage open PRs: CI failures, review comments, batch repair. |
| `doc-freshness-review` | [CloudBase-AI-Toolkit] | Audit docs for drift against the code. |
| `skill-authoring` | [CloudBase-AI-Toolkit] | Write and review skills: trigger wording, progressive disclosure, evaluation. |
| `manage-local-skills` | [CloudBase-AI-Toolkit] | Inspect, validate, and install skills across agent directories. Ships a working Node validator. |
| `planning-workflows` | [CloudBase-AI-Toolkit] | Spec vs. no-spec planning modes. |
| `review-automation-orchestrator` | [CloudBase-AI-Toolkit] | Dispatches a periodic review cycle to the right reviewer above. |

[regutierrez/ui-ux-skill]: https://github.com/regutierrez/ui-ux-skill
[CloudBase-AI-Toolkit]: https://github.com/TencentCloudBase/CloudBase-AI-Toolkit

## Provenance

| Upstream | Commit | Licence |
|----------|--------|---------|
| `regutierrez/ui-ux-skill` | `26cc83db2aced632ae97dea7bcc6ae0c6a2c39f4` | MIT — `licenses/ui-ux-skill.MIT.txt` |
| `TencentCloudBase/CloudBase-AI-Toolkit` | `46855cd6b6e4d53cf0d3022a2c7d2e2cfaf94279` | MIT — `licenses/CloudBase-AI-Toolkit.MIT.txt` |

Both licences require the copyright notice to be retained; the texts are kept
verbatim under `licenses/`.

---

## Local patches

Anything below diverges from upstream. Re-apply it after a version bump.

### `ui-ux-pro-max`

Upstream publishes only `SKILL.md`; the engine lives in the repo's `cli/assets/`
tree and is copied into place by their `uipro init` CLI. We vendored it directly
instead, so there is no install step and no runtime dependency beyond Python 3
(stdlib only — no network, no subprocess).

- Copied `cli/assets/scripts/*.py` → `scripts/`, `cli/assets/data/**` → `data/`.
  `core.py` resolves data as `Path(__file__).parent.parent / "data"`, so the two
  must stay siblings.
- Rewrote the 12 invocation paths in `SKILL.md` from `skills/ui-ux-pro-max/...`
  to `.claude/skills/ui-ux-pro-max/...`.
- **Fixed corrupt CSV data.** `landing.csv` rows 28–30 had an unterminated quote:
  three landing patterns (Bento Grid Showcase, Interactive 3D Configurator,
  AI-Driven Dynamic Landing) were unreachable, and their raw text leaked into the
  "Conversion Optimization" field of pattern 27, so `--design-system` emitted
  visible CSV garbage. Also repaired a field misalignment in row 26 and a missing
  `Don't` column in `stacks/astro.csv` (row 35) and `web-interface.csv`
  (rows 19, 26, 27). Re-report upstream rather than re-fixing on the next bump.
- **Fixed SKILL.md/CLI drift.** The docs advertised a `prompt` domain that
  `search.py` rejects, and omitted the `icons` domain that it accepts.
- **Trimmed the stack datasets** to the five this repo can use: `html-tailwind`,
  `react` (`frontend/`), `nextjs`, `react-native` (`mobile-app/`), and `shadcn`.
  Dropped `astro`, `vue`, `nuxtjs`, `nuxt-ui`, `svelte`, `swiftui`, `flutter`,
  and `jetpack-compose` — `STACK_CONFIG` in `core.py` and the tables in
  `SKILL.md` were trimmed to match, so the CLI never offers a stack whose data
  is absent. Re-add the CSV *and* the `STACK_CONFIG` entry together if a stack
  is adopted. This also removed a Nuxt row that `scripts/check_secrets.sh`
  flagged: a documentation example naming `dbPassword` in order to teach that it
  must not go in public runtime config. Dropping the unused file was preferable
  to adding an exclusion to a security gate.
- Whitespace and end-of-file normalisation applied by this repo's pre-commit
  hygiene hooks. Ignore it when diffing against upstream.

Verify after any change:

```bash
python3 .claude/skills/ui-ux-pro-max/scripts/search.py "fintech trading dashboard dark" --design-system -f markdown
```

`--persist` writes to `design-system/` in the working directory. Nothing else
writes to disk.

### CloudBase skills

All seven were rewritten away from CloudBase's own repository:

- `config/source/skills` → `.claude/skills` throughout; dropped the
  `plugin/cloudbase/skill-metadata.json` packaging steps, which have no analogue
  here.
- `codebase-audit`: default audit target was CloudBase's `mcp/src/`. Its
  `security-severity-checklist.md` was a Tencent bug-bounty rubric keyed to
  QQ/WeChat asset tiers and CNY thresholds — the vulnerability taxonomy (RCE,
  SQLi, SSRF, IDOR, XSS, path traversal) was kept, the asset qualifiers were
  replaced, and a **trading-system escalation rule** was added at the top:
  anything touching the risk gate, kill switch, ML staleness/drift gating, order
  execution, broker credentials, the decision pipeline, or prop-firm limits is
  Critical regardless of its generic tier, and is never auto-fixed into a PR.
- `pr-review-fix`: `ci-pipeline.md` rewritten for this repo's actual workflows,
  the 3.11/3.12 matrix, and local reproduction commands. The environment-gating
  recipe was TypeScript/`test.skipIf`; it is now pytest markers.
- `doc-freshness-review`: `review-scope.md` rewritten around this repo's real doc
  surfaces, tiered by blast radius, with the agent contracts (`CLAUDE.md`,
  `AGENTS.md`, `ARCHITECTURE.md`) first — drift there misleads every later change.
- `review-automation-orchestrator`: dispatch table repointed at the skills that
  are actually installed, plus the built-in `/code-review` and `/security-review`.
- `skill-authoring`: CloudBase frontmatter examples replaced with HOPEFX ones.

---

## Evaluated and rejected

Recorded so they are not re-proposed.

**`home-assistant/frontend` `.agents/skills` — all 11 skills, rejected.**
`ha-frontend-components`, `-contexts`, `-demo`, `-events`, `-gallery`, `-lit`,
`-review`, `-styling`, `-testing`, `-types`, `-user-facing-text`. They are
high-quality but bound to Lit web components, the `hass` object, Lovelace cards,
and paths (`gallery/`, `demo/`, `src/panels/`) that do not exist here. This
repo's frontend is React 19 + Vite + Tailwind, so they would have triggered on
frontend work and given Lit conventions for React code.

**`CloudBase-AI-Toolkit` — 3 of 11 skills, rejected.**

| Skill | Why |
|-------|-----|
| `api-contract-review` | Audits CloudBase cloud API wrappers and generated action metadata. Nothing analogous here. |
| `mcp-attribution-worktree` | Drives CloudBase's internal attribution report API and Worktrunk. Unreachable infrastructure. |
| `docs-workflows` | 14 files of CloudBase docs-site authoring (tutorial/AIIDE/prototype templates). |

**`git-workflows`** was installed and then removed. Its 529-line reference is
CloudBase release tooling — release-note templates branded "CloudBase MCP", IDE
icon-consistency checks against a sibling `cloudbase-docs` checkout — and its
commit guidance duplicates and partially conflicts with `CONTRIBUTING.md` and
`CLAUDE.md`, which are authoritative here.

---

## Adding or updating a skill

1. Install into `.claude/skills/<name>/`, with `name:` in the frontmatter equal
   to the directory name.
2. Validate: `node .claude/skills/manage-local-skills/scripts/validate-skill.mjs --skill-dir <name>`
3. Run any bundled script at least once. A skill whose tooling does not run is
   worse than no skill — the model will keep trying to invoke it.
4. Grep for upstream-specific paths, CI names, and product names, and repoint
   them. This is where most of the work is.
5. Record the upstream commit, licence, and every local patch above.

`.claude/` is excluded from `ruff.toml` and from the `healer-check` and
`coverage-gate` pre-commit hooks: vendored code should not be reformatted to
this repo's rules or held to its coverage gate, or it can no longer be diffed
against upstream.
