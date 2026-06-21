/**
 * AISupportWidget — floating AI support chat, available on every authenticated
 * page. A bubble in the bottom-right corner opens a compact support assistant.
 *
 * Uses the shared <AIChat> core with a dedicated "support" session so its
 * history stays separate from the full-page assistant. Backed by POST /api/chat
 * (Claude/OpenAI, with offline fallback), so it always responds.
 */
import React, { useState } from 'react';
import AIChat from './AIChat';

const SUPPORT_INTRO =
  '**HOPEFX Support.** I can help with logging in, subscriptions and billing, ' +
  'connecting a broker, KYC, deposits/withdrawals, and finding features. How can I help?';

const SUPPORT_SUGGESTIONS = [
  'How do I connect my broker account?',
  'How do I upgrade my plan?',
  'Where do I complete KYC verification?',
  'How do deposits and withdrawals work?',
];

const AISupportWidget: React.FC = () => {
  const [open, setOpen] = useState(false);

  return (
    <>
      {/* Launcher bubble */}
      <button
        onClick={() => setOpen(o => !o)}
        aria-label={open ? 'Close support chat' : 'Open support chat'}
        style={{
          position: 'fixed', right: 20, bottom: 20, zIndex: 1200,
          width: 56, height: 56, borderRadius: '50%', border: 'none', cursor: 'pointer',
          background: open ? '#1e293b' : 'linear-gradient(135deg, #3b82f6, #6366f1)',
          color: '#fff', fontSize: 24, boxShadow: '0 6px 20px rgba(0,0,0,0.35)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}
      >
        {open ? '✕' : '💬'}
      </button>

      {/* Panel */}
      {open && (
        <div
          style={{
            position: 'fixed', right: 20, bottom: 88, zIndex: 1200,
            width: 'min(380px, calc(100vw - 40px))', height: 'min(560px, calc(100vh - 130px))',
            background: '#0f172a', border: '1px solid #1e293b', borderRadius: 14,
            boxShadow: '0 12px 40px rgba(0,0,0,0.5)', display: 'flex', flexDirection: 'column', overflow: 'hidden',
          }}
        >
          <div style={{ padding: '12px 16px', borderBottom: '1px solid #1e293b', display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 18 }}>🎧</span>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: '#f1f5f9' }}>AI Support</div>
              <div style={{ fontSize: 11, color: '#64748b' }}>Typically replies instantly</div>
            </div>
            <button onClick={() => setOpen(false)} aria-label="Close" style={{ background: 'none', border: 'none', color: '#64748b', fontSize: 18, cursor: 'pointer' }}>✕</button>
          </div>
          <div style={{ flex: 1, minHeight: 0 }}>
            <AIChat sessionId="support" intro={SUPPORT_INTRO} suggestions={SUPPORT_SUGGESTIONS} placeholder="Ask support…" compact />
          </div>
        </div>
      )}
    </>
  );
};

export default AISupportWidget;
