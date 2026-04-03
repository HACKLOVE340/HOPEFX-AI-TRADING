// settings/ui.tsx — shared UI primitives used across all settings sections
import React from 'react';

// ── Toggle ────────────────────────────────────────────────────────────────────

interface ToggleProps {
  id: string;
  label: string;
  description?: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}

export const Toggle: React.FC<ToggleProps> = ({ id, label, description, checked, onChange, disabled }) => (
  <label
    htmlFor={id}
    style={{
      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      padding: '10px 0', cursor: disabled ? 'not-allowed' : 'pointer',
      userSelect: 'none', opacity: disabled ? 0.5 : 1,
    }}
  >
    <div>
      <div style={{ fontSize: 14, color: '#e2e8f0', fontWeight: 500 }}>{label}</div>
      {description && <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>{description}</div>}
    </div>
    <div
      id={id}
      role="switch"
      aria-checked={checked}
      tabIndex={disabled ? -1 : 0}
      onClick={() => !disabled && onChange(!checked)}
      onKeyDown={(e) => !disabled && (e.key === 'Enter' || e.key === ' ') && onChange(!checked)}
      style={{
        width: 44, height: 24, borderRadius: 12, flexShrink: 0, marginLeft: 16,
        background: checked ? '#22c55e' : '#374151',
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

// ── Field ─────────────────────────────────────────────────────────────────────

interface FieldProps {
  label: string;
  description?: string;
  children: React.ReactNode;
}

export const Field: React.FC<FieldProps> = ({ label, description, children }) => (
  <div style={{ marginBottom: 20 }}>
    <label style={{ display: 'block', fontSize: 13, fontWeight: 600, color: '#94a3b8', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
      {label}
    </label>
    {description && <p style={{ fontSize: 12, color: '#64748b', marginBottom: 8, marginTop: 0 }}>{description}</p>}
    {children}
  </div>
);

// ── Input ─────────────────────────────────────────────────────────────────────

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  icon?: string;
}

export const Input: React.FC<InputProps> = ({ icon, style, ...props }) => (
  <div style={{ position: 'relative' }}>
    {icon && (
      <span style={{
        position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)',
        fontSize: 14, pointerEvents: 'none',
      }}>{icon}</span>
    )}
    <input
      {...props}
      style={{
        width: '100%', padding: icon ? '10px 12px 10px 36px' : '10px 12px',
        background: '#0f172a', border: '1px solid #334155', borderRadius: 8,
        color: '#f1f5f9', fontSize: 14, boxSizing: 'border-box', outline: 'none',
        transition: 'border-color 0.15s',
        ...style,
      }}
      onFocus={(e) => { e.currentTarget.style.borderColor = '#3b82f6'; props.onFocus?.(e); }}
      onBlur={(e) => { e.currentTarget.style.borderColor = '#334155'; props.onBlur?.(e); }}
    />
  </div>
);

// ── Select ────────────────────────────────────────────────────────────────────

interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  options: { value: string; label: string }[];
}

export const Select: React.FC<SelectProps> = ({ options, style, ...props }) => (
  <select
    {...props}
    style={{
      width: '100%', padding: '10px 12px',
      background: '#0f172a', border: '1px solid #334155', borderRadius: 8,
      color: '#f1f5f9', fontSize: 14, boxSizing: 'border-box', outline: 'none',
      cursor: 'pointer', appearance: 'none',
      backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%2394a3b8' d='M6 8L1 3h10z'/%3E%3C/svg%3E")`,
      backgroundRepeat: 'no-repeat', backgroundPosition: 'right 12px center',
      ...style,
    }}
  >
    {options.map((o) => (
      <option key={o.value} value={o.value}>{o.label}</option>
    ))}
  </select>
);

// ── Card ──────────────────────────────────────────────────────────────────────

interface CardProps {
  children: React.ReactNode;
  style?: React.CSSProperties;
  danger?: boolean;
}

export const Card: React.FC<CardProps> = ({ children, style, danger }) => (
  <div style={{
    background: '#1e293b',
    border: `1px solid ${danger ? '#7f1d1d' : '#334155'}`,
    borderRadius: 12, padding: '20px 24px', marginBottom: 16,
    ...style,
  }}>
    {children}
  </div>
);

// ── SectionHeader ─────────────────────────────────────────────────────────────

interface SectionHeaderProps {
  title: string;
  description?: string;
  icon?: string;
}

export const SectionHeader: React.FC<SectionHeaderProps> = ({ title, description, icon }) => (
  <div style={{ marginBottom: 24 }}>
    <h2 style={{ fontSize: 20, fontWeight: 700, color: '#f8fafc', margin: 0, display: 'flex', alignItems: 'center', gap: 10 }}>
      {icon && <span style={{ fontSize: 22 }}>{icon}</span>}
      {title}
    </h2>
    {description && <p style={{ fontSize: 14, color: '#64748b', marginTop: 6, marginBottom: 0 }}>{description}</p>}
  </div>
);

// ── Button ────────────────────────────────────────────────────────────────────

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost';
  size?: 'sm' | 'md' | 'lg';
  loading?: boolean;
}

export const Button: React.FC<ButtonProps> = ({
  variant = 'primary', size = 'md', loading, children, style, disabled, ...props
}) => {
  const bg = variant === 'primary' ? '#3b82f6'
    : variant === 'danger' ? '#dc2626'
    : variant === 'secondary' ? '#1e293b'
    : 'transparent';
  const border = variant === 'secondary' ? '1px solid #334155'
    : variant === 'ghost' ? '1px solid transparent'
    : 'none';
  const padding = size === 'sm' ? '6px 14px' : size === 'lg' ? '14px 32px' : '10px 20px';
  const fontSize = size === 'sm' ? 12 : size === 'lg' ? 16 : 14;

  return (
    <button
      {...props}
      disabled={disabled || loading}
      style={{
        padding, fontSize, fontWeight: 600, background: bg, border,
        borderRadius: 8, color: '#fff', cursor: disabled || loading ? 'not-allowed' : 'pointer',
        opacity: disabled || loading ? 0.6 : 1, transition: 'opacity 0.15s, transform 0.1s',
        display: 'inline-flex', alignItems: 'center', gap: 6,
        ...style,
      }}
    >
      {loading && (
        <span style={{
          width: 14, height: 14, border: '2px solid rgba(255,255,255,0.3)',
          borderTopColor: '#fff', borderRadius: '50%',
          animation: 'spin 0.7s linear infinite', flexShrink: 0,
        }} />
      )}
      {children}
    </button>
  );
};

// ── StatusBadge ───────────────────────────────────────────────────────────────

interface StatusBadgeProps {
  status: 'ok' | 'error' | 'warning' | 'info';
  label: string;
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({ status, label }) => {
  const colors = {
    ok:      { bg: '#052e16', border: '#166534', text: '#22c55e' },
    error:   { bg: '#450a0a', border: '#7f1d1d', text: '#f87171' },
    warning: { bg: '#451a03', border: '#78350f', text: '#fbbf24' },
    info:    { bg: '#0c1a2e', border: '#1e3a5f', text: '#60a5fa' },
  }[status];
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5,
      padding: '3px 10px', borderRadius: 20, fontSize: 12, fontWeight: 600,
      background: colors.bg, border: `1px solid ${colors.border}`, color: colors.text,
    }}>
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: colors.text }} />
      {label}
    </span>
  );
};

// ── Divider ───────────────────────────────────────────────────────────────────

export const Divider: React.FC = () => (
  <hr style={{ border: 'none', borderTop: '1px solid #1e293b', margin: '16px 0' }} />
);

// ── SaveBar ───────────────────────────────────────────────────────────────────

interface SaveBarProps {
  onSave: () => void;
  saving: boolean;
  saved: boolean;
  error: string;
}

export const SaveBar: React.FC<SaveBarProps> = ({ onSave, saving, saved, error }) => (
  <div style={{
    display: 'flex', alignItems: 'center', justifyContent: 'flex-end',
    gap: 12, marginTop: 24, paddingTop: 20, borderTop: '1px solid #1e293b',
  }}>
    {error && <span style={{ fontSize: 13, color: '#fbbf24' }}>⚠️ {error}</span>}
    {saved && !saving && <span style={{ fontSize: 13, color: '#22c55e' }}>✅ Saved</span>}
    <Button onClick={onSave} loading={saving} variant="primary">
      {saved && !saving ? 'Saved' : 'Save changes'}
    </Button>
  </div>
);
