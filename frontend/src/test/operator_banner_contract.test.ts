/**
 * Operator feedback contract.
 *
 * Eighteen superadmin control surfaces used to pick their banner colour by
 * sniffing the message text — `msg.includes('fail') || msg.includes('error')`.
 * Those strings are the server's `detail`, so any rejection whose wording
 * lacked the magic substring rendered green: "Insufficient permissions",
 * "Already engaged", "Connection timed out". That covered the kill switch,
 * emergency halt, risk limits and GDPR erasure.
 *
 * This project has no ESLint config, so the guard lives here instead — it runs
 * with `npm test` in CI. It is a source-text assertion by design: the point is
 * to stop the pattern being reintroduced by copy-paste, which is exactly how it
 * reached eighteen files.
 */
import { describe, it, expect } from 'vitest';
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

const SUPERADMIN_DIR = join(__dirname, '..', 'pages', 'superadmin');
const SETTINGS_DIR = join(__dirname, '..', 'pages', 'settings');

/**
 * Colour or severity chosen from the text of a message.
 *
 * Two spellings, because the first sweep only looked for `.includes(...)` and a
 * regex form was hiding behind it — `FinancialSection`'s Flash component used
 * `/fail|error/i.test(msg)` on the panel that resolves chargebacks.
 */
const SNIFFS_MESSAGE_TEXT = [
  /\.includes\(\s*['"](?:fail|failed|Failed|error|Error|ACTIVATED)['"]\s*\)/,
  /\/[^/\n]*\b(?:fail|error)\b[^/\n]*\/[a-z]*\.test\(/i,
];

function tsxFilesIn(dir: string): string[] {
  return readdirSync(dir).filter((f) => f.endsWith('.tsx'));
}

describe('operator action banners', () => {
  it('never infer success or failure from the message text', () => {
    const offenders: string[] = [];

    for (const dir of [SUPERADMIN_DIR, SETTINGS_DIR]) {
      for (const file of tsxFilesIn(dir)) {
        const src = readFileSync(join(dir, file), 'utf8');
        src.split('\n').forEach((line, i) => {
          if (SNIFFS_MESSAGE_TEXT.some((re) => re.test(line))) {
            offenders.push(`${file}:${i + 1}  ${line.trim().slice(0, 100)}`);
          }
        });
      }
    }

    expect(
      offenders,
      'Pass an explicit ok flag to <ActionBanner> instead of testing the message ' +
        'string. A rejection that does not contain the magic word renders as success:\n' +
        offenders.join('\n'),
    ).toEqual([]);
  });

  it('keep the kill switch out of bulk settings saves', () => {
    // A settings object is POSTed wholesale. Including a kill switch field means
    // a stale or defaulted value can resume trading as a side effect of saving
    // an unrelated preference.
    const cases: Array<[string, string]> = [
      ['AdminSettingsSection.tsx', 'global_kill_switch'],
      ['TradingSection.tsx', 'kill_switch_enabled'],
    ];

    for (const [file, field] of cases) {
      const src = readFileSync(join(SETTINGS_DIR, file), 'utf8');
      expect(src, `${file} must strip ${field} before POSTing the settings object`).toContain(
        `${field}: _killSwitch`,
      );
    }
  });
});
