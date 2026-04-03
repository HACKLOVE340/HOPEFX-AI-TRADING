/**
 * Sidebar.tsx
 * Role-aware, subscription-aware collapsible sidebar.
 *
 * Rules:
 *  - Admin/superadmin see ALL groups including the Admin group
 *  - Traders see items up to their plan tier; locked items show a lock badge
 *  - Admin-only items are completely hidden from non-admins
 *  - Groups with no visible items are hidden entirely
 */

import React from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { useStore, selectIsAuth, selectUser, selectWsStatus, selectPlan } from '../../store';
import { ThemeToggle } from '../ThemeToggle';
import { isAdmin, isSuperAdmin, hasFeatureAccess, PLAN_LABELS, PLAN_COLORS } from '../../lib/subscription';
import { NAV_ITEMS, NAV_GROUPS } from './navConfig';
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

// ── Group label ───────────────────────────────────────────────────────────────
const GroupLabel: React.FC<{ label: string; collapsed: boolean }> = ({ label, collapsed }) => {
  if (collapsed) return <div style={{ height: 1, background: '#1e293b', margin: '6px 8px' }} />;
  return (
    <div style={{
      fontSize: 10, fontWeight: 700, color: '#334155', textTransform: 'uppercase',
      letterSpacing: '0.08em', padding: '14px 14px 4px',
    }}>
      {label}
    </div>
  );
};

// ── Main Sidebar ──────────────────────────────────────────────────────────────
interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

const Sidebar: React.FC<SidebarProps> = ({ collapsed, onToggle }) => {
  const location  = useLocation();
  const navigate  = useNavigate();
  const isAuth    = useStore(selectIsAuth);
  const user      = useStore(selectUser);
  const plan      = useStore(selectPlan);
  const clearAuth = useStore((s) => s.clearAuth);

  const admin      = user ? isAdmin(user.role) : false;
  const superAdmin = user ? isSuperAdmin(user.role) : false;

  // Build visible groups
  const visibleGroups = NAV_GROUPS.filter((g) => {
    if (g.id === 'superadmin') return superAdmin;
    if (g.id === 'admin')      return admin;
    return true;
  });

  return (
    <aside style={{
      width: collapsed ? 60 : 224,
      background: 'var(--surface, #1e293b)',
      borderRight: '1px solid var(--border, #334155)',
      display: 'flex', flexDirection: 'column', flexShrink: 0,
      transition: 'width 0.2s ease', overflow: 'hidden',
      height: '100vh',
    }}>
      {/* Logo */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '18px 14px 14px', borderBottom: '1px solid var(--border, #334155)',
        minHeight: 60,
      }}>
        {collapsed
          ? <span style={{ fontSize: 20, fontWeight: 800, color: '#3b82f6' }}>H</span>
          : <span style={{ fontSize: 18, fontWeight: 800, color: '#f8fafc', letterSpacing: -0.5 }}>
              HOPE<span style={{ color: '#3b82f6' }}>FX</span>
            </span>
        }
        <button
          onClick={onToggle}
          title={collapsed ? 'Expand' : 'Collapse'}
          style={{
            background: 'transparent', border: 'none', color: '#64748b',
            fontSize: 18, cursor: 'pointer', padding: '2px 4px', lineHeight: 1,
          }}
        >
          {collapsed ? '›' : '‹'}
        </button>
      </div>

      {/* Nav */}
      <nav style={{
        flex: 1, padding: '6px 0',
        display: 'flex', flexDirection: 'column',
        overflowY: 'auto', overflowX: 'hidden',
      }}>
        {visibleGroups.map((group) => {
          const items = NAV_ITEMS.filter((item) => {
            if (item.group !== group.id)  return false;
            if (item.superAdminOnly)      return superAdmin;
            if (item.adminOnly)           return admin;
            return true;
          });

          if (items.length === 0) return null;

          return (
            <div key={group.id}>
              <GroupLabel label={group.label} collapsed={collapsed} />
              {items.map((item) => {
                const active  = location.pathname.startsWith(item.path);
                const locked  = !admin && item.featureKey
                  ? !hasFeatureAccess(user?.role ?? 'user', plan, item.featureKey)
                  : false;

                return (
                  <NavLink
                    key={item.path}
                    to={item.path}
                    title={collapsed ? item.label : undefined}
                    style={{
                      display: 'flex', alignItems: 'center',
                      gap: 10, padding: '9px 14px',
                      textDecoration: 'none', fontSize: 13, fontWeight: 500,
                      transition: 'background 0.15s, color 0.15s',
                      borderRadius: '0 6px 6px 0', marginRight: 8,
                      background:  active ? '#1e3a5f' : 'transparent',
                      color:       active ? '#60a5fa' : locked ? '#334155' : '#94a3b8',
                      borderLeft:  active ? '3px solid #3b82f6' : '3px solid transparent',
                      justifyContent: collapsed ? 'center' : 'flex-start',
                      opacity: locked ? 0.6 : 1,
                    }}
                  >
                    <span style={{ fontSize: 15, flexShrink: 0, width: 20, textAlign: 'center' }}>
                      {item.icon}
                    </span>
                    {!collapsed && (
                      <>
                        <span style={{ whiteSpace: 'nowrap', overflow: 'hidden', flex: 1 }}>
                          {item.label}
                        </span>
                        {locked && item.plan && <LockBadge requiredPlan={item.plan} />}
                      </>
                    )}
                  </NavLink>
                );
              })}
            </div>
          );
        })}
      </nav>

      {/* Footer */}
      {!collapsed && (
        <div style={{
          borderTop: '1px solid var(--border, #334155)',
          padding: '12px 14px',
          display: 'flex', flexDirection: 'column', gap: 8,
        }}>
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
                onClick={clearAuth}
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
            <a href="/" style={{ fontSize: 12, color: '#475569', textDecoration: 'none' }}>
              ← Landing
            </a>
            <ThemeToggle />
          </div>
        </div>
      )}
    </aside>
  );
};

export default Sidebar;
