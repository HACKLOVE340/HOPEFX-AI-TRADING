// ESLint flat config.
//
// This project had no ESLint at all. That is how `Cannot access 'N' before
// initialization` reached production: `Watchlist.tsx` read `tickHistory` ~24
// lines above its `useState` declaration, `tsc` does not flag a reference
// inside a callback (TS2448 is same-scope only), and `no-use-before-define`
// had never run here.
//
// `scripts/find_tdz_reads.mjs` was written to catch that one shape. This is the
// general tool that should have come first — it covers that class plus the
// hook-dependency and unsafe-pattern classes nothing else here checks.
//
// Deliberately scoped: this is an established codebase, so the config is tuned
// to catch real defects rather than to impose a style. Rules that would produce
// hundreds of cosmetic findings are off; rules that catch bugs are errors.

import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import reactHooks from 'eslint-plugin-react-hooks';

export default tseslint.config(
  {
    ignores: [
      'dist/**',
      'node_modules/**',
      'coverage/**',
      'playwright-report/**',
      'scripts/__fixtures__/**', // deliberately-broken fixtures for find_tdz_reads
    ],
  },

  js.configs.recommended,
  ...tseslint.configs.recommended,

  {
    files: ['**/*.{ts,tsx}'],
    plugins: { 'react-hooks': reactHooks },
    languageOptions: {
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    rules: {
      // ── The class that shipped: NOT covered here, deliberately ──────────
      //
      // The Watchlist crash was a temporal dead zone read, and the obvious move
      // is `no-use-before-define` with `variables: true`. Measured on this
      // codebase it produces **1,990 errors**, essentially all false positives:
      // it flags selector callback parameters like the `s` in
      // `useStore((s) => s.prices)` as "used before defined" whenever some
      // later scope declares an `s`. It does not model shadowing across scopes,
      // and it cannot tell a read that happens during render from one inside a
      // callback that runs later.
      //
      // That is the same distinction `scripts/find_tdz_reads.mjs` was built to
      // make — and it makes it correctly: 11 findings on its first run, all
      // false positives, then 0 after the shadowing and type-position blind
      // spots were closed, while still catching the real Watchlist shape in its
      // regression fixture.
      //
      // So the bespoke checker stays the gate for this class and this rule
      // stays off. Turning it on at `error` would mean a 1,990-error wall
      // nobody can adopt; at `warn` it would bury the rules below.
      'no-use-before-define': 'off',
      '@typescript-eslint/no-use-before-define': 'off',

      // TypeScript already resolves identifiers, and `no-undef` does not know
      // about DOM/Node globals here — 58 errors, all on `process`/`console` in
      // build scripts. tsc is the authority for this.
      'no-undef': 'off',

      // ── Hook correctness ────────────────────────────────────────────────
      // A missing dependency is a stale closure; an extra one is a render
      // loop. Both were real defects in this codebase (useDataFreshness
      // returned a fresh object every render and caused 138 requests in one
      // pass, caught by the F1 harness rather than by tooling).
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',

      // ── Quiet the noise, keep the substance ─────────────────────────────
      // `any` is pervasive in the existing API-response handling. Flagging it
      // as an error here would bury the rules above under hundreds of
      // findings; as a warning it stays visible without drowning them.
      '@typescript-eslint/no-explicit-any': 'warn',
      '@typescript-eslint/no-unused-vars': [
        'warn',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_', caughtErrorsIgnorePattern: '^_' },
      ],
      // tsconfig already sets noUnusedLocals/noUnusedParameters to false
      // deliberately; do not contradict it with an error here.

      // ── Genuine footguns ────────────────────────────────────────────────
      eqeqeq: ['error', 'always', { null: 'ignore' }],
      'no-fallthrough': 'error',
      'no-self-compare': 'error',
      'no-unmodified-loop-condition': 'error',
      'no-unreachable-loop': 'error',
      'no-constant-binary-expression': 'error',
      'require-atomic-updates': 'error',
    },
  },

  // Build/tooling scripts run under Node, not in the browser. Without this,
  // `no-undef` fires on every `process` and `console` in them (58 errors).
  {
    files: ['**/*.mjs', '**/*.cjs', '*.js', 'scripts/**'],
    languageOptions: {
      globals: {
        process: 'readonly',
        console: 'readonly',
        Buffer: 'readonly',
        __dirname: 'readonly',
        URL: 'readonly',
      },
    },
    rules: {
      'no-undef': 'off', // Node globals vary by version; tsc/runtime is authority
    },
  },

  // Tests may do things application code should not.
  {
    files: ['**/*.test.{ts,tsx}', 'src/test/**', 'e2e/**'],
    rules: {
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/no-non-null-assertion': 'off',
    },
  },
);
