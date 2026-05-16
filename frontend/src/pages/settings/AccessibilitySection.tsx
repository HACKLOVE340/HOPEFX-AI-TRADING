// settings/AccessibilitySection.tsx — Motion, contrast, font size, color-blind modes
import React, { useState, useEffect, useCallback } from 'react';
import { api } from '../../hooks/useApi';
import type { AccessibilitySettings } from './types';
import { Card, SectionHeader, Field, Select, Toggle, SaveBar } from './ui';
import { extractApiError } from '../../lib/utils';

const DEFAULT: AccessibilitySettings = {
  reduce_motion: false,
  high_contrast: false,
  large_text: false,
  keyboard_shortcuts: true,
  screen_reader_hints: false,
  color_blind_mode: 'none',
  font_size: 'medium',
};

const STORAGE_KEY = 'hopefx_accessibility';

function applyAccessibility(s: AccessibilitySettings) {
  const root = document.documentElement;
  root.style.setProperty('--font-scale', s.font_size === 'small' ? '0.875' : s.font_size === 'large' ? '1.125' : s.font_size === 'xlarge' ? '1.25' : '1');
  root.setAttribute('data-reduce-motion', String(s.reduce_motion));
  root.setAttribute('data-high-contrast', String(s.high_contrast));
  root.setAttribute('data-color-blind', s.color_blind_mode);
}

const AccessibilitySection: React.FC = () => {
  const [form, setForm] = useState<AccessibilitySettings>(() => {
    try {
      const cached = localStorage.getItem(STORAGE_KEY);
      if (cached) return { ...DEFAULT, ...JSON.parse(cached) as AccessibilitySettings };
    } catch { /* ignore */ }
    return DEFAULT;
  });
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');

  // Apply on mount and on change
  useEffect(() => { applyAccessibility(form); }, [form]);

  const update = useCallback((patch: Partial<AccessibilitySettings>) =>
    setForm((prev) => ({ ...prev, ...patch })), []);

  const handleSave = async () => {
    setSaving(true); setError('');
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(form));
      await api.post('/settings/accessibility', form).catch(() => {/* non-fatal */});
      applyAccessibility(form);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (err: unknown) {
      setError(extractApiError(err, 'Failed to save accessibility settings.'));
    } finally { setSaving(false); }
  };

  return (
    <div>
      <SectionHeader icon="♿" title="Accessibility" description="Adjust the interface to suit your needs." />

      {/* Motion & display */}
      <Card>
        <h3 style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginTop: 0, marginBottom: 4 }}>Motion & Display</h3>
        <Toggle id="reduce-motion" label="Reduce motion" description="Disable animations and transitions throughout the app." checked={form.reduce_motion} onChange={(v) => update({ reduce_motion: v })} />
        <Toggle id="high-contrast" label="High contrast" description="Increase border and text contrast for better readability." checked={form.high_contrast} onChange={(v) => update({ high_contrast: v })} />
        <Toggle id="large-text" label="Large text" description="Increase base font size across the dashboard." checked={form.large_text} onChange={(v) => update({ large_text: v, font_size: v ? 'large' : 'medium' })} />
      </Card>

      {/* Font size */}
      <Card>
        <h3 style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginTop: 0, marginBottom: 14 }}>Font Size</h3>
        <Field label="Base font size">
          <Select
            value={form.font_size}
            onChange={(e) => update({ font_size: e.target.value as AccessibilitySettings['font_size'] })}
            options={[
              { value: 'small',  label: 'Small (87.5%)' },
              { value: 'medium', label: 'Medium (100%) — default' },
              { value: 'large',  label: 'Large (112.5%)' },
              { value: 'xlarge', label: 'Extra large (125%)' },
            ]}
          />
        </Field>
        <div style={{
          marginTop: 12, padding: '12px 16px', background: '#0f172a',
          borderRadius: 8, border: '1px solid #1e293b',
          fontSize: `calc(14px * ${form.font_size === 'small' ? 0.875 : form.font_size === 'large' ? 1.125 : form.font_size === 'xlarge' ? 1.25 : 1})`,
          color: '#94a3b8',
        }}>
          Preview: The quick brown fox jumps over the lazy dog.
        </div>
      </Card>

      {/* Color blind */}
      <Card>
        <h3 style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginTop: 0, marginBottom: 14 }}>Color Vision</h3>
        <Field label="Color blind mode" description="Adjusts chart and P&L colors for different types of color vision deficiency.">
          <Select
            value={form.color_blind_mode}
            onChange={(e) => update({ color_blind_mode: e.target.value as AccessibilitySettings['color_blind_mode'] })}
            options={[
              { value: 'none',         label: 'None — standard colors' },
              { value: 'deuteranopia', label: 'Deuteranopia (red-green, most common)' },
              { value: 'protanopia',   label: 'Protanopia (red-green, less common)' },
              { value: 'tritanopia',   label: 'Tritanopia (blue-yellow)' },
            ]}
          />
        </Field>
        {/* Color preview swatches */}
        <div style={{ display: 'flex', gap: 10, marginTop: 8 }}>
          {[
            { label: 'Profit', color: form.color_blind_mode === 'none' ? '#22c55e' : form.color_blind_mode === 'deuteranopia' ? '#0077bb' : form.color_blind_mode === 'protanopia' ? '#0077bb' : '#009988' },
            { label: 'Loss',   color: form.color_blind_mode === 'none' ? '#f87171' : form.color_blind_mode === 'deuteranopia' ? '#ee7733' : form.color_blind_mode === 'protanopia' ? '#ee3377' : '#cc3311' },
            { label: 'Signal', color: form.color_blind_mode === 'none' ? '#3b82f6' : '#aa3377' },
          ].map(({ label, color }) => (
            <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <div style={{ width: 16, height: 16, borderRadius: 4, background: color }} />
              <span style={{ fontSize: 12, color: '#94a3b8' }}>{label}</span>
            </div>
          ))}
        </div>
      </Card>

      {/* Keyboard & screen reader */}
      <Card>
        <h3 style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginTop: 0, marginBottom: 4 }}>Input & Assistive Tech</h3>
        <Toggle id="keyboard" label="Keyboard shortcuts" description="Enable global keyboard shortcuts (press ? to see all)." checked={form.keyboard_shortcuts} onChange={(v) => update({ keyboard_shortcuts: v })} />
        <Toggle id="screen-reader" label="Screen reader hints" description="Add extra ARIA labels and descriptions for screen readers." checked={form.screen_reader_hints} onChange={(v) => update({ screen_reader_hints: v })} />
      </Card>

      <SaveBar onSave={handleSave} saving={saving} saved={saved} error={error} />
    </div>
  );
};

export default AccessibilitySection;
