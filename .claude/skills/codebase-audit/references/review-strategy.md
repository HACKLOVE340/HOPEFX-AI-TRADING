# Review Strategy

## Scope

Default target: the module under review. This repository is Python-first
(`api/`, `core/`, `brain/`, `ml/`, `risk/`, `execution/`, `data_layer/`) with a
React/TypeScript SPA under `frontend/`. There is no single source root — ask the
user which package to audit. Upstream defaulted to "all TypeScript files", which
is the wrong default here.

Before starting, confirm the scope:
```bash
# Python packages
find <target-dir> -name '*.py' -not -path '*/.venv/*' | wc -l

# frontend/
find frontend/src -name '*.ts' -o -name '*.tsx' | wc -l
```

## Approach

Read every file in scope, covering ALL review categories in one pass. Do NOT
sample — a sampled audit reports a clean bill of health it did not earn.

Upstream instructs delegating this to a `code-explorer` subagent and launching
parallel subagents past 50 files. Neither applies here: no `code-explorer` agent
exists, and this repository's operating rules forbid spawning agents unless the
user explicitly asks. Read the files directly. If the target is large enough that
this is impractical, split it by subdirectory and audit one subdirectory per
pass, rather than sampling within a single pass. If the user does ask for
subagents, use `general-purpose` — **not** `Explore`, which reads excerpts rather
than whole files and will silently miss findings past its read window.

## Review checklist

For **every** file, check each category below. Not every category applies to every file — skip inapplicable ones but never skip a file.

### 1. Security (Critical priority)

For severity classification of security findings, reference `security-severity-checklist.md` which maps each vulnerability type to severity tiers (Critical/High/Medium/Low/Ignore) with concrete technical conditions.

| Check | What to look for | Min Severity |
|-------|-----------------|-------------|
| Path traversal | User-controlled paths not validated with `path.resolve` + prefix check | HIGH |
| Command injection | String interpolation in `exec()`, `execSync()`, shell commands | CRITICAL |
| SQL/NoSQL injection | Unparameterized queries with user input | HIGH (readable data) |
| Hardcoded secrets | API keys, tokens, passwords in source code | MEDIUM |
| Improper error exposure | Stack traces, internal paths, or secrets in error messages returned to clients | MEDIUM |
| Missing input validation | Tool parameters accepted without type/range/format checks | HIGH |
| Prototype pollution | Unchecked `Object.assign`, spread of user-controlled objects | HIGH |
| SSRF | User-controlled URLs fetched without allowlist validation | MEDIUM (blind) / HIGH (with response) |
| Vulnerable dependencies | Known CVEs in direct or transitive dependencies (see `dependency-audit.md`) | Varies |
| Unauthorized data access | Missing auth/ownership checks on user data APIs | HIGH |
| Open redirect | Unvalidated redirect parameters | LOW |
| XSS (stored) | User content rendered without sanitization | HIGH (platform products) / MEDIUM (others) |
| XSS (reflected/DOM) | Input reflected in response without encoding | LOW / MEDIUM |
| CSRF | Missing anti-CSRF tokens on state-changing operations | MEDIUM |
| Arbitrary file read/write | Path traversal in file operations | HIGH (write) / MEDIUM (read) |
| IDOR / privilege escalation | User-controlled IDs without ownership validation | HIGH (core features) / MEDIUM (single endpoint) |
| Rate limiting defects | Missing throttling on auth/sms/OTP endpoints | LOW |

### 2. Error handling (High priority)

| Check | What to look for |
|-------|-----------------|
| Missing try-catch | Async operations without error handling |
| Swallowed errors | `catch` blocks that log but don't rethrow or return error state |
| Generic catch | `catch(e)` that loses error type information |
| Missing finally | Resources opened but not cleaned up on error path |
| Error message quality | Error messages that don't help diagnose the problem |

### 3. Type safety (Medium priority)

| Check | What to look for |
|-------|-----------------|
| `as any` | Unsafe type casts that bypass type checking |
| Missing null checks | Optional values used without `?.` or explicit null check |
| Implicit any | Function parameters or returns without type annotations |
| Incorrect generics | Generic types that don't match actual usage |
| Union type narrowing | Missing type guards before accessing union-specific properties |

### 4. Logic bugs (High priority)

| Check | What to look for |
|-------|-----------------|
| Race conditions | Shared mutable state accessed from async code without synchronization |
| Off-by-one | Loop bounds, slice indices, pagination offsets |
| Unreachable code | Code after unconditional return/throw |
| Incorrect conditionals | Flipped boolean logic, wrong comparison operators |
| Missing edge cases | Empty arrays, zero values, undefined, boundary conditions |
| Dead code | Functions or branches that are never called/reached |

### 5. Code quality (Medium priority)

| Check | What to look for |
|-------|-----------------|
| Duplication | Same logic repeated in multiple places |
| Complexity | Functions > 50 lines, deeply nested conditionals |
| Naming | Misleading variable/function names |
| Inconsistency | Different patterns for the same operation across files |
| Magic values | Hardcoded numbers or strings without explanation |

### 6. Resource management (High priority)

| Check | What to look for |
|-------|-----------------|
| Unclosed connections | Database, HTTP, or file handles not closed |
| Missing cleanup | Temporary files, directories not removed |
| Memory leaks | Growing collections without bounds, event listeners not removed |
| Timeout management | Missing timeouts on network operations |

### 7. API design (Medium priority)

| Check | What to look for |
|-------|-----------------|
| Inconsistent validation | Some tools validate input, others don't |
| Missing required fields | Required parameters not checked at entry |
| Return type inconsistency | Same operation returns different shapes in different code paths |
| Error response format | Inconsistent error formats across tools |

## Recording findings

For each finding, capture:

```
File: <path>
Lines: <start>-<end>
Category: <Security|Error handling|Type safety|Logic|Quality|Resource|API>
Severity: <Critical|High|Medium|Low>
Title: <one-line summary>
Description: <what's wrong and why it matters>
Suggested fix: <concrete code change or approach>
```

Group related findings (same root cause across files) into a single entry with multiple locations listed.
