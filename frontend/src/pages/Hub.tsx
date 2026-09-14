/**
 * Hub — the page behind a sidebar entry.
 *
 * The sidebar listed 61 destinations in one flat column. Fifteen of them were
 * under Analytics; eleven were under Account, and four of those eleven were
 * already sections inside Settings. A column that long stops being navigation
 * and becomes an index: the eight or nine things a trader opens daily sat
 * among fifty they open twice a year, in the same type, at the same weight.
 *
 * So the column now holds the daily ones, and everything else lives one click
 * behind a named hub. Nothing was removed and no route changed — each item is
 * a described, clickable card here instead of one more line there, which is
 * strictly more information than the sidebar could give it.
 *
 * One component serves every hub. The content comes from `navConfig.ts`, which
 * is already the single source of truth for what exists, who may see it and
 * what plan unlocks it — so a new page appears here by being added there, and
 * cannot be added to the app while being invisible in it.
 */

import React, { useMemo } from 'react';
import { useLocation, Navigate } from 'react-router-dom';

import { PageHeader } from '../components/PageHeader';
import { Surface, SurfaceBody } from '../components/system/Surface';
import { SubPageGrid, type SubPage } from '../components/system/SubPageGrid';
import { Tag } from '../components/system/Data';
import { hubByPath, itemsInHub, NAV_GROUPS } from '../components/sidebar/navConfig';
import { useStore, selectUser } from '../store';
import { hasFeatureAccess, isAdmin, normalisePlan } from '../lib/subscription';

/**
 * Cards for one hub, split into what this account can open and what it cannot.
 *
 * Locked items are shown rather than hidden. A product that hides what you
 * have not bought cannot tell you what buying would give you, and the
 * sidebar's own lock badges have always taken the opposite view.
 */
function toCards(items: ReturnType<typeof itemsInHub>): SubPage[] {
  return items.map((item) => ({
    to: item.path,
    title: item.label,
    description: DESCRIPTIONS[item.path] ?? 'Open this page.',
    icon: item.icon,
  }));
}

/**
 * One line each, written from the reader's side.
 *
 * The sidebar could only ever show a label, so "TCA" and "Walk-Forward" were
 * navigable only by people who already knew what they were. A hub has room for
 * the sentence that makes them findable by everyone else.
 */
const DESCRIPTIONS: Record<string, string> = {
  '/ai-assistant': 'Ask about the book, a position, or a signal in plain language.',
  '/ai-chart': 'The model annotates the chart: levels it sees, and why.',
  '/ai-chart-dashboard': 'Every annotated chart at once, across timeframes.',
  '/nuclear': 'The high-conviction engine and what it is currently refusing.',
  '/intelligence': 'Regime, sentiment and flow read together rather than separately.',
  '/ai-strategy': 'Generate a strategy from a description, then see it backtested.',
  '/pattern-detector': 'Recurring formations the model has found in this instrument.',
  '/strategy-builder': 'Compose entry, exit and sizing rules without writing code.',
  '/ai-core': 'Which model answered, what it cost, and what was refused.',

  '/performance': 'Win rate, drawdown and risk-adjusted return over time.',
  '/pnl': 'Realised and unrealised profit, by day, instrument and strategy.',
  '/transparency': 'Every claim this platform makes, with the measurement behind it.',
  '/correlation': 'What in your book moves together — and is therefore one bet.',
  '/indicators': 'Build and test your own indicators against real history.',
  '/walk-forward': 'Does the strategy survive out of sample, or only in it?',
  '/ab-testing': 'Two strategies, the same market, side by side.',
  '/tca': 'Execution quality: slippage, spread and commission versus expected.',
  '/replay': 'Replay a session tick by tick and watch the decisions again.',
  '/research': 'Long-form analysis and the data behind it.',
  '/geopolitical': 'Events that move gold, and how much they have historically.',
  '/news': 'Headlines scored for sentiment, newest first.',
  '/calendar': 'Scheduled releases that move the market, with prior impact.',
  '/prop-firm': 'Challenge progress against the daily loss and drawdown rules.',
  '/risk-calculator': 'Size a position from your stop and the risk you accept.',

  '/leaderboard': 'Who is performing, over what period, on what risk.',
  '/feed': 'Signals and commentary from traders you follow.',
  '/signals': 'Live model signals with confidence, entry and bracket.',
  '/marketplace': 'Strategies and indicators published by other traders.',
  '/affiliate': 'Your referrals, conversions and commission.',
  '/teams': 'Shared books and desks you belong to.',
  '/chat': 'Talk to other traders in real time.',
  '/copy-trading': 'Mirror another trader, with your own sizing and limits.',
  '/social': 'The public feed.',

  '/profile': 'Your public trader profile and what others can see.',
  '/wallet': 'Balance, deposits, withdrawals and payout history.',
  '/notifications': 'What you are told about, and where it reaches you.',
  '/kyc': 'Identity verification — required before a withdrawal.',
  '/sub-accounts': 'Separate books under one login.',
  '/mobile': 'Get the app, and pair this account with it.',
  '/upgrade': 'Compare plans and change yours.',
  '/academy': 'Learn the platform and the strategy behind it.',
  '/elite': 'Elite tier tools and the desk that comes with them.',
  '/support': 'Reach a human, and see your open tickets.',
  '/docs': 'Reference for every endpoint, flag and setting.',

  '/admin': 'User, plan and platform administration.',
  '/audit': 'Every privileged action, who took it and when.',
  '/security': 'Threats seen, blocked and pending review.',
  '/auto-heal': 'What the platform repaired without being asked.',
  '/observability': 'Metrics, traces and the health of every component.',
  '/ml-ops': 'Training runs, model registry and promotion gates.',
  '/support-console': 'The operator side of the support queue.',
  '/whitelabel': 'Tenant branding and per-tenant configuration.',
  '/master-control': 'Superadmin control plane.',
  '/reliability': 'SLOs, error budgets and incident history.',
  '/status': 'Live component status, as customers see it.',
};

const Hub: React.FC = () => {
  const { pathname } = useLocation();
  const user = useStore(selectUser);
  const hub = hubByPath(pathname);

  const items = useMemo(() => (hub ? itemsInHub(hub.id) : []), [hub]);

  const { open, locked } = useMemo(() => {
    // Exactly the predicate Sidebar.tsx uses for its lock badges. Two
    // independent answers to "can this account open this page" is one answer
    // too many: they drift, and the one the user sees becomes a coin toss.
    const role = user?.role ?? 'user';
    const plan = normalisePlan(user?.plan);
    const admin = isAdmin(role);
    const o: typeof items = [];
    const l: typeof items = [];
    for (const item of items) {
      const allowed = admin || !item.featureKey || hasFeatureAccess(role, plan, item.featureKey);
      (allowed ? o : l).push(item);
    }
    return { open: o, locked: l };
  }, [items, user]);

  // A URL naming a hub that does not exist is a 404's job, not a blank page's.
  if (!hub) return <Navigate to="/dashboard" replace />;

  const groupLabel = NAV_GROUPS.find((g) => g.id === hub.group)?.label ?? hub.label;

  return (
    <div className="flex flex-col gap-grid p-card">
      <PageHeader
        title={hub.label}
        subtitle={hub.description}
        icon={hub.icon}
        breadcrumbs={[{ label: 'Dashboard', href: '/dashboard' }, { label: hub.label }]}
        badge={<Tag tone="accent">{`${items.length} pages`}</Tag>}
      />

      {open.length > 0 && (
        <SubPageGrid items={toCards(open)} label={`${groupLabel} pages`} />
      )}

      {locked.length > 0 && (
        <Surface
          tone="quiet"
          title="On a higher plan"
          titleId="hub-locked"
          aside={`${locked.length} more`}
        >
          <SurfaceBody>
            {/* Shown, not hidden. A product that hides what you have not
                bought cannot tell you what buying would give you — and the
                sidebar's lock badges have always taken this view. */}
            <SubPageGrid items={toCards(locked)} label={`${groupLabel} pages on a higher plan`} />
          </SurfaceBody>
        </Surface>
      )}
    </div>
  );
};

export default Hub;
