/**
 * GenerationWorkbench — several generations at once, each one legible.
 *
 * Owner requirement, 2026-09-06: the AI Core screen must generate multiple
 * things simultaneously, stay interactive while it does, and communicate well.
 * Before this, a model call was one request, one answer, one blocked page.
 *
 * Three rules carried over from the rest of this page, because they are what
 * make it readable under pressure:
 *
 *  * **Absence is a state, not a blank.** A queued job says it is waiting for a
 *    slot; a cancelled one says who stopped it; a timed-out one says it passed
 *    its deadline. None of them render as an empty panel the operator has to
 *    interpret.
 *  * **A failure never renders as a healthy value.** A failed panel shows its
 *    error where it sits. Its neighbours succeeding must not imply it did.
 *  * **Colour is never the only signal.** Every state is a word as well as a
 *    hue — the page's job is being read correctly by someone under stress, and
 *    two greens are not distinguishable to everyone.
 *
 * The concurrency ceiling is shown rather than hidden. An operator who submits
 * six jobs against a ceiling of four should see why two are waiting instead of
 * wondering whether the page is broken.
 */

import React, { useCallback, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Ban, Clock, Loader2, Play, Send, XCircle, CheckCircle2, AlarmClock } from 'lucide-react';

import { aiCoreApi } from '../../hooks/useApi';

const COLOR = {
  ok: '#42d392',
  warn: '#f5b84b',
  bad: '#f36d78',
  info: '#73a7ff',
  muted: '#70809a',
  text: '#e7edf7',
  dim: '#a7b5c9',
} as const;

const panel: React.CSSProperties = {
  background: 'linear-gradient(145deg, rgba(16,25,42,.96), rgba(10,16,28,.96))',
  border: '1px solid #20304a',
  borderRadius: 12,
  padding: 16,
};

const label: React.CSSProperties = {
  color: COLOR.muted, fontSize: 10, fontWeight: 800,
  letterSpacing: '.09em', textTransform: 'uppercase',
};

const button: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 7, justifyContent: 'center',
  minHeight: 44, padding: '0 14px', borderRadius: 8,
  background: '#172740', border: '1px solid #2c4c7a', color: '#c9dcfb',
  fontSize: 12, fontWeight: 800, cursor: 'pointer',
};

export interface GenerationJob {
  id: string;
  prompt: string;
  state: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'timed_out';
  result: { text?: string; provider?: string; model?: string; cost_usd?: number; cached?: boolean } | null;
  error: string;
  progress: string[];
  elapsed_s: number;
}

interface Snapshot {
  jobs: GenerationJob[];
  running: number;
  queued: number;
  max_concurrent: number;
  max_queued: number;
}

/**
 * Every state, as a word and a colour.
 *
 * `timed_out` is deliberately distinct from `failed`: the model may well have
 * answered, and the operator's next move differs — retry a failure, raise the
 * ceiling or simplify the prompt for a timeout.
 */
const STATE: Record<GenerationJob['state'], { word: string; color: string; Icon: React.ElementType }> = {
  queued:    { word: 'Waiting for a slot', color: COLOR.muted, Icon: Clock },
  running:   { word: 'Generating',         color: COLOR.info,  Icon: Loader2 },
  succeeded: { word: 'Done',               color: COLOR.ok,    Icon: CheckCircle2 },
  failed:    { word: 'Failed',             color: COLOR.bad,   Icon: XCircle },
  cancelled: { word: 'Cancelled by you',   color: COLOR.muted, Icon: Ban },
  timed_out: { word: 'Passed its deadline', color: COLOR.warn, Icon: AlarmClock },
};

const StateChip: React.FC<{ state: GenerationJob['state'] }> = ({ state }) => {
  const { word, color, Icon } = STATE[state];
  return (
    <span
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 5,
        color, fontSize: 11, fontWeight: 800, whiteSpace: 'nowrap',
      }}
    >
      <Icon size={12} aria-hidden />
      {word}
    </span>
  );
};

const JobPanel: React.FC<{ job: GenerationJob; onCancel: (id: string) => void; busy: boolean }> = ({
  job, onCancel, busy,
}) => {
  const live = job.state === 'queued' || job.state === 'running';
  return (
    <article
      style={{ ...panel, display: 'flex', flexDirection: 'column', gap: 10, minWidth: 0 }}
      aria-label={`Generation: ${STATE[job.state].word}`}
    >
      <header style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'flex-start' }}>
        <StateChip state={job.state} />
        <span style={{ ...label, whiteSpace: 'nowrap' }}>
          {job.elapsed_s > 0 ? `${job.elapsed_s.toFixed(1)}s` : '—'}
        </span>
      </header>

      <p style={{ margin: 0, color: COLOR.dim, fontSize: 12, lineHeight: 1.5, wordBreak: 'break-word' }}>
        {job.prompt}
      </p>

      {/* Progress, not a spinner. An operator can see which step it reached. */}
      {live && job.progress.length > 0 && (
        <ol style={{ margin: 0, paddingLeft: 16, color: COLOR.muted, fontSize: 11, lineHeight: 1.6 }}>
          {job.progress.map((note, i) => <li key={`${note}-${i}`}>{note}</li>)}
        </ol>
      )}

      {job.state === 'queued' && (
        <p style={{ margin: 0, color: COLOR.muted, fontSize: 11 }}>
          Every slot is busy. This starts as soon as one frees up.
        </p>
      )}

      {/* A failure states itself here rather than letting a neighbour's success
          imply this one worked. */}
      {(job.state === 'failed' || job.state === 'timed_out') && job.error && (
        <p role="alert" style={{ margin: 0, color: COLOR.bad, fontSize: 11, lineHeight: 1.5 }}>
          {job.error}
        </p>
      )}

      {job.state === 'succeeded' && job.result && (
        <>
          <div
            style={{
              background: '#0b1220', border: '1px solid #1e2d44', borderRadius: 8,
              padding: 10, color: COLOR.text, fontSize: 12, lineHeight: 1.6,
              maxHeight: 260, overflowY: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-word',
            }}
          >
            {job.result.text || 'The model returned an empty answer.'}
          </div>
          <footer style={{ ...label, display: 'flex', flexWrap: 'wrap', gap: 10 }}>
            <span>{job.result.provider ?? 'unknown vendor'}</span>
            <span>{job.result.model ?? ''}</span>
            {/* Cost is shown per panel because four panels is four times the
                spend, and that should be visible while deciding to run more. */}
            <span>{job.result.cached ? 'cached · $0.00' : `$${(job.result.cost_usd ?? 0).toFixed(4)}`}</span>
          </footer>
        </>
      )}

      {live && (
        <button
          type="button"
          onClick={() => onCancel(job.id)}
          disabled={busy}
          style={{ ...button, alignSelf: 'flex-start', opacity: busy ? 0.6 : 1 }}
        >
          <Ban size={13} aria-hidden /> Stop this one
        </button>
      )}
    </article>
  );
};

export const GenerationWorkbench: React.FC = () => {
  const [prompt, setPrompt] = useState('');
  const [role, setRole] = useState('reasoning');
  const [notice, setNotice] = useState('');
  const queryClient = useQueryClient();

  const snapshot = useQuery<Snapshot>({
    queryKey: ['ai-core', 'generate-jobs'],
    queryFn: async () => (await aiCoreApi.generateJobs()).data,
    // Fast while anything is live, idle otherwise. A page that polls at the
    // same rate whether or not work is happening is a page that costs the
    // server the same whether or not anyone is using it.
    refetchInterval: (query) => {
      const data = query.state.data as Snapshot | undefined;
      return data && (data.running > 0 || data.queued > 0) ? 900 : 6000;
    },
  });

  const submit = useMutation({
    mutationFn: async () => (await aiCoreApi.generate({ prompt, role })).data,
    onSuccess: () => {
      setPrompt('');
      setNotice('');
      void queryClient.invalidateQueries({ queryKey: ['ai-core', 'generate-jobs'] });
    },
    onError: (error: { response?: { status?: number; data?: { detail?: string } } }) => {
      // 429 is backpressure, not a fault. Saying "server error" here would send
      // an operator looking for an outage that is not happening.
      const status = error?.response?.status;
      setNotice(
        status === 429
          ? 'Too many generations are already waiting. Let some finish, then try again.'
          : error?.response?.data?.detail || 'That could not be started.',
      );
    },
  });

  const cancel = useMutation({
    mutationFn: async (jobId: string) => (await aiCoreApi.cancelGenerate(jobId)).data,
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ['ai-core', 'generate-jobs'] }),
  });

  const onCancel = useCallback((id: string) => cancel.mutate(id), [cancel]);

  const jobs = useMemo(() => {
    const all = snapshot.data?.jobs ?? [];
    // Live work first, then most recent. An operator looking at this page cares
    // about what is happening now before what already happened.
    const rank: Record<GenerationJob['state'], number> = {
      running: 0, queued: 1, succeeded: 2, failed: 2, timed_out: 2, cancelled: 3,
    };
    return [...all].sort((a, b) => rank[a.state] - rank[b.state]);
  }, [snapshot.data]);

  const running = snapshot.data?.running ?? 0;
  const queued = snapshot.data?.queued ?? 0;
  const ceiling = snapshot.data?.max_concurrent ?? 0;
  const canSubmit = prompt.trim().length > 0 && !submit.isPending;

  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {/* ── composer ── */}
      <div style={{ ...panel, display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
          <div style={label}>Run several at once</div>
          {/* The ceiling is shown, not hidden: six jobs against a ceiling of
              four should look deliberate rather than broken. */}
          <div style={{ ...label, color: running > 0 ? COLOR.info : COLOR.muted }}>
            {running} of {ceiling} running{queued > 0 ? ` · ${queued} waiting` : ''}
          </div>
        </div>

        <label htmlFor="wb-prompt" style={{ ...label, color: COLOR.dim }}>
          What should it work on?
        </label>
        <textarea
          id="wb-prompt"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={3}
          placeholder="Ask one thing. Submit again to run another alongside it."
          style={{
            // border-box explicitly: the global reset in index.css is scoped to
            // a container class, not `*`, so width:100% plus padding would
            // overflow by 20px and scroll the page sideways on a narrow screen.
            width: '100%', boxSizing: 'border-box',
            resize: 'vertical', background: '#0b1220',
            border: '1px solid #1e2d44', borderRadius: 8, padding: 10,
            color: COLOR.text, fontSize: 13, lineHeight: 1.5, fontFamily: 'inherit',
          }}
        />

        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
          <label htmlFor="wb-role" style={{ ...label, color: COLOR.dim }}>Depth</label>
          <select
            id="wb-role"
            value={role}
            onChange={(e) => setRole(e.target.value)}
            style={{
              minHeight: 44, background: '#0b1220', border: '1px solid #1e2d44',
              borderRadius: 8, color: COLOR.text, fontSize: 12, padding: '0 10px',
              cursor: 'pointer',
            }}
          >
            <option value="reasoning">Reasoning — slower, more capable</option>
            <option value="fast">Fast — cheaper, for routine work</option>
          </select>

          <button
            type="button"
            onClick={() => submit.mutate()}
            disabled={!canSubmit}
            style={{ ...button, opacity: canSubmit ? 1 : 0.55, cursor: canSubmit ? 'pointer' : 'not-allowed' }}
          >
            {submit.isPending ? <Loader2 size={13} aria-hidden /> : <Send size={13} aria-hidden />}
            Start generating
          </button>
        </div>

        {notice && (
          <p role="alert" style={{ margin: 0, color: COLOR.warn, fontSize: 12 }}>{notice}</p>
        )}
      </div>

      {/* ── panels ── */}
      {snapshot.isError && (
        <div role="alert" style={{ ...panel, color: COLOR.bad, fontSize: 12 }}>
          The job list could not be loaded, so what is shown below may be out of date.
        </div>
      )}

      {jobs.length === 0 ? (
        <div style={{ ...panel, color: COLOR.muted, fontSize: 12, display: 'flex', gap: 8, alignItems: 'center' }}>
          <Play size={14} aria-hidden />
          Nothing running yet. Submit above — then submit again without waiting, and both run together.
        </div>
      ) : (
        <div
          style={{
            display: 'grid',
            // Panels fill the row they are in; a single job does not stretch
            // across dead space and two do not sit alone in a three-up row.
            gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))',
            gap: 12,
            alignItems: 'start',
          }}
        >
          {jobs.map((job) => (
            <JobPanel key={job.id} job={job} onCancel={onCancel} busy={cancel.isPending} />
          ))}
        </div>
      )}
    </section>
  );
};

export default GenerationWorkbench;
