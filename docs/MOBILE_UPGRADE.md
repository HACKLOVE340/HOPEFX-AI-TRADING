# Mobile App — Expo / React Native Upgrade Runbook

Why this exists, what it fixes, and the exact procedure — so the upgrade is a
known, low-surprise operation when run in a real React Native dev environment.

_Last updated: 2026-06-27._

---

## Why upgrade

The mobile app is on **Expo SDK 55 / react-native 0.74.5 / react 18.2**. That
toolchain pins old transitive dev/build dependencies that carry the remaining
**Moderate/Low** Dependabot advisories, most notably:

- **js-yaml 3.14.x** (CWE-407 quadratic-merge DoS, GHSA-h67p-54hq-rp68) — pinned
  by `cosmiconfig@5` inside RN 0.74's Metro bundler + CLI. It is **doubly locked**
  (can't raise js-yaml: cosmiconfig@5 needs the removed `safeLoad`; can't raise
  cosmiconfig: `cli-config@13` uses `.searchSync` and `metro-config@0.80` uses
  `cosmiconfig.loadJson/loadYaml`, both removed in cosmiconfig 7+). See
  `docs/SECURITY_DEPENDENCIES.md`.
- ~30 other Moderate `expo-*` / `react-native-*` / `jest` toolchain transitives.

Upgrading react-native + Expo SDK is the **only** clean fix — it pulls
`@react-native-community/cli@20` → `cosmiconfig@9` → js-yaml 4 (patched), and
refreshes the whole transitive set. All of these are **build-time / dev-time,
local-trusted-input** advisories — not runtime or network-facing — so this is a
hygiene upgrade, not an emergency.

## Target version matrix (as of this writing)

| Package | From | To |
|---|---|---|
| expo | ^55.0.15 | ^56.0.x |
| react-native | 0.74.5 | 0.86.x |
| react / react-dom | 18.2.0 | 19.2.x |
| jest-expo | ^47 | ^56 |
| @react-native-community/cli | (transitive 13) | 20.x |
| every `expo-*` package | SDK 55 pins | the SDK 56 pin |
| `react-native-*` (gesture-handler, reanimated, screens, safe-area-context, svg, web) | SDK 55 pins | the SDK 56 pins |
| @types/react | ~18 | ~19 |

> Do **not** hand-bump these one by one. A direct `npm install` of just the core
> five **fails** with an eresolve peer conflict (react 19 vs jest-expo, plus the
> ~25 `expo-*`/`react-native-*` packages still on SDK-55 pins). Verified
> 2026-06-27. The correct tool is `expo install --fix`, which aligns **every**
> package to the installed SDK's compatibility map in one pass.

## Procedure (run in a real RN dev environment)

Prereqs: Node + a working RN build setup (Xcode for iOS, Android SDK for
Android), a simulator/emulator or device, and network access.

```bash
cd mobile-app

# 1. Bump the SDK + framework anchors.
npx expo install expo@^56            # or: npm i expo@^56
npx expo install react@19.2.x react-dom@19.2.x react-native@0.86.x

# 2. Align EVERY expo-*/react-native-* package to the SDK's compatible versions.
npx expo install --fix               # the key step — fixes the eresolve cascade

# 3. Dev tooling to match the new RN/react.
npm i -D jest-expo@^56 @types/react@~19 react-test-renderer@19.2.x

# 4. Drop the now-obsolete overrides that were RN-0.74 workarounds:
#    uuid, @tootallnate/once, @expo/plist, @expo/config-plugins, @expo/config
#    (SDK 56 pulls patched versions natively). Keep the generic security
#    overrides (braces, micromatch, semver, postcss, @xmldom/xmldom, fast-xml-parser).

# 5. Sanity + diagnostics.
npx expo-doctor                      # flags remaining mismatches
npm audit                            # confirm js-yaml + toolchain advisories cleared
```

## Verification gate (must pass before merging)

1. `npx expo-doctor` reports no version mismatches.
2. `npm audit` shows the js-yaml (GHSA-h67p-54hq-rp68) advisory **gone** and the
   high/moderate toolchain count materially reduced.
3. **The app builds and boots** on a simulator/device (iOS *and* Android) — this
   is the step that cannot be done in a headless CI/code environment and is the
   whole reason this upgrade was deferred rather than shipped blind.
4. Smoke-test the core flows (login, dashboard, place a paper order) on device.

## Known breaking changes to expect (react 18 → 19, RN 0.74 → 0.86)

- React 19: removed legacy APIs (`ReactDOM.render` patterns, string refs,
  `propTypes`/`defaultProps` on function components). Audit components/screens.
- RN New Architecture (Fabric/TurboModules) is the default on recent RN — verify
  every native module (`react-native-reanimated`, `-screens`,
  `-gesture-handler`, `-svg`, async-storage, netinfo) is on a New-Arch-compatible
  version (the `expo install --fix` pins handle most of this).
- `@types/react` 19 tightens types — expect some `tsc` fixes in the RN screens.

## Status

- **Attempted in the headless environment (2026-06-27):** failed at `npm install`
  with a peer-dependency conflict; reverted to keep the app on the working SDK 55
  tree. Confirmed this upgrade requires Expo tooling + a device build.
- **Next action:** run the procedure above in a real RN dev environment.
