// superadmin/ui.tsx — shared UI primitives for all superadmin sections
import React from 'react';

// ── KPI Tile ──────────────────────────────────────────────────────────────────

interface KpiTileProps {
  label: string;
  value: string | number;
  sub?: string;
  icon?: string;
  accent?: string;
  trend?: 'up' | 'down' | 'neutral';
  trendValue?: string;
  onClick?: () => void;
}

export const KpiTile: React.FC<KpiTileProps> = ({
  label, value, sub, icon, accent = '#3b82f6', trend, trendValue, onClick,
}) => (
  <div
    onClick={onClick}
    style={{
      background: '#0f172a',
      border: `1px solid #1e293b`,
      borderTop: `3px solid ${accent}`,
      borderRadius: 12,
      padding: '18px 20px',
      cursor: onClick ? 'pointer' : 'default',
      transition: 'border-color 0.15s, transform 0.1s',
      position: 'relative',
      overflow: 'hidden',
    }}
    onMouseEnter={e => onClick && ((e.currentTarget as HTMLDivElement).style.borderColor = accent)}
    onMouseLeave={e => onClick && ((e.currentTarget as HTMLDivElement).style.borderColor = '#1e293b')}
  >
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.07em' }}>
        {label}
      </div>
      {icon && <span style={{ fontSize: 18, opacity: 0.7 }}>{icon}</span>}
    </div>
    <div style={{ fontSize: 28, fontWeight: 800, color: '#f8fafc', marginTop: 8, letterSpacing: '-0.02em' }}>
      {value}
    </div>
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 4 }}>
      {trend && trendValue && (
        <span style={{
          fontSize: 11, fontWeight: 600,
          color: trend === 'up' ? '#4ade80' : trend === 'down' ? '#f87171' : '#94a3b8',
        }}>
          {trend === 'up' ? '▲' : trend === 'down' ? '▼' : '—'} {trendValue}
        </span>
      )}
      {sub && <span style={{ fontSize: 11, color: '#475569' }}>{sub}</span>}
    </div>
  </div>
);

// ── Section Card ──────────────────────────────────────────────────────────────

interface SectionCardProps {
  title: string;
  subtitle?: string;
  icon?: string;
  accent?: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
  noPad?: boolean;
}

export const SectionCard: React.FC<SectionCardProps> = ({
  title, subtitle, icon, accent = '#3b82f6', actions, children, noPad,
}) => (
  <div style={{
    background: '#0f172a',
    border: '1px solid #1e293b',
    borderRadius: 14,
    overflow: 'hidden',
    marginBottom: 20,
  }}>
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '16px 20px',
      borderBottom: '1px solid #1e293b',
      background: '#0a1628',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        {icon && (
          <div style={{
            width: 32, height: 32, borderRadius: 8,
            background: `${accent}22`, border: `1px solid ${accent}44`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 16,
          }}>
            {icon}
          </div>
        )}
        <div>
          <div style={{ fontSize: 14, fontWeight: 700, color: '#f1f5f9' }}>{title}</div>
          {subtitle && <div style={{ fontSize: 12, color: '#475569', marginTop: 1 }}>{subtitle}</div>}
        </div>
      </div>
      {actions && <div style={{ display: 'flex', gap: 8 }}>{actions}</div>}
    </div>
    <div style={noPad ? {} : { padding: '16px 20px' }}>{children}</div>
  </div>
);

// ── Status Badge ──────────────────────────────────────────────────────────────

const STATUS_COLORS: Record<string, { bg: string; color: string }> = {
  active:    { bg: '#052e16', color: '#4ade80' },
  running:   { bg: '#052e16', color: '#4ade80' },
  healthy:   { bg: '#052e16', color: '#4ade80' },
  ok:        { bg: '#052e16', color: '#4ade80' },
  online:    { bg: '#052e16', color: '#4ade80' },
  banned:    { bg: '#450a0a', color: '#f87171' },
  stopped:   { bg: '#450a0a', color: '#f87171' },
  critical:  { bg: '#450a0a', color: '#f87171' },
  error:     { bg: '#450a0a', color: '#f87171' },
  paused:    { bg: '#78350f', color: '#fbbf24' },
  degraded:  { bg: '#78350f', color: '#fbbf24' },
  warn:      { bg: '#78350f', color: '#fbbf24' },
  training:  { bg: '#1e3a5f', color: '#60a5fa' },
  staged:    { bg: '#2e1065', color: '#c084fc' },
  pending:   { bg: '#78350f', color: '#fbbf24' },
  inactive:  { bg: '#1e293b', color: '#64748b' },
  retired:   { bg: '#1e293b', color: '#64748b' },
};

export const StatusBadge: React.FC<{ status: string; size?: 'sm' | 'md' }> = ({ status, size = 'md' }) => {
  const s = STATUS_COLORS[status.toLowerCase()] ?? { bg: '#1e293b', color: '#94a3b8' };
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5,
      background: s.bg, color: s.color,
      border: `1px solid ${s.color}33`,
      borderRadius: 20,
      padding: size === 'sm' ? '2px 8px' : '3px 10px',
      fontSize: size === 'sm' ? 10 : 11,
      fontWeight: 700,
      textTransform: 'uppercase',
      letterSpacing: '0.05em',
    }}>
      <span style={{ width: 5, height: 5, borderRadius: '50%', background: s.color, flexShrink: 0 }} />
      {status}
    </span>
  );
};

// ── Severity Badge ────────────────────────────────────────────────────────────

const SEV_COLORS: Record<string, { bg: string; color: string }> = {
  low:      { bg: '#1e293b', color: '#94a3b8' },
  medium:   { bg: '#78350f', color: '#fbbf24' },
  high:     { bg: '#7c2d12', color: '#fb923c' },
  critical: { bg: '#450a0a', color: '#f87171' },
};

export const SeverityBadge: React.FC<{ severity: string }> = ({ severity }) => {
  const s = SEV_COLORS[severity.toLowerCase()] ?? SEV_COLORS.low;
  return (
    <span style={{
      display: 'inline-block',
      background: s.bg, color: s.color,
      border: `1px solid ${s.color}44`,
      borderRadius: 4, padding: '2px 7px',
      fontSize: 10, fontWeight: 700,
      textTransform: 'uppercase', letterSpacing: '0.05em',
    }}>
      {severity}
    </span>
  );
};

// ── Action Button ─────────────────────────────────────────────────────────────

interface ActionBtnProps {
  label: string;
  onClick: () => void;
  variant?: 'primary' | 'danger' | 'ghost' | 'warning' | 'success';
  disabled?: boolean;
  loading?: boolean;
  icon?: string;
  size?: 'sm' | 'md';
  style?: React.CSSProperties;
  accent?: string;
}

const BTN_VARIANTS = {
  primary: { bg: '#1e3a5f', color: '#60a5fa', border: '#1d4ed8' },
  danger:  { bg: '#450a0a', color: '#f87171', border: '#dc2626' },
  ghost:   { bg: 'transparent', color: '#94a3b8', border: '#334155' },
  warning: { bg: '#78350f', color: '#fbbf24', border: '#d97706' },
  success: { bg: '#052e16', color: '#4ade80', border: '#16a34a' },
};

export const ActionBtn: React.FC<ActionBtnProps> = ({
  label, onClick, variant = 'ghost', disabled, loading, icon, size = 'md', style,
}) => {
  const v = BTN_VARIANTS[variant];
  return (
    <button
      onClick={onClick}
      disabled={disabled || loading}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 6,
        background: v.bg, color: v.color,
        border: `1px solid ${v.border}`,
        borderRadius: 7, cursor: disabled || loading ? 'not-allowed' : 'pointer',
        fontSize: size === 'sm' ? 12 : 13, fontWeight: 600,
        padding: size === 'sm' ? '5px 12px' : '8px 16px',
        opacity: disabled ? 0.5 : 1,
        transition: 'opacity 0.15s',
        whiteSpace: 'nowrap',
        ...style,
      }}
    >
      {loading ? <Spinner size={12} /> : icon ? <span>{icon}</span> : null}
      {label}
    </button>
  );
};

// ── Spinner ───────────────────────────────────────────────────────────────────

export const Spinner: React.FC<{ size?: number; color?: string }> = ({ size = 16, color = '#60a5fa' }) => (
  <div style={{
    width: size, height: size,
    border: `2px solid ${color}33`,
    borderTopColor: color,
    borderRadius: '50%',
    animation: 'sa-spin 0.7s linear infinite',
    flexShrink: 0,
  }} />
);

// ── Input ─────────────────────────────────────────────────────────────────────

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
}

export const Input: React.FC<InputProps> = ({ label, style, ...rest }) => (
  <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
    {label && <label style={{ fontSize: 12, color: '#94a3b8', fontWeight: 500 }}>{label}</label>}
    <input
      {...rest}
      style={{
        background: '#1e293b', border: '1px solid #334155', borderRadius: 7,
        color: '#f1f5f9', fontSize: 13, padding: '8px 12px',
        outline: 'none', width: '100%', boxSizing: 'border-box',
        ...style,
      }}
    />
  </div>
);

// ── Select ────────────────────────────────────────────────────────────────────

interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  options: { value: string; label: string }[];
}

export const Select: React.FC<SelectProps> = ({ label, options, style, ...rest }) => (
  <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
    {label && <label style={{ fontSize: 12, color: '#94a3b8', fontWeight: 500 }}>{label}</label>}
    <select
      {...rest}
      style={{
        background: '#1e293b', border: '1px solid #334155', borderRadius: 7,
        color: '#f1f5f9', fontSize: 13, padding: '8px 12px',
        outline: 'none', width: '100%', boxSizing: 'border-box',
        cursor: 'pointer',
        ...style,
      }}
    >
      {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  </div>
);

// ── Toggle ────────────────────────────────────────────────────────────────────

interface ToggleProps {
  label?: string;
  description?: string;
  checked: boolean;
  onChange: (v: boolean) => void | Promise<void>;
  disabled?: boolean;
  accent?: string;
}

export const Toggle: React.FC<ToggleProps> = ({ label, description, checked, onChange, disabled, accent = '#22c55e' }) => (
  <label style={{
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    padding: '10px 0', cursor: disabled ? 'not-allowed' : 'pointer',
    userSelect: 'none', opacity: disabled ? 0.5 : 1,
  }}>
    <div>
      <div style={{ fontSize: 13, color: '#e2e8f0', fontWeight: 500 }}>{label}</div>
      {description && <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>{description}</div>}
    </div>
    <div
      role="switch"
      aria-checked={checked}
      tabIndex={disabled ? -1 : 0}
      onClick={() => !disabled && onChange(!checked)}
      onKeyDown={e => !disabled && (e.key === 'Enter' || e.key === ' ') && onChange(!checked)}
      style={{
        width: 44, height: 24, borderRadius: 12, flexShrink: 0, marginLeft: 16,
        background: checked ? accent : '#374151',
        position: 'relative', cursor: disabled ? 'not-allowed' : 'pointer',
        transition: 'background 0.2s',
      }}
    >
      <div style={{
        position: 'absolute', top: 2, width: 20, height: 20, borderRadius: '50%',
        background: '#fff', transition: 'transform 0.2s',
        transform: checked ? 'translateX(20px)' : 'translateX(2px)',
        boxShadow: '0 1px 3px rgba(0,0,0,0.4)',
      }} />
    </div>
  </label>
);

// ── Divider ───────────────────────────────────────────────────────────────────

export const Divider: React.FC = () => (
  <div style={{ height: 1, background: '#1e293b', margin: '8px 0' }} />
);

// ── Empty State ───────────────────────────────────────────────────────────────

export const EmptyState: React.FC<{ icon?: string; message: string }> = ({ icon = '📭', message }) => (
  <div style={{ textAlign: 'center', padding: '40px 20px', color: '#475569' }}>
    <div style={{ fontSize: 32, marginBottom: 10 }}>{icon}</div>
    <div style={{ fontSize: 13 }}>{message}</div>
  </div>
);

// ── Error State ───────────────────────────────────────────────────────────────

export const ErrorState: React.FC<{ message: string; onRetry?: () => void }> = ({ message, onRetry }) => (
  <div style={{ textAlign: 'center', padding: '32px 20px' }}>
    <div style={{ fontSize: 28, marginBottom: 8 }}>⚠️</div>
    <div style={{ fontSize: 13, color: '#f87171', marginBottom: onRetry ? 16 : 0 }}>{message}</div>
    {onRetry && (
      <button onClick={onRetry} style={{
        background: '#1e293b', border: '1px solid #334155', borderRadius: 7,
        color: '#94a3b8', cursor: 'pointer', fontSize: 12, padding: '6px 14px',
      }}>
        Retry
      </button>
    )}
  </div>
);

// ── Loading Rows ──────────────────────────────────────────────────────────────

export const LoadingRows: React.FC<{ rows?: number }> = ({ rows = 5 }) => (
  <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
    {Array.from({ length: rows }).map((_, i) => (
      <div key={i} style={{
        height: 40, borderRadius: 6, background: '#1e293b',
        animation: 'sa-pulse 1.5s ease-in-out infinite',
        animationDelay: `${i * 0.1}s`,
        opacity: 1 - i * 0.1,
      }} />
    ))}
  </div>
);

// ── Confirm Dialog ────────────────────────────────────────────────────────────

interface ConfirmDialogProps {
  title: string;
  message: string;
  confirmLabel?: string;
  variant?: 'danger' | 'warning';
  /** @deprecated Use variant="danger" instead. Kept for backwards compat. */
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export const ConfirmDialog: React.FC<ConfirmDialogProps> = ({
  title, message, confirmLabel = 'Confirm', variant, danger, onConfirm, onCancel,
}) => {
  // variant takes precedence; danger=false downgrades to 'warning' for backwards compat
  const resolvedVariant: 'danger' | 'warning' =
    variant ?? (danger === false ? 'warning' : 'danger');
  return (
  <div style={{
    position: 'fixed', inset: 0, zIndex: 9999,
    background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
  }}>
    <div style={{
      background: '#0f172a', border: `1px solid ${resolvedVariant === 'danger' ? '#7f1d1d' : '#92400e'}`,
      borderRadius: 14, padding: '28px 32px', maxWidth: 420, width: '90%',
    }}>
      <div style={{ fontSize: 16, fontWeight: 700, color: '#f8fafc', marginBottom: 10 }}>{title}</div>
      <div style={{ fontSize: 13, color: '#94a3b8', lineHeight: 1.6, marginBottom: 24 }}>{message}</div>
      <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
        <ActionBtn label="Cancel" onClick={onCancel} variant="ghost" />
        <ActionBtn label={confirmLabel} onClick={onConfirm} variant={resolvedVariant === 'danger' ? 'danger' : 'warning'} />
      </div>
    </div>
  </div>
  );
};

// ── Global keyframes (injected once) ─────────────────────────────────────────

export const SAStyles: React.FC = () => (
  <style>{`
    @keyframes sa-spin { to { transform: rotate(360deg); } }
    @keyframes sa-pulse {
      0%, 100% { opacity: 0.6; }
      50% { opacity: 0.3; }
    }
    @keyframes sa-fadein {
      from { opacity: 0; transform: translateY(6px); }
      to   { opacity: 1; transform: translateY(0); }
    }
    .sa-row:hover { background: #0f1f35 !important; }
    .sa-tab-btn:hover { background: #1e293b !important; }
  `}</style>
);
