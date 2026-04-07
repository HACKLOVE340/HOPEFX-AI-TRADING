/**
 * NotFound — 404 page shown for any unmatched route.
 * Provides navigation back to the dashboard and a link to the previous page.
 */

import React from 'react';
import { useNavigate, useLocation } from 'react-router-dom';

const NotFound: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();

  return (
    <div
      style={{
        display:        'flex',
        flexDirection:  'column',
        alignItems:     'center',
        justifyContent: 'center',
        minHeight:      '100vh',
        background:     'var(--bg, #0a0f1a)',
        color:          'var(--text, #f1f5f9)',
        fontFamily:     'Inter, system-ui, -apple-system, sans-serif',
        padding:        '2rem',
        textAlign:      'center',
        gap:            '1.5rem',
      }}
    >
      {/* Status code */}
      <div
        style={{
          fontSize:    '6rem',
          fontWeight:  900,
          lineHeight:  1,
          background:  'linear-gradient(135deg, #3b82f6, #8b5cf6)',
          WebkitBackgroundClip: 'text',
          WebkitTextFillColor:  'transparent',
          backgroundClip:       'text',
          userSelect:           'none',
        }}
      >
        404
      </div>

      {/* Heading */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
        <h1 style={{ fontSize: '1.5rem', fontWeight: 700, margin: 0, color: '#f1f5f9' }}>
          Page not found
        </h1>
        <p style={{ fontSize: '0.875rem', color: '#64748b', margin: 0 }}>
          <code
            style={{
              background:   '#1e2d3d',
              borderRadius: '4px',
              padding:      '2px 6px',
              fontSize:     '0.8rem',
              color:        '#94a3b8',
            }}
          >
            {location.pathname}
          </code>{' '}
          does not exist.
        </p>
      </div>

      {/* Actions */}
      <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', justifyContent: 'center' }}>
        <button
          onClick={() => navigate('/dashboard', { replace: true })}
          style={{
            background:   '#3b82f6',
            border:       'none',
            borderRadius: '8px',
            color:        '#fff',
            cursor:       'pointer',
            fontSize:     '0.875rem',
            fontWeight:   600,
            padding:      '10px 20px',
            transition:   'background 0.15s',
          }}
          onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.background = '#2563eb'; }}
          onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.background = '#3b82f6'; }}
        >
          Go to Dashboard
        </button>

        <button
          onClick={() => navigate(-1)}
          style={{
            background:   'transparent',
            border:       '1px solid #334155',
            borderRadius: '8px',
            color:        '#94a3b8',
            cursor:       'pointer',
            fontSize:     '0.875rem',
            fontWeight:   600,
            padding:      '10px 20px',
            transition:   'border-color 0.15s, color 0.15s',
          }}
          onMouseEnter={(e) => {
            const btn = e.currentTarget as HTMLButtonElement;
            btn.style.borderColor = '#475569';
            btn.style.color = '#f1f5f9';
          }}
          onMouseLeave={(e) => {
            const btn = e.currentTarget as HTMLButtonElement;
            btn.style.borderColor = '#334155';
            btn.style.color = '#94a3b8';
          }}
        >
          Go Back
        </button>
      </div>
    </div>
  );
};

export default NotFound;
