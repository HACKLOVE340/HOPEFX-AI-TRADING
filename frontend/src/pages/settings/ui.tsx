// settings/ui.tsx — shared UI primitives used across all settings sections
import React from 'react';
import { AlertTriangle, Check } from 'lucide-react';

// ── Toggle ────────────────────────────────────────────────────────────────────

interface ToggleProps {
  id: string;
  label: string;
  description?: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}

/**
 * The switch had no accessible name.
 *
 * `<label htmlFor={id}>` pointed at a `<div role="switch">`, and a `<label>`
 * only labels a *labellable* element — a form control. A div is not one, so the
 * association was silently dropped: assistive technology announced "switch,
 * checked" with no indication of WHICH setting, on every toggle across every
 * settings page, including the ones that enable live trading. It is also
 * invalid HTML, which is how the defect stayed invisible — nothing errors.
 *
 * `aria-labelledby` is the association that works on a non-labellable element.
 * The wrapper keeps the whole row clickable (a 24px switch alone is under the
 * 44px target rule), and the click handler now lives ONLY on the wrapper: with
 * one on each, a click on the switch fired twice and toggled back.
 */
export const Toggle: React.FC<ToggleProps> = ({ id, label, description, checked, onChange, disabled }) => (
  <div
    onClick={() => !disabled && onChange(!checked)}
    style={{
      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      padding: '10px 0', cursor: disabled ? 'not-allowed' : 'pointer',
      userSelect: 'none', opacity: disabled ? 0.5 : 1,
    }}
  >
    <div>
      <div id={`${id}-label`} style={{ fontSize: 14, color: 'var(--text)', fontWeight: 500 }}>{label}</div>
      {description && (
        <div id={`${id}-desc`} style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>{description}</div>
      )}
    </div>
    <div
      id={id}
      role="switch"
      aria-checked={checked}
      aria-labelledby={`${id}-label`}
      aria-describedby={description ? `${id}-desc` : undefined}
      aria-disabled={disabled || undefined}
      tabIndex={disabled ? -1 : 0}
      onKeyDown={(e) => {
        if (disabled || (e.key !== 'Enter' && e.key !== ' ')) return;
        // Space scrolls the page by default; a switch that also jumps the view
        // is a switch a keyboard user loses track of.
        e.preventDefault();
        onChange(!checked);
      }}
      // The switch is keyboard-operable but had no visible focus indicator,
      // so a keyboard user could not see which toggle they were on
      // (rubric: focus-states, HIGH).
      className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500
                 focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--surface)]"
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
  </div>
);

// ── Field ─────────────────────────────────────────────────────────────────────

interface FieldProps {
  label: string;
  description?: string;
  children: React.ReactNode;
}

/**
 * The label WRAPS the control, rather than sitting beside it.
 *
 * It used to render `<label>Protected Paths</label>` and then the control as a
 * sibling, with no `for` and no id — so across the 60-odd places this is used,
 * the settings pages showed a label and the control had no name at all. A
 * screen reader reached each field as an unlabelled text box; clicking the
 * label did nothing.
 *
 * Wrapping is the fix that needs no ids anywhere: the enclosing <label> is the
 * accessible name of the first labelable control inside it, so every existing
 * call site is corrected without touching one of them, and there is no second
 * copy of the text to drift from what is on screen (WCAG 2.5.3).
 *
 * The inner elements are <span display:block> rather than <p>/<div> because a
 * <label> takes phrasing content — a <p> nested in a label is invalid and
 * parsers may close the label early, which would undo the association.
 */
export const Field: React.FC<FieldProps> = ({ label, description, children }) => (
  <label style={{ display: 'block', marginBottom: 20 }}>
    <span style={{ display: 'block', fontSize: 13, fontWeight: 600, color: 'var(--text-dim)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
      {label}
    </span>
    {description && <span style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginBottom: 8, marginTop: 0 }}>{description}</span>}
    {children}
  </label>
);

// ── Input ─────────────────────────────────────────────────────────────────────

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  /** Lucide element preferred; a string is a legacy glyph call site (F170). */
  icon?: React.ReactNode;
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
        background: 'var(--surface)', border: '1px solid var(--border-strong)', borderRadius: 8,
        color: 'var(--text-strong)', fontSize: 14, boxSizing: 'border-box', outline: 'none',
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
      background: 'var(--surface)', border: '1px solid var(--border-strong)', borderRadius: 8,
      color: 'var(--text-strong)', fontSize: 14, boxSizing: 'border-box', outline: 'none',
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
    background: 'var(--raised)',
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
  /** Long-form description shown below the title. */
  description?: string;
  /** Alias for `description` — accepted for backwards compatibility. */
  desc?: string;
  /** Lucide element preferred; a string is a legacy glyph call site (F170). */
  icon?: React.ReactNode;
}

export const SectionHeader: React.FC<SectionHeaderProps> = ({ title, description, desc, icon }) => {
  const subtitle = description ?? desc;
  return (
    <div style={{ marginBottom: 24 }}>
      <h2 style={{ fontSize: 20, fontWeight: 700, color: 'var(--text-strong)', margin: 0, display: 'flex', alignItems: 'center', gap: 10 }}>
        {icon && <span style={{ fontSize: 22 }}>{icon}</span>}
        {title}
      </h2>
      {subtitle && <p style={{ fontSize: 14, color: 'var(--text-muted)', marginTop: 6, marginBottom: 0 }}>{subtitle}</p>}
    </div>
  );
};

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
  // 44px minimum target (rubric: touch-target-size, CRITICAL). `sm` was
  // ~26px tall — and this kit renders the buttons that delete accounts, revoke
  // API keys and change broker credentials.
  const padding = size === 'sm' ? '0 14px' : size === 'lg' ? '0 32px' : '0 20px';
  const fontSize = size === 'sm' ? 12 : size === 'lg' ? 16 : 14;

  return (
    <button
      {...props}
      disabled={disabled || loading}
      className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500
                 focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg)]"
      style={{
        padding, fontSize, fontWeight: 600, background: bg, border,
        minHeight: size === 'lg' ? 52 : 44,
        borderRadius: 8, color: '#fff', cursor: disabled || loading ? 'not-allowed' : 'pointer',
        opacity: disabled || loading ? 0.6 : 1, transition: 'opacity 0.15s, transform 0.1s',
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 6,
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
  <hr style={{ border: 'none', borderTop: '1px solid var(--border)', margin: '16px 0' }} />
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
    gap: 12, marginTop: 24, paddingTop: 20, borderTop: '1px solid var(--border)',
  }}>
    {error && (
      <span role="alert" style={{ fontSize: 13, color: 'var(--warn)', display: 'inline-flex', alignItems: 'center', gap: 6 }}>
        <AlertTriangle size={14} strokeWidth={2} aria-hidden /> {error}
      </span>
    )}
    {saved && !saving && (
      <span role="status" style={{ fontSize: 13, color: '#22c55e', display: 'inline-flex', alignItems: 'center', gap: 6 }}>
        <Check size={14} strokeWidth={2.5} aria-hidden /> Saved
      </span>
    )}
    <Button onClick={onSave} loading={saving} variant="primary">
      {saved && !saving ? 'Saved' : 'Save changes'}
    </Button>
  </div>
);
