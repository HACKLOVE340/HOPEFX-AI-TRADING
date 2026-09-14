/**
 * Position detail — the drill-down this app did not have.
 *
 * Before this page there were 87 routes and exactly one of them took a
 * parameter (`/profile/:id`). Nothing drilled in, so a large product read as a
 * shallow one: a trader could see a row for a position and had nowhere to go
 * with it. The row's click went to `/trade` with the symbol and side prefilled
 * (audit F225) — useful, and one level too early. That action is still here,
 * as an action, where it belongs once you already know what you're looking at.
 *
 * It is also the reference implementation for the token layer. Every colour,
 * size, radius, shadow and duration comes from `src/index.css` through the
 * primitives in `components/system/`, so this page is correct in dark, in
 * light, and inside an AI surface, and contains no literal for the colour
 * ratchet to count.
 *
 * Two rules of this repository shape what is on screen more than the styling
 * does. Money figures are derived from the server's own numbers or shown as
 * absent — never as zero, which on a risk screen reads as "safe" (see
 * `lib/position_math.ts`). And nothing here enforces anything: the gates live
 * in `risk/manager.py` and `invariants/`, and a page that implied otherwise
 * would be the shape this codebase keeps finding.
 */

import React, { useMemo } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, Coins } from 'lucide-react';

import { PageShell } from '../components/system/PageShell';
import { EmptyState } from '../components/EmptyState';
import { Surface, SurfaceBody } from '../components/system/Surface';
import { KeyValue, MetricStrip, Tag, toneOf } from '../components/system/Data';
import { useStore, selectPositions } from '../store';
import { fmtPnl, fmtPrice, fmtRelative, fmtDateTime, positionSide } from '../lib/utils';
import { bracketProgress, distanceTo, riskReward } from '../lib/position_math';

/** Absent, not zero. Every unknown on this page renders the same way. */
const DASH = '—';
const money = (v: number | null): string => (v === null ? DASH : fmtPnl(v).replace(/^\+/, ''));
const price = (v: number | null | undefined): string =>
  v === null || v === undefined ? DASH : fmtPrice(v);

/**
 * Where the mark sits between stop and target.
 *
 * The bracket is the question a trader is actually asking — how much room is
 * left, which way — and it is answerable by looking rather than by subtracting
 * two numbers in your head. Rendered from the position alone, so it is
 * available even when nothing else about the session is.
 */
const BracketLadder: React.FC<{
  stop: number | null | undefined;
  target: number | null | undefined;
  mark: number | null | undefined;
  at: number | null;
}> = ({ stop, target, mark, at }) => {
  if (at === null) {
    return (
      <p className="text-label text-dim">
        {stop === null || stop === undefined
          ? 'No stop is set on this position, so there is no bracket to show and the downside is unbounded.'
          : 'No target is set on this position.'}
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-s3">
      <div
        className="relative h-2 rounded-pill border border-hairline bg-sunken"
        role="img"
        aria-label={`Mark ${price(mark)} sits ${Math.round(at * 100)} percent of the way from the stop at ${price(stop)} to the target at ${price(target)}.`}
      >
        <i
          className="absolute inset-y-0 left-0 rounded-pill bg-accent-soft"
          style={{ width: `${(at * 100).toFixed(1)}%` }}
        />
        <i
          className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-pill border-2 border-edge-strong bg-accent"
          style={{ left: `${(at * 100).toFixed(1)}%` }}
        />
      </div>
      <div className="flex justify-between font-mono text-micro tabular-nums">
        <span className="text-loss">Stop {price(stop)}</span>
        <span className="text-strong">Mark {price(mark)}</span>
        <span className="text-gain">Target {price(target)}</span>
      </div>
    </div>
  );
};

const PositionDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const positions = useStore(selectPositions);

  const position = useMemo(
    () => positions.find((p) => p.id === id) ?? null,
    [positions, id],
  );

  const side = positionSide(position);
  const rr = useMemo(() => riskReward(position), [position]);
  const at = useMemo(() => bracketProgress(position), [position]);

  const crumbs = [
    { label: 'Dashboard', href: '/dashboard' },
    { label: 'Portfolio', href: '/portfolio' },
    { label: position ? position.symbol : 'Position' },
  ];

  if (!position) {
    return (
      <PageShell title="Position" width="standard" breadcrumbs={crumbs}>
        <Surface>
          <EmptyState
            icon={Coins}
            title="That position is not open"
            description={
              id
                ? `Nothing open matches ${id}. It may have closed since the link was made, or it belongs to another account.`
                : 'No position was named in the link.'
            }
            links={[
              { label: 'Open positions', href: '/portfolio' },
              { label: 'Closed trades', href: '/journal' },
            ]}
          />
        </Surface>
      </PageShell>
    );
  }

  const openTicket = () =>
    navigate('/trade', {
      state: { signal: { symbol: position.symbol, direction: side === 'short' ? 'SELL' : 'BUY' } },
    });

  return (
    <PageShell
      width="wide"
      title={position.symbol}
        subtitle={`${side ? side.toUpperCase() : 'Position'} · opened ${fmtRelative(position.opened_at)}`}
        breadcrumbs={crumbs}
        badge={<Tag tone={side === 'short' ? 'loss' : 'gain'}>{side ?? 'unknown'}</Tag>}
        actions={
          <div className="flex flex-wrap gap-s2">
            <Link
              to="/portfolio"
              className="inline-flex min-h-touch items-center gap-s2 rounded-sm2 border border-edge px-s4
                         text-label font-semibold text-ink no-underline transition-colors duration-fast
                         ease-out hover:border-accent focus-visible:outline-none focus-visible:ring-2
                         focus-visible:ring-focus"
            >
              <ArrowLeft size={13} strokeWidth={2} aria-hidden />
              All positions
            </Link>
            <button
              type="button"
              onClick={openTicket}
              className="inline-flex min-h-touch items-center rounded-sm2 border border-accent bg-accent
                         px-s4 text-label font-semibold text-on-accent transition-opacity duration-fast
                         ease-out hover:opacity-90 focus-visible:outline-none focus-visible:ring-2
                         focus-visible:ring-focus"
            >
              Open ticket
            </button>
          </div>
        }
      >
      {/* The figure the page is about, and immediately what it cost to get it. */}
      <Surface tone="raised">
        <div className="flex flex-wrap items-start justify-between gap-s4 p-card">
          <div className="flex flex-col gap-s1">
            <span className="font-mono text-micro uppercase tabular-nums text-faint">
              {position.id} · size {fmtPrice(position.size, 2)} · entry {price(position.entry_price)}
            </span>
            <span className="text-label text-dim">Unrealised on the open position</span>
          </div>
          <div className="text-right">
            <div
              className={`font-mono text-hero font-bold tabular-nums ${
                toneOf(position.unrealized_pnl) === 'gain'
                  ? 'text-gain'
                  : toneOf(position.unrealized_pnl) === 'loss'
                    ? 'text-loss'
                    : 'text-strong'
              }`}
            >
              {fmtPnl(position.unrealized_pnl)}
            </div>
            <div className="mt-s1 font-mono text-micro tabular-nums text-faint">
              {rr.risk === null
                ? 'Risk to stop is not derivable until the price moves off the entry'
                : `${money(rr.risk)} risked to the stop · realised ${fmtPnl(position.realized_pnl)}`}
            </div>
          </div>
        </div>

        <SurfaceBody className="border-t border-hairline">
          <BracketLadder
            stop={position.stop_loss}
            target={position.take_profit}
            mark={position.current_price}
            at={at}
          />
        </SurfaceBody>
      </Surface>

      <MetricStrip
        items={[
          { label: 'Mark', value: price(position.current_price) },
          { label: 'Entry', value: price(position.entry_price) },
          {
            label: 'To stop',
            value: price(distanceTo(position, position.stop_loss)),
            sub: money(rr.risk),
            tone: 'loss',
          },
          {
            label: 'To target',
            value: price(distanceTo(position, position.take_profit)),
            sub: money(rr.reward),
            tone: 'gain',
          },
          {
            label: 'Reward / risk',
            value: rr.ratio === null ? DASH : `${rr.ratio.toFixed(2)}R`,
            sub: rr.ratio === null ? 'needs both levels' : 'at the current levels',
          },
        ]}
      />

      <div className="grid gap-grid [grid-template-columns:repeat(auto-fit,minmax(min(300px,100%),1fr))]">
        <Surface title="Position" titleId="pd-position">
          <KeyValue
            rows={[
              { label: 'Instrument', value: position.symbol },
              { label: 'Side', value: side ? side.toUpperCase() : DASH },
              { label: 'Size', value: fmtPrice(position.size, 2) },
              { label: 'Entry price', value: price(position.entry_price) },
              { label: 'Stop loss', value: price(position.stop_loss), tone: 'loss' },
              { label: 'Take profit', value: price(position.take_profit), tone: 'gain' },
              { label: 'Opened', value: fmtDateTime(position.opened_at) },
            ]}
          />
        </Surface>

        <Surface title="Risk and result" titleId="pd-risk">
          <KeyValue
            rows={[
              { label: 'Unrealised', value: fmtPnl(position.unrealized_pnl), tone: toneOf(position.unrealized_pnl) },
              { label: 'Realised', value: fmtPnl(position.realized_pnl), tone: toneOf(position.realized_pnl) },
              { label: 'Risked to stop', value: money(rr.risk), tone: 'loss' },
              { label: 'Earned at target', value: money(rr.reward), tone: 'gain' },
              { label: 'Reward / risk', value: rr.ratio === null ? DASH : `${rr.ratio.toFixed(2)}R` },
              {
                label: 'Room to stop',
                value: at === null ? DASH : `${Math.round(at * 100)}% of the bracket used`,
              },
            ]}
          />
          <div className="border-t border-hairline px-card py-s3 text-micro text-dim">
            Money figures are derived from this position&apos;s own P&amp;L rather than a contract
            table the frontend does not have. Where the price has not moved off the entry, or a
            level is not set, the figure is shown as {DASH} rather than as zero.
          </div>
        </Surface>
      </div>

    </PageShell>
  );
};

export default PositionDetail;
