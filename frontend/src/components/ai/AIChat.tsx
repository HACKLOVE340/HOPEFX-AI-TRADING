/**
 * AIChat — reusable conversational UI wired to the HOPEFX AI assistant.
 *
 * Backend: POST /api/chat (api/chat.py). The backend works with Claude
 * (ANTHROPIC_API_KEY) or OpenAI, and falls back to a rule-based offline
 * assistant when no key is configured — so this component always gets a reply.
 *
 * Shared by the full-page assistant (pages/AIAssistant.tsx) and the floating
 * support widget (components/ai/AISupportWidget.tsx); `sessionId` keeps their
 * histories isolated.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { aiAssistantApi } from '../../hooks/useApi';
import { useVoice } from '../../hooks/useVoice';

interface ChatTurn {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  ts: number;
}

interface AIChatProps {
  sessionId: string;
  /** First assistant message shown before any user input. */
  intro?: string;
  placeholder?: string;
  /** Quick-start prompts shown when the conversation is empty. */
  suggestions?: string[];
  /** Compact mode for the floating widget (smaller fonts/padding). */
  compact?: boolean;
}

/** Render a small subset of markdown (**bold**, `code`, and line breaks)
 *  without pulling in a markdown dependency. */
function renderText(text: string): React.ReactNode {
  return text.split('\n').map((line, i) => {
    const parts: React.ReactNode[] = [];
    const regex = /(\*\*[^*]+\*\*|`[^`]+`)/g;
    let last = 0;
    let m: RegExpExecArray | null;
    let k = 0;
    while ((m = regex.exec(line)) !== null) {
      if (m.index > last) parts.push(line.slice(last, m.index));
      const tok = m[0];
      if (tok.startsWith('**')) parts.push(<strong key={`b${i}-${k}`}>{tok.slice(2, -2)}</strong>);
      else parts.push(<code key={`c${i}-${k}`} style={{ background: 'rgba(148,163,184,0.18)', borderRadius: 4, padding: '0 4px', fontSize: '0.92em' }}>{tok.slice(1, -1)}</code>);
      last = m.index + tok.length;
      k++;
    }
    if (last < line.length) parts.push(line.slice(last));
    return (
      <React.Fragment key={i}>
        {parts.length ? parts : line}
        {i < text.split('\n').length - 1 && <br />}
      </React.Fragment>
    );
  });
}

const AIChat: React.FC<AIChatProps> = ({ sessionId, intro, placeholder, suggestions, compact }) => {
  const [turns, setTurns]     = useState<ChatTurn[]>([]);
  const [input, setInput]     = useState('');
  const [sending, setSending] = useState(false);
  const [speakReplies, setSpeakReplies] = useState(false);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const inputRef  = useRef<HTMLTextAreaElement | null>(null);
  const mountedRef = useRef(true);
  const spokenRef  = useRef<string | null>(null);

  // Browser-native voice (talk + listen). No key, no money path; safe no-op
  // when the browser lacks the Web Speech API. Available to all users.
  const voice = useVoice();

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [turns, sending]);

  // Mirror the live dictation transcript into the input box while listening,
  // so the user sees what was heard before it is sent.
  useEffect(() => {
    if (voice.listening && voice.transcript) setInput(voice.transcript);
  }, [voice.listening, voice.transcript]);

  // Read the latest assistant reply aloud when "speak replies" is enabled.
  useEffect(() => {
    if (!speakReplies) return;
    const last = turns[turns.length - 1];
    if (last && last.role === 'assistant' && last.id !== spokenRef.current) {
      spokenRef.current = last.id;
      voice.speak(last.content);
    }
  }, [turns, speakReplies, voice]);

  // Stop any in-progress read-out the moment the toggle is switched off.
  useEffect(() => {
    if (!speakReplies) voice.cancelSpeak();
  }, [speakReplies, voice]);

  const send = useCallback(async (text: string) => {
    const content = text.trim();
    if (!content || sending) return;
    setInput('');
    const userTurn: ChatTurn = { id: `u-${Date.now()}`, role: 'user', content, ts: Date.now() };
    setTurns(prev => [...prev, userTurn]);
    setSending(true);
    try {
      const res = await aiAssistantApi.send(content, sessionId);
      const reply = (res.data as { response?: string }).response ?? 'No response.';
      if (!mountedRef.current) return;
      setTurns(prev => [...prev, { id: `a-${Date.now()}`, role: 'assistant', content: reply, ts: Date.now() }]);
    } catch {
      if (!mountedRef.current) return;
      setTurns(prev => [...prev, {
        id: `a-${Date.now()}`,
        role: 'assistant',
        content: '⚠️ I couldn\'t reach the assistant just now. Please check your connection and try again.',
        ts: Date.now(),
      }]);
    } finally {
      if (mountedRef.current) { setSending(false); inputRef.current?.focus(); }
    }
  }, [sending, sessionId]);

  const clear = useCallback(async () => {
    setTurns([]);
    try { await aiAssistantApi.clearHistory(sessionId); } catch { /* best-effort */ }
    inputRef.current?.focus();
  }, [sessionId]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void send(input); }
  };

  // Toggle hands-free dictation: start listening, and when the user stops
  // speaking auto-send the final transcript.
  const toggleMic = useCallback(() => {
    if (voice.listening) { voice.stopListening(); return; }
    voice.startListening((finalText) => {
      const t = finalText.trim();
      if (t) void send(t);
    });
  }, [voice, send]);

  const fs = compact ? 13 : 14;
  const pad = compact ? '8px 12px' : '10px 14px';
  const empty = turns.length === 0;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      {/* Messages */}
      <div style={{ flex: 1, overflowY: 'auto', padding: compact ? '12px 14px' : '16px 20px', display: 'flex', flexDirection: 'column', gap: 12 }}>
        {empty && (
          <div style={{ color: '#94a3b8', fontSize: fs, lineHeight: 1.6 }}>
            <div style={{ marginBottom: suggestions?.length ? 14 : 0 }}>{renderText(intro ?? 'Hi — how can I help?')}</div>
            {suggestions?.map(s => (
              <button
                key={s}
                onClick={() => void send(s)}
                style={{
                  display: 'block', width: '100%', textAlign: 'left', marginBottom: 8,
                  background: 'rgba(59,130,246,0.10)', border: '1px solid rgba(59,130,246,0.30)',
                  borderRadius: 8, color: '#93c5fd', fontSize: fs - 1, cursor: 'pointer', padding: '8px 12px',
                }}
              >
                {s}
              </button>
            ))}
          </div>
        )}
        {turns.map(t => {
          const own = t.role === 'user';
          return (
            <div key={t.id} style={{ display: 'flex', flexDirection: own ? 'row-reverse' : 'row', gap: 8, alignItems: 'flex-end' }}>
              <div style={{ width: 28, height: 28, borderRadius: '50%', flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14, background: own ? '#1e3a5f' : '#16233a' }}>
                {own ? '🧑' : '🤖'}
              </div>
              <div style={{
                maxWidth: '78%',
                background: own ? '#1e3a5f' : '#16233a',
                border: `1px solid ${own ? '#1e4a7f' : '#243b5a'}`,
                borderRadius: own ? '12px 12px 2px 12px' : '12px 12px 12px 2px',
                padding: pad, fontSize: fs, color: '#e2e8f0', lineHeight: 1.55, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
              }}>
                {renderText(t.content)}
              </div>
            </div>
          );
        })}
        {sending && (
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', color: '#64748b', fontSize: fs }}>
            <div style={{ width: 28, height: 28, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14, background: '#16233a' }}>🤖</div>
            <span>Thinking…</span>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div style={{ borderTop: '1px solid #1e293b', padding: compact ? '10px 12px' : '12px 20px' }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
          <textarea
            ref={inputRef}
            value={input}
            rows={1}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={placeholder ?? 'Ask the AI assistant…'}
            style={{
              flex: 1, resize: 'none', maxHeight: 120, background: '#1e293b', border: '1px solid #334155',
              borderRadius: 10, color: '#f1f5f9', fontSize: fs, outline: 'none', padding: pad, fontFamily: 'inherit',
            }}
          />
          {voice.sttSupported && (
            <button
              type="button"
              onClick={toggleMic}
              title={voice.listening ? 'Stop listening' : 'Speak your message'}
              aria-label={voice.listening ? 'Stop listening' : 'Speak your message'}
              aria-pressed={voice.listening}
              style={{
                background: voice.listening ? '#dc2626' : '#1e293b',
                border: `1px solid ${voice.listening ? '#ef4444' : '#334155'}`, borderRadius: 10,
                color: voice.listening ? '#fff' : '#94a3b8', cursor: 'pointer',
                fontSize: fs + 2, padding: compact ? '8px 11px' : '10px 13px',
              }}
            >
              {voice.listening ? '⏹' : '🎤'}
            </button>
          )}
          {voice.ttsSupported && (
            <button
              type="button"
              onClick={() => setSpeakReplies(v => !v)}
              title={speakReplies ? 'Mute spoken replies' : 'Read replies aloud'}
              aria-label={speakReplies ? 'Mute spoken replies' : 'Read replies aloud'}
              aria-pressed={speakReplies}
              style={{
                background: speakReplies ? '#1e3a5f' : '#1e293b',
                border: `1px solid ${speakReplies ? '#1d4ed8' : '#334155'}`, borderRadius: 10,
                color: speakReplies ? '#60a5fa' : '#94a3b8', cursor: 'pointer',
                fontSize: fs + 2, padding: compact ? '8px 11px' : '10px 13px',
              }}
            >
              {speakReplies ? '🔊' : '🔈'}
            </button>
          )}
          <button
            onClick={() => void send(input)}
            disabled={!input.trim() || sending}
            style={{
              background: input.trim() && !sending ? '#3b82f6' : '#1e293b', border: 'none', borderRadius: 10,
              color: input.trim() && !sending ? '#fff' : '#475569', cursor: input.trim() && !sending ? 'pointer' : 'not-allowed',
              fontSize: fs, fontWeight: 700, padding: compact ? '8px 14px' : '10px 18px',
            }}
          >
            {sending ? '…' : 'Send'}
          </button>
        </div>
        {!empty && (
          <button onClick={() => void clear()} style={{ marginTop: 6, background: 'none', border: 'none', color: '#475569', fontSize: 11, cursor: 'pointer', padding: 0 }}>
            Clear conversation
          </button>
        )}
      </div>
    </div>
  );
};

export default AIChat;
