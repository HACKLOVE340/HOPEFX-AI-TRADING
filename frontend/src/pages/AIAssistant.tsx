/**
 * AI Assistant — full-page conversational trading assistant.
 *
 * Wraps the shared <AIChat> core (POST /api/chat). Works with Claude/OpenAI
 * when a key is configured, and with the built-in offline assistant otherwise.
 */
import React from 'react';
import AIChat from '../components/ai/AIChat';

const SUGGESTIONS = [
  'What is my account balance and P&L?',
  'Show me my open positions',
  'What are the latest trade signals?',
  'What economic events are coming up?',
  'Explain how the risk kill-switch works',
];

const INTRO =
  '**HOPEFX AI Assistant.** Ask me about your account, open positions, live signals, ' +
  'the gold market, risk controls, or how to use any part of the platform.';

const AIAssistant: React.FC = () => {
  return (
    <div className="page-content" style={{ padding: 0, flexDirection: 'column', overflow: 'hidden' }}>
      <div style={{ padding: '16px 20px 12px', borderBottom: '1px solid #1e293b', display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{ fontSize: 22 }}>🤖</span>
        <div>
          <h2 style={{ fontSize: 17, fontWeight: 700, color: '#f1f5f9', margin: 0 }}>AI Assistant</h2>
          <div style={{ fontSize: 12, color: '#64748b' }}>Your trading copilot — powered by HOPEFX AI</div>
        </div>
      </div>
      <div style={{ flex: 1, minHeight: 0 }}>
        <AIChat sessionId="assistant" intro={INTRO} suggestions={SUGGESTIONS} placeholder="Ask about your account, signals, risk…" />
      </div>
    </div>
  );
};

export default AIAssistant;
