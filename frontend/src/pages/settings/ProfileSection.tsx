// settings/ProfileSection.tsx — Profile & account identity settings
import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../../hooks/useApi';
import { useStore } from '../../store';
import type { ProfileSettings } from './types';
import { TIMEZONES, LANGUAGES } from './types';
import { Field, Input, Select, Toggle, Card, SectionHeader, SaveBar } from './ui';

const DEFAULT: ProfileSettings = {
  username: '', email: '', bio: '', avatar_url: '',
  website: '', is_public: true, timezone: 'UTC', language: 'en',
};

const ProfileSection: React.FC = () => {
  const navigate = useNavigate();
  const user = useStore((s) => s.user);
  const setAuth = useStore((s) => s.setAuth);
  const token = useStore((s) => s.token);

  const [form, setForm] = useState<ProfileSettings>(DEFAULT);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');
  const [avatarPreview, setAvatarPreview] = useState('');

  useEffect(() => {
    api.get<ProfileSettings>('/profiles/me')
      .then((r) => {
        const data = { ...DEFAULT, ...r.data };
        setForm(data);
        setAvatarPreview(data.avatar_url || '');
      })
      .catch((err: unknown) => {
        // Seed from store if API unavailable
        if (user) {
          setForm((prev) => ({ ...prev, username: user.username, email: user.email }));
        }
        console.warn('[Settings/Profile] load failed:', err);
      })
      .finally(() => setLoading(false));
  }, [user]);

  const update = useCallback((patch: Partial<ProfileSettings>) =>
    setForm((prev) => ({ ...prev, ...patch })), []);

  const handleSave = async () => {
    setSaving(true);
    setError('');
    try {
      await api.put('/profiles/me', {
        bio: form.bio,
        avatar_url: form.avatar_url,
        website: form.website,
        is_public: form.is_public,
      });
      // Persist timezone/language to user preferences endpoint
      await api.post('/settings/preferences', {
        timezone: form.timezone,
        language: form.language,
      }).catch(() => {/* non-fatal */});

      // Refresh user in store if username changed
      if (user && token) {
        const me = await api.get('/auth/me').catch(() => null);
        if (me?.data) setAuth(token, me.data);
      }

      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail ?? 'Failed to save profile.');
    } finally {
      setSaving(false);
    }
  };

  if (loading) return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: '#64748b', padding: 20 }}>
      <div style={{ width: 18, height: 18, border: '2px solid #334155', borderTopColor: '#3b82f6', borderRadius: '50%', animation: 'spin 0.7s linear infinite' }} />
      Loading profile…
    </div>
  );

  return (
    <div>
      <SectionHeader icon="👤" title="Profile" description="Your public identity and account preferences." />

      {/* Avatar */}
      <Card>
        <div style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
          <div style={{
            width: 72, height: 72, borderRadius: '50%', background: '#0f172a',
            border: '2px solid #334155', overflow: 'hidden', flexShrink: 0,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            {avatarPreview
              ? <img src={avatarPreview} alt="avatar" style={{ width: '100%', height: '100%', objectFit: 'cover' }} onError={() => setAvatarPreview('')} />
              : <span style={{ fontSize: 28, color: '#475569' }}>
                  {form.username ? form.username[0].toUpperCase() : '?'}
                </span>
            }
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: '#e2e8f0', marginBottom: 4 }}>
              {form.username || 'Your Name'}
            </div>
            <div style={{ fontSize: 12, color: '#64748b', marginBottom: 10 }}>{form.email}</div>
            <Input
              placeholder="https://example.com/avatar.jpg"
              value={form.avatar_url}
              onChange={(e) => { update({ avatar_url: e.target.value }); setAvatarPreview(e.target.value); }}
              style={{ fontSize: 12 }}
            />
          </div>
        </div>
      </Card>

      {/* Identity */}
      <Card>
        <Field label="Username">
          <Input
            value={form.username}
            onChange={(e) => update({ username: e.target.value })}
            placeholder="your_username"
            icon="@"
          />
        </Field>
        <Field label="Email address">
          <Input
            type="email"
            value={form.email}
            onChange={(e) => update({ email: e.target.value })}
            placeholder="you@example.com"
            icon="✉"
          />
        </Field>
        <Field label="Bio" description="Shown on your public profile (max 500 chars).">
          <textarea
            value={form.bio}
            onChange={(e) => update({ bio: e.target.value })}
            maxLength={500}
            rows={3}
            placeholder="Tell other traders about yourself…"
            style={{
              width: '100%', padding: '10px 12px', background: '#0f172a',
              border: '1px solid #334155', borderRadius: 8, color: '#f1f5f9',
              fontSize: 14, boxSizing: 'border-box', outline: 'none', resize: 'vertical',
              fontFamily: 'inherit',
            }}
          />
          <div style={{ textAlign: 'right', fontSize: 11, color: '#475569', marginTop: 4 }}>
            {form.bio.length}/500
          </div>
        </Field>
        <Field label="Website">
          <Input
            type="url"
            value={form.website}
            onChange={(e) => update({ website: e.target.value })}
            placeholder="https://yoursite.com"
            icon="🌐"
          />
        </Field>
      </Card>

      {/* Locale */}
      <Card>
        <Field label="Timezone" description="Used for calendar events and daily summaries.">
          <Select
            value={form.timezone}
            onChange={(e) => update({ timezone: e.target.value })}
            options={TIMEZONES.map((tz) => ({ value: tz, label: tz }))}
          />
        </Field>
        <Field label="Language">
          <Select
            value={form.language}
            onChange={(e) => update({ language: e.target.value })}
            options={LANGUAGES.map((l) => ({ value: l.code, label: l.label }))}
          />
        </Field>
        <Toggle
          id="profile-public"
          label="Public profile"
          description="Allow other traders to view your profile and signals."
          checked={form.is_public}
          onChange={(v) => update({ is_public: v })}
        />
      </Card>

      <SaveBar onSave={handleSave} saving={saving} saved={saved} error={error} />

      {/* Quick actions */}
      <Card>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: '#64748b', letterSpacing: 1, textTransform: 'uppercase' }}>
            Quick Actions
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
            <button
              onClick={() => navigate('/profile')}
              style={{
                padding: '8px 16px', borderRadius: 8,
                background: 'rgba(59,130,246,0.1)', border: '1px solid rgba(59,130,246,0.3)',
                color: '#60a5fa', fontSize: 13, cursor: 'pointer',
                display: 'inline-flex', alignItems: 'center', gap: 6,
                fontFamily: 'inherit',
              }}
            >
              👁 View Public Profile
            </button>
            <button
              onClick={() => {
                localStorage.removeItem('hopefx_onboarding_complete');
                navigate('/onboarding');
              }}
              style={{
                padding: '8px 16px', borderRadius: 8,
                background: 'rgba(139,92,246,0.1)', border: '1px solid rgba(139,92,246,0.3)',
                color: '#a78bfa', fontSize: 13, cursor: 'pointer',
                display: 'inline-flex', alignItems: 'center', gap: 6,
              }}
            >
              🚀 Restart Onboarding
            </button>
            <a
              href="/docs"
              style={{
                padding: '8px 16px', borderRadius: 8,
                background: 'rgba(16,185,129,0.1)', border: '1px solid rgba(16,185,129,0.3)',
                color: '#34d399', fontSize: 13, textDecoration: 'none',
                display: 'inline-flex', alignItems: 'center', gap: 6,
              }}
            >
              📚 Documentation
            </a>
          </div>
        </div>
      </Card>
    </div>
  );
};

export default ProfileSection;
