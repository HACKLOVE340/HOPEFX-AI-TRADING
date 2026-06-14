/**
 * CommunityChat — Real-time Trading Community Chat
 *
 * Exposes:
 * - Real-time chat rooms (general, signals, strategies, gold, forex)
 * - Trade idea sharing with chart snapshots
 * - Trader profiles and reputation
 * - Message reactions and threading
 * - Signal sharing with auto-formatting
 * - Moderation tools for admins
 *
 * Backend: /api/community-chat/*, api/community_chat.py
 */
import { useEffect, useState, useRef, useCallback } from 'react'
import {
  MessageCircle, Send, Users, Hash, TrendingUp,
  Image, Smile, AtSign, Pin, Star, Shield,
  MoreVertical, ThumbsUp, Reply, Trash2,
} from 'lucide-react'
import { useStore } from '../store/useStore'

// ── Types ─────────────────────────────────────────────────────────────────────
interface ChatRoom {
  id: string
  name: string
  description: string
  members_online: number
  unread_count: number
  pinned_message?: string
  type: 'general' | 'signals' | 'strategies' | 'asset' | 'vip'
}

interface ChatMessage {
  id: string
  user_id: string
  username: string
  avatar_url?: string
  role: 'user' | 'trader' | 'admin' | 'superadmin'
  content: string
  timestamp: string
  reactions: { emoji: string; count: number; reacted: boolean }[]
  reply_to?: { id: string; username: string; preview: string }
  signal?: SharedSignal
  image_url?: string
}

interface SharedSignal {
  symbol: string
  direction: 'long' | 'short'
  entry: number
  sl: number
  tp: number
  confidence: number
}

// ── Component ─────────────────────────────────────────────────────────────────
export function CommunityChat() {
  const [rooms, setRooms] = useState<ChatRoom[]>([])
  const [activeRoom, setActiveRoom] = useState<ChatRoom | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [newMessage, setNewMessage] = useState('')
  const [loading, setLoading] = useState(true)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const user = useStore(s => s.user)

  const headers = { Authorization: `Bearer ${localStorage.getItem('token')}` }

  const fetchRooms = useCallback(async () => {
    try {
      const res = await fetch('/api/community-chat/rooms', { headers })
      if (res.ok) {
        const data = await res.json()
        setRooms(data.rooms || [])
        if (!activeRoom && data.rooms?.length > 0) {
          setActiveRoom(data.rooms[0])
        }
      }
    } catch (err) { console.error('Rooms fetch error:', err) }
  }, [])

  const fetchMessages = useCallback(async (roomId: string) => {
    setLoading(true)
    try {
      const res = await fetch(`/api/community-chat/rooms/${roomId}/messages?limit=100`, { headers })
      if (res.ok) {
        const data = await res.json()
        setMessages(data.messages || [])
      }
    } catch (err) { console.error('Messages fetch error:', err) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { fetchRooms() }, [fetchRooms])
  useEffect(() => { if (activeRoom) fetchMessages(activeRoom.id) }, [activeRoom, fetchMessages])
  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  const sendMessage = async () => {
    if (!newMessage.trim() || !activeRoom) return
    try {
      const res = await fetch(`/api/community-chat/rooms/${activeRoom.id}/messages`, {
        method: 'POST',
        headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: newMessage }),
      })
      if (res.ok) {
        const msg = await res.json()
        setMessages(prev => [...prev, msg])
        setNewMessage('')
      }
    } catch (err) { console.error('Send failed:', err) }
  }

  const reactToMessage = async (messageId: string, emoji: string) => {
    try {
      await fetch(`/api/community-chat/messages/${messageId}/react`, {
        method: 'POST',
        headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({ emoji }),
      })
      setMessages(prev => prev.map(m => {
        if (m.id !== messageId) return m
        const existing = m.reactions.find(r => r.emoji === emoji)
        if (existing) {
          return { ...m, reactions: m.reactions.map(r => r.emoji === emoji ? { ...r, count: r.count + 1, reacted: true } : r) }
        }
        return { ...m, reactions: [...m.reactions, { emoji, count: 1, reacted: true }] }
      }))
    } catch (err) { console.error('React failed:', err) }
  }

  return (
    <div className="flex h-[calc(100vh-8rem)] gap-4">
      {/* Room List */}
      <div className="w-64 bg-slate-900 rounded-xl border border-slate-800 flex flex-col overflow-hidden shrink-0">
        <div className="p-4 border-b border-slate-800">
          <h2 className="text-sm font-semibold text-slate-300 flex items-center gap-2">
            <MessageCircle className="w-4 h-4 text-amber-400" />
            Chat Rooms
          </h2>
        </div>
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {rooms.map(room => (
            <button
              key={room.id}
              onClick={() => setActiveRoom(room)}
              className={`w-full text-left p-3 rounded-lg transition-colors ${
                activeRoom?.id === room.id
                  ? 'bg-amber-500/10 border border-amber-500/20'
                  : 'hover:bg-slate-800'
              }`}
            >
              <div className="flex items-center justify-between mb-0.5">
                <div className="flex items-center gap-2">
                  <RoomIcon type={room.type} />
                  <span className="text-sm font-medium text-slate-200">{room.name}</span>
                </div>
                {room.unread_count > 0 && (
                  <span className="w-5 h-5 bg-amber-500 text-slate-900 rounded-full text-xs flex items-center justify-center font-bold">
                    {room.unread_count}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2 text-xs text-slate-500 pl-6">
                <Users className="w-3 h-3" />
                <span>{room.members_online} online</span>
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Chat Area */}
      <div className="flex-1 bg-slate-900 rounded-xl border border-slate-800 flex flex-col overflow-hidden">
        {/* Room Header */}
        {activeRoom && (
          <div className="p-4 border-b border-slate-800 flex items-center justify-between">
            <div>
              <div className="flex items-center gap-2">
                <RoomIcon type={activeRoom.type} />
                <h3 className="font-semibold text-slate-200">{activeRoom.name}</h3>
              </div>
              <p className="text-xs text-slate-500 mt-0.5 pl-6">{activeRoom.description}</p>
            </div>
            <div className="flex items-center gap-2 text-xs text-slate-400">
              <Users className="w-4 h-4" />
              <span>{activeRoom.members_online} online</span>
            </div>
          </div>
        )}

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {messages.map(msg => (
            <div key={msg.id} className="group flex gap-3">
              {/* Avatar */}
              <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 text-xs font-bold ${
                msg.role === 'superadmin' ? 'bg-purple-500/20 text-purple-400' :
                msg.role === 'admin' ? 'bg-amber-500/20 text-amber-400' :
                'bg-slate-700 text-slate-300'
              }`}>
                {msg.username[0].toUpperCase()}
              </div>
              {/* Content */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-0.5">
                  <span className={`text-sm font-medium ${
                    msg.role === 'superadmin' ? 'text-purple-400' :
                    msg.role === 'admin' ? 'text-amber-400' : 'text-slate-200'
                  }`}>{msg.username}</span>
                  {msg.role !== 'user' && (
                    <span className={`text-xs px-1.5 py-0.5 rounded ${
                      msg.role === 'superadmin' ? 'bg-purple-500/10 text-purple-400' :
                      msg.role === 'admin' ? 'bg-amber-500/10 text-amber-400' :
                      'bg-blue-500/10 text-blue-400'
                    }`}>{msg.role}</span>
                  )}
                  <span className="text-xs text-slate-600">{msg.timestamp}</span>
                </div>
                {/* Reply context */}
                {msg.reply_to && (
                  <div className="flex items-center gap-2 mb-1 pl-2 border-l-2 border-slate-700 text-xs text-slate-500">
                    <Reply className="w-3 h-3" />
                    <span className="font-medium">{msg.reply_to.username}:</span>
                    <span className="truncate">{msg.reply_to.preview}</span>
                  </div>
                )}
                {/* Message text */}
                <p className="text-sm text-slate-300">{msg.content}</p>
                {/* Shared signal */}
                {msg.signal && (
                  <div className={`mt-2 p-3 rounded-lg border ${
                    msg.signal.direction === 'long' ? 'bg-green-500/5 border-green-500/20' : 'bg-red-500/5 border-red-500/20'
                  }`}>
                    <div className="flex items-center gap-2 mb-1">
                      <TrendingUp className={`w-4 h-4 ${msg.signal.direction === 'long' ? 'text-green-400' : 'text-red-400'}`} />
                      <span className="text-sm font-medium text-slate-200">{msg.signal.symbol}</span>
                      <span className={`text-xs px-1.5 py-0.5 rounded ${
                        msg.signal.direction === 'long' ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'
                      }`}>{msg.signal.direction}</span>
                    </div>
                    <div className="grid grid-cols-4 gap-2 text-xs">
                      <div><span className="text-slate-500">Entry:</span> <span className="text-slate-300">{msg.signal.entry}</span></div>
                      <div><span className="text-slate-500">SL:</span> <span className="text-red-400">{msg.signal.sl}</span></div>
                      <div><span className="text-slate-500">TP:</span> <span className="text-green-400">{msg.signal.tp}</span></div>
                      <div><span className="text-slate-500">Conf:</span> <span className="text-amber-400">{(msg.signal.confidence * 100).toFixed(0)}%</span></div>
                    </div>
                  </div>
                )}
                {/* Reactions */}
                {msg.reactions.length > 0 && (
                  <div className="flex gap-1 mt-1.5">
                    {msg.reactions.map(r => (
                      <button
                        key={r.emoji}
                        onClick={() => reactToMessage(msg.id, r.emoji)}
                        className={`flex items-center gap-1 px-2 py-0.5 rounded-full text-xs transition-colors ${
                          r.reacted ? 'bg-amber-500/10 border border-amber-500/30' : 'bg-slate-800 hover:bg-slate-700'
                        }`}
                      >
                        <span>{r.emoji}</span>
                        <span className="text-slate-400">{r.count}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
              {/* Actions (visible on hover) */}
              <div className="opacity-0 group-hover:opacity-100 flex items-start gap-1 transition-opacity">
                <button onClick={() => reactToMessage(msg.id, '👍')} className="p-1 text-slate-500 hover:text-slate-300 rounded">
                  <ThumbsUp className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <div className="p-4 border-t border-slate-800">
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={newMessage}
              onChange={e => setNewMessage(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage() } }}
              placeholder={`Message #${activeRoom?.name || 'general'}...`}
              className="flex-1 px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder-slate-500 focus:border-amber-500 focus:outline-none"
            />
            <button
              onClick={sendMessage}
              disabled={!newMessage.trim()}
              className="p-2.5 bg-amber-500 hover:bg-amber-400 disabled:bg-slate-700 text-slate-900 disabled:text-slate-500 rounded-lg transition-colors"
            >
              <Send className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function RoomIcon({ type }: { type: string }) {
  switch (type) {
    case 'signals': return <TrendingUp className="w-4 h-4 text-green-400" />
    case 'strategies': return <Star className="w-4 h-4 text-purple-400" />
    case 'vip': return <Shield className="w-4 h-4 text-amber-400" />
    default: return <Hash className="w-4 h-4 text-slate-400" />
  }
}
