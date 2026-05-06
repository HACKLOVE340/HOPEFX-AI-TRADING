/**
 * pages/NuclearDashboardPage.tsx
 * Route wrapper for the nuclear AI trading dashboard.
 * Accessible at /nuclear
 */

import React from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { NuclearDashboard } from '../features/chart-bot';

const NuclearDashboardPage: React.FC = () => {
  const navigate = useNavigate();

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', width: '100%', overflow: 'hidden' }}>
      {/* Breadcrumb + cross-link bar */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '6px 16px',
        background: 'rgba(8,12,20,0.95)',
        borderBottom: '1px solid #1a2e4a',
        flexShrink: 0,
        flexWrap: 'wrap',
        gap: 8,
      }}>
        {/* Breadcrumb */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, color: '#475569' }}>
          <Link to="/dashboard" style={{ color: '#475569', textDecoration: 'none' }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLAnchorElement).style.color = '#64748b'; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLAnchorElement).style.color = '#475569'; }}
          >
            Dashboard
          </Link>
          <span style={{ color: '#1e293b' }}>›</span>
          <Link to="/geopolitical" style={{ color: '#475569', textDecoration: 'none' }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLAnchorElement).style.color = '#64748b'; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLAnchorElement).style.color = '#475569'; }}
          >
            Geopolitical
          </Link>
          <span style={{ color: '#1e293b' }}>›</span>
          <span style={{ color: '#64748b', fontWeight: 500 }}>Nuclear AI Dashboard</span>
        </div>

        {/* Cross-links */}
        <div style={{ display: 'flex', gap: 6 }}>
          {[
            { label: '🌍 Geopolitical', path: '/geopolitical', color: '#f59e0b' },
            { label: '📊 Correlation',  path: '/correlation',  color: '#60a5fa' },
            { label: '🔬 Research',     path: '/research',     color: '#a78bfa' },
            { label: '⚡ Trade XAU',    path: '/trade',        color: '#4ade80' },
          ].map(({ label, path, color }) => (
            <button
              key={path}
              onClick={() => navigate(path)}
              style={{
                padding: '3px 10px', background: 'transparent',
                border: `1px solid ${color}30`, borderRadius: 5,
                color: '#94a3b8', fontSize: 10, fontWeight: 600,
                cursor: 'pointer', fontFamily: 'inherit',
                transition: 'all 0.15s',
              }}
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLButtonElement).style.color = color;
                (e.currentTarget as HTMLButtonElement).style.borderColor = `${color}70`;
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLButtonElement).style.color = '#94a3b8';
                (e.currentTarget as HTMLButtonElement).style.borderColor = `${color}30`;
              }}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Dashboard content */}
      <div style={{ flex: 1, overflow: 'hidden' }}>
        <NuclearDashboard />
      </div>
    </div>
  );
};

export default NuclearDashboardPage;
