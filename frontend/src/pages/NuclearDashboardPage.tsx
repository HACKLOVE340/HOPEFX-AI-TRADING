/**
 * pages/NuclearDashboardPage.tsx
 * Route wrapper for the nuclear AI trading dashboard.
 * Accessible at /nuclear
 */

import React from 'react';
import { Link } from 'react-router-dom';
import { NuclearDashboard } from '../features/chart-bot';
import { PageHeader } from '../components/PageHeader';

const CROSS_LINKS = [
  { label: '🌍 Geopolitical', to: '/geopolitical', color: '#f59e0b' },
  { label: '📊 Correlation',  to: '/correlation',  color: '#60a5fa' },
  { label: '🔬 Research',     to: '/research',     color: '#a78bfa' },
  { label: '☢ Nuclear Risk',  to: '/geopolitical', color: '#ef4444' },
  { label: '⚡ Trade XAU',    to: '/trade',        color: '#4ade80' },
];

const NuclearDashboardPage: React.FC = () => (
  <div style={{ display: 'flex', flexDirection: 'column', height: '100%', width: '100%', overflow: 'hidden' }}>
    {/* PageHeader strip */}
    <div style={{
      padding: '8px 16px 0',
      background: 'rgba(8,12,20,0.97)',
      borderBottom: '1px solid #1a2e4a',
      flexShrink: 0,
    }}>
      <PageHeader
        title="☢ Nuclear AI Dashboard"
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
        style={{ marginBottom: 0, paddingBottom: 8 }}
      />
    </div>

    {/* Dashboard content */}
    <div style={{ flex: 1, overflow: 'hidden' }}>
      <NuclearDashboard />
    </div>
  </div>
);

export default NuclearDashboardPage;
