// settings/AppearanceSection.tsx — Theme, accent color, chart style, display prefs
import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../../hooks/useApi';
import type { AppearanceSettings } from './types';
import { ACCENT_COLORS } from './types';
import { Card, SectionHeader, Field, Select, Toggle, SaveBar } from './ui';
import { extractApiError } from '../../lib/utils';

const DEFAULT: AppearanceSettings = {
  theme: 'dark',
  accent_color: '#3b82f6',
  chart_style: 'candles',
  compact_sidebar: false,
  show_pnl_in_header: true,
  number_format: 'standard',
  currency_display: 'USD',
};

const STORAGE_KEY = 'hopefx_appearance';

function applyTheme(theme: AppearanceSettings['theme'], accent: string) {
  const root = document.documentElement;
  const isDark = theme === 'dark' || (theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);
  root.style.setProperty('--bg', isDark ? '#0f172a' : '#f8fafc');
  root.style.setProperty('--surface', isDark ? '#1e293b' : '#ffffff');
  root.style.setProperty('--text', isDark ? '#f1f5f9' : '#0f172a');
  root.style.setProperty('--accent', accent);
  root.setAttribute('data-theme', isDark ? 'dark' : 'light');
}

const AppearanceSection: React.FC = () => {
  const [form, setForm] = useState<AppearanceSettings>(() => {
    try {
      const cached = localStorage.getItem(STORAGE_KEY);
      if (cached) return { ...DEFAULT, ...JSON.parse(cached) };
    } catch { /* ignore */ }
    return DEFAULT;
  });
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    api.get<AppearanceSettings>('/settings/appearance')
      .then((r) => {
        const merged = { ...DEFAULT, ...r.data };
        setForm(merged);
        applyTheme(merged.theme, merged.accent_color);
      })
      .catch(() => {
        // Use cached/default — non-fatal
        applyTheme(form.theme, form.accent_color);
      });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const update = useCallback((patch: Partial<AppearanceSettings>) => {
    setForm((prev) => {
      const next = { ...prev, ...patch };
      applyTheme(next.theme, next.accent_color);
      return next;
    });
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setError('');
    try {
      await api.post('/settings/appearance', form);
      localStorage.setItem(STORAGE_KEY, JSON.stringify(form));
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (err: unknown) {
      setError(extractApiError(err, 'Failed to save appearance settings.'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <SectionHeader icon="🎨" title="Appearance" description="Theme, colors, and display preferences." />

      {/* Theme */}
      <Card>
        <h3 style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginTop: 0, marginBottom: 16 }}>Theme</h3>
        <div style={{ display: 'flex', gap: 12, marginBottom: 20 }}>
          {(['dark', 'light', 'system'] as const).map((t) => (
            <button
              key={t}
              onClick={() => update({ theme: t })}
              style={{
                flex: 1, padding: '14px 8px', borderRadius: 10, cursor: 'pointer',
                border: `2px solid ${form.theme === t ? '#3b82f6' : '#334155'}`,
                background: form.theme === t ? '#0c1a2e' : '#0f172a',
                color: form.theme === t ? '#60a5fa' : '#64748b',
                fontSize: 13, fontWeight: 600, transition: 'all 0.15s',
                display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6,
              }}
            >
              <span style={{ fontSize: 22 }}>
                {t === 'dark' ? '🌙' : t === 'light' ? '☀️' : '💻'}
              </span>
              {t.charAt(0).toUpperCase() + t.slice(1)}
            </button>
          ))}
        </div>

        <Field label="Accent color">
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            {ACCENT_COLORS.map((color) => (
              <button
                key={color}
                onClick={() => update({ accent_color: color })}
                title={color}
                style={{
                  width: 36, height: 36, borderRadius: '50%', background: color,
                  border: `3px solid ${form.accent_color === color ? '#fff' : 'transparent'}`,
                  cursor: 'pointer', transition: 'transform 0.15s',
                  transform: form.accent_color === color ? 'scale(1.2)' : 'scale(1)',
                  outline: 'none',
                }}
              />
            ))}
            <input
              type="color"
              value={form.accent_color}
              onChange={(e) => update({ accent_color: e.target.value })}
              title="Custom color"
              style={{
                width: 36, height: 36, borderRadius: '50%', border: '2px solid #334155',
                cursor: 'pointer', background: 'transparent', padding: 0,
              }}
            />
          </div>
        </Field>
      </Card>

      {/* Charts */}
      <Card>
        <h3 style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginTop: 0, marginBottom: 16 }}>Charts</h3>
        <Field label="Default chart style">
          <Select
            value={form.chart_style}
            onChange={(e) => update({ chart_style: e.target.value as AppearanceSettings['chart_style'] })}
            options={[
              { value: 'candles', label: '🕯️ Candlestick' },
              { value: 'bars',    label: '📊 OHLC Bars' },
              { value: 'line',    label: '📈 Line' },
              { value: 'area',    label: '🏔️ Area' },
            ]}
          />
        </Field>
      </Card>

      {/* Display */}
      <Card>
        <h3 style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginTop: 0, marginBottom: 8 }}>Display</h3>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
          <Field label="Number format">
            <Select
              value={form.number_format}
              onChange={(e) => update({ number_format: e.target.value as AppearanceSettings['number_format'] })}
              options={[
                { value: 'standard', label: '1,234,567.89' },
                { value: 'compact',  label: '1.23M' },
              ]}
            />
          </Field>
          <Field label="Currency display">
            <Select
              value={form.currency_display}
              onChange={(e) => update({ currency_display: e.target.value as AppearanceSettings['currency_display'] })}
              options={[
                { value: 'USD', label: '$ USD' },
                { value: 'EUR', label: '€ EUR' },
                { value: 'GBP', label: '£ GBP' },
              ]}
            />
          </Field>
        </div>
        <Toggle
          id="compact-sidebar"
          label="Compact sidebar"
          description="Show icons only in the navigation sidebar."
          checked={form.compact_sidebar}
          onChange={(v) => update({ compact_sidebar: v })}
        />
        <Toggle
          id="pnl-header"
          label="Show P&L in header"
          description="Display live unrealized P&L in the top navigation bar."
          checked={form.show_pnl_in_header}
          onChange={(v) => update({ show_pnl_in_header: v })}
        />
      </Card>

      <SaveBar onSave={handleSave} saving={saving} saved={saved} error={error} />
    </div>
  );
};

export default AppearanceSection;
