/**
 * PrivacyPolicy.tsx
 * Privacy Policy page — public, no auth required.
 * Route: /privacy
 */

import React, { useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Activity, ArrowLeft, Shield, Lock, Eye, Database, Globe, Mail } from 'lucide-react';

interface Section {
  icon: React.ReactNode;
  title: string;
  body: string;
}

const SECTIONS: Section[] = [
  {
    icon: <Database size={16} />,
    title: '1. Information We Collect',
    body: `We collect information you provide directly:
• Account information: email address, username, and password (hashed with bcrypt).
• Profile data: display name, country, and optional bio.
• Trading preferences: broker credentials (encrypted at rest), strategy settings, risk parameters.
• Payment information: processed by third-party providers (Stripe, crypto payment processors). We do not store card numbers.
• Communications: support emails and feedback you send us.

We collect information automatically:
• Usage data: pages visited, features used, session duration.
• Device data: browser type, operating system, IP address.
• Trading activity: orders placed, positions opened/closed, P&L (for your account only).`,
  },
  {
    icon: <Eye size={16} />,
    title: '2. How We Use Your Information',
    body: `We use collected information to:
• Provide, operate, and improve the Platform.
• Process transactions and send related notices.
• Send administrative messages, security alerts, and support responses.
• Send marketing communications (you may opt out at any time).
• Monitor and analyse usage patterns to improve user experience.
• Detect, investigate, and prevent fraudulent or illegal activity.
• Comply with legal obligations.

We do not sell your personal data to third parties.`,
  },
  {
    icon: <Globe size={16} />,
    title: '3. Information Sharing',
    body: `We share your information only in these circumstances:
• Service providers: hosting, analytics, payment processing, and email delivery partners who process data on our behalf under strict confidentiality agreements.
• Legal requirements: when required by law, court order, or governmental authority.
• Business transfers: in connection with a merger, acquisition, or sale of assets, with notice to affected users.
• With your consent: for any other purpose with your explicit consent.

We do not share trading data, positions, or account balances with any third party except your connected broker.`,
  },
  {
    icon: <Lock size={16} />,
    title: '4. Data Security',
    body: `We implement industry-standard security measures:
• Passwords are hashed using bcrypt with a minimum cost factor of 12.
• Broker API credentials are encrypted at rest using AES-256.
• All data in transit is protected by TLS 1.2 or higher.
• Access tokens expire after 15 minutes; refresh tokens after 30 days.
• Two-factor authentication (TOTP) is available and recommended.
• We conduct regular security audits and penetration tests.

No method of transmission over the internet is 100% secure. We cannot guarantee absolute security but commit to prompt disclosure of any breach affecting your data.`,
  },
  {
    icon: <Shield size={16} />,
    title: '5. Your Rights',
    body: `Depending on your jurisdiction, you may have the right to:
• Access: request a copy of the personal data we hold about you.
• Rectification: correct inaccurate or incomplete data.
• Erasure: request deletion of your account and associated data.
• Portability: receive your data in a machine-readable format.
• Objection: object to processing for direct marketing purposes.
• Restriction: request that we limit processing of your data.

To exercise any of these rights, contact privacy@hopefx.io. We will respond within 30 days.`,
  },
  {
    icon: <Database size={16} />,
    title: '6. Data Retention',
    body: `We retain your data for as long as your account is active or as needed to provide services. Specifically:
• Account data: retained until account deletion, then purged within 90 days.
• Trading history: retained for 7 years to comply with financial record-keeping requirements.
• Audit logs: retained for 2 years for security and compliance purposes.
• Backups: purged within 180 days of account deletion.

You may request earlier deletion subject to legal retention requirements.`,
  },
  {
    icon: <Globe size={16} />,
    title: '7. Cookies and Tracking',
    body: `We use the following cookies:
• Essential cookies: required for authentication and security (session tokens, CSRF protection).
• Preference cookies: remember your settings (theme, language, dashboard layout).
• Analytics cookies: anonymous usage statistics to improve the Platform (can be disabled).

We do not use advertising or cross-site tracking cookies. You can control cookies through your browser settings. Disabling essential cookies will prevent login.`,
  },
  {
    icon: <Globe size={16} />,
    title: '8. International Transfers',
    body: `HOPEFX operates globally. Your data may be processed in countries outside your own, including the United States and European Union. We ensure appropriate safeguards are in place for international transfers, including Standard Contractual Clauses where required by GDPR.`,
  },
  {
    icon: <Mail size={16} />,
    title: '9. Contact Us',
    body: `For privacy-related questions, requests, or complaints:

Email: privacy@hopefx.io
Response time: within 30 days

For EU/UK residents, you also have the right to lodge a complaint with your local data protection authority.

Last updated: ${new Date().getFullYear()}`,
  },
];

const PrivacyPolicy: React.FC = () => {
  useEffect(() => {
    document.title = 'Privacy Policy — HOPEFX';
    return () => { document.title = 'HOPEFX'; };
  }, []);

  return (
    <div style={s.page}>
      {/* Header */}
      <div style={s.header}>
        <div style={s.headerInner}>
          <Link to="/" style={s.logoLink}>
            <div style={s.logoIcon}><Activity size={14} color="#3b82f6" /></div>
            <span style={s.logo}>HOPE<span style={{ color: '#3b82f6' }}>FX</span></span>
          </Link>
          <Link to="/" style={s.backLink}>
            <ArrowLeft size={14} /> Back to home
          </Link>
        </div>
      </div>

      <div style={s.container}>
        {/* Title */}
        <div style={s.titleBlock}>
          <div style={s.badge}>
            <Shield size={12} />
            Privacy Policy
          </div>
          <h1 style={s.title}>How we handle your data</h1>
          <p style={s.subtitle}>
            Last updated: {new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })}
          </p>
          <p style={s.intro}>
            HOPEFX is committed to protecting your privacy. This policy explains what data we collect,
            how we use it, and your rights regarding your personal information.
          </p>
        </div>

        {/* Sections */}
        <div style={s.sections}>
          {SECTIONS.map((sec) => (
            <div key={sec.title} style={s.section}>
              <div style={s.sectionHeader}>
                <div style={s.sectionIcon}>{sec.icon}</div>
                <h2 style={s.sectionTitle}>{sec.title}</h2>
              </div>
              <div style={s.sectionBody}>
                {sec.body.split('\n').map((line, i) => (
                  line.trim() === '' ? <br key={i} /> :
                  line.startsWith('•') ? (
                    <div key={i} style={s.bullet}>
                      <span style={s.bulletDot}>•</span>
                      <span>{line.slice(1).trim()}</span>
                    </div>
                  ) : (
                    <p key={i} style={s.para}>{line}</p>
                  )
                ))}
              </div>
            </div>
          ))}
        </div>

        {/* Footer links */}
        <div style={s.footerLinks}>
          <Link to="/terms" style={s.footerLink}>Terms of Service</Link>
          <span style={{ color: '#334155' }}>·</span>
          <Link to="/risk-disclosure" style={s.footerLink}>Risk Disclosure</Link>
          <span style={{ color: '#334155' }}>·</span>
          <a href="mailto:privacy@hopefx.io" style={s.footerLink}>privacy@hopefx.io</a>
        </div>
      </div>
    </div>
  );
};

const s: Record<string, React.CSSProperties> = {
  page:       { minHeight: '100vh', background: '#0f172a', color: '#e2e8f0' },
  header:     { background: '#1e293b', borderBottom: '1px solid #334155', position: 'sticky', top: 0, zIndex: 10 },
  headerInner: {
    maxWidth: 800, margin: '0 auto', padding: '0 24px',
    height: 56, display: 'flex', alignItems: 'center', justifyContent: 'space-between',
  },
  logoLink:   { display: 'flex', alignItems: 'center', gap: 8, textDecoration: 'none' },
  logoIcon:   {
    width: 26, height: 26, borderRadius: 7,
    background: 'rgba(59,130,246,0.15)', border: '1px solid rgba(59,130,246,0.3)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
  },
  logo:       { fontSize: 18, fontWeight: 800, color: '#f8fafc', letterSpacing: -0.5 },
  backLink:   { display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, color: '#64748b', textDecoration: 'none' },
  container:  { maxWidth: 800, margin: '0 auto', padding: '48px 24px 80px' },
  titleBlock: { marginBottom: 48 },
  badge: {
    display: 'inline-flex', alignItems: 'center', gap: 6,
    background: 'rgba(59,130,246,0.1)', border: '1px solid rgba(59,130,246,0.25)',
    color: '#60a5fa', fontSize: 11, fontWeight: 700, letterSpacing: 0.5,
    padding: '4px 12px', borderRadius: 20, marginBottom: 16,
    textTransform: 'uppercase',
  },
  title:      { fontSize: 36, fontWeight: 800, color: '#f1f5f9', margin: '0 0 8px', letterSpacing: -0.5 },
  subtitle:   { fontSize: 13, color: '#64748b', margin: '0 0 16px' },
  intro:      { fontSize: 15, color: '#94a3b8', lineHeight: 1.7, margin: 0 },
  sections:   { display: 'flex', flexDirection: 'column', gap: 32 },
  section:    {
    background: '#1e293b', border: '1px solid #334155', borderRadius: 12,
    padding: '24px 28px',
  },
  sectionHeader: { display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 },
  sectionIcon: {
    width: 32, height: 32, borderRadius: 8,
    background: 'rgba(59,130,246,0.1)', border: '1px solid rgba(59,130,246,0.2)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    color: '#60a5fa', flexShrink: 0,
  },
  sectionTitle: { fontSize: 16, fontWeight: 700, color: '#f1f5f9', margin: 0 },
  sectionBody:  { fontSize: 14, color: '#94a3b8', lineHeight: 1.7 },
  bullet:       { display: 'flex', gap: 8, marginBottom: 6 },
  bulletDot:    { color: '#3b82f6', flexShrink: 0, fontWeight: 700 },
  para:         { margin: '0 0 8px' },
  footerLinks:  { display: 'flex', justifyContent: 'center', gap: 16, marginTop: 48, fontSize: 13 },
  footerLink:   { color: '#64748b', textDecoration: 'none' },
};

export default PrivacyPolicy;
