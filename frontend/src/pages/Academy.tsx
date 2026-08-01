/**
 * pages/Academy.tsx
 * HOPEFX Academy — the video tutorial series surfaced from docs/VIDEO_TUTORIALS.md.
 *
 * - Fetches the episode catalogue from GET /api/tutorials (each episode carries a
 *   `locked` flag computed server-side from the caller's plan).
 * - Locked episodes show a plan badge and route to /upgrade.
 * - Unlocked episodes open a detail panel; if the episode is published it embeds
 *   the player, otherwise it shows the script preview (chapters) + "Coming soon".
 *
 * Gating is enforced by the backend — the frontend lock UI is a convenience, not
 * a security boundary (GET /api/tutorials/{id} returns 403 + required_plan when
 * the plan is insufficient).
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { tutorialsApi } from '../hooks/useApi';
import { extractApiError } from '../lib/utils';
import { PageHeader } from '../components/PageHeader';
import { useToast } from '../components/Toast';
import { Modal } from '../components/Modal';
import { PLAN_LABELS, PLAN_COLORS, type Plan } from '../lib/subscription';

// ── Types ───────────────────────────────────────────────────────────────────

interface Episode {
  episode: number;
  title: string;
  level: string;
  duration_min: number;
  plan: Plan;
  status: string;
  summary: string;
  /** Optional — the API omits it for unpublished episodes. */
  chapters?: string[];
  thumbnail_text: string;
  locked: boolean;
  published: boolean;
  video_url?: string | null;
}

// ── Helpers ─────────────────────────────────────────────────────────────────

function planColor(plan: Plan): string {
  return PLAN_COLORS[plan] ?? '#475569';
}

function levelColor(level: string): string {
  const l = level.toLowerCase();
  if (l.includes('advanced')) return '#f87171';
  if (l.includes('intermediate')) return '#fbbf24';
  return '#4ade80'; // beginner / all levels
}

// ── Episode card ──────────────────────────────────────────────────────────────

const EpisodeCard: React.FC<{ ep: Episode; onOpen: (ep: Episode) => void }> = ({ ep, onOpen }) => {
  const accent = planColor(ep.plan);
  return (
    <button
      onClick={() => onOpen(ep)}
      style={{
        textAlign: 'left', cursor: 'pointer', display: 'flex', flexDirection: 'column',
        background: '#0d1421', border: '1px solid #1e2d3d', borderRadius: 12,
        overflow: 'hidden', transition: 'border-color 0.15s, transform 0.15s',
      }}
      onMouseEnter={(e) => { e.currentTarget.style.borderColor = ep.locked ? '#334155' : '#3b82f6'; e.currentTarget.style.transform = 'translateY(-2px)'; }}
      onMouseLeave={(e) => { e.currentTarget.style.borderColor = '#1e2d3d'; e.currentTarget.style.transform = 'translateY(0)'; }}
    >
      {/* Thumbnail strip (text-based until artwork is uploaded) */}
      <div style={{
        position: 'relative', height: 116, display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: 14, background: 'linear-gradient(135deg, #0a1628 0%, #0d1f33 100%)',
        borderBottom: '1px solid #1e2d3d',
      }}>
        <span style={{
          position: 'absolute', top: 8, left: 10, fontSize: 11, fontWeight: 800,
          color: '#64748b', letterSpacing: '0.08em',
        }}>
          EP {ep.episode.toString().padStart(2, '0')}
        </span>
        <span style={{
          textAlign: 'center', fontSize: 13, fontWeight: 700, color: '#cbd5e1', lineHeight: 1.4,
        }}>
          {ep.thumbnail_text}
        </span>
        {/* Play / lock overlay */}
        <div style={{
          position: 'absolute', bottom: 8, right: 10, fontSize: 18,
          opacity: ep.locked ? 0.85 : 1,
        }}>
          {ep.locked ? '🔒' : ep.published ? '▶' : '🎬'}
        </div>
      </div>

      {/* Body */}
      <div style={{ padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 8, flex: 1 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: '#f1f5f9', flex: 1, minWidth: 0 }}>
            {ep.title}
          </span>
        </div>
        <p style={{ fontSize: 11, color: '#64748b', lineHeight: 1.5, margin: 0, flex: 1 }}>
          {ep.summary}
        </p>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginTop: 2 }}>
          <span style={{ fontSize: 10, fontWeight: 700, color: levelColor(ep.level) }}>{ep.level}</span>
          <span style={{ fontSize: 10, color: '#475569' }}>· {ep.duration_min} min</span>
          <span style={{ flex: 1 }} />
          {ep.locked ? (
            <span style={{
              fontSize: 9, fontWeight: 800, padding: '2px 7px', borderRadius: 4,
              background: `${accent}18`, color: accent, border: `1px solid ${accent}40`,
              textTransform: 'uppercase', letterSpacing: '0.05em',
            }}>
              🔒 {PLAN_LABELS[ep.plan]}
            </span>
          ) : ep.published ? (
            <span style={{ fontSize: 9, fontWeight: 800, padding: '2px 7px', borderRadius: 4, background: 'rgba(74,222,128,0.12)', color: '#4ade80', border: '1px solid rgba(74,222,128,0.35)', textTransform: 'uppercase' }}>
              Watch
            </span>
          ) : (
            <span style={{ fontSize: 9, fontWeight: 700, padding: '2px 7px', borderRadius: 4, background: '#1e293b', color: '#94a3b8', border: '1px solid #334155', textTransform: 'uppercase' }}>
              Coming soon
            </span>
          )}
        </div>
      </div>
    </button>
  );
};

// ── Detail modal ──────────────────────────────────────────────────────────────

/**
 * Episode detail dialog.
 *
 * Uses the shared `Modal` (audit #65/#66). This hand-rolled a second modal that
 * declared `role="dialog" aria-modal="true"` while delivering none of the
 * behaviour those attributes promise: the Escape handler sat on a non-focusable
 * `<div>` with no tabIndex and nothing autofocusing it, so `onKeyDown` could
 * never fire — the key looked implemented and did nothing. There was also no
 * focus trap and no focus restore, and body scroll continued behind the
 * overlay. `Modal` already provides all four, plus a portal.
 */
const EpisodeDetail: React.FC<{ ep: Episode; onClose: () => void }> = ({ ep, onClose }) => {
  return (
    <Modal open onClose={onClose} maxWidth={760}>
      <div>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, paddingBottom: 14, borderBottom: '1px solid #1e2d3d' }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <span style={{ fontSize: 11, fontWeight: 800, color: '#64748b', letterSpacing: '0.08em' }}>
              EPISODE {ep.episode.toString().padStart(2, '0')} · {ep.level} · {ep.duration_min} min
            </span>
            <h2 id="academy-detail-title" style={{ fontSize: 18, fontWeight: 800, color: '#f1f5f9', margin: '4px 0 0' }}>
              {ep.title}
            </h2>
          </div>
          <button onClick={onClose} aria-label="Close"
            style={{ background: 'transparent', border: 'none', color: '#64748b', fontSize: 22, cursor: 'pointer', lineHeight: 1, padding: 0 }}>
            ×
          </button>
        </div>

        {/* Player or preview */}
        <div style={{ paddingTop: 20, display: 'flex', flexDirection: 'column', gap: 16 }}>
          {ep.published && ep.video_url ? (
            <div style={{ position: 'relative', paddingTop: '56.25%', background: '#000', borderRadius: 10, overflow: 'hidden' }}>
              <iframe
                src={ep.video_url}
                title={ep.title}
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                allowFullScreen
                style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', border: 'none' }}
              />
            </div>
          ) : (
            <div style={{
              display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
              gap: 8, padding: '36px 20px', background: 'linear-gradient(135deg, #0a1628 0%, #0d1f33 100%)',
              borderRadius: 10, border: '1px dashed #1e2d3d',
            }}>
              <span style={{ fontSize: 28 }}>🎬</span>
              <span style={{ fontSize: 14, fontWeight: 700, color: '#cbd5e1' }}>Coming soon</span>
              <span style={{ fontSize: 12, color: '#64748b', textAlign: 'center', maxWidth: 420 }}>
                This episode is scripted and in production. The full chapter outline is below so you
                can preview what it covers.
              </span>
            </div>
          )}

          <p style={{ fontSize: 13, color: '#94a3b8', lineHeight: 1.6, margin: 0 }}>{ep.summary}</p>

          {/* Chapters */}
          <div>
            <span style={{ fontSize: 11, fontWeight: 700, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
              Chapters
            </span>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2, marginTop: 8 }}>
              {(ep.chapters ?? []).map((c) => {
                // Chapters arrive as "MM:SS Title". Splitting on the first space
                // unconditionally meant a chapter without a leading timestamp
                // lost its first word into the time column. Only treat the first
                // token as a time when it looks like one.
                const m = /^(\d{1,2}:\d{2}(?::\d{2})?)\s+(.*)$/.exec(c.trim());
                const time  = m ? m[1] : '';
                const title = m ? m[2] : c.trim();
                return (
                  <div key={c} style={{ display: 'flex', gap: 12, padding: '6px 0', borderBottom: '1px solid #0f1a2a' }}>
                    <span style={{ fontSize: 12, fontWeight: 700, color: '#60a5fa', fontVariantNumeric: 'tabular-nums', minWidth: 44 }}>{time}</span>
                    <span style={{ fontSize: 12, color: '#cbd5e1' }}>{title}</span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </Modal>
  );
};

// ── Page ────────────────────────────────────────────────────────────────────

const Academy: React.FC = () => {
  const navigate = useNavigate();
  const toast = useToast();
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [userPlan, setUserPlan] = useState<Plan>('free');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Episode | null>(null);

  const mountedRef = useRef(true);
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const r = await tutorialsApi.list();
      if (!mountedRef.current) return;
      const data = r.data as { episodes?: Episode[]; user_plan?: Plan };
      setEpisodes(data.episodes ?? []);
      setUserPlan(data.user_plan ?? 'free');
    } catch (e: unknown) {
      if (!mountedRef.current) return;
      setError(extractApiError(e, 'Failed to load tutorials'));
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const handleOpen = useCallback(async (ep: Episode) => {
    if (ep.locked) {
      toast.info(`Episode ${ep.episode} requires the ${PLAN_LABELS[ep.plan]} plan or above.`);
      navigate('/upgrade');
      return;
    }
    // Open immediately with the catalogue entry (shows the script preview), then
    // hydrate the playable video_url from the gated detail endpoint in the
    // background. If the fetch fails we keep the preview rather than blanking.
    setSelected(ep);
    try {
      const r = await tutorialsApi.get(ep.episode);
      if (!mountedRef.current) return;
      const full = r.data as Episode;
      setSelected((cur) => (cur && cur.episode === ep.episode ? { ...cur, ...full } : cur));
    } catch {
      /* keep the preview — detail hydration is best-effort */
    }
  }, [navigate, toast]);

  const unlockedCount = episodes.filter((e) => !e.locked).length;

  return (
    <div className="page-content" style={{ flexDirection: 'column', overflow: 'auto', padding: 0 }}>
      <div style={{ padding: '12px 16px 0', flexShrink: 0 }}>
        <PageHeader
          title="🎓 HOPEFX Academy"
          icon="🎓"
          subtitle="Step-by-step video tutorials — from your first backtest to production deployment"
          breadcrumbs={[{ label: 'Dashboard', href: '/dashboard' }, { label: 'Academy' }]}
          badge={
            <span style={{ fontSize: 10, fontWeight: 800, padding: '2px 8px', borderRadius: 10, background: `${PLAN_COLORS[userPlan]}18`, color: PLAN_COLORS[userPlan], border: `1px solid ${PLAN_COLORS[userPlan]}40`, letterSpacing: 1 }}>
              {PLAN_LABELS[userPlan]}
            </span>
          }
        />
      </div>

      <div style={{ padding: 16, flex: 1, minHeight: 0 }}>
        {loading ? (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 48, color: '#64748b', fontSize: 13 }}>
            Loading tutorials…
          </div>
        ) : error ? (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10, padding: 48 }}>
            <span style={{ color: '#f87171', fontSize: 13 }}>⚠ {error}</span>
            <button onClick={() => void load()} style={{ background: '#1e2d3d', border: '1px solid #334155', borderRadius: 6, color: '#cbd5e1', fontSize: 12, fontWeight: 600, padding: '6px 14px', cursor: 'pointer' }}>
              Retry
            </button>
          </div>
        ) : episodes.length === 0 ? (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 48, color: '#64748b', fontSize: 13 }}>
            No tutorials available yet.
          </div>
        ) : (
          <>
            <div style={{ fontSize: 12, color: '#64748b', marginBottom: 12 }}>
              {episodes.length} episodes · {unlockedCount} available on your plan
              {unlockedCount < episodes.length && (
                <>
                  {' · '}
                  <button onClick={() => navigate('/upgrade')}
                    style={{ background: 'transparent', border: 'none', color: '#60a5fa', fontSize: 12, fontWeight: 700, cursor: 'pointer', padding: 0, textDecoration: 'underline' }}>
                    Upgrade to unlock all
                  </button>
                </>
              )}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 14 }}>
              {episodes.map((ep) => (
                <EpisodeCard key={ep.episode} ep={ep} onOpen={handleOpen} />
              ))}
            </div>
          </>
        )}
      </div>

      {selected && <EpisodeDetail ep={selected} onClose={() => setSelected(null)} />}
    </div>
  );
};

export default Academy;
