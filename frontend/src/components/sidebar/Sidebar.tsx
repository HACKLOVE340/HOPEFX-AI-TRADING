/**
 * Sidebar.tsx
 * Role-aware, subscription-aware collapsible sidebar with search.
 *
 * Rules:
 *  - Admin/superadmin see ALL groups including the Admin group
 *  - Traders see items up to their plan tier; locked items show a lock badge
 *  - Admin-only items are completely hidden from non-admins
 *  - Groups with no visible items are hidden entirely
 *  - Search box filters all visible nav items in real-time
 */

import React, { useEffect, useState, useMemo } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import {
  useStore, selectIsAuth, selectUser, selectWsStatus, selectPlan,
  selectFavorites, selectCollapsedGroups, selectRecentPaths,
} from '../../store';
import { ThemeToggle } from '../ThemeToggle';
import { isAdmin, isSuperAdmin, hasFeatureAccess, PLAN_LABELS, PLAN_COLORS } from '../../lib/subscription';
import { NAV_ITEMS, NAV_GROUPS } from './navConfig';
import type { NavItem } from './navConfig';
import { authApi, notificationsApi } from '../../hooks/useApi';
import type { Plan } from '../../lib/subscription';

// ── WS status dot ─────────────────────────────────────────────────────────────
const WsDot: React.FC = () => {
  const status = useStore(selectWsStatus);
  const color =
    status === 'connected'  ? '#22c55e' :
    status === 'connecting' ? '#fbbf24' :
    status === 'error'      ? '#f87171' : '#475569';
  return (
    <span
      title={`WebSocket: ${status}`}
      style={{
        width: 7, height: 7, borderRadius: '50%', display: 'inline-block',
        background: color,
        boxShadow: status === 'connected' ? `0 0 5px ${color}` : 'none',
        flexShrink: 0,
      }}
    />
  );
};

// ── Plan badge ────────────────────────────────────────────────────────────────
const PlanBadge: React.FC<{ plan: Plan; role: string }> = ({ plan, role }) => {
  if (role === 'admin' || role === 'superadmin') {
    return (
      <span style={{
        fontSize: 9, fontWeight: 700, padding: '2px 6px', borderRadius: 4,
        background: '#1e3a5f', color: '#60a5fa', border: '1px solid #1e3a5f',
        textTransform: 'uppercase', letterSpacing: '0.05em',
      }}>
        ADMIN
      </span>
    );
  }
  const color = PLAN_COLORS[plan];
  return (
    <span style={{
      fontSize: 9, fontWeight: 700, padding: '2px 6px', borderRadius: 4,
      background: `${color}18`, color, border: `1px solid ${color}40`,
      textTransform: 'uppercase', letterSpacing: '0.05em',
    }}>
      {PLAN_LABELS[plan]}
    </span>
  );
};

// ── Lock badge ────────────────────────────────────────────────────────────────
const LockBadge: React.FC<{ requiredPlan: string }> = ({ requiredPlan }) => (
  <span style={{
    fontSize: 9, fontWeight: 700, padding: '2px 5px', borderRadius: 4,
    background: '#1e293b', color: '#475569', border: '1px solid #334155',
    textTransform: 'uppercase', letterSpacing: '0.04em', marginLeft: 'auto',
  }}>
    {requiredPlan}
  </span>
);

// ── Trading mode badge ────────────────────────────────────────────────────────
const TradingModeBadge: React.FC<{ collapsed: boolean }> = ({ collapsed }) => {
  const [mode, setMode] = useState<'paper' | 'live' | null>(null);

  useEffect(() => {
    let cancelled = false;
    const fetch_mode = async () => {
      try {
        const res = await fetch('/api/health/live');
        if (!res.ok) return;
        const data = await res.json();
        if (!cancelled) setMode(data.trading_mode === 'live' ? 'live' : 'paper');
      } catch {
        // health endpoint unavailable — don't show badge
      }
    };
    fetch_mode();
    const interval = setInterval(fetch_mode, 60_000);
    return () => { cancelled = true; clearInterval(interval); };
  }, []);

  if (mode === null) return null;

  const isLive = mode === 'live';
  const label = isLive ? 'LIVE' : 'PAPER';
  const bg    = isLive ? 'rgba(34,197,94,0.12)'  : 'rgba(251,191,36,0.12)';
  const color = isLive ? '#22c55e'                : '#fbbf24';
  const border = isLive ? 'rgba(34,197,94,0.35)' : 'rgba(251,191,36,0.35)';

  if (collapsed) {
    return (
      <span
        title={`Trading mode: ${label}`}
        style={{
          width: 8, height: 8, borderRadius: '50%', display: 'block',
          background: color, margin: '0 auto',
          boxShadow: `0 0 6px ${color}`,
        }}
      />
    );
  }

  return (
    <span
      title={`Trading mode: ${label}${isLive ? ' — real orders will be placed' : ' — no real orders'}`}
      style={{
        fontSize: 9, fontWeight: 800, padding: '2px 7px', borderRadius: 4,
        background: bg, color, border: `1px solid ${border}`,
        textTransform: 'uppercase', letterSpacing: '0.08em',
        display: 'inline-flex', alignItems: 'center', gap: 4,
      }}
    >
      <span style={{
        width: 5, height: 5, borderRadius: '50%', background: color,
        boxShadow: isLive ? `0 0 4px ${color}` : 'none',
        flexShrink: 0,
      }} />
      {label}
    </span>
  );
};

// ── Collapsible group label ─────────────────────────────────────────────────
// In the expanded sidebar the header is a button that collapses/expands the
// group. In the icon-only sidebar it degrades to a plain divider.
const GroupLabel: React.FC<{
  label: string;
  collapsed: boolean;
  groupCollapsed?: boolean;
  onToggle?: () => void;
}> = ({ label, collapsed, groupCollapsed, onToggle }) => {
  if (collapsed) return <div style={{ height: 1, background: '#1e293b', margin: '6px 8px' }} />;
  return (
    <button
      onClick={onToggle}
      aria-expanded={!groupCollapsed}
      style={{
        display: 'flex', alignItems: 'center', gap: 6, width: '100%',
        background: 'transparent', border: 'none', cursor: 'pointer',
        fontSize: 10, fontWeight: 700, color: '#334155', textTransform: 'uppercase',
        letterSpacing: '0.08em', padding: '14px 14px 4px', textAlign: 'left',
        fontFamily: 'inherit',
      }}
    >
      <span style={{
        fontSize: 9, transition: 'transform 0.15s',
        transform: groupCollapsed ? 'rotate(-90deg)' : 'rotate(0deg)',
        display: 'inline-block', width: 8,
      }}>
        ▼
      </span>
      {label}
    </button>
  );
};

// ── Reusable nav item row ───────────────────────────────────────────────────
// Shared by the Favorites section, recents, search results and grouped nav so
// pin/lock/badge behaviour stays consistent everywhere.
interface NavItemRowProps {
  item:             NavItem;
  active:           boolean;
  locked:           boolean;
  collapsed:        boolean;
  unreadCount:      number;
  isFavorite:       boolean;
  onToggleFavorite: (path: string) => void;
  onNavigate?:      () => void;
}

const NavItemRow: React.FC<NavItemRowProps> = ({
  item, active, locked, collapsed, unreadCount, isFavorite, onToggleFavorite, onNavigate,
}) => (
  <NavLink
    to={locked ? '/upgrade' : item.path}
    className="hopefx-navrow"
    title={collapsed ? (locked ? `${item.label} — upgrade to ${item.plan}` : item.label) : undefined}
    onClick={onNavigate}
    style={{
      display: 'flex', alignItems: 'center',
      gap: 10, padding: '10px 14px',
      minHeight: 44,
      textDecoration: 'none', fontSize: 13, fontWeight: 500,
      transition: 'background 0.15s, color 0.15s',
      borderRadius: '0 6px 6px 0', marginRight: 8,
      background:  active ? '#1e3a5f' : 'transparent',
      color:       active ? '#60a5fa' : locked ? '#334155' : '#94a3b8',
      borderLeft:  active ? '3px solid #3b82f6' : '3px solid transparent',
      justifyContent: collapsed ? 'center' : 'flex-start',
      opacity: locked ? 0.6 : 1,
      position: 'relative',
      cursor: locked ? 'not-allowed' : 'pointer',
    }}
  >
    <span style={{ fontSize: 15, flexShrink: 0, width: 20, textAlign: 'center' }}>
      {item.icon}
    </span>
    {!collapsed && (
      <>
        {/* ellipsis + title: long labels ("AI Chart Dashboard", "Copy Trading")
            were hard-clipped mid-word by nowrap+hidden at every viewport width */}
        <span
          title={item.label}
          style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', flex: 1 }}
        >
          {item.label}
        </span>
        {locked && item.plan && <LockBadge requiredPlan={item.plan} />}
        {item.path === '/notifications' && unreadCount > 0 && (
          <span style={{
            minWidth: 16, height: 16, borderRadius: 8,
            background: '#ef4444', color: '#fff',
            fontSize: 9, fontWeight: 800, lineHeight: '16px',
            textAlign: 'center', padding: '0 4px', flexShrink: 0,
          }}>
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
        {/* Pin / unpin — appears on row hover, stays visible when pinned */}
        {!locked && (
          <button
            className={`hopefx-pin${isFavorite ? ' pinned' : ''}`}
            title={isFavorite ? 'Unpin from favorites' : 'Pin to favorites'}
            aria-label={isFavorite ? 'Unpin from favorites' : 'Pin to favorites'}
            onClick={(e) => { e.preventDefault(); e.stopPropagation(); onToggleFavorite(item.path); }}
            style={{
              background: 'transparent', border: 'none', cursor: 'pointer',
              color: isFavorite ? '#fbbf24' : '#475569',
              fontSize: 12, lineHeight: 1, padding: 2, flexShrink: 0,
            }}
          >
            {isFavorite ? '★' : '☆'}
          </button>
        )}
      </>
    )}
    {collapsed && item.path === '/notifications' && unreadCount > 0 && (
      <span style={{
        position: 'absolute', top: 4, right: 4,
        width: 8, height: 8, borderRadius: '50%',
        background: '#ef4444',
      }} />
    )}
  </NavLink>
);

// ── Search box ────────────────────────────────────────────────────────────────
const SearchBox: React.FC<{ value: string; onChange: (v: string) => void }> = ({ value, onChange }) => (
  <div style={{
    padding: '6px 10px',
    borderBottom: '1px solid #1e293b',
  }}>
    <div style={{
      display: 'flex', alignItems: 'center', gap: 6,
      background: '#0f172a', border: '1px solid #1e293b',
      borderRadius: 6, padding: '5px 8px',
    }}>
      <span style={{ fontSize: 11, color: '#475569', flexShrink: 0 }}>🔍</span>
      <input
        type="text"
        placeholder="Search…"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{
          background: 'transparent', border: 'none', outline: 'none',
          color: '#e2e8f0', fontSize: 12, width: '100%',
          fontFamily: 'inherit',
        }}
      />
      {value && (
        <button
          onClick={() => onChange('')}
          style={{
            background: 'transparent', border: 'none', cursor: 'pointer',
            color: '#475569', fontSize: 14, padding: 0, lineHeight: 1,
          }}
        >
          ×
        </button>
      )}
    </div>
  </div>
);

// ── Main Sidebar ──────────────────────────────────────────────────────────────
interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
  /** Called after any nav-link click — used by mobile drawer to close itself */
  onNavigate?: () => void;
}

const Sidebar: React.FC<SidebarProps> = ({ collapsed, onToggle, onNavigate }) => {
  const location  = useLocation();
  const navigate  = useNavigate();
  const isAuth    = useStore(selectIsAuth);
  const user      = useStore(selectUser);
  const plan      = useStore(selectPlan);
  const clearAuth = useStore((s) => s.clearAuth);
  const favorites       = useStore(selectFavorites);
  const collapsedGroups = useStore(selectCollapsedGroups);
  const recentPaths     = useStore(selectRecentPaths);
  const toggleFavorite  = useStore((s) => s.toggleFavorite);
  const toggleGroup     = useStore((s) => s.toggleGroup);
  const pushRecentPath  = useStore((s) => s.pushRecentPath);
  const [search, setSearch] = useState('');
  const [unreadCount, setUnreadCount] = useState(0);

  // Track recently-visited nav items (only real nav destinations, not aliases).
  useEffect(() => {
    const match = NAV_ITEMS.find((i) => location.pathname.startsWith(i.path) && i.path !== '/');
    if (match) pushRecentPath(match.path);
  }, [location.pathname, pushRecentPath]);

  useEffect(() => {
    if (!isAuth) return;
    const fetchUnread = () =>
      notificationsApi.list({ page: 1, limit: 1, unread_only: true })
        .then(r => {
          const d = r.data as { total?: number } | unknown[];
          const n = Array.isArray(d) ? d.length : ((d as { total?: number }).total ?? 0);
          setUnreadCount(typeof n === 'number' ? n : 0);
        })
        .catch(() => {/* non-fatal */});
    fetchUnread();
    const id = setInterval(fetchUnread, 60_000);
    return () => clearInterval(id);
  }, [isAuth]);

  const handleSignOut = async () => {
    try { await authApi.logout(); } catch { /* ignore network errors on logout */ }
    clearAuth();
    navigate('/login', { replace: true });
  };

  const admin      = user ? isAdmin(user.role) : false;
  const superAdmin = user ? isSuperAdmin(user.role) : false;

  // Build visible groups
  const visibleGroups = NAV_GROUPS.filter((g) => {
    if (g.id === 'superadmin') return superAdmin;
    if (g.id === 'admin')      return admin;
    return true;
  });

  // Filter nav items by search query
  const searchLower = search.toLowerCase().trim();
  const filteredItems = useMemo(() => {
    if (!searchLower) return null;
    return NAV_ITEMS.filter((item) => {
      if (item.superAdminOnly && !superAdmin) return false;
      if (item.adminOnly && !admin) return false;
      return item.label.toLowerCase().includes(searchLower) ||
             item.path.toLowerCase().includes(searchLower);
    });
  }, [searchLower, admin, superAdmin]);

  // Per-item access/state helpers shared by all render paths.
  const isLocked = (item: NavItem) =>
    !admin && item.featureKey
      ? !hasFeatureAccess(user?.role ?? 'user', plan, item.featureKey)
      : false;
  const isActive = (item: NavItem) => location.pathname.startsWith(item.path);
  const favoriteSet = useMemo(() => new Set(favorites), [favorites]);

  // Resolve pinned paths back to nav items the user is actually allowed to see.
  const favoriteItems = useMemo(() => {
    if (!favorites.length) return [];
    return favorites
      .map((p) => NAV_ITEMS.find((i) => i.path === p))
      .filter((i): i is NavItem => {
        if (!i) return false;
        if (i.superAdminOnly) return superAdmin;
        if (i.adminOnly)      return admin;
        return true;
      });
  }, [favorites, admin, superAdmin]);

  // Recently-visited items: exclude the current page and anything already
  // pinned (to avoid duplication with Favorites), cap at 4.
  const recentItems = useMemo(() => {
    return recentPaths
      .filter((p) => p !== location.pathname && !favoriteSet.has(p))
      .map((p) => NAV_ITEMS.find((i) => i.path === p))
      .filter((i): i is NavItem => {
        if (!i) return false;
        if (i.superAdminOnly) return superAdmin;
        if (i.adminOnly)      return admin;
        return true;
      })
      .slice(0, 4);
  }, [recentPaths, location.pathname, favoriteSet, admin, superAdmin]);

  return (
    <aside style={{
      width: collapsed ? 60 : 224,
      background: 'var(--surface, #1e293b)',
      borderRight: '1px solid var(--border, #334155)',
      display: 'flex', flexDirection: 'column', flexShrink: 0,
      transition: 'width 0.2s ease', overflow: 'hidden',
      height: '100%',
      /* When used as a mobile drawer the parent sets position:fixed and height */
    }}>
      {/* Logo / header */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '0 14px', borderBottom: '1px solid var(--border, #334155)',
        minHeight: 56, flexShrink: 0,
        paddingTop: 'env(safe-area-inset-top, 0px)',
      }}>
        {collapsed
          ? (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6 }}>
              <span style={{ fontSize: 20, fontWeight: 800, color: '#3b82f6' }}>H</span>
              <TradingModeBadge collapsed={true} />
            </div>
          )
          : (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0, flex: 1 }}>
              <span style={{ fontSize: 18, fontWeight: 800, color: '#f8fafc', letterSpacing: -0.5, flexShrink: 0 }}>
                HOPE<span style={{ color: '#3b82f6' }}>FX</span>
              </span>
              <TradingModeBadge collapsed={false} />
            </div>
          )
        }
        {/* Toggle / close button — 44×44 touch target */}
        <button
          onClick={onToggle}
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          style={{
            background: 'transparent', border: 'none', color: '#64748b',
            fontSize: 18, cursor: 'pointer',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            minWidth: 44, minHeight: 44, flexShrink: 0,
            borderRadius: 6,
          }}
        >
          {collapsed ? '›' : '‹'}
        </button>
      </div>

      {/* Search box — only when expanded */}
      {!collapsed && (
        <SearchBox value={search} onChange={setSearch} />
      )}

      {/* Nav */}
      <nav style={{
        flex: 1, padding: '6px 0',
        display: 'flex', flexDirection: 'column',
        overflowY: 'auto', overflowX: 'hidden',
      }}>
        {/* Hover-reveal behaviour for the pin button (can't be done inline). */}
        <style>{`
          .hopefx-pin { opacity: 0; transition: opacity 0.12s, color 0.12s; }
          .hopefx-navrow:hover .hopefx-pin { opacity: 0.7; }
          .hopefx-pin:hover { opacity: 1 !important; color: #fbbf24 !important; }
          .hopefx-pin.pinned { opacity: 1; }
        `}</style>

        {/* ── Search results mode ── */}
        {filteredItems && !collapsed ? (
          filteredItems.length === 0 ? (
            <div style={{ padding: '16px 14px', fontSize: 12, color: '#475569', textAlign: 'center' }}>
              No results for "{search}"
            </div>
          ) : (
            <div>
              <div style={{
                fontSize: 10, fontWeight: 700, color: '#334155', textTransform: 'uppercase',
                letterSpacing: '0.08em', padding: '8px 14px 4px',
              }}>
                {filteredItems.length} result{filteredItems.length !== 1 ? 's' : ''}
              </div>
              {filteredItems.map((item) => (
                <NavItemRow
                  key={item.path}
                  item={item}
                  active={isActive(item)}
                  locked={isLocked(item)}
                  collapsed={false}
                  unreadCount={unreadCount}
                  isFavorite={favoriteSet.has(item.path)}
                  onToggleFavorite={toggleFavorite}
                  onNavigate={() => { setSearch(''); onNavigate?.(); }}
                />
              ))}
            </div>
          )
        ) : (
          /* ── Normal grouped nav ── */
          <>
            {/* Favorites — pinned items, expanded sidebar only */}
            {!collapsed && favoriteItems.length > 0 && (
              <div>
                <div style={{
                  fontSize: 10, fontWeight: 700, color: '#334155', textTransform: 'uppercase',
                  letterSpacing: '0.08em', padding: '8px 14px 4px',
                  display: 'flex', alignItems: 'center', gap: 5,
                }}>
                  <span style={{ color: '#fbbf24' }}>★</span> Favorites
                </div>
                {favoriteItems.map((item) => (
                  <NavItemRow
                    key={`fav-${item.path}`}
                    item={item}
                    active={isActive(item)}
                    locked={isLocked(item)}
                    collapsed={false}
                    unreadCount={unreadCount}
                    isFavorite
                    onToggleFavorite={toggleFavorite}
                    onNavigate={onNavigate}
                  />
                ))}
              </div>
            )}

            {/* Recent — recently visited, expanded sidebar only */}
            {!collapsed && recentItems.length > 0 && (
              <div>
                <div style={{
                  fontSize: 10, fontWeight: 700, color: '#334155', textTransform: 'uppercase',
                  letterSpacing: '0.08em', padding: '8px 14px 4px',
                  display: 'flex', alignItems: 'center', gap: 5,
                }}>
                  <span>🕘</span> Recent
                </div>
                {recentItems.map((item) => (
                  <NavItemRow
                    key={`recent-${item.path}`}
                    item={item}
                    active={isActive(item)}
                    locked={isLocked(item)}
                    collapsed={false}
                    unreadCount={unreadCount}
                    isFavorite={favoriteSet.has(item.path)}
                    onToggleFavorite={toggleFavorite}
                    onNavigate={onNavigate}
                  />
                ))}
              </div>
            )}

            {visibleGroups.map((group) => {
              const items = NAV_ITEMS.filter((item) => {
                if (item.group !== group.id)  return false;
                if (item.superAdminOnly)      return superAdmin;
                if (item.adminOnly)           return admin;
                return true;
              });

              if (items.length === 0) return null;

              const groupCollapsed = !collapsed && collapsedGroups.includes(group.id);

              return (
                <div key={group.id}>
                  <GroupLabel
                    label={group.label}
                    collapsed={collapsed}
                    groupCollapsed={groupCollapsed}
                    onToggle={() => toggleGroup(group.id)}
                  />
                  {!groupCollapsed && items.map((item) => (
                    <NavItemRow
                      key={item.path}
                      item={item}
                      active={isActive(item)}
                      locked={isLocked(item)}
                      collapsed={collapsed}
                      unreadCount={unreadCount}
                      isFavorite={favoriteSet.has(item.path)}
                      onToggleFavorite={toggleFavorite}
                      onNavigate={onNavigate}
                    />
                  ))}
                </div>
              );
            })}
          </>
        )}
      </nav>

      {/* Footer */}
      <div style={{
        borderTop: '1px solid var(--border, #334155)',
        padding: collapsed ? '10px 0' : '12px 14px',
        display: 'flex',
        flexDirection: 'column',
        alignItems: collapsed ? 'center' : 'stretch',
        gap: 8,
        flexShrink: 0,
      }}>
        {collapsed ? (
          /* ── Collapsed: icon-only footer ─────────────────────────────── */
          <>
            <div style={{ display: 'flex', justifyContent: 'center', padding: '2px 0' }}>
              <WsDot />
            </div>
            {isAuth ? (
              <button
                onClick={handleSignOut}
                title="Sign out"
                style={{
                  background: 'transparent', border: 'none', cursor: 'pointer',
                  color: '#475569', fontSize: 16, lineHeight: 1,
                  padding: '4px', display: 'flex', alignItems: 'center', justifyContent: 'center',
                  borderRadius: 6,
                }}
              >
                ⏻
              </button>
            ) : (
              <button
                onClick={() => navigate('/login')}
                title="Sign in"
                style={{
                  background: 'transparent', border: 'none', cursor: 'pointer',
                  color: '#60a5fa', fontSize: 16, lineHeight: 1,
                  padding: '4px', display: 'flex', alignItems: 'center', justifyContent: 'center',
                  borderRadius: 6,
                }}
              >
                →
              </button>
            )}
          </>
        ) : (
          /* ── Expanded: full footer ───────────────────────────────────── */
          <>
            {isAuth && user ? (
              <>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <WsDot />
                  <span style={{
                    fontSize: 12, color: '#94a3b8',
                    overflow: 'hidden', textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap', flex: 1,
                  }}>
                    {user.username}
                  </span>
                  <PlanBadge plan={plan} role={user.role} />
                </div>
                <button
                  onClick={handleSignOut}
                  style={{
                    background: 'transparent', border: '1px solid #334155',
                    borderRadius: 6, color: '#64748b', fontSize: 12,
                    cursor: 'pointer', padding: '4px 8px', textAlign: 'left',
                  }}
                >
                  Sign out
                </button>
              </>
            ) : (
              <button
                onClick={() => navigate('/login')}
                style={{
                  background: '#1e3a5f', border: 'none', borderRadius: 6,
                  color: '#60a5fa', fontSize: 12, cursor: 'pointer',
                  padding: '6px 10px', fontWeight: 600,
                }}
              >
                Sign in →
              </button>
            )}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                <NavLink to="/" onClick={onNavigate} style={{ fontSize: 12, color: '#475569', textDecoration: 'none' }}>
                  ← Landing
                </NavLink>
                <NavLink to="/docs" onClick={onNavigate} style={{ fontSize: 12, color: '#475569', textDecoration: 'none' }} title="Documentation">
                  Docs
                </NavLink>
                <NavLink to="/system-status" onClick={onNavigate} style={{ fontSize: 12, color: '#475569', textDecoration: 'none' }} title="System status">
                  Status
                </NavLink>
              </div>
              <ThemeToggle />
            </div>
          </>
        )}
      </div>
    </aside>
  );
};

export default Sidebar;
