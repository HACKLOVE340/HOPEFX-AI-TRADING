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
import { Badge } from '../components/Badge';

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
    <div style={{
      minHeight: '100vh',
      background: '#0f172a',
      color: '#f1f5f9',
      fontFamily: 'Inter, system-ui, -apple-system, sans-serif',
      padding: '32px 24px',
      boxSizing: 'border-box',
    }}>
      <div style={{ maxWidth: 1200, margin: '0 auto' }}>
        <PageHeader
          title="System Reliability Dashboard"
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

        {/* Cross-links */}
        <div style={{ borderTop: '1px solid #1e293b', paddingTop: 20, marginTop: 32 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 12 }}>
            Related
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 10 }}>
            {[
              { icon: '⚡', label: 'Super Admin',          desc: 'Master control panel',             to: '/superadmin' },
              { icon: '🟢', label: 'System Status',        desc: 'Component health & uptime',        to: '/status' },
              { icon: '🩺', label: 'Auto-Heal',            desc: 'Self-healing & fix approvals',     to: '/auto-heal' },
              { icon: '🛡️', label: 'Security Dashboard',  desc: 'Threats, IPs, lockdown controls',  to: '/security' },
              { icon: '🔍', label: 'Audit Log',            desc: 'Full event trail with filters',    to: '/audit' },
              { icon: '🔧', label: 'Admin Panel',          desc: 'Platform overview & KPIs',         to: '/admin' },
            ].map(({ icon, label, desc, to }) => (
              <Link
                key={to}
                to={to}
                style={{ display: 'flex', alignItems: 'center', gap: 12, background: '#0d1421', border: '1px solid #1e293b', borderRadius: 10, padding: '12px 16px', textDecoration: 'none' }}
                onMouseEnter={e => { (e.currentTarget as HTMLAnchorElement).style.borderColor = '#334155'; (e.currentTarget as HTMLAnchorElement).style.background = '#111827'; }}
                onMouseLeave={e => { (e.currentTarget as HTMLAnchorElement).style.borderColor = '#1e293b'; (e.currentTarget as HTMLAnchorElement).style.background = '#0d1421'; }}
              >
                <span style={{ fontSize: 20, flexShrink: 0 }}>{icon}</span>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: '#f1f5f9' }}>{label}</div>
                  <div style={{ fontSize: 11, color: '#64748b', marginTop: 1 }}>{desc}</div>
                </div>
                <span style={{ marginLeft: 'auto', color: '#334155', fontSize: 16 }}>›</span>
              </Link>
            ))}
          </div>
        </div>
      </div>
    </div>
  </>
);

export default SystemReliability;
