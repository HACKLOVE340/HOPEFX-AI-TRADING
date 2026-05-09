/**
 * SystemReliability.tsx
 * Full-page System Reliability Dashboard — Super Admin only.
 *
 * Accessible at /system-reliability (behind SuperAdminGuard).
 * Wraps SystemReliabilitySection with a page header and breadcrumb.
 */

import React, { Suspense, lazy } from 'react';
import { Link } from 'react-router-dom';
import { PageHeader } from '../components/PageHeader';
import { CrossLinkBar } from '../components/CrossLinkBar';
import { Badge } from '../components/Badge';

const SR_CROSS_LINKS = [
  { label: 'Super Admin',         href: '/superadmin',         icon: '⚡', color: '#f87171' },
  { label: 'System Status',       href: '/status',             icon: '🟢', color: '#4ade80' },
  { label: 'Auto-Heal',           href: '/auto-heal',          icon: '🩺', color: '#34d399' },
  { label: 'Security Dashboard',  href: '/security',           icon: '🛡️', color: '#f59e0b' },
  { label: 'Audit Log',           href: '/audit',              icon: '🔍', color: '#a78bfa' },
  { label: 'Admin Panel',         href: '/admin',              icon: '🔧', color: '#60a5fa' },
];

const SystemReliabilitySection = lazy(
  () => import('./superadmin/SystemReliabilitySection'),
);

const Fallback: React.FC = () => (
  <div style={{
    display: 'flex', alignItems: 'center', gap: 10,
    color: '#64748b', padding: '48px 0',
    fontFamily: 'Inter, system-ui, sans-serif',
  }}>
    <div style={{
      width: 20, height: 20, border: '2px solid #334155',
      borderTopColor: '#3b82f6', borderRadius: '50%',
      animation: 'spin 0.7s linear infinite',
    }} />
    Loading System Reliability Dashboard…
  </div>
);

const SystemReliability: React.FC = () => (
  <>
    <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    <div className="page-content">
        <PageHeader
          title="System Reliability Dashboard"
        icon="🔬"
          subtitle="Real-time end-to-end connectivity, OTel tracing, self-test suite, environment audit, and system metrics for every platform component."
          breadcrumbs={[
            { label: 'Home',        href: '/home' },
            { label: 'Admin Panel', href: '/admin' },
            { label: 'Super Admin', href: '/superadmin' },
            { label: 'System Reliability' },
          ]}
          badge={<Badge variant="info" style={{ fontSize: 11 }}>🔬 Live</Badge>}
          actions={
            <div style={{ display: 'flex', gap: 8 }}>
              <Link to="/superadmin"
                style={{ padding: '6px 14px', background: 'rgba(239,68,68,0.12)', border: '1px solid rgba(239,68,68,0.35)', borderRadius: 7, color: '#f87171', fontSize: 12, fontWeight: 700, textDecoration: 'none', display: 'flex', alignItems: 'center', gap: 4 }}>
                ⚡ Super Admin
              </Link>
              <Link to="/status"
                style={{ padding: '6px 14px', background: 'rgba(34,197,94,0.12)', border: '1px solid rgba(34,197,94,0.35)', borderRadius: 7, color: '#4ade80', fontSize: 12, fontWeight: 700, textDecoration: 'none', display: 'flex', alignItems: 'center', gap: 4 }}>
                🟢 Status
              </Link>
            </div>
          }
        />

        {/* Section content */}
        <Suspense fallback={<Fallback />}>
          <SystemReliabilitySection />
        </Suspense>

        <CrossLinkBar links={SR_CROSS_LINKS} title="Related" style={{ marginTop: 32 }} />
    </div>
  </>
);

export default SystemReliability;
