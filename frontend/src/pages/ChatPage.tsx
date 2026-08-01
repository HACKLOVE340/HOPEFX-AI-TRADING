/**
 * Chat — real-time community and support chat.
 *
 * Wires to:
 *   GET  /api/chat/rooms           — list chat rooms
 *   GET  /api/chat/rooms/:id/messages — message history
 *   POST /api/chat/rooms/:id/messages — send message
 *   WS   /ws/chat/:room_id          — real-time messages
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { chatApi } from '../hooks/useApi';
import { useStore, selectUser } from '../store';
import { getWsBase } from '../lib/utils';
import { useToast } from '../components/Toast';

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
}

const ROOM_ICONS: Record<string, string> = {
  community: '💬',
  support:   '🎧',
  private:   '🔒',
};

const ChatPage: React.FC = () => {
  const navigate = useNavigate();
  const user = useStore(selectUser);
  const token = useStore(s => s.token);

  const toast = useToast();
  const [rooms, setRooms]           = useState<ChatRoom[]>([]);
  const [activeRoom, setActiveRoom] = useState<ChatRoom | null>(null);
  const [messages, setMessages]     = useState<ChatMessage[]>([]);
  const [input, setInput]           = useState('');
  const [sending, setSending]       = useState(false);
  const [loadingRooms, setLoadingRooms] = useState(true);
  const [loadingMsgs, setLoadingMsgs]   = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const inputRef  = useRef<HTMLInputElement | null>(null);
  const mountedRef = useRef(true);

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
        // Bind rather than index: r.length > 0 does not narrow r[0] (audit #38).
        const firstRoom = r[0];
        if (firstRoom) setActiveRoom(firstRoom);
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

  // WebSocket for real-time messages
  useEffect(() => {
    if (!activeRoom || !token) return;
    wsRef.current?.close();
    let ws: WebSocket | null = null;
    try {
      ws = new WebSocket(`${getWsBase()}/ws/chat/${activeRoom.id}?token=${token}`);
      wsRef.current = ws;
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data as string) as { type?: string; message?: ChatMessage };
          if (msg.type === 'message' && msg.message) {
            setMessages(prev => [...prev, msg.message!]);
          }
        } catch { /* ignore */ }
      };
    } catch { /* WS unavailable */ }
    return () => { ws?.close(); };
  }, [activeRoom, token]);

  const handleSend = async () => {
    if (!input.trim() || !activeRoom || sending) return;
    const content = input.trim();
    setInput('');
    setSending(true);
    // Optimistic update
    const optimistic: ChatMessage = {
      id: `opt-${Date.now()}`,
      room_id: activeRoom.id,
      user_id: user?.id ?? '',
      username: user?.username ?? user?.email ?? 'You',
      content,
      created_at: new Date().toISOString(),
    };
    setMessages(prev => [...prev, optimistic]);
    try {
      await chatApi.sendMessage(activeRoom.id, content);
    } catch {
      // Remove optimistic message, restore the draft, and tell the user.
      setMessages(prev => prev.filter(m => m.id !== optimistic.id));
      setInput(content);
      toast.error('Message failed to send — check your connection and try again.');
    } finally { setSending(false); inputRef.current?.focus(); }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
  };

  const isOwn = (msg: ChatMessage) => msg.user_id === user?.id;

  return (
    <div className="page-content" style={{ flexDirection: 'row', overflow: 'hidden', padding: 0 }}>
      {/* Sidebar — room list */}
      <div style={{ width: 260, borderRight: '1px solid #1e293b', display: 'flex', flexDirection: 'column', flexShrink: 0 }}>
        <div style={{ padding: '16px 16px 12px', borderBottom: '1px solid #1e293b' }}>
          <h2 style={{ fontSize: 16, fontWeight: 700, color: '#f1f5f9', margin: 0 }}>Chat</h2>
        </div>
        <div style={{ overflowY: 'auto', flex: 1 }}>
          {loadingRooms && <div style={{ color: '#64748b', fontSize: 13, padding: 16 }}>Loading rooms…</div>}
          {rooms.map(room => (
            <div
              key={room.id}
              onClick={() => setActiveRoom(room)}
              style={{
                padding: '12px 16px', cursor: 'pointer',
                background: activeRoom?.id === room.id ? '#1e293b' : 'transparent',
                borderLeft: `3px solid ${activeRoom?.id === room.id ? '#3b82f6' : 'transparent'}`,
                transition: 'background 0.15s',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontSize: 16 }}>{ROOM_ICONS[room.type] ?? '💬'}</span>
                  <span style={{ fontSize: 14, fontWeight: 600, color: '#f1f5f9' }}>{room.name}</span>
                </div>
                {room.unread_count > 0 && (
                  <span style={{ background: '#3b82f6', color: '#fff', borderRadius: 10, fontSize: 11, fontWeight: 700, padding: '1px 6px' }}>
                    {room.unread_count}
                  </span>
                )}
              </div>
              {room.last_message && (
                <div style={{ fontSize: 12, color: '#64748b', marginTop: 3, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {room.last_message}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Main chat area */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {/* Room header */}
        {activeRoom && (
          <div style={{ padding: '14px 20px', borderBottom: '1px solid #1e293b', display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 20 }}>{ROOM_ICONS[activeRoom.type] ?? '💬'}</span>
            <div>
              <div style={{ fontSize: 15, fontWeight: 700, color: '#f1f5f9' }}>{activeRoom.name}</div>
              {activeRoom.description && (
                <div style={{ fontSize: 12, color: '#64748b' }}>{activeRoom.description}</div>
              )}
            </div>
            <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
              <button onClick={() => navigate('/trade')}
                style={{ background: 'rgba(59,130,246,0.12)', border: '1px solid rgba(59,130,246,0.35)', borderRadius: 6, color: '#60a5fa', fontSize: 12, fontWeight: 700, cursor: 'pointer', padding: '5px 12px' }}>
                ⚡ Trade
              </button>
              <button onClick={() => navigate('/signals')}
                style={{ background: 'rgba(167,139,250,0.12)', border: '1px solid rgba(167,139,250,0.35)', borderRadius: 6, color: '#a78bfa', fontSize: 12, fontWeight: 700, cursor: 'pointer', padding: '5px 12px' }}>
                📡 Signals
              </button>
            </div>
          </div>
        )}

        {/* Messages */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 12 }}>
          {loadingMsgs && <div style={{ color: '#64748b', fontSize: 13, textAlign: 'center' }}>Loading messages…</div>}
          {!loadingMsgs && messages.length === 0 && (
            <div style={{ color: '#475569', fontSize: 13, textAlign: 'center', marginTop: 40 }}>
              No messages yet. Be the first to say something!
            </div>
          )}
          {messages.map(msg => (
            <div key={msg.id} style={{ display: 'flex', flexDirection: isOwn(msg) ? 'row-reverse' : 'row', gap: 10, alignItems: 'flex-end' }}>
              {/* Avatar */}
              <div style={{ width: 32, height: 32, borderRadius: '50%', background: isOwn(msg) ? '#1e3a5f' : '#1e293b', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 13, fontWeight: 700, color: isOwn(msg) ? '#60a5fa' : '#94a3b8', flexShrink: 0 }}>
                {msg.username.charAt(0).toUpperCase()}
              </div>
              <div style={{ maxWidth: '70%' }}>
                {!isOwn(msg) && (
                  <div style={{ fontSize: 11, color: '#64748b', marginBottom: 3 }}>{msg.username}</div>
                )}
                <div style={{
                  background: isOwn(msg) ? '#1e3a5f' : '#1e293b',
                  border: `1px solid ${isOwn(msg) ? '#1e4a7f' : '#334155'}`,
                  borderRadius: isOwn(msg) ? '12px 12px 2px 12px' : '12px 12px 12px 2px',
                  padding: '8px 12px', fontSize: 14, color: '#f1f5f9', lineHeight: 1.5,
                }}>
                  {msg.content}
                </div>
                <div style={{ fontSize: 10, color: '#475569', marginTop: 3, textAlign: isOwn(msg) ? 'right' : 'left' }}>
                  {new Date(msg.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  {msg.edited && ' (edited)'}
                </div>
              </div>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        {/* Input bar */}
        {activeRoom && (
          <div style={{ padding: '12px 20px', borderTop: '1px solid #1e293b', display: 'flex', gap: 10 }}>
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={`Message #${activeRoom.name}…`}
              style={{ flex: 1, background: '#1e293b', border: '1px solid #334155', borderRadius: 10, color: '#f1f5f9', fontSize: 14, outline: 'none', padding: '10px 14px' }}
            />
            <button
              onClick={handleSend}
              disabled={!input.trim() || sending}
              style={{ background: input.trim() ? '#3b82f6' : '#1e293b', border: 'none', borderRadius: 10, color: input.trim() ? '#fff' : '#475569', cursor: input.trim() ? 'pointer' : 'not-allowed', fontSize: 14, fontWeight: 700, padding: '10px 20px' }}
            >
              {sending ? '…' : 'Send'}
            </button>
          </div>
        )}

        {!activeRoom && !loadingRooms && (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#475569' }}>
            Select a room to start chatting
          </div>
        )}
      </div>
    </div>
  );
};

export default ChatPage;
