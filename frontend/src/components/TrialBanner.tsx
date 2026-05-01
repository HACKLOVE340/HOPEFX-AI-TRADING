/**
 * TrialBanner.tsx
 * Sticky top banner shown to users on a free trial.
 *
 * Reads trial state from the Zustand store (populated by usePlan).
 * Dismissed per-session via localStorage so it doesn't reappear on
 * every navigation within the same tab.
 */

import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useStore, selectTrial, selectTrialDaysRemaining } from '../store';

const DISMISS_KEY = 'hopefx_trial_banner_dismissed';

const TrialBanner: React.FC = () => {
  const trial              = useStore(selectTrial);
  const daysRemaining      = useStore(selectTrialDaysRemaining);
  const navigate           = useNavigate();
  const [dismissed, setDismissed] = useState<boolean>(
    () => sessionStorage.getItem(DISMISS_KEY) === '1',
  );

  if (!trial || dismissed) return null;

  const handleDismiss = () => {
    sessionStorage.setItem(DISMISS_KEY, '1');
    setDismissed(true);
  };

  const urgency = daysRemaining !== null && daysRemaining <= 3;

  return (
    <div style={{
      position: 'sticky',
      top: 0,
      zIndex: 1000,
      background: urgency ? '#7f1d1d' : '#1e3a5f',
      borderBottom: `1px solid ${urgency ? '#991b1b' : '#1d4ed8'}`,
      padding: '8px 16px',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 12,
      fontSize: 13,
      color: urgency ? '#fca5a5' : '#93c5fd',
    }}>
      <span>
        {urgency ? '⚠️' : '🎉'}{' '}
        <strong style={{ color: urgency ? '#fef2f2' : '#eff6ff' }}>
          {daysRemaining !== null
            ? daysRemaining === 0
              ? 'Your free trial expires today'
              : `${daysRemaining} day${daysRemaining === 1 ? '' : 's'} left on your free trial`
            : 'You\'re on a free trial'}
        </strong>
        {' — '}
        Upgrade to keep access to journal, performance analytics, alerts, and more.
      </span>
      <div style={{ display: 'flex', gap: 8, flexShrink: 0 }}>
        <button
          onClick={() => navigate('/pricing')}
          style={{
            background: urgency ? '#dc2626' : '#2563eb',
            border: 'none',
            borderRadius: 6,
            color: '#fff',
            cursor: 'pointer',
            fontSize: 12,
            fontWeight: 600,
            padding: '5px 14px',
          }}
        >
          Upgrade now
        </button>
        <button
          onClick={handleDismiss}
          aria-label="Dismiss trial banner"
          style={{
            background: 'transparent',
            border: 'none',
            color: urgency ? '#fca5a5' : '#93c5fd',
            cursor: 'pointer',
            fontSize: 16,
            lineHeight: 1,
            padding: '2px 6px',
          }}
        >
          ×
        </button>
      </div>
    </div>
  );
};

export default TrialBanner;
