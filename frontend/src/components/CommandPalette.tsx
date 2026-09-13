/**
 * CommandPalette — global Cmd+K / Ctrl+K fuzzy search across all pages and actions.
 *
 * Usage:
 *   Mount <CommandPalette /> once in App.tsx (inside Router).
 *   The palette opens on Cmd+K / Ctrl+K from anywhere.
 *
 *   To register dynamic actions from a page:
 *     import { Zap } from 'lucide-react';
 *     import { useCommandActions } from '../components/CommandPalette';
 *     const { register, unregister } = useCommandActions();
 *     useEffect(() => {
 *       register({ id: 'open-trade', label: 'Open Trade', icon: Zap, action: () => navigate('/trade') });
 *       return () => unregister('open-trade');
 *     }, []);
 *
 * The navigable entries are NOT listed here. They are derived from NAV_ITEMS
 * in `sidebar/navConfig.ts`, which the sidebar also reads — see
 * `buildNavCommands` below for why that matters (F175).
 */

import React, {
  createContext, useCallback, useContext, useEffect,
  useRef, useState,
} from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import type { LucideIcon } from 'lucide-react';
import { ArrowRight, CreditCard, Search as SearchIcon, Star, StarOff } from 'lucide-react';
import { useStore, type UserRole } from '../store';
import { isAdmin, isSuperAdmin } from '../lib/subscription';
import { NAV_ITEMS, NAV_GROUPS, type NavItem } from './sidebar/navConfig';

// ── Types ─────────────────────────────────────────────────────────────────────

export interface CommandItem {
  id:       string;
  label:    string;
  /** Short description shown below label */
  desc?:    string;
  /** A Lucide component, or a string for the rare glyph that has no icon.
   *  Not an emoji: see `buildNavCommands`. */
  icon?:    LucideIcon | string;
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

// ── Navigation commands, derived from the sidebar's config ───────────────────

/**
 * The palette's navigable entries come from NAV_ITEMS — the same list the
 * sidebar renders — rather than from a second list maintained here.
 *
 * There *was* a second list: fifty hand-written entries, each with an emoji for
 * an icon, immediately below the `import { NAV_ITEMS }` this file already had.
 * It had drifted, exactly as a duplicate source of truth does:
 *
 *   * `Dashboard` pointed at `/home`, which is now a redirect to `/dashboard`;
 *   * `2FA Setup` pointed at `/2fa`, which is not a route at all — the palette
 *     offered a page that 404s into the SPA shell;
 *   * `/system-status` and `/system-reliability` were the pre-rename paths, both
 *     now redirects;
 *   * eleven pages added to the sidebar since (AI Assistant, Strategy Builder,
 *     Transparency, News & Sentiment, Support, Academy, Upgrade Plan,
 *     Observability, ML-Ops, AI Core, Support Console) were not offered at all.
 *
 * Deriving fixes the class, not the instances: a page added to the sidebar is
 * in the palette the same commit.
 *
 * The emoji went with it. `ui-ux-pro-max` forbids emoji as icons and navConfig
 * says why in detail (F170): they render per-platform, are announced literally,
 * and cannot inherit `currentColor`, so they ignore the selected row's colour.
 *
 * Role filtering matches `Sidebar.tsx:384-385`. Without it the palette listed
 * every admin and superadmin page to every user — the routes are guarded, so
 * this was a disclosure of page names rather than of access, but it is still
 * the sidebar's rule and the palette should not have its own.
 */

const GROUP_LABEL: Record<string, string> = Object.fromEntries(
  NAV_GROUPS.map((g) => [g.id, g.label]),
);

export function visibleNavItems(role: UserRole | undefined): NavItem[] {
  const admin      = role ? isAdmin(role) : false;
  const superAdmin = role ? isSuperAdmin(role) : false;
  return NAV_ITEMS.filter((item) => {
    if (item.superAdminOnly && !superAdmin) return false;
    if (item.adminOnly && !admin) return false;
    return true;
  });
}

function buildNavCommands(
  navigate: ReturnType<typeof useNavigate>,
  role: UserRole | undefined,
): CommandItem[] {
  const go = (path: string) => () => navigate(path);
  const fromNav = visibleNavItems(role).map<CommandItem>((item) => ({
    id:       `nav-${item.path.slice(1)}`,
    label:    item.label,
    icon:     item.icon,
    category: GROUP_LABEL[item.group] ?? 'Other',
    action:   go(item.path),
  }));

  // Pages that are real routes but deliberately absent from the sidebar,
  // because they are reachable before sign-in.
  return [
    ...fromNav,
    { id: 'nav-pricing', label: 'Pricing', icon: CreditCard, category: 'Other', action: go('/pricing') },
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

// ── Icon ──────────────────────────────────────────────────────────────────────

/**
 * Renders a Lucide component, or a plain string for the rare entry that has no
 * icon.
 *
 * It names no colour. Lucide defaults to `currentColor`, so the icon takes the
 * row's colour and therefore follows selection and hover — which is exactly what
 * an emoji could not do, and the concrete reason the palette's fifty emoji kept
 * their own appearance on the highlighted row. `opacity` rather than a second
 * grey keeps the icon a step behind the label without another literal.
 */
function CommandIcon({ icon, selected }: { icon?: LucideIcon | string; selected: boolean }) {
  const box = { flexShrink: 0, width: 24, opacity: selected ? 1 : 0.7 } as const;
  if (typeof icon === 'string') {
    return <span style={{ ...box, fontSize: 17, textAlign: 'center' as const }}>{icon}</span>;
  }
  const Glyph = icon ?? ArrowRight;
  return (
    <span style={{ ...box, display: 'flex', justifyContent: 'center' }}>
      <Glyph size={17} strokeWidth={2} aria-hidden="true" />
    </span>
  );
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
  const user           = useStore((s) => s.user);
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
      icon: pinned ? StarOff : Star,
      category: 'Actions',
      action: () => toggleFavorite(currentNav.path),
    });
  }

  const staticItems = buildNavCommands(navigate, user?.role);
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
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
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
          <SearchIcon size={16} strokeWidth={2} color="#475569" style={{ flexShrink: 0 }} aria-hidden="true" />
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
              // `globalIdx` was computed here and never read — a leftover from
              // when the group header showed its first row's index.
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
                          // On the row, not the label: the Lucide icon inherits
                          // it through currentColor.
                          color: isSelected ? '#f1f5f9' : '#cbd5e1',
                          transition: 'background 0.1s',
                        }}
                      >
                        <CommandIcon icon={item.icon} selected={isSelected} />
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontSize: 13, fontWeight: 500 }}>
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
