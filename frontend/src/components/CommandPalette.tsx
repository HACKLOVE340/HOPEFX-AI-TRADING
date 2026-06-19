/**
 * CommandPalette — global Cmd+K / Ctrl+K fuzzy search across all pages and actions.
 *
 * Usage:
 *   Mount <CommandPalette /> once in App.tsx (inside Router).
 *   The palette opens on Cmd+K / Ctrl+K from anywhere.
 *
 *   To register dynamic actions from a page:
 *     import { useCommandActions } from '../components/CommandPalette';
 *     const { register, unregister } = useCommandActions();
 *     useEffect(() => {
 *       register({ id: 'open-trade', label: 'Open Trade', icon: '⚡', action: () => navigate('/trade') });
 *       return () => unregister('open-trade');
 *     }, []);
 */

import React, {
  createContext, useCallback, useContext, useEffect,
  useRef, useState,
} from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useStore } from '../store';
import { NAV_ITEMS } from './sidebar/navConfig';

// ── Types ─────────────────────────────────────────────────────────────────────

export interface CommandItem {
  id:       string;
  label:    string;
  /** Short description shown below label */
  desc?:    string;
  icon?:    string;
  /** Keyboard shortcut hint (display only) */
  shortcut?: string;
  /** Category for grouping */
  category?: string;
  action:   () => void;
}

interface CommandContextValue {
  register:   (item: CommandItem) => void;
  unregister: (id: string) => void;
  open:       () => void;
  close:      () => void;
}

// ── Context ───────────────────────────────────────────────────────────────────

const CommandContext = createContext<CommandContextValue | null>(null);

export function useCommandActions() {
  const ctx = useContext(CommandContext);
  if (!ctx) throw new Error('useCommandActions must be used inside <CommandPalette>');
  return { register: ctx.register, unregister: ctx.unregister };
}

export function useCommandPalette() {
  const ctx = useContext(CommandContext);
  if (!ctx) throw new Error('useCommandPalette must be used inside <CommandPalette>');
  return { open: ctx.open, close: ctx.close };
}

// ── Static navigation commands ────────────────────────────────────────────────

function buildStaticCommands(navigate: ReturnType<typeof useNavigate>): CommandItem[] {
  const go = (path: string) => () => navigate(path);
  return [
    // Trading
    { id: 'nav-trade',        label: 'Trade',                  icon: '⚡', category: 'Trading',    action: go('/trade') },
    { id: 'nav-dashboard',    label: 'Dashboard',              icon: '📊', category: 'Trading',    action: go('/home') },
    { id: 'nav-portfolio',    label: 'Portfolio',              icon: '💼', category: 'Trading',    action: go('/portfolio') },
    { id: 'nav-watchlist',    label: 'Watchlist',              icon: '👁', category: 'Trading',    action: go('/watchlist') },
    { id: 'nav-journal',      label: 'Trade Journal',          icon: '📓', category: 'Trading',    action: go('/journal') },
    { id: 'nav-pnl',          label: 'P&L Dashboard',          icon: '💰', category: 'Trading',    action: go('/pnl') },
    { id: 'nav-performance',  label: 'Performance',            icon: '📈', category: 'Trading',    action: go('/performance') },
    { id: 'nav-risk-calc',    label: 'Risk Calculator',        icon: '🛡', category: 'Trading',    action: go('/risk-calculator') },
    { id: 'nav-replay',       label: 'Market Replay',          icon: '⏪', category: 'Trading',    action: go('/replay') },
    { id: 'nav-alerts',       label: 'Price Alerts',           icon: '🔔', category: 'Trading',    action: go('/alerts') },
    { id: 'nav-calendar',     label: 'Economic Calendar',      icon: '📅', category: 'Trading',    action: go('/calendar') },
    // AI & Analytics
    { id: 'nav-terminal',     label: 'Trading Terminal',       icon: '🖥️', category: 'Trading',    action: go('/terminal') },
    { id: 'nav-intelligence', label: 'AI Intelligence',        icon: '🧠', category: 'AI',         action: go('/intelligence') },
    { id: 'nav-ai-strategy',  label: 'AI Strategy Generator',  icon: '🤖', category: 'AI',         action: go('/ai-strategy') },
    { id: 'nav-ai-chart',     label: 'AI Chart Dashboard',     icon: '🧠', category: 'AI',         action: go('/ai-chart') },
    { id: 'nav-correlation',  label: 'Correlation Dashboard',  icon: '🔗', category: 'AI',         action: go('/correlation') },
    { id: 'nav-pattern',      label: 'Pattern Detector',       icon: '🔍', category: 'AI',         action: go('/pattern-detector') },
    { id: 'nav-walk-forward', label: 'Walk-Forward Testing',   icon: '🔬', category: 'AI',         action: go('/walk-forward') },
    { id: 'nav-ab-testing',   label: 'A/B Testing',            icon: '⚗️', category: 'AI',         action: go('/ab-testing') },
    { id: 'nav-tca',          label: 'TCA Dashboard',          icon: '📉', category: 'AI',         action: go('/tca') },
    { id: 'nav-indicators',   label: 'Custom Indicators',      icon: '📐', category: 'AI',         action: go('/indicators') },
    { id: 'nav-research',     label: 'Research Notebook',      icon: '🧪', category: 'AI',         action: go('/research') },
    { id: 'nav-nuclear',      label: 'Nuclear Dashboard',      icon: '☢️', category: 'AI',         action: go('/nuclear') },
    { id: 'nav-geopolitical', label: 'Geopolitical Risk',      icon: '🌍', category: 'AI',         action: go('/geopolitical') },
    // Social
    { id: 'nav-copy-trading', label: 'Copy Trading',           icon: '👥', category: 'Social',     action: go('/copy-trading') },
    { id: 'nav-leaderboard',  label: 'Leaderboard',            icon: '🏆', category: 'Social',     action: go('/leaderboard') },
    { id: 'nav-signals',      label: 'Signal Feed',            icon: '📡', category: 'Social',     action: go('/signals') },
    { id: 'nav-marketplace',  label: 'Marketplace',            icon: '🛒', category: 'Social',     action: go('/marketplace') },
    { id: 'nav-affiliate',    label: 'Affiliate',              icon: '🤝', category: 'Social',     action: go('/affiliate') },
    { id: 'nav-teams',        label: 'Teams',                  icon: '🫂', category: 'Social',     action: go('/teams') },
    { id: 'nav-chat',         label: 'Chat',                   icon: '💬', category: 'Social',     action: go('/chat') },
    // Account
    { id: 'nav-wallet',       label: 'Wallet',                 icon: '💳', category: 'Account',    action: go('/wallet') },
    { id: 'nav-profile',      label: 'Profile',                icon: '👤', category: 'Account',    action: go('/profile') },
    { id: 'nav-settings',     label: 'Settings',               icon: '⚙️', category: 'Account',    action: go('/settings') },
    { id: 'nav-kyc',          label: 'KYC Verification',       icon: '🪪', category: 'Account',    action: go('/kyc') },
    { id: 'nav-mobile',       label: 'Mobile App',             icon: '📱', category: 'Account',    action: go('/mobile') },
    { id: 'nav-sub-accounts', label: 'Sub-Accounts',           icon: '🗂', category: 'Account',    action: go('/sub-accounts') },
    { id: 'nav-2fa',          label: '2FA Setup',              icon: '🔐', category: 'Account',    action: go('/2fa') },
    { id: 'nav-notifications',label: 'Notifications',          icon: '🔔', category: 'Account',    action: go('/notifications') },
    { id: 'nav-elite',        label: 'Elite Dashboard',        icon: '👑', category: 'Account',    action: go('/elite') },
    { id: 'nav-prop-firm',    label: 'Prop Firm Tracker',      icon: '🏦', category: 'Account',    action: go('/prop-firm') },
    // Admin
    { id: 'nav-admin',        label: 'Admin Panel',            icon: '🔧', category: 'Admin',      action: go('/admin') },
    { id: 'nav-audit',        label: 'Audit Log',              icon: '🔍', category: 'Admin',      action: go('/audit') },
    { id: 'nav-security',     label: 'Security Dashboard',     icon: '🛡️', category: 'Admin',      action: go('/security') },
    { id: 'nav-auto-heal',    label: 'Auto-Heal',              icon: '🩺', category: 'Admin',      action: go('/auto-heal') },
    { id: 'nav-whitelabel',   label: 'Whitelabel Admin',       icon: '🏷️', category: 'Admin',      action: go('/whitelabel') },
    { id: 'nav-superadmin',   label: 'Super Admin',            icon: '⚡', category: 'Admin',      action: go('/superadmin') },
    { id: 'nav-reliability',  label: 'System Reliability',     icon: '🔬', category: 'Admin',      action: go('/system-reliability') },
    { id: 'nav-status',       label: 'System Status',          icon: '🟢', category: 'Admin',      action: go('/system-status') },
    // Other
    { id: 'nav-docs',         label: 'Documentation',          icon: '📖', category: 'Other',      action: go('/docs') },
    { id: 'nav-pricing',      label: 'Pricing',                icon: '💎', category: 'Other',      action: go('/pricing') },
  ];
}

// ── Fuzzy match ───────────────────────────────────────────────────────────────

function fuzzyMatch(query: string, text: string): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  const t = text.toLowerCase();
  if (t.includes(q)) return true;
  // character-by-character fuzzy
  let qi = 0;
  for (let i = 0; i < t.length && qi < q.length; i++) {
    if (t[i] === q[qi]) qi++;
  }
  return qi === q.length;
}

function scoreMatch(query: string, item: CommandItem): number {
  if (!query) return 0;
  const q = query.toLowerCase();
  const label = item.label.toLowerCase();
  if (label === q) return 100;
  if (label.startsWith(q)) return 80;
  if (label.includes(q)) return 60;
  if (item.desc?.toLowerCase().includes(q)) return 40;
  return 20;
}

// ── Highlight matching chars ──────────────────────────────────────────────────

function HighlightMatch({ text, query }: { text: string; query: string }) {
  if (!query) return <>{text}</>;
  const q = query.toLowerCase();
  const t = text.toLowerCase();
  const idx = t.indexOf(q);
  if (idx === -1) return <>{text}</>;
  return (
    <>
      {text.slice(0, idx)}
      <mark style={{ background: 'rgba(59,130,246,0.35)', color: '#93c5fd', borderRadius: 2, padding: '0 1px' }}>
        {text.slice(idx, idx + q.length)}
      </mark>
      {text.slice(idx + q.length)}
    </>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export const CommandPalette: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const favorites      = useStore((s) => s.favorites);
  const toggleFavorite = useStore((s) => s.toggleFavorite);
  const [open, setOpen]         = useState(false);
  const [query, setQuery]       = useState('');
  const [selected, setSelected] = useState(0);
  const [dynamicItems, setDynamicItems] = useState<CommandItem[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  // Context-aware quick actions (e.g. pin the page you're currently on).
  const actionItems: CommandItem[] = [];
  const currentNav = NAV_ITEMS.find((i) => location.pathname.startsWith(i.path) && i.path !== '/');
  if (currentNav) {
    const pinned = favorites.includes(currentNav.path);
    actionItems.push({
      id: 'action-pin-current',
      label: pinned ? `Unpin "${currentNav.label}" from favorites` : `Pin "${currentNav.label}" to favorites`,
      icon: pinned ? '★' : '☆',
      category: 'Actions',
      action: () => toggleFavorite(currentNav.path),
    });
  }

  const staticItems = buildStaticCommands(navigate);
  const allItems    = [...actionItems, ...staticItems, ...dynamicItems];

  const filtered = allItems
    .filter(item => fuzzyMatch(query, item.label) || fuzzyMatch(query, item.desc ?? '') || fuzzyMatch(query, item.category ?? ''))
    .sort((a, b) => scoreMatch(query, b) - scoreMatch(query, a))
    .slice(0, 12);

  // Group by category
  const groups = filtered.reduce<Record<string, CommandItem[]>>((acc, item) => {
    const cat = item.category ?? 'Other';
    if (!acc[cat]) acc[cat] = [];
    acc[cat].push(item);
    return acc;
  }, {});

  const openPalette  = useCallback(() => { setOpen(true); setQuery(''); setSelected(0); }, []);
  const closePalette = useCallback(() => { setOpen(false); setQuery(''); }, []);

  const register   = useCallback((item: CommandItem) => setDynamicItems(prev => [...prev.filter(i => i.id !== item.id), item]), []);
  const unregister = useCallback((id: string) => setDynamicItems(prev => prev.filter(i => i.id !== id)), []);

  // Global keyboard shortcut
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setOpen(prev => !prev);
        if (!open) { setQuery(''); setSelected(0); }
      }
      if (e.key === 'Escape') closePalette();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, closePalette]);

  // Focus input when opened
  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 50);
  }, [open]);

  // Arrow key navigation
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setSelected(s => Math.min(s + 1, filtered.length - 1)); }
    if (e.key === 'ArrowUp')   { e.preventDefault(); setSelected(s => Math.max(s - 1, 0)); }
    if (e.key === 'Enter') {
      e.preventDefault();
      if (filtered[selected]) { filtered[selected].action(); closePalette(); }
    }
  };

  const ctxValue: CommandContextValue = { register, unregister, open: openPalette, close: closePalette };

  if (!open) {
    return (
      <CommandContext.Provider value={ctxValue}>
        {/* Keyboard hint in corner — only visible on desktop */}
        <div
          onClick={openPalette}
          title="Open command palette (Cmd+K)"
          style={{
            position: 'fixed', bottom: 24, left: 24, zIndex: 8000,
            background: '#0d1421', border: '1px solid #1e293b',
            borderRadius: 8, padding: '6px 10px',
            display: 'flex', alignItems: 'center', gap: 6,
            cursor: 'pointer', fontSize: 11, color: '#475569',
            boxShadow: '0 4px 16px rgba(0,0,0,0.4)',
            transition: 'border-color 0.15s, color 0.15s',
          }}
          onMouseEnter={e => { (e.currentTarget as HTMLDivElement).style.borderColor = '#334155'; (e.currentTarget as HTMLDivElement).style.color = '#94a3b8'; }}
          onMouseLeave={e => { (e.currentTarget as HTMLDivElement).style.borderColor = '#1e293b'; (e.currentTarget as HTMLDivElement).style.color = '#475569'; }}
        >
          <span style={{ fontSize: 13 }}>⌘</span>
          <kbd style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 4, padding: '1px 5px', fontSize: 10, fontFamily: 'monospace' }}>K</kbd>
          <span>Search</span>
        </div>
      </CommandContext.Provider>
    );
  }

  return (
    <CommandContext.Provider value={ctxValue}>
      {/* Backdrop */}
      <div
        style={{
          position: 'fixed', inset: 0, zIndex: 9000,
          background: 'rgba(0,0,0,0.65)', backdropFilter: 'blur(6px)',
        }}
        onClick={closePalette}
      />

      {/* Palette */}
      <div
        style={{
          position: 'fixed', top: '18%', left: '50%', transform: 'translateX(-50%)',
          zIndex: 9001, width: '90%', maxWidth: 580,
          background: '#0d1421', border: '1px solid #1e293b',
          borderRadius: 14, boxShadow: '0 32px 80px rgba(0,0,0,0.7)',
          overflow: 'hidden',
          animation: 'cmdSlideIn 0.18s cubic-bezier(0.34,1.56,0.64,1)',
        }}
        onKeyDown={handleKeyDown}
      >
        <style>{`@keyframes cmdSlideIn { from { transform: translateX(-50%) translateY(-12px) scale(0.97); opacity: 0 } to { transform: translateX(-50%) translateY(0) scale(1); opacity: 1 } }`}</style>

        {/* Search input */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '14px 16px', borderBottom: '1px solid #1e293b' }}>
          <span style={{ fontSize: 16, color: '#475569', flexShrink: 0 }}>🔍</span>
          <input
            ref={inputRef}
            value={query}
            onChange={e => { setQuery(e.target.value); setSelected(0); }}
            placeholder="Search pages, actions, settings…"
            style={{
              flex: 1, background: 'transparent', border: 'none', outline: 'none',
              color: '#f1f5f9', fontSize: 15, fontFamily: 'Inter, system-ui, sans-serif',
            }}
          />
          <kbd style={{
            background: '#1e293b', border: '1px solid #334155', borderRadius: 5,
            padding: '2px 7px', fontSize: 11, color: '#475569', fontFamily: 'monospace', flexShrink: 0,
          }}>
            Esc
          </kbd>
        </div>

        {/* Results */}
        <div style={{ maxHeight: 380, overflowY: 'auto', padding: '8px 0' }}>
          {filtered.length === 0 ? (
            <div style={{ padding: '24px 16px', textAlign: 'center', color: '#475569', fontSize: 13 }}>
              No results for <strong style={{ color: '#64748b' }}>"{query}"</strong>
            </div>
          ) : (
            Object.entries(groups).map(([cat, items]) => {
              const globalIdx = filtered.indexOf(items[0]);
              return (
                <div key={cat}>
                  <div style={{ fontSize: 10, fontWeight: 700, color: '#334155', textTransform: 'uppercase', letterSpacing: '0.08em', padding: '8px 16px 4px' }}>
                    {cat}
                  </div>
                  {items.map(item => {
                    const idx = filtered.indexOf(item);
                    const isSelected = idx === selected;
                    return (
                      <div
                        key={item.id}
                        onClick={() => { item.action(); closePalette(); }}
                        onMouseEnter={() => setSelected(idx)}
                        style={{
                          display: 'flex', alignItems: 'center', gap: 12,
                          padding: '9px 16px', cursor: 'pointer',
                          background: isSelected ? '#1e293b' : 'transparent',
                          transition: 'background 0.1s',
                        }}
                      >
                        <span style={{ fontSize: 17, flexShrink: 0, width: 24, textAlign: 'center' }}>{item.icon ?? '▸'}</span>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontSize: 13, fontWeight: 500, color: isSelected ? '#f1f5f9' : '#cbd5e1' }}>
                            <HighlightMatch text={item.label} query={query} />
                          </div>
                          {item.desc && (
                            <div style={{ fontSize: 11, color: '#475569', marginTop: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                              {item.desc}
                            </div>
                          )}
                        </div>
                        {item.shortcut && (
                          <kbd style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 4, padding: '1px 6px', fontSize: 10, color: '#475569', fontFamily: 'monospace', flexShrink: 0 }}>
                            {item.shortcut}
                          </kbd>
                        )}
                        {isSelected && <span style={{ color: '#334155', fontSize: 12, flexShrink: 0 }}>↵</span>}
                      </div>
                    );
                  })}
                </div>
              );
            })
          )}
        </div>

        {/* Footer */}
        <div style={{ borderTop: '1px solid #1e293b', padding: '8px 16px', display: 'flex', gap: 16, fontSize: 11, color: '#334155' }}>
          <span><kbd style={{ background: '#1e293b', border: '1px solid #1e293b', borderRadius: 3, padding: '1px 4px', fontFamily: 'monospace' }}>↑↓</kbd> navigate</span>
          <span><kbd style={{ background: '#1e293b', border: '1px solid #1e293b', borderRadius: 3, padding: '1px 4px', fontFamily: 'monospace' }}>↵</kbd> open</span>
          <span><kbd style={{ background: '#1e293b', border: '1px solid #1e293b', borderRadius: 3, padding: '1px 4px', fontFamily: 'monospace' }}>Esc</kbd> close</span>
          <span style={{ marginLeft: 'auto' }}>{filtered.length} result{filtered.length !== 1 ? 's' : ''}</span>
        </div>
      </div>
    </CommandContext.Provider>
  );
};
