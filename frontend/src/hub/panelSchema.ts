/**
 * hub/panelSchema.ts — a request becomes a panel nobody hand-wrote.
 *
 * §23 asks for schema-driven panel generation. §27 asks for accessibility.
 * Generated panels are exactly where the second one quietly dies: a hand-built
 * panel gets a label because somebody typed one, and a generated panel gets
 * whatever the generator remembered — which is usually nothing, so a screen
 * reader announces "region" forty times.
 *
 * The only arrangement where both survive is one where a descriptor **cannot
 * exist** without a label. `describePanel` throws on an empty intent rather
 * than emitting an unlabelled panel, because a panel that renders is a panel
 * somebody will ship.
 *
 * ## A panel that cannot be drawn says so
 *
 * A `chart` with no series is not a chart. Rendering an empty frame produces
 * something indistinguishable from a loading state, and an operator waiting for
 * data that was never coming. `renderable: false` with a reason instead.
 *
 * ## Empty is not the same as missing
 *
 * A table with no rows IS an answer — "no open positions" is information. A
 * chart with no series is a missing input. The schema distinguishes them,
 * because collapsing the two is how "you have no positions" and "we could not
 * load your positions" end up looking identical.
 *
 * ## It invents no fields
 *
 * Every field in the descriptor was found in the data. A schema that lists what
 * a kind *could* have produces panels with permanent blank rows.
 */

import type { SurfaceKind } from './contracts.shared';

/** ARIA role per kind. Roles a screen reader can actually use, not decoration. */
export const PANEL_ROLE: Partial<Record<SurfaceKind, string>> = {
  chart: 'img',
  heatmap: 'img',
  distribution: 'img',
  network: 'img',
  timeline: 'img',
  table: 'table',
  document: 'article',
  news: 'feed',
  research: 'article',
  code: 'code',
  terminal: 'log',
  text: 'article',
  agent_activity: 'log',
  image: 'img',
  video: 'region',
  map: 'img',
  camera: 'img',
};

export interface PanelField {
  name: string;
  /** Always true: a field is listed only when the data carried it. */
  present: boolean;
  kind: 'series' | 'rows' | 'text' | 'scalar' | 'unknown';
}

export interface PanelA11y {
  label: string;
  role: string;
  /** The text alternative. §27: the drawing is never the only channel. */
  description: string;
  animated: boolean;
}

export interface PanelDescriptor {
  kind: SurfaceKind;
  renderable: boolean;
  fields: PanelField[];
  a11y: PanelA11y;
  /** Shown when the panel is renderable and has nothing in it. */
  emptyMessage: string;
  /** Empty when renderable. Populated with why not, otherwise. */
  reason: string;
}

export interface PanelRequestLike {
  kind: SurfaceKind;
  intent: string;
  data?: Record<string, unknown>;
}

export interface DescribeOptions {
  reducedMotion?: boolean;
}

/** Kinds whose emptiness is a MISSING INPUT rather than an answer. */
const NEEDS_SERIES = new Set<SurfaceKind>(['chart', 'heatmap', 'distribution', 'timeline', 'network']);

/** Kinds whose emptiness is a real answer worth showing. */
const EMPTY_IS_AN_ANSWER = new Set<SurfaceKind>(['table', 'news', 'research', 'agent_activity']);

function fieldsOf(data: Record<string, unknown>): PanelField[] {
  const fields: PanelField[] = [];
  for (const [name, value] of Object.entries(data)) {
    let kind: PanelField['kind'] = 'unknown';
    if (Array.isArray(value)) kind = name === 'rows' ? 'rows' : 'series';
    else if (typeof value === 'string') kind = 'text';
    else if (typeof value === 'number') kind = 'scalar';
    fields.push({ name, present: true, kind });
  }
  return fields;
}

export function describePanel(request: PanelRequestLike, options: DescribeOptions = {}): PanelDescriptor {
  const intent = (request.intent ?? '').trim();
  if (!intent) {
    // Not a `renderable: false` result. A descriptor with no label must not be
    // constructible at all, because one that exists is one somebody renders.
    throw new Error('a generated panel needs an intent to build its accessible label from');
  }

  const data = request.data ?? {};
  const role = PANEL_ROLE[request.kind];
  const animated = options.reducedMotion !== true;

  const a11y: PanelA11y = {
    label: intent,
    role: role ?? 'region',
    description: `${request.kind} showing ${intent}`,
    animated,
  };

  if (role === undefined) {
    return {
      kind: request.kind,
      renderable: false,
      fields: [],
      a11y,
      emptyMessage: '',
      reason: `no schema describes a ${request.kind} panel, so it is not described rather than drawn blank`,
    };
  }

  const fields = fieldsOf(data);

  if (NEEDS_SERIES.has(request.kind)) {
    const series = fields.find((f) => f.kind === 'series');
    if (series === undefined) {
      return {
        kind: request.kind,
        renderable: false,
        fields: [],
        a11y,
        emptyMessage: '',
        reason: `a ${request.kind} needs a series and the data carries none; an empty frame reads as a loading state that never resolves`,
      };
    }
  }

  const emptyMessage = EMPTY_IS_AN_ANSWER.has(request.kind) ? `Nothing to show for ${intent}.` : '';

  return { kind: request.kind, renderable: true, fields, a11y, emptyMessage, reason: '' };
}
