/**
 * The OS voice must never say "asterisk".
 *
 * Assistant replies are Markdown, and `useVoice.speak()` handed the raw string
 * straight to `SpeechSynthesisUtterance`. Measured in Chromium by spying on
 * `window.speechSynthesis.speak` and driving /ai-assistant with "Read replies
 * aloud" on, the platform asked the OS to say, verbatim:
 *
 *   "Your live account balance, equity, margin and P&L are on the
 *    **Dashboard → Account** panel, refreshed in real time.\n\n_(O…"
 *
 * — so the user hears "star star Dashboard arrow Account star star" and
 * "underscore open-paren". Every emphasis marker, backtick, heading hash, list
 * bullet and link bracket is pronounced.
 *
 * Stripped at `speak()` rather than at the four call sites, because that is the
 * one place text meets the voice: AIChat, PresencePanel, VoiceTradingPanel and
 * the toast read-out all pass human-facing prose, and none of them wants markup
 * spoken. It is deliberately a READ-ALOUD transform only — the transcript and
 * the on-screen text keep their formatting.
 */
import { describe, it, expect } from 'vitest';

import { speechText } from '../hooks/useVoice';

describe('speechText — what the OS is actually asked to say', () => {
  it('drops emphasis markers but keeps the words', () => {
    expect(speechText('are on the **Dashboard → Account** panel')).toBe(
      'are on the Dashboard → Account panel',
    );
    expect(speechText('_(Offline mode)_')).toBe('(Offline mode)');
    expect(speechText('a *single* star and __bold__ too')).toBe('a single star and bold too');
  });

  it('reads a link by its text, not its URL', () => {
    expect(speechText('see [the runbook](https://example.test/a/b) for more')).toBe(
      'see the runbook for more',
    );
  });

  it('drops code fences and backticks', () => {
    expect(speechText('run `pytest -q` first')).toBe('run pytest -q first');
    expect(speechText('```bash\nls -la\n```')).toBe('ls -la');
  });

  it('drops heading hashes and list bullets', () => {
    expect(speechText('## Risk\n- one\n- two\n1. three')).toBe('Risk. one. two. three');
  });

  it('leaves ordinary prose exactly as it was', () => {
    const plain = 'Your balance is 10,432.17 and margin is 3% — comfortable.';
    expect(speechText(plain)).toBe(plain);
  });

  it('does not invent speech for an empty or markup-only string', () => {
    expect(speechText('')).toBe('');
    expect(speechText('   ')).toBe('');
    expect(speechText('***')).toBe('');
  });

  it('collapses the blank lines that become long silences', () => {
    expect(speechText('first line\n\n\n\nsecond line')).toBe('first line. second line');
  });
});
