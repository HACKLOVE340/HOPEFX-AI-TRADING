/**
 * Chat — real-time community and support chat.
 *
 * Wires to:
 *   GET    /api/chat/rooms                                    — list rooms
 *   GET    /api/chat/rooms/:id/messages                       — history
 *   POST   /api/chat/rooms/:id/messages                       — send
 *   POST   /api/chat/rooms/:id/messages/:msgId/reactions      — add reaction
 *   DELETE /api/chat/rooms/:id/messages/:msgId/reactions/:e   — remove reaction
 *   POST   /api/chat/rooms/:id/read                           — mark read
 *   WS     /ws/chat/:room_id                                  — real-time
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { chatApi } from '../hooks/useApi';
import { useStore, selectUser } from '../store';
import { getWsBase } from '../lib/utils';
import { EmptyState } from '../components/EmptyState';
import { Spinner } from '../components/Spinner';
import { PageHeader } from '../components/PageHeader';

interface Reaction {
  emoji: string;
  count: number;
  reacted: boolean; // current user has reacted
}

interface ChatRoom {
  id: string;
  name: string;
  description: string;
  type: 'community' | 'support' | 'private';
  unread_count: number;
  last_message?: string;
  last_message_at?: string;
}

interface ChatMessage {
  id: string;
  room_id: string;
  user_id: string;
  username: string;
  avatar?: string;
  content: string;
  created_at: string;
  edited?: boolean;
  reactions?: Reaction[];
}

const ROOM_ICONS: Record<string, string> = {
  community: '💬',
  support:   '🎧',
  private:   '🔒',
};

const QUICK_REACTIONS = ['👍', '❤️', '😂', '🚀', '💯', '🔥'];

// ── Typing indicator component ────────────────────────────────────────────────
const TypingIndicator: React.FC<{ typers: string[] }> = ({ typers }) => {
  if (typers.length === 0) return null;
  const label = typers.length === 1
    ? `${typers[0]} is typing…`
    : typers.length === 2
    ? `${typers[0]} and ${typers[1]} are typing…`
    : `${typers[0]} and ${typers.length - 1} others are typing…`;
  return (
    <div style={{ padding: '4px 20px 8px', display: 'flex', alignItems: 'center', gap: 8, minHeight: 24 }}>
      <span style={{ display: 'flex', gap: 3, alignItems: 'center' }}>
        {[0, 1, 2].map(i => (
          <span key={i} style={{
            width: 5, height: 5, borderRadius: '50%', background: '#475569',
            animation: `typingBounce 1.2s ${i * 0.2}s infinite ease-in-out`,
          }} />
        ))}
      </span>
      <span style={{ fontSize: 11, color: '#475569', fontStyle: 'italic' }}>{label}</span>
      <style>{`
        @keyframes typingBounce {
          0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
          30% { transform: translateY(-4px); opacity: 1; }
        }
      `}</style>
    </div>
  );
};

// ── Reaction bar component ────────────────────────────────────────────────────
const ReactionBar: React.FC<{
  reactions: Reaction[];
  onToggle: (emoji: string, reacted: boolean) => void;
}> = ({ reactions, onToggle }) => {
  if (reactions.length === 0) return null;
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 4 }}>
      {reactions.map(r => (
        <button
          key={r.emoji}
          onClick={() => onToggle(r.emoji, r.reacted)}
          style={{
            background: r.reacted ? 'rgba(59,130,246,0.2)' : 'rgba(30,41,59,0.8)',
            border: `1px solid ${r.reacted ? '#3b82f6' : '#334155'}`,
            borderRadius: 12, cursor: 'pointer', fontSize: 11,
            padding: '2px 7px', display: 'flex', alignItems: 'center', gap: 4,
            color: r.reacted ? '#60a5fa' : '#94a3b8',
            transition: 'all 0.15s',
          }}
        >
          <span>{r.emoji}</span>
          <span style={{ fontWeight: 600 }}>{r.count}</span>
        </button>
      ))}
    </div>
  );
};

const ChatPage: React.FC = () => {
  const user = useStore(selectUser);
  const token = useStore(s => s.token);

  const [rooms, setRooms]           = useState<ChatRoom[]>([]);
  const [activeRoom, setActiveRoom] = useState<ChatRoom | null>(null);
  const [messages, setMessages]     = useState<ChatMessage[]>([]);
  const [input, setInput]           = useState('');
  const [sending, setSending]       = useState(false);
  const [loadingRooms, setLoadingRooms] = useState(true);
  const [loadingMsgs, setLoadingMsgs]   = useState(false);
  const [typers, setTypers]         = useState<string[]>([]);
  const [hoveredMsg, setHoveredMsg] = useState<string | null>(null);
  const [showReactionPicker, setShowReactionPicker] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const inputRef  = useRef<HTMLInputElement | null>(null);
  const mountedRef = useRef(true);
  const typingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isTypingRef = useRef(false);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  // Load rooms
  useEffect(() => {
    let mounted = true;
    (async () => {
      setLoadingRooms(true);
      try {
        const res = await chatApi.rooms();
        if (!mounted) return;
        const d = res.data as ChatRoom[] | { rooms?: ChatRoom[] };
        const r = Array.isArray(d) ? d : (d.rooms ?? []);
        setRooms(r);
        if (r.length > 0) setActiveRoom(r[0]);
      } catch { if (mounted) setRooms([]); }
      finally { if (mounted) setLoadingRooms(false); }
    })();
    return () => { mounted = false; };
  }, []);

  // Load messages when room changes
  const loadMessages = useCallback(async (roomId: string) => {
    setLoadingMsgs(true);
    try {
      const res = await chatApi.messages(roomId, { limit: 50 });
      if (!mountedRef.current) return;
      const d = res.data as ChatMessage[] | { messages?: ChatMessage[] };
      setMessages(Array.isArray(d) ? d : (d.messages ?? []));
    } catch { if (mountedRef.current) setMessages([]); }
    finally { if (mountedRef.current) setLoadingMsgs(false); }
  }, []);

  useEffect(() => {
    if (!activeRoom) return;
    loadMessages(activeRoom.id);
  }, [activeRoom, loadMessages]);

  // Scroll to bottom on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // WebSocket for real-time messages, typing, reactions
  useEffect(() => {
    if (!activeRoom || !token) return;
    wsRef.current?.close();
    let ws: WebSocket | null = null;
    try {
      ws = new WebSocket(`${getWsBase()}/ws/chat/${activeRoom.id}?token=${token}`);
      wsRef.current = ws;
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data as string) as {
            type?: string;
            message?: ChatMessage;
            username?: string;
            msg_id?: string;
            emoji?: string;
            count?: number;
            reacted?: boolean;
          };
          if (msg.type === 'message' && msg.message) {
            setMessages(prev => [...prev, msg.message!]);
            setTypers(prev => prev.filter(u => u !== msg.message!.username));
          } else if (msg.type === 'typing_start' && msg.username && msg.username !== user?.username) {
            setTypers(prev => prev.includes(msg.username!) ? prev : [...prev, msg.username!]);
          } else if (msg.type === 'typing_stop' && msg.username) {
            setTypers(prev => prev.filter(u => u !== msg.username));
          } else if (msg.type === 'reaction' && msg.msg_id && msg.emoji) {
            setMessages(prev => prev.map(m => {
              if (m.id !== msg.msg_id) return m;
              const existing = (m.reactions ?? []).find(r => r.emoji === msg.emoji);
              const reactions: Reaction[] = existing
                ? (m.reactions ?? []).map(r => r.emoji === msg.emoji
                    ? { ...r, count: msg.count ?? r.count, reacted: msg.reacted ?? r.reacted }
                    : r)
                : [...(m.reactions ?? []), { emoji: msg.emoji!, count: msg.count ?? 1, reacted: msg.reacted ?? false }];
              return { ...m, reactions };
            }));
          }
        } catch { /* ignore */ }
      };
    } catch { /* WS unavailable */ }
    return () => { ws?.close(); };
  }, [activeRoom, token, user?.username]);

  // Mark room as read when switching
  useEffect(() => {
    if (!activeRoom) return;
    chatApi.markRead(activeRoom.id).catch(() => {/* non-fatal */});
    setRooms(prev => prev.map(r => r.id === activeRoom.id ? { ...r, unread_count: 0 } : r));
  }, [activeRoom?.id]);

  // Send typing indicator via WS
  const sendTyping = useCallback((typing: boolean) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    try { ws.send(JSON.stringify({ type: typing ? 'typing_start' : 'typing_stop' })); } catch { /* ignore */ }
  }, []);

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setInput(e.target.value);
    if (!isTypingRef.current) {
      isTypingRef.current = true;
      sendTyping(true);
    }
    if (typingTimerRef.current) clearTimeout(typingTimerRef.current);
    typingTimerRef.current = setTimeout(() => {
      isTypingRef.current = false;
      sendTyping(false);
    }, 2000);
  };

  const handleToggleReaction = useCallback(async (msgId: string, emoji: string, reacted: boolean) => {
    if (!activeRoom) return;
    // Optimistic update
    setMessages(prev => prev.map(m => {
      if (m.id !== msgId) return m;
      const reactions = (m.reactions ?? []).map(r =>
        r.emoji === emoji ? { ...r, count: reacted ? r.count - 1 : r.count + 1, reacted: !reacted } : r
      ).filter(r => r.count > 0);
      if (!reacted && !(m.reactions ?? []).find(r => r.emoji === emoji)) {
        reactions.push({ emoji, count: 1, reacted: true });
      }
      return { ...m, reactions };
    }));
    try {
      if (reacted) {
        await chatApi.removeReaction(activeRoom.id, msgId, emoji);
      } else {
        await chatApi.addReaction(activeRoom.id, msgId, emoji);
      }
    } catch { /* revert on error — WS will sync */ }
  }, [activeRoom]);

  const handleSend = async () => {
    if (!input.trim() || !activeRoom || sending) return;
    const content = input.trim();
    setInput('');
    setSending(true);
    if (typingTimerRef.current) clearTimeout(typingTimerRef.current);
    isTypingRef.current = false;
    sendTyping(false);
    // Optimistic update
    const optimistic: ChatMessage = {
      id: `opt-${Date.now()}`,
      room_id: activeRoom.id,
      user_id: user?.id ?? '',
      username: user?.username ?? user?.email ?? 'You',
      content,
      created_at: new Date().toISOString(),
      reactions: [],
    };
    setMessages(prev => [...prev, optimistic]);
    try {
      await chatApi.sendMessage(activeRoom.id, content);
    } catch {
      setMessages(prev => prev.filter(m => m.id !== optimistic.id));
      setInput(content);
    } finally { setSending(false); inputRef.current?.focus(); }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void handleSend(); }
  };

  const isOwn = (msg: ChatMessage) => msg.user_id === user?.id;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 64px)', background: '#0a0f1a', overflow: 'hidden' }}>
      {/* Page header strip */}
      <div style={{ padding: '10px 20px 0', borderBottom: '1px solid #1e293b', background: '#0d1421', flexShrink: 0 }}>
        <PageHeader
          title="💬 Chat"
          subtitle="Community rooms, support, and team messaging"
          breadcrumbs={[
            { label: 'Dashboard', href: '/dashboard' },
            { label: 'Community', href: '/social' },
            { label: 'Chat' },
          ]}
          actions={
            <div style={{ display: 'flex', gap: 6 }}>
              <Link to="/teams" style={{ fontSize: 11, color: '#64748b', textDecoration: 'none', padding: '4px 10px', border: '1px solid #334155', borderRadius: 6 }}>👥 Teams</Link>
              <Link to="/leaderboard" style={{ fontSize: 11, color: '#64748b', textDecoration: 'none', padding: '4px 10px', border: '1px solid #334155', borderRadius: 6 }}>🏆 Leaderboard</Link>
              <Link to="/signals" style={{ fontSize: 11, color: '#64748b', textDecoration: 'none', padding: '4px 10px', border: '1px solid #334155', borderRadius: 6 }}>📡 Signals</Link>
            </div>
          }
          style={{ marginBottom: 0, paddingBottom: 10 }}
        />
      </div>

      {/* Main layout */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
      {/* Sidebar — room list */}
      <div style={{ width: 272, borderRight: '1px solid #1e293b', display: 'flex', flexDirection: 'column', flexShrink: 0 }}>
        {/* Sidebar header */}
        <div style={{ padding: '10px 16px 8px', borderBottom: '1px solid #1e293b' }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Rooms</div>
        </div>

        {/* Room list */}
        <div style={{ overflowY: 'auto', flex: 1 }}>
          {loadingRooms && (
            <div style={{ display: 'flex', justifyContent: 'center', padding: 24 }}>
              <Spinner size="sm" />
            </div>
          )}
          {!loadingRooms && rooms.length === 0 && (
            <div style={{ padding: '24px 16px', textAlign: 'center', color: '#475569', fontSize: 13 }}>
              No chat rooms available
            </div>
          )}
          {rooms.map(room => (
            <div
              key={room.id}
              onClick={() => setActiveRoom(room)}
              style={{
                padding: '11px 16px', cursor: 'pointer',
                background: activeRoom?.id === room.id ? '#1e293b' : 'transparent',
                borderLeft: `3px solid ${activeRoom?.id === room.id ? '#3b82f6' : 'transparent'}`,
                transition: 'background 0.15s',
              }}
              onMouseEnter={e => { if (activeRoom?.id !== room.id) e.currentTarget.style.background = 'rgba(30,41,59,0.5)'; }}
              onMouseLeave={e => { if (activeRoom?.id !== room.id) e.currentTarget.style.background = 'transparent'; }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontSize: 15 }}>{ROOM_ICONS[room.type] ?? '💬'}</span>
                  <span style={{ fontSize: 13, fontWeight: 600, color: '#f1f5f9' }}>{room.name}</span>
                </div>
                {room.unread_count > 0 && (
                  <span style={{ background: '#3b82f6', color: '#fff', borderRadius: 10, fontSize: 10, fontWeight: 700, padding: '1px 6px', minWidth: 18, textAlign: 'center' }}>
                    {room.unread_count}
                  </span>
                )}
              </div>
              {room.last_message && (
                <div style={{ fontSize: 11, color: '#64748b', marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', paddingLeft: 23 }}>
                  {room.last_message}
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Sidebar footer cross-links */}
        <div style={{ padding: '12px 16px', borderTop: '1px solid #1e293b', display: 'flex', flexDirection: 'column', gap: 4 }}>
          {[
            { to: '/trade',       label: '⚡ Trade' },
            { to: '/social',      label: '📰 Social Feed' },
            { to: '/notifications', label: '🔔 Notifications' },
          ].map(({ to, label }) => (
            <Link key={to} to={to} style={{ fontSize: 12, color: '#64748b', textDecoration: 'none', padding: '5px 8px', borderRadius: 6, transition: 'background 0.15s' }}
              onMouseEnter={e => { e.currentTarget.style.background = '#1e293b'; e.currentTarget.style.color = '#94a3b8'; }}
              onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = '#64748b'; }}>
              {label}
            </Link>
          ))}
        </div>
      </div>

      {/* Main chat area */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {/* Room header */}
        {activeRoom && (
          <div style={{ padding: '12px 20px', borderBottom: '1px solid #1e293b', display: 'flex', alignItems: 'center', gap: 10, background: '#0d1421' }}>
            <span style={{ fontSize: 18 }}>{ROOM_ICONS[activeRoom.type] ?? '💬'}</span>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: '#f1f5f9' }}>{activeRoom.name}</div>
              {activeRoom.description && (
                <div style={{ fontSize: 11, color: '#64748b' }}>{activeRoom.description}</div>
              )}
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={() => navigate('/trade')}
                style={{ background: 'rgba(59,130,246,0.12)', border: '1px solid rgba(59,130,246,0.3)', borderRadius: 6, color: '#60a5fa', fontSize: 11, fontWeight: 700, cursor: 'pointer', padding: '5px 10px' }}>
                ⚡ Trade
              </button>
              <button onClick={() => navigate('/signals')}
                style={{ background: 'rgba(167,139,250,0.12)', border: '1px solid rgba(167,139,250,0.3)', borderRadius: 6, color: '#a78bfa', fontSize: 11, fontWeight: 700, cursor: 'pointer', padding: '5px 10px' }}>
                📡 Signals
              </button>
              <button onClick={() => navigate('/teams')}
                style={{ background: 'rgba(6,182,212,0.12)', border: '1px solid rgba(6,182,212,0.3)', borderRadius: 6, color: '#06b6d4', fontSize: 11, fontWeight: 700, cursor: 'pointer', padding: '5px 10px' }}>
                👥 Teams
              </button>
            </div>
          </div>
        )}

        {/* Messages */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 10 }}>
          {loadingMsgs && (
            <div style={{ display: 'flex', justifyContent: 'center', padding: 32 }}>
              <Spinner size="md" />
            </div>
          )}
          {!loadingMsgs && messages.length === 0 && (
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', marginTop: 60 }}>
              <EmptyState
                icon="💬"
                title="No messages yet"
                description="Be the first to say something in this room!"
              />
            </div>
          )}
          {messages.map(msg => (
            <div
              key={msg.id}
              style={{ display: 'flex', flexDirection: isOwn(msg) ? 'row-reverse' : 'row', gap: 8, alignItems: 'flex-end', position: 'relative' }}
              onMouseEnter={() => setHoveredMsg(msg.id)}
              onMouseLeave={() => { setHoveredMsg(null); setShowReactionPicker(null); }}
            >
              {/* Avatar */}
              <div style={{ width: 30, height: 30, borderRadius: '50%', background: isOwn(msg) ? '#1e3a5f' : '#1e293b', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, fontWeight: 700, color: isOwn(msg) ? '#60a5fa' : '#94a3b8', flexShrink: 0, border: `1px solid ${isOwn(msg) ? '#1e4a7f' : '#334155'}` }}>
                {msg.username.charAt(0).toUpperCase()}
              </div>
              <div style={{ maxWidth: '68%' }}>
                {!isOwn(msg) && (
                  <div style={{ fontSize: 11, color: '#64748b', marginBottom: 3, fontWeight: 600 }}>{msg.username}</div>
                )}
                <div style={{ position: 'relative' }}>
                  <div style={{
                    background: isOwn(msg) ? '#1e3a5f' : '#1e293b',
                    border: `1px solid ${isOwn(msg) ? '#1e4a7f' : '#334155'}`,
                    borderRadius: isOwn(msg) ? '12px 12px 2px 12px' : '12px 12px 12px 2px',
                    padding: '8px 12px', fontSize: 13, color: '#f1f5f9', lineHeight: 1.55,
                  }}>
                    {msg.content}
                  </div>
                  {/* Reaction picker trigger */}
                  {hoveredMsg === msg.id && (
                    <div style={{
                      position: 'absolute', top: -28,
                      [isOwn(msg) ? 'left' : 'right']: 0,
                      display: 'flex', gap: 2, background: '#1e293b',
                      border: '1px solid #334155', borderRadius: 20, padding: '3px 6px',
                      zIndex: 10,
                    }}>
                      {QUICK_REACTIONS.map(emoji => (
                        <button
                          key={emoji}
                          onClick={() => {
                            const existing = (msg.reactions ?? []).find(r => r.emoji === emoji);
                            void handleToggleReaction(msg.id, emoji, existing?.reacted ?? false);
                          }}
                          style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 14, padding: '0 2px', lineHeight: 1 }}
                          title={`React with ${emoji}`}
                        >
                          {emoji}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                {/* Reaction bar */}
                {(msg.reactions ?? []).length > 0 && (
                  <ReactionBar
                    reactions={msg.reactions ?? []}
                    onToggle={(emoji, reacted) => void handleToggleReaction(msg.id, emoji, reacted)}
                  />
                )}
                <div style={{ fontSize: 10, color: '#475569', marginTop: 2, textAlign: isOwn(msg) ? 'right' : 'left' }}>
                  {new Date(msg.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  {msg.edited && ' · edited'}
                </div>
              </div>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        {/* Typing indicator */}
        <TypingIndicator typers={typers} />

        {/* Input bar */}
        {activeRoom && (
          <div style={{ padding: '8px 20px 12px', borderTop: '1px solid #1e293b', display: 'flex', gap: 10, background: '#0d1421' }}>
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={handleInputChange}
              onKeyDown={handleKeyDown}
              placeholder={`Message #${activeRoom.name}…`}
              style={{ flex: 1, background: '#1e293b', border: '1px solid #334155', borderRadius: 10, color: '#f1f5f9', fontSize: 14, outline: 'none', padding: '10px 14px', transition: 'border-color 0.15s' }}
              onFocus={e => (e.currentTarget.style.borderColor = '#3b82f6')}
              onBlur={e => (e.currentTarget.style.borderColor = '#334155')}
            />
            <button
              onClick={() => void handleSend()}
              disabled={!input.trim() || sending}
              style={{ background: input.trim() ? '#3b82f6' : '#1e293b', border: 'none', borderRadius: 10, color: input.trim() ? '#fff' : '#475569', cursor: input.trim() ? 'pointer' : 'not-allowed', fontSize: 14, fontWeight: 700, padding: '10px 20px', transition: 'background 0.15s' }}
            >
              {sending ? '…' : 'Send'}
            </button>
          </div>
        )}

        {!activeRoom && !loadingRooms && (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <EmptyState
              icon="💬"
              title="Select a room"
              description="Choose a chat room from the sidebar to start messaging."
            />
          </div>
        )}
      </div>
      </div>{/* end main layout */}
    </div>
  );
};

export default ChatPage;
