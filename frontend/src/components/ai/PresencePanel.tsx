/**
 * components/ai/PresencePanel.tsx — the AI presence, inside the AI Core page.
 *
 * Phase 1 of the AI Hub specification (§4, §5, §7, §17, §27).
 *
 * ## Why it lives here and not on a route of its own
 *
 * The first attempt at this built a separate `/hub` page, which was wrong: it
 * produced a second AI screen beside the AI screen. §4 asks for the AI Core to
 * *be* the primary interface, not to be joined by one. So this is a tab on the
 * page that already exists, and it is the tab that opens first — every other tab
 * (Workbench, Overview, Model chain, Spend, Calls, Governance) is exactly where
 * it was.
 *
 * ## Everything shown is derived, nothing is decorative
 *
 * State comes from `hub/presence.ts`, a pure function of the WebSocket status,
 * the stale-feed watchdog, live job counts and provider reachability. §22 forbids
 * fake live values, and this page's own predecessor — `HologramPanel`, whose
 * comment admits it "narrated an analysis that never happened" — is why that
 * rule is written down.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Mic, Square, Volume2, VolumeX } from 'lucide-react';

import { PresenceCore } from '../../hub/PresenceCore';
import { derivePresence, type PresenceInputs } from '../../hub/presence';
import { ConversationTurn, type TranscriptLine } from '../../hub/conversation';
import { useStore, selectAiJobs } from '../../store';
import { useVoice } from '../../hooks/useVoice';

const COLOR = {
  edge: '#1e2d47',
  edge2: '#2b3d5c',
  text: '#e7edf7',
  dim: '#a7b5c9',
  quiet: '#70809a',
  core: '#73a7ff',
  bad: '#f36d78',
} as const;

const button: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 8,
  minHeight: 44,
  padding: '0 16px',
  borderRadius: 9,
  border: `1px solid ${COLOR.edge2}`,
  background: 'linear-gradient(160deg, #182842, #121e33)',
  color: COLOR.text,
  fontSize: 12.5,
  fontWeight: 700,
  letterSpacing: '.04em',
  cursor: 'pointer',
};

export interface PresencePanelProps {
  /** From the page's existing summary query — no second request for it. */
  providersReachable?: number;
  /**
   * Whether those inputs have actually arrived.
   *
   * The greeting waits for this. Without it the panel greeted at mount with
   * "Nothing needs you", the summary then landed reporting no reachable vendor,
   * and the caption changed to "I cannot answer" while the transcript still
   * held the earlier line — the AI on record saying something that had stopped
   * being true. Found in the browser; `presence_greeting_is_true.test.tsx` is
   * the test that would have found it first.
   */
  ready?: boolean;
}

export const PresencePanel: React.FC<PresencePanelProps> = ({ providersReachable, ready = true }) => {
  const wsStatus = useStore((s) => s.wsStatus);
  const feedStale = useStore((s) => s.feedStale);
  const jobs = useStore(selectAiJobs);
  const voice = useVoice();

  const [muted, setMuted] = useState(false);
  const [transcript, setTranscript] = useState<readonly TranscriptLine[]>([]);

  const jobCounts = useMemo(() => {
    const all = Object.values(jobs);
    return {
      running: all.filter((j) => j.state === 'running').length,
      queued: all.filter((j) => j.state === 'queued').length,
    };
  }, [jobs]);

  const inputs: PresenceInputs = {
    wsStatus,
    feedStale,
    micOpen: voice.listening,
    speaking: voice.speaking,
    jobsRunning: jobCounts.running,
    jobsQueued: jobCounts.queued,
    // Not published by any endpoint yet. `null` means unmeasured, and the
    // presence draws no ring rather than assuming full headroom — a full ring
    // for a number nobody has measured is exactly the decorative value §22
    // forbids. Phase 4 connects it.
    riskHeadroom: null,
    alert: null,
    providersReachable: providersReachable ?? 1,
  };

  const presence = derivePresence(inputs);

  // `useVoice.speak` reports completion through its `speaking` flag rather than
  // a callback, so the signal is bridged here. Adapting at the boundary is what
  // keeps `ConversationTurn` testable without a browser.
  const pendingDone = useRef<(() => void) | null>(null);
  useEffect(() => {
    if (!voice.speaking && pendingDone.current) {
      const done = pendingDone.current;
      pendingDone.current = null;
      done();
    }
  }, [voice.speaking]);

  const turnRef = useRef<ConversationTurn | null>(null);
  if (turnRef.current === null) {
    turnRef.current = new ConversationTurn(
      {
        speak: (text, done) => {
          pendingDone.current = done;
          voice.speak(text);
        },
        cancel: () => {
          pendingDone.current = null;
          voice.cancelSpeak();
        },
      },
      { start: () => voice.startListening(), stop: () => voice.stopListening() },
      { muted },
    );
  }
  const turn = turnRef.current;

  // A microphone still capturing after the tab changes is a privacy problem,
  // not an untidiness one.
  useEffect(() => () => turn.dispose(), [turn]);

  // Greet once. Browsers refuse synthesis until the page has been interacted
  // with, so the caption appears immediately and the first click gives it a
  // voice — a real constraint, surfaced rather than hidden.
  const greeted = useRef(false);
  useEffect(() => {
    // Not until the inputs are real.
    if (greeted.current || !ready) return;
    greeted.current = true;
    turn.say(presence.reason);
    setTranscript([...turn.transcript]);
  }, [presence.reason, turn, ready]);

  const onTalk = useCallback(() => {
    if (voice.listening) turn.userStoppedSpeaking(voice.transcript ?? '');
    else turn.userStartedSpeaking();
    setTranscript([...turn.transcript]);
  }, [turn, voice.listening, voice.transcript]);

  const onStop = useCallback(() => {
    turn.dispose();
    setTranscript([...turn.transcript]);
  }, [turn]);

  return (
    <section style={{ display: 'grid', gap: 20, justifyItems: 'center', padding: '18px 0 6px' }}>
      <PresenceCore presence={presence} />

      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', justifyContent: 'center' }}>
        <button
          type="button"
          onClick={onTalk}
          disabled={!voice.sttSupported}
          style={{
            ...button,
            borderColor: voice.listening ? COLOR.bad : COLOR.edge2,
            opacity: voice.sttSupported ? 1 : 0.5,
          }}
        >
          <Mic size={14} aria-hidden /> {voice.listening ? 'Stop listening' : 'Talk to it'}
        </button>
        <button type="button" onClick={onStop} style={button}>
          <Square size={13} aria-hidden /> Stop
        </button>
        <button type="button" onClick={() => setMuted((m) => !m)} aria-pressed={muted} style={button}>
          {muted ? <VolumeX size={14} aria-hidden /> : <Volume2 size={14} aria-hidden />}
          {muted ? 'Muted' : 'Speaking aloud'}
        </button>
      </div>

      {!voice.sttSupported && (
        <p style={{ margin: 0, fontSize: 11.5, color: COLOR.quiet, textAlign: 'center', maxWidth: '52ch' }}>
          This browser has no speech recognition — that is Chromium-only today. Everything else works, and it
          will still speak to you.
        </p>
      )}

      {/* The transcript. Captions are not a lesser channel (§27): this is the
          same text that was spoken, in the same order, whether or not audio was
          ever switched on. */}
      {transcript.length > 0 && (
        <ol
          aria-label="Conversation transcript"
          style={{
            margin: 0,
            padding: '12px 14px',
            listStyle: 'none',
            display: 'grid',
            gap: 6,
            width: '100%',
            maxWidth: 720,
            maxHeight: 160,
            overflowY: 'auto',
            fontSize: 12.5,
            color: COLOR.dim,
            border: `1px solid ${COLOR.edge}`,
            borderRadius: 10,
            background: 'rgba(12,20,36,.6)',
            boxSizing: 'border-box',
          }}
        >
          {transcript.map((line, i) => (
            <li key={`${line.at}-${i}`}>
              <span style={{ color: line.who === 'ai' ? COLOR.core : COLOR.quiet, fontWeight: 700 }}>
                {line.who === 'ai' ? 'HOPEFX' : 'You'}:{' '}
              </span>
              {line.text}
              {line.interrupted && (
                <span style={{ color: COLOR.quiet, fontStyle: 'italic' }}> — interrupted</span>
              )}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
};
