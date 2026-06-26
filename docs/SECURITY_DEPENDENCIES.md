# Dependency Security — Status & Accepted Risk

Record of the Dependabot remediation pass and the one **deliberately accepted**
advisory, so the decision is documented and auditable rather than silently
ignored. Update this file whenever the dependency posture changes.

_Last updated: 2026-06-26._

---

## Fixed

### Python (`requirements.txt`, `requirements-ci.txt`)
| Package | Was | Now | Advisory |
|---------|-----|-----|----------|
| PyJWT | 2.12.0 | **2.13.0** | JWK public key accepted as HMAC secret → HS256 token forgery; empty-key signing now rejected |
| cryptography | 46.0.7 | **>=47.0.0** | Vulnerable OpenSSL bundled in wheels through 46.0.7 |
| starlette | 0.40.x cap | **>=1.3.1** | Host-header path poisoning; UNC StaticFiles SSRF; `form()` request-limit DoS |
| fastapi | >=0.115 | **>=0.136** | Floor raised so it resolves with the patched starlette 1.3.x line |
| aiohttp | <3.14 (capped) | **>=3.14.1** | websocket-frame memory bypass, C-parser `max_line_size`, pipelined-request queue, compressed-body `client_max_size`, cross-origin redirect cookie/digest, deserialization, + Low: TLS hostname override, mid-body payload close, host-only cookie persistence |

The aiohttp cap was only there because the test mock library **aioresponses
0.7.9** breaks on aiohttp 3.14 (`ClientResponse` missing `stream_writer`). It was
removed and replaced with an in-repo, version-agnostic shim
(`tests/support/aioresponses_shim.py`).

### Frontend (`frontend/`)
| Package | Fix | Advisory |
|---------|-----|----------|
| vite | 8.0.13 → **8.1.0** | `server.fs.deny` bypass on Windows alternate paths |
| undici (transitive) | `npm audit fix` | TLS validation bypass / SOCKS5 cross-origin / WebSocket DoS |
| form-data (transitive) | `npm audit fix` | CRLF injection via unescaped multipart field names |

`frontend` npm audit: **0 vulnerabilities**.

### Mobile (`mobile-app/`)
| Package | Fix | Advisory |
|---------|-----|----------|
| form-data | lockfile bump | CRLF injection |
| ws | lockfile bump | memory-exhaustion DoS |
| uuid | override `>=11.1.1 <12` | missing buffer bounds check in v3/v5/v6 (consumer `xcode` uses `uuid.v4()`, verified present) |
| @tootallnate/once | override `>=2.0.1 <3` | incorrect control-flow scoping (consumer `http-proxy-agent@4` imports via `__importDefault().default`, compatible) |

`mobile-app` npm audit: **0 high, 0 critical, 0 low**.

---

## Accepted (won't-fix, documented) — `js-yaml` in `mobile-app`

**Advisory:** js-yaml quadratic-complexity DoS in merge-key handling
(GHSA-h67p-54hq-rp68). **Severity:** Moderate.

**Why it is not fixed:** it is **structurally locked by react-native 0.74**. The
Metro bundler and RN CLI pull `cosmiconfig@5.2.1`, which depends on
`js-yaml@^3.13.1` and calls `yaml.safeLoad()` — an API that js-yaml 4+ **removed**
(it now throws). Verified directly:

- `node_modules/cosmiconfig/dist/loaders.js:23` → `yaml.safeLoad(content, …)`
- `cosmiconfig@5.2.1` `dependencies.js-yaml === "^3.13.1"`
- forcing js-yaml ≥4 across the tree throws inside Metro config loading → the
  mobile build breaks.

Forcing `cosmiconfig` up instead risks breaking RN CLI 13's config loader
(cosmiconfig changed its API at v6). Either way the fix cannot be verified
without a mobile build (simulator/device), which this environment lacks.

**Risk assessment:** **low/practically nil.** The vulnerable path is a
**build-time** YAML config loader operating on **local, trusted** config files,
not a runtime or network-facing surface. Exploitation would require an attacker
who already controls the build machine's config.

**Real fix (tracked, deferred):** a `react-native` major upgrade (0.74 →
current) brings `@react-native-community/cli@20` → `cosmiconfig@9` → js-yaml 4,
clearing this and the remaining ~30 Moderate expo/RN/jest toolchain transitives
in one sweep. Do it as a separate, device-tested effort when the mobile app is
next actively developed — not as a blind security patch.

**Recommended Dependabot action:** dismiss alert #208 as
*"won't fix — toolchain-locked; build-time/local-config only; tracked under RN
upgrade."*
