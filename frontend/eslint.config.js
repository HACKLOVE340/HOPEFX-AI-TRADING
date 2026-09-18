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
import jsxA11y from 'eslint-plugin-jsx-a11y';

import a11yDebt from './a11y-debt.json' with { type: 'json' };

// One options object for `jsx-a11y/control-has-associated-label`, shared by the
// error-level rule and the warn-level debt override below.
//
// They were two separate configurations and the second was a bare `'warn'`,
// which in flat config RESETS the options to the rule's defaults. So the 18
// files on the debt list were not merely being warned instead of errored —
// they were being checked by a DIFFERENT RULE: no `controlComponents`, and the
// default `depth: 2`.
//
// Sharing the object changes no current finding — 18 warnings before and 18
// after, verified — and that is the point: the two configurations agreeing is
// what makes the debt list a severity switch rather than a second rule.
//
// `depth` was tried here and deliberately NOT kept. The hypothesis was that
// the remaining warnings are controls whose label text sits deeper than the
// default reach; raising it to 6 changed nothing, because this rule looks DOWN
// into a control's children and never UP at a wrapping <label>. Implicit label
// association is valid HTML the rule cannot see. See a11y-debt.json.
const A11Y_LABEL_OPTIONS = { controlComponents: ['button'] };

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
    plugins: { 'react-hooks': reactHooks, 'jsx-a11y': jsxA11y },
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

      // ── Accessibility: the one rule, and why only one ───────────────────
      //
      // F172 — "icon-only buttons without an accessible name" — sat UNVERIFIED
      // in the correction register for a reason worth keeping: two attempts to
      // measure it by regex each produced a confident WRONG answer, one saying
      // clean across 552 buttons and the other finding 9 files. A JSX opening
      // tag cannot be bracketed by a regex, because an attribute may contain
      // `>` and `onClick={() => nav('/x')}` ends the match at the arrow.
      //
      // A real parser answers it: 138 violations across 67 files. The rule is
      // the fix and the count came with it.
      //
      // Classified with that same parser on 2026-09-14, the NAME was wrong even
      // though the count was right: by tag the 138 were input 108, textarea 17,
      // div 5, td 4, th 2, **button 1**, option 1. Sixteen more were controls
      // carrying id="x" beside a <label htmlFor="x"> — correctly labelled at
      // runtime, and unresolvable by this rule, which reads one element's own
      // props and children and cannot follow a reference to a sibling. Clear one
      // of those by giving the label an id and the control an aria-labelledby,
      // never by copying the text into an aria-label that can drift from what is
      // on screen (WCAG 2.5.3). See a11y-debt.json's `_shape`.
      //
      // Only this rule is on. `jsx-a11y`'s recommended set produces a wall on
      // an established codebase, and the config above already refuses that
      // trade twice (no-use-before-define at 1,990, no-explicit-any).
      'jsx-a11y/control-has-associated-label': ['error', A11Y_LABEL_OPTIONS],

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

  // ── The a11y debt list, and the rule that makes it a ratchet ────────────
  //
  // 67 files carried the 138 violations the parser found on 2026-09-13 (64 and
  // 127 after the sign-in/register/profile flow was cleared on 2026-09-14; the
  // file itself is the current figure, this comment is not). Turning
  // the rule on at `error` across all of them would be a wall nobody adopts,
  // and at `warn` everywhere it would bury the hook rules above. So it is an
  // ERROR everywhere EXCEPT these files, which means a violation in any file
  // not listed fails `npm run lint` — new debt cannot arrive quietly.
  //
  // The list may only shrink. `src/test/a11y_debt_is_accurate.test.ts` fails if
  // a listed file has no violations left, or no longer exists: an entry that
  // describes nothing is how a ratchet stops being one.
  {
    files: Object.keys(a11yDebt.files),
    rules: {
      'jsx-a11y/control-has-associated-label': ['warn', A11Y_LABEL_OPTIONS],
    },
  },
);
