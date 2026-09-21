/**
 * Settings panels must not render defaults they could not load. (Audit S7/S8.)
 *
 * Every one of these panels shares a shape: state is initialised from a
 * `DEFAULT` object, the API response is merged over it, and Save POSTs the
 * *whole* object back. So a failed GET is not a display bug — it is a write
 * path:
 *
 *   1. the panel renders DEFAULT, indistinguishable from saved config;
 *   2. the user changes one field and clicks Save;
 *   3. the POST sends DEFAULT plus that one edit, replacing real settings.
 *
 * On TradingSection that resets risk-per-trade and max-drawdown. On
 * IntegrationsSection it blanks MT4/MT5 passwords and webhook secrets. On
 * SystemSection it disables live trading platform-wide. On
 * PlatformConfiguration, `savePlatformConfigFull` PUTs 200+ fields at once. And
 * on the healer config, DEFAULT has self-healing *enabled* — a failed read plus
 * an unrelated toggle arms automated patching of a live trading system.
 *
 * The fix in all cases is to refuse to render an editable form that could not be
 * populated. This test pins that: each panel must both record the failure and
 * branch on it before rendering the form.
 *
 * Source assertions rather than renders, because the regression is structural
 * and arrives by copy-paste — which is how it reached fifteen files.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const SETTINGS = join(__dirname, '..', 'pages', 'settings');
const read = (f: string) => readFileSync(join(SETTINGS, f), 'utf8');

/** Panels whose Save posts the whole settings object. */
const GATED_PANELS = [
  'TradingSection.tsx',
  'IntegrationsSection.tsx',
  'BrokerSection.tsx',
  'NotificationsSection.tsx',
  'PrivacySection.tsx',
  'ProfileSection.tsx',
  'SystemSection.tsx',
  'AdminSettingsSection.tsx',
];

describe('settings load gating', () => {
  it.each(GATED_PANELS)('%s records a failed load and gates the form on it', (file) => {
    const src = read(file);

    expect(src, `${file} must track that the load failed`).toMatch(/setLoadFailed\(true\)/);

    // The flag has to actually short-circuit the render, not just sit in state.
    expect(src, `${file} must branch on loadFailed before rendering the form`).toMatch(
      /if \(loadFailed\) return/,
    );

    // And offer a way out that isn't a full page reload.
    expect(src, `${file} must offer a retry`).toMatch(/onClick=\{load\}/);
  });

  it('no gated panel swallows its load error with console.warn alone', () => {
    for (const file of GATED_PANELS) {
      const src = read(file);
      // `.catch((err) => console.warn(...))` with nothing else was the original
      // bug in all fifteen panels.
      expect(src, `${file} still has a console.warn-only load handler`).not.toMatch(
        /\.catch\(\(\s*err[^)]*\)\s*=>\s*console\.warn\([^)]*\)\)/,
      );
    }
  });

  it('PlatformConfiguration gates both the 200-field PUT and the healer config', () => {
    const src = read('PlatformConfiguration.tsx');
    expect(src).toMatch(/setCfgLoadFailed\(true\)/);
    expect(src).toMatch(/if \(cfgLoadFailed\) return/);
    // The healer tab is gated separately — its config loads independently.
    expect(src).toMatch(/setHealerLoadFailed\(true\)/);
    expect(src).toMatch(/activeTab === 'healing' && healerLoadFailed/);
  });

  it('AutoHealingSection never falls back to an enabled default config', () => {
    const src = readFileSync(
      join(__dirname, '..', 'pages', 'superadmin', 'AutoHealingSection.tsx'),
      'utf8',
    );
    expect(src).toMatch(/setConfigLoadFailed\(true\)/);
    // The original code was `catch { /* use defaults */ }` — the comment stated
    // the intent outright.
    expect(src).not.toMatch(/catch\s*\{\s*\/\*\s*use defaults\s*\*\/\s*\}/);
  });

  it('SecuritySection reports unknown 2FA state rather than "off"', () => {
    const src = read('SecuritySection.tsx');
    // Tri-state: a failed status fetch must not render as Disabled, which is a
    // security claim about the account rather than a form default.
    expect(src).toMatch(/useState<boolean \| null>\(null\)/);
    expect(src).toMatch(/is2FA === null/);
    // An empty session list on a failed fetch would read as "nobody else is
    // signed in".
    expect(src).toMatch(/setSessionsErr/);
    expect(src).toMatch(/setRevokeErr/);
  });
});
