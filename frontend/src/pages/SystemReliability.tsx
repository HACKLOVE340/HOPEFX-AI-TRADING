/**
 * SystemReliability.tsx
 * Full-page System Reliability Dashboard — Super Admin only.
 *
 * Accessible at /system-reliability (behind SuperAdminGuard).
 * Wraps SystemReliabilitySection with a page header and breadcrumb.
 */

import React, { Suspense, lazy } from 'react';

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
        {/* Page header */}
        <div style={{ marginBottom: 28 }}>
          <div style={{ fontSize: 12, color: '#475569', marginBottom: 6 }}>
            Super Admin → System Reliability
          </div>
          <h1 style={{
            fontSize: 28, fontWeight: 800, color: '#f8fafc',
            margin: 0, letterSpacing: '-0.02em',
          }}>
            🔬 System Reliability Dashboard
          </h1>
          <p style={{ fontSize: 14, color: '#64748b', marginTop: 6, marginBottom: 0 }}>
            Real-time end-to-end connectivity status, OTel tracing, self-test suite,
            environment audit, and system metrics for every platform component.
          </p>
        </div>

        {/* Section content */}
        <Suspense fallback={<Fallback />}>
          <SystemReliabilitySection />
        </Suspense>
      </div>
    </div>
  </>
);

export default SystemReliability;
