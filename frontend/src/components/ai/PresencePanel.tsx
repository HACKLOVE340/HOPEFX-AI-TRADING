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

import { PresenceStage } from '../../hub/PresenceStage';
import { derivePresence, type PresenceInputs } from '../../hub/presence';
import { ConversationTurn, type TranscriptLine } from '../../hub/conversation';
import { Workspace, type Surface } from '../../hub/workspace';
import { readIntent } from '../../hub/intent';
import { readLayout, suggestLayout, type LayoutName } from '../../hub/layout';
import { SnapshotStore, capacityFor, readHistoryIntent } from '../../hub/history';
import { spokenFocus } from '../../hub/reference';
import { asksForSummary, summarise } from '../../hub/summary';
import { useViewportWidth } from '../../hub/useViewportWidth';
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
  /** Leave the immersive stage and go back to the page's tabs. */
  onExit?: () => void;
}

export const PresencePanel: React.FC<PresencePanelProps> = ({ providersReachable, ready = true, onExit }) => {
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

  // The plane. One engine for the life of the panel — rebuilding it would wipe
  // whatever the operator had summoned on every render.
  const workspaceRef = useRef<Workspace | null>(null);
  if (workspaceRef.current === null) workspaceRef.current = new Workspace();
  const workspace = workspaceRef.current;

  const [surfaces, setSurfaces] = useState<readonly Surface[]>([]);
  const [focusedId, setFocusedId] = useState<string | null>(null);

  /**
   * The layout the operator NAMED, or null for "you decide".
   *
   * Kept as two states rather than one so that asking for a war room stays a
   * war room after the next surface opens. If the named choice were folded into
   * a single resolved value, every command would re-derive it from the object
   * count and quietly overrule what was asked for — the plane rearranging
   * itself under someone who told it not to.
   */
  const [namedLayout, setNamedLayout] = useState<LayoutName | null>(null);
  const layout = namedLayout ?? suggestLayout(surfaces, focusedId);

  // History (§8: "bring back yesterday's workspace"). One store for the life of
  // the panel; it reads and writes localStorage and fails soft when that is
  // unavailable, which is every server render and Safari's private mode.
  const historyRef = useRef<SnapshotStore | null>(null);
  if (historyRef.current === null) historyRef.current = new SnapshotStore();
  const history = historyRef.current;

  /**
   * §8's "subject to device capacity", and the degrade-rather-than-fail half.
   *
   * Applied on every width change rather than only at mount: rotating a phone
   * to portrait with twelve surfaces open must reduce them now, not leave a
   * twelve-screen scroll standing until somebody asks for a thirteenth.
   */
  const viewportWidth = useViewportWidth();
  useEffect(() => {
    workspace.setCapacity(capacityFor(viewportWidth));
    setSurfaces([...workspace.surfaces]);
    setFocusedId(workspace.focused);
  }, [viewportWidth, workspace]);

  /**
   * Keep an automatic snapshot of the plane, at most once a minute.
   *
   * Without this, "bring back yesterday's workspace" only ever finds
   * arrangements somebody thought to name, which is almost none of them — the
   * command would work perfectly and answer "there is nothing from yesterday"
   * forever.
   */
  const lastAuto = useRef(0);
  useEffect(() => {
    if (surfaces.length === 0) return;
    const now = Date.now();
    if (now - lastAuto.current < 60_000) return;
    lastAuto.current = now;
    history.save(workspace.snapshot(), { auto: true, layout: namedLayout });
  }, [surfaces, history, workspace, namedLayout]);

  const syncWorkspace = useCallback(() => {
    setSurfaces([...workspace.surfaces]);
    setFocusedId(workspace.focused);
  }, [workspace]);

  /**
   * What happens when someone asks for something.
   *
   * The local reader handles the obvious commands instantly and for free. What
   * it does not recognise is answered by the AI in words rather than silently
   * dropped — a workspace that ignores a sentence it cannot parse teaches
   * people to stop talking to it.
   */
  /**
   * Restore, save or list an arrangement. Returns true when it handled the
   * phrase, so the ordinary surface commands are not also run against it.
   *
   * Checked BEFORE `readIntent`, because "bring back yesterday's workspace"
   * names no subject and would otherwise fall through as unhandled — the
   * specification's own example, answered with a refusal.
   */
  const onHistory = useCallback(
    (phrase: string): boolean => {
      const intent = readHistoryIntent(phrase);
      if (!intent) return false;

      const restore = (snapshot: ReturnType<SnapshotStore['latest']>, missing: string) => {
        if (!snapshot) {
          // Not "here is something else". An operator who cannot tell that the
          // plane they got is not the plane they asked for is worse off than
          // one who was told there is nothing.
          turn.say(missing);
          return;
        }
        const { restored, skipped } = workspace.restore(snapshot.surfaces);
        setNamedLayout(snapshot.layout);
        syncWorkspace();
        turn.say(
          skipped.length > 0
            ? `Restored ${snapshot.name} — ${restored} of ${restored + skipped.length} surfaces. ` +
                `${skipped.length} could not be rebuilt: this version no longer draws ${skipped.join(', ')}.`
            : `Restored ${snapshot.name}, ${restored} ${restored === 1 ? 'surface' : 'surfaces'}.`,
        );
      };

      switch (intent.kind) {
        case 'restore_yesterday':
          restore(history.yesterday(), 'There is no workspace saved from yesterday.');
          break;
        case 'restore_previous':
          restore(history.previous(), 'There is no earlier workspace saved.');
          break;
        case 'restore_named':
          restore(history.byName(intent.name), `I have no workspace called \u201c${intent.name}\u201d.`);
          break;
        case 'save': {
          const saved = history.save(workspace.snapshot(), { name: intent.name, layout: namedLayout });
          turn.say(
            saved
              ? `Saved as \u201c${saved.name}\u201d.`
              : workspace.snapshot().length === 0
                ? 'There is nothing on the plane to save.'
                : 'I could not keep that — this browser is refusing to store it.',
          );
          break;
        }
        case 'list': {
          const all = history.list();
          turn.say(
            all.length === 0
              ? 'No workspaces are saved yet.'
              : `${all.length} saved: ${all.slice(0, 6).map((s) => s.name).join(', ')}.`,
          );
          break;
        }
      }
      setTranscript([...turn.transcript]);
      return true;
    },
    [history, turn, workspace, syncWorkspace, namedLayout],
  );

  const onCommand = useCallback(
    (phrase: string) => {
      turn.userStoppedSpeaking(phrase);
      if (onHistory(phrase)) return;

      // §10: "summarise across surfaces and name relationships." Checked before
      // the surface reader for the same reason history is — "what am I looking
      // at" names no subject and would otherwise open nothing and be refused.
      if (asksForSummary(phrase)) {
        const summary = summarise(surfaces);
        turn.say(summary.text || 'The plane is empty — there is nothing to summarise yet.');
        setTranscript([...turn.transcript]);
        return;
      }

      const intent = readIntent(phrase);

      if (intent.clear) {
        workspace.clear();
        // "Simplify this" resets the arrangement too. Leaving a war room
        // standing over two surfaces answers half the request.
        setNamedLayout(null);
      }
      for (const request of intent.open) workspace.open(request);
      if (intent.focus) {
        const target = workspace.resolve(intent.focus);
        workspace.focus(target);
      }

      // §8's layout commands. Read locally and instantly for the same reason
      // the rest of `intent.ts` is: rearranging the plane should not cost a
      // model call or stop working when a vendor is unreachable.
      const named = readLayout(phrase);
      if (named) setNamedLayout(named === 'auto' ? null : named);

      syncWorkspace();

      if (named) {
        turn.say(named === 'auto' ? 'Back to the default arrangement.' : `${named.replace('_', ' ')} layout.`);
      } else if (intent.unhandled) {
        turn.say(
          "I can put things on the plane — try \u201cshow me everything affecting gold\u201d, \u201cfocus on risk\u201d or \u201csimplify this\u201d. " +
            'Answering that question needs a model, and none is reachable from here yet.',
        );
      } else if (intent.clear && intent.open.length === 0) {
        turn.say('Cleared.');
      } else if (intent.open.length > 0) {
        const what = intent.open.map((r) => r.intent).join(', ');
        turn.say(`Showing ${what}.`);
      }
      setTranscript([...turn.transcript]);
    },
    [turn, workspace, syncWorkspace, onHistory, surfaces],
  );

  /**
   * §9/§10: what the AI is talking about lights up while it says it.
   *
   * Driven by a real measurement — `speechProgress` is a character index from
   * the synthesis engine or a playback position from the audio element, and it
   * is null when neither exists. On null the highlight covers everything the
   * whole utterance refers to instead of stepping from a timer, which would
   * drift within two sentences and point at the wrong panel.
   */
  const focus = useMemo(
    () => spokenFocus({ utterance: voice.spokenText, surfaces, progress: voice.speechProgress }),
    [voice.spokenText, voice.speechProgress, surfaces],
  );

  return (
    <PresenceStage
      presence={presence}
      surfaces={surfaces}
      focusedId={focusedId}
      listening={voice.listening}
      muted={muted}
      sttSupported={voice.sttSupported}
      transcript={transcript}
      layout={layout}
      spokenAbout={focus.ids}
      onCommand={onCommand}
      onTalk={onTalk}
      onStop={onStop}
      onToggleMute={() => setMuted((m) => !m)}
      onCloseSurface={(id) => {
        workspace.close(id);
        syncWorkspace();
      }}
      onPinSurface={(id) => {
        const current = surfaces.find((x) => x.id === id);
        workspace.pin(id, !current?.pinned);
        syncWorkspace();
      }}
      onExit={() => onExit?.()}
    />
  );
};
