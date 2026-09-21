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

import { PageShell } from '../components/system/PageShell';
import { Surface, SurfaceBody } from '../components/system/Surface';
import { SubPageGrid, type SubPage } from '../components/system/SubPageGrid';
import { Tag } from '../components/system/Data';
import { hubByPath, itemsInHub, NAV_GROUPS } from '../components/sidebar/navConfig';
import { NAV_DESCRIPTIONS } from '../components/sidebar/navDescriptions';
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
    description: NAV_DESCRIPTIONS[item.path] ?? 'Open this page.',
    icon: item.icon,
  }));
}


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
    <PageShell
      width="wide"
      title={hub.label}
      subtitle={hub.description}
      icon={hub.icon}
      breadcrumbs={[{ label: 'Dashboard', href: '/dashboard' }, { label: hub.label }]}
      badge={<Tag tone="accent">{`${items.length} pages`}</Tag>}
      /* A hub IS the "where to next" page; a second one at its foot would be
         the same grid twice. */
      related={false}
    >

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
    </PageShell>
  );
};

export default Hub;
