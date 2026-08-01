import React from 'react';

/**
 * ActionBanner — result of an operator action.
 *
 * Takes an EXPLICIT `ok` flag. Never infer success from the message text.
 *
 * Eighteen superadmin control surfaces chose their banner colour with
 * `msg.includes('fail') || msg.includes('error')`. Those messages carry the
 * server's `detail`, so any rejection whose wording lacks the magic substring
 * rendered green, styled identically to success — "Insufficient permissions",
 * "Already engaged", "Connection timed out", "Broker rejected request". That
 * covered the kill switch, emergency halt, risk limits, rate limiting, feature
 * flags, GDPR erasure and white-label provisioning: the screens where an
 * operator most needs to know whether the action actually landed.
 *
 * Two sites showed the pattern actively decaying — one had grown to test three
 * different spellings of "failed", and another tested for 'ACTIVATED' to force
 * red on a success, because keyword-sniffing had reached the point of inverting
 * its own meaning.
 *
 * `aria-live` is not incidental: none of the hand-rolled banners announced
 * themselves, so an operator using a screen reader got no feedback at all.
 * Failures assert, successes are polite.
 */
export const ActionBanner: React.FC<{
  message: string;
  ok: boolean;
  onDismiss?: () => void;
}> = ({ message, ok, onDismiss }) => {
  if (!message) return null;
  return (
    <div
      role={ok ? 'status' : 'alert'}
      aria-live={ok ? 'polite' : 'assertive'}
      style={{
        background: ok ? 'rgba(74,222,128,0.1)' : 'rgba(248,113,113,0.1)',
        border: `1px solid ${ok ? '#4ade80' : '#f87171'}`,
        borderRadius: 8,
        padding: '10px 14px',
        marginBottom: 16,
        fontSize: 13,
        color: ok ? '#4ade80' : '#f87171',
        display: 'flex',
        justifyContent: 'space-between',
        gap: 12,
      }}
    >
      <span>{ok ? '' : '⚠️ '}{message}</span>
      {onDismiss && (
        <button
          onClick={onDismiss}
          aria-label="Dismiss"
          style={{
            background: 'none',
            border: 'none',
            color: 'inherit',
            cursor: 'pointer',
            flexShrink: 0,
            fontSize: 15,
            lineHeight: 1,
          }}
        >
          ×
        </button>
      )}
    </div>
  );
};

export default ActionBanner;
