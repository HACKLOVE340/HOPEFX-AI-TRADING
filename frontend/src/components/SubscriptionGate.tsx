/**
 * SubscriptionGate.tsx
 * Wraps any route/component and blocks access if the user's plan is below
 * the required tier. Admins always pass through.
 */

import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useStore, selectUser, selectPlan } from '../store';
import { isAdmin, hasFeatureAccess, PLAN_LABELS, PLAN_COLORS, requiredPlan } from '../lib/subscription';
import type { Plan } from '../lib/subscription';

interface Props {
  featureKey: string;
  children: React.ReactNode;
}

const SubscriptionGate: React.FC<Props> = ({ featureKey, children }) => {
  const user    = useStore(selectUser);
  const plan    = useStore(selectPlan);
  const navigate = useNavigate();

  // user is null while AuthGuard is syncing the role from /api/auth/me.
  // Return a spinner rather than null (blank) or the upgrade wall (wrong role).
  if (!user) {
    return (
      <div style={{
        minHeight: '60vh', display: 'flex', alignItems: 'center',
        justifyContent: 'center', background: '#0f172a',
      }}>
        <div style={{
          width: 28, height: 28, borderRadius: '50%',
          border: '3px solid #1e293b', borderTopColor: '#3b82f6',
          animation: 'spin 0.7s linear infinite',
        }} />
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      </div>
    );
  }

  if (hasFeatureAccess(user.role, plan, featureKey)) {
    return <>{children}</>;
  }

  const needed      = requiredPlan(featureKey) as Plan;
  const neededLabel = PLAN_LABELS[needed];
  const neededColor = PLAN_COLORS[needed];

  return (
    <div style={{
      minHeight: '60vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: '#0f172a', padding: 40,
    }}>
      <div style={{
        maxWidth: 440, textAlign: 'center',
        background: '#1e293b', border: '1px solid #334155',
        borderRadius: 16, padding: '40px 36px',
      }}>
        <div style={{
          width: 56, height: 56, borderRadius: '50%',
          background: `${neededColor}18`, border: `2px solid ${neededColor}40`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          margin: '0 auto 20px', fontSize: 24,
        }}>
          🔒
        </div>

        <h2 style={{ fontSize: 20, fontWeight: 700, color: '#f8fafc', margin: '0 0 10px' }}>
          {neededLabel} plan required
        </h2>
        <p style={{ fontSize: 14, color: '#64748b', margin: '0 0 28px', lineHeight: 1.6 }}>
          This feature is available on the{' '}
          <span style={{ color: neededColor, fontWeight: 600 }}>{neededLabel}</span> plan and above.
          Upgrade to unlock it.
        </p>

        <div style={{ display: 'flex', gap: 12, justifyContent: 'center' }}>
          <button
            onClick={() => navigate('/pricing')}
            style={{
              background: neededColor, border: 'none', borderRadius: 8,
              color: '#fff', cursor: 'pointer', fontSize: 14, fontWeight: 600,
              padding: '10px 24px',
            }}
          >
            Upgrade now
          </button>
          <button
            onClick={() => navigate(-1)}
            style={{
              background: 'transparent', border: '1px solid #334155', borderRadius: 8,
              color: '#94a3b8', cursor: 'pointer', fontSize: 14, fontWeight: 500,
              padding: '10px 20px',
            }}
          >
            Go back
          </button>
        </div>
      </div>
    </div>
  );
};

export default SubscriptionGate;
