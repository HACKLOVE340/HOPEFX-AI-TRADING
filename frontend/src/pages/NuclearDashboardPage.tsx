/**
 * pages/NuclearDashboardPage.tsx
 * Route wrapper for the nuclear AI trading dashboard.
 * Accessible at /nuclear
 */

import React from 'react';
import { Link } from 'react-router-dom';
import { Globe, Newspaper, Radiation, Sparkles, Zap } from 'lucide-react';
import { NuclearDashboard } from '../features/chart-bot';
import { PageShell } from '../components/system/PageShell';

const CROSS_LINKS = [
  { label: '🌍 Geopolitical', to: '/geopolitical', color: '#f59e0b' },
  { label: '📊 Correlation',  to: '/correlation',  color: '#60a5fa' },
  { label: '🔬 Research',     to: '/research',     color: '#a78bfa' },
  { label: '☢ Nuclear Risk',  to: '/geopolitical', color: '#ef4444' },
  { label: '⚡ Trade XAU',    to: '/trade',        color: '#4ade80' },
];

/*
 * On the standard shell, at the fourth width.
 *
 * This page could not migrate until `PageShell` had a `full` width: it is a
 * workspace, and the three max-width tiers would have letterboxed the dashboard
 * inside it. `fills` is what lets `<NuclearDashboard />` keep its own scroller
 * instead of growing the page.
 *
 * The hand-rolled header strip is gone and nothing it carried is: the title,
 * the icon, the subtitle, the breadcrumbs, the LIVE badge and the four cross
 * links are all `PageShell` props now. The ☢ in the title went with it — the
 * `icon={Radiation}` beside it said the same thing, and one of the two was an
 * emoji standing in for an icon.
 */
const NuclearDashboardPage: React.FC = () => (
  <PageShell
    width="full"
    fills
    title="Nuclear AI Dashboard"
    icon={Radiation}
    subtitle="Real-time nuclear risk intelligence · geopolitical threat scoring · XAU/USD safe-haven impact"
    breadcrumbs={[
      { label: 'Dashboard',    href: '/dashboard' },
      { label: 'Analytics',    href: '/performance' },
      { label: 'Geopolitical', href: '/geopolitical' },
      { label: 'Nuclear AI' },
    ]}
    badge={
      <span style={{
        fontSize: 10, fontWeight: 800, padding: '2px 8px', borderRadius: 10,
        background: 'rgba(239,68,68,0.15)', color: '#ef4444',
        border: '1px solid rgba(239,68,68,0.35)', letterSpacing: 1,
      }}>
        ● LIVE
      </span>
    }
    actions={
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {CROSS_LINKS.map(({ label, to, color }) => (
          <Link
            key={to + label}
            to={to}
            style={{
              padding: '4px 10px',
              background: `${color}12`,
              border: `1px solid ${color}35`,
              borderRadius: 6,
              color,
              fontSize: 11,
              fontWeight: 600,
              textDecoration: 'none',
              transition: 'background 0.15s',
            }}
            onMouseEnter={e => { (e.currentTarget as HTMLAnchorElement).style.background = `${color}22`; }}
            onMouseLeave={e => { (e.currentTarget as HTMLAnchorElement).style.background = `${color}12`; }}
          >
            {label}
          </Link>
        ))}
      </div>
    }
    related={[
      { to: '/geopolitical', label: 'Geopolitical risk', hint: 'What is driving the hedge', icon: Globe },
      { to: '/news', label: 'News & sentiment', hint: 'Headlines behind the score', icon: Newspaper },
      { to: '/intelligence', label: 'AI intelligence', hint: 'Model health and gates', icon: Sparkles },
      { to: '/trade', label: 'Trading ticket', hint: 'Act on the signal', icon: Zap },
    ]}
  >
    {/* Dashboard content */}
    <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
      <NuclearDashboard />
    </div>
  </PageShell>
);

export default NuclearDashboardPage;
