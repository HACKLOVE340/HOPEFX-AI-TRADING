/**
 * KYC (Know Your Customer) — identity verification flow.
 *
 * Wires to:
 *   GET  /api/kyc/status          — current KYC status
 *   POST /api/kyc/submit          — submit documents
 *   POST /api/kyc/upload          — upload document file (multipart)
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { kycApi } from '../hooks/useApi';
import { extractApiError } from '../lib/utils';
import { PageHeader } from '../components/PageHeader';
import { CrossLinkBar } from '../components/CrossLinkBar';
import { Badge } from '../components/Badge';
import { ErrorBanner } from '../components/ErrorBanner';
import { Spinner } from '../components/Spinner';

type KYCStatus = 'not_started' | 'pending' | 'under_review' | 'approved' | 'rejected';

interface KYCState {
  status: KYCStatus;
  submitted_at: string | null;
  reviewed_at: string | null;
  rejection_reason: string | null;
  documents: { type: string; status: string; uploaded_at: string }[];
}

const STATUS_CONFIG: Record<KYCStatus, {
  label: string; color: string; bg: string; border: string; icon: string;
  badgeVariant: 'success' | 'warning' | 'info' | 'danger' | 'neutral';
}> = {
  not_started:  { label: 'Not Started',  color: '#94a3b8', bg: '#1e293b22', border: '#334155', icon: '○', badgeVariant: 'neutral' },
  pending:      { label: 'Pending',       color: '#f59e0b', bg: '#78350f22', border: '#92400e', icon: '⏳', badgeVariant: 'warning' },
  under_review: { label: 'Under Review',  color: '#60a5fa', bg: '#1e3a5f22', border: '#1d4ed8', icon: '🔍', badgeVariant: 'info' },
  approved:     { label: 'Approved',      color: '#4ade80', bg: '#14532d22', border: '#166534', icon: '✓', badgeVariant: 'success' },
  rejected:     { label: 'Rejected',      color: '#f87171', bg: '#450a0a22', border: '#7f1d1d', icon: '✕', badgeVariant: 'danger' },
};

const DOC_TYPES = [
  { id: 'passport',         label: 'Passport',          desc: 'Valid government-issued passport' },
  { id: 'national_id',      label: 'National ID',        desc: 'Government-issued national identity card' },
  { id: 'drivers_license',  label: "Driver's License",   desc: "Valid driver's license with photo" },
  { id: 'proof_of_address', label: 'Proof of Address',   desc: 'Utility bill or bank statement (< 3 months)' },
  { id: 'selfie',           label: 'Selfie with ID',     desc: 'Clear photo of you holding your ID' },
];

const STEPS = [
  { id: 1, label: 'Upload Documents' },
  { id: 2, label: 'Submit for Review' },
  { id: 3, label: 'Verification Complete' },
];

function getStep(status: KYCStatus): number {
  if (status === 'approved') return 3;
  if (status === 'under_review' || status === 'pending') return 2;
  return 1;
}

const StepIndicator: React.FC<{ status: KYCStatus }> = ({ status }) => {
  const current = getStep(status);
  return (
    <div style={{ display: 'flex', alignItems: 'center', marginBottom: 28 }}>
      {STEPS.map((step, idx) => {
        const done   = step.id < current;
        const active = step.id === current;
        return (
          <React.Fragment key={step.id}>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, flex: 1 }}>
              <div style={{
                width: 32, height: 32, borderRadius: '50%',
                background: done ? '#166534' : active ? '#1d4ed8' : '#1e293b',
                border: `2px solid ${done ? '#4ade80' : active ? '#3b82f6' : '#334155'}`,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 13, fontWeight: 700,
                color: done ? '#4ade80' : active ? '#93c5fd' : '#475569',
              }}>
                {done ? '✓' : step.id}
              </div>
              <span style={{ fontSize: 11, color: active ? '#93c5fd' : done ? '#4ade80' : '#475569', fontWeight: active ? 600 : 400, textAlign: 'center' }}>
                {step.label}
              </span>
            </div>
            {idx < STEPS.length - 1 && (
              <div style={{ height: 2, flex: 1, marginBottom: 18, background: done ? '#166534' : '#1e293b' }} />
            )}
          </React.Fragment>
        );
      })}
    </div>
  );
};



const KYCPage: React.FC = () => {
  const [kycState, setKycState]     = useState<KYCState | null>(null);
  const [loading, setLoading]       = useState(true);
  const [error, setError]           = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitMsg, setSubmitMsg]   = useState('');
  const [submitOk, setSubmitOk]     = useState(false);
  const [uploads, setUploads]       = useState<Record<string, File>>({});
  const [uploading, setUploading]   = useState<string | null>(null);
  const [uploadedDocs, setUploadedDocs] = useState<string[]>([]);
  const [uploadErrors, setUploadErrors] = useState<Record<string, string>>({});
  const fileRefs = useRef<Record<string, HTMLInputElement | null>>({});
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const loadStatus = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await kycApi.status();
      if (!mountedRef.current) return;
      setKycState(res.data as KYCState);
    } catch {
      if (!mountedRef.current) return;
      setError('Failed to load KYC status. Please refresh.');
      setKycState({ status: 'not_started', submitted_at: null, reviewed_at: null, rejection_reason: null, documents: [] });
    } finally { if (mountedRef.current) setLoading(false); }
  }, []);

  useEffect(() => { loadStatus(); }, [loadStatus]);

  const handleFileSelect = (docType: string, file: File) => {
    if (file.size > 10 * 1024 * 1024) {
      setUploadErrors(prev => ({ ...prev, [docType]: 'File exceeds 10 MB limit.' }));
      return;
    }
    const allowed = ['image/jpeg', 'image/png', 'application/pdf'];
    if (!allowed.includes(file.type)) {
      setUploadErrors(prev => ({ ...prev, [docType]: 'Only JPG, PNG, or PDF files are accepted.' }));
      return;
    }
    setUploadErrors(prev => { const n = { ...prev }; delete n[docType]; return n; });
    setUploads(prev => ({ ...prev, [docType]: file }));
  };

  const handleUpload = async (docType: string) => {
    const file = uploads[docType];
    if (!file) return;
    setUploading(docType);
    setUploadErrors(prev => { const n = { ...prev }; delete n[docType]; return n; });
    try {
      const form = new FormData();
      form.append('document_type', docType);
      form.append('file', file);
      await kycApi.uploadDocument(form);
      setUploadedDocs(prev => [...prev.filter(d => d !== docType), docType]);
      setUploads(prev => { const n = { ...prev }; delete n[docType]; return n; });
    } catch (e: unknown) {
      setUploadErrors(prev => ({ ...prev, [docType]: extractApiError(e, 'Upload failed.') }));
    } finally { setUploading(null); }
  };

  const handleSubmit = async () => {
    setSubmitting(true);
    setSubmitMsg('');
    setSubmitOk(false);
    try {
      const form = new FormData();
      uploadedDocs.forEach(d => form.append('document_types[]', d));
      await kycApi.submit(form);
      setSubmitMsg('Documents submitted. Review typically takes 1–2 business days.');
      setSubmitOk(true);
      await loadStatus();
    } catch (e: unknown) {
      setSubmitMsg(extractApiError(e, 'Submission failed. Please try again.'));
      setSubmitOk(false);
    } finally { setSubmitting(false); }
  };

  const status = kycState?.status ?? 'not_started';
  const cfg    = STATUS_CONFIG[status];
  const canSubmit = status === 'not_started' || status === 'rejected';

  return (
    <div className="page-content">
      <PageHeader
        title="Identity Verification (KYC)"
        icon="🪪"
        subtitle="Complete verification to unlock full trading features and higher withdrawal limits."
        breadcrumbs={[
          { label: 'Home',    href: '/home' },
          { label: 'Profile', href: '/profile' },
          { label: 'KYC Verification' },
        ]}
        badge={
          <Badge variant={cfg.badgeVariant} style={{ fontSize: 11 }}>
            {cfg.icon} {cfg.label}
          </Badge>
        }
        actions={
          <button
            onClick={loadStatus}
            disabled={loading}
            style={{
              background: 'transparent', border: '1px solid #334155',
              borderRadius: 8, color: '#94a3b8', cursor: 'pointer',
              fontSize: 12, padding: '6px 14px', display: 'flex', alignItems: 'center', gap: 6,
            }}
          >
            {loading ? <Spinner size="sm" /> : '↻'} Refresh
          </button>
        }
      />

      {error && <ErrorBanner message={error} style={{ marginBottom: 20 }} />}

      {loading && !kycState ? (
        <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: 200, gap: 12, color: '#64748b' }}>
          <Spinner size="md" /> Loading KYC status…
        </div>
      ) : (
        <>
          <StepIndicator status={status} />

          {/* Status card */}
          <div style={{ background: cfg.bg, border: `1px solid ${cfg.border}`, borderRadius: 12, padding: '20px 24px', marginBottom: 24 }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16 }}>
              <div style={{
                width: 48, height: 48, borderRadius: 12,
                background: `${cfg.color}22`, border: `1px solid ${cfg.border}`,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 22, flexShrink: 0,
              }}>
                {cfg.icon}
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 18, fontWeight: 700, color: cfg.color }}>{cfg.label}</div>
                <div style={{ display: 'flex', gap: 20, marginTop: 6, flexWrap: 'wrap' }}>
                  {kycState?.submitted_at && (
                    <span style={{ fontSize: 12, color: '#64748b' }}>
                      Submitted: <strong style={{ color: '#94a3b8' }}>{new Date(kycState.submitted_at).toLocaleDateString()}</strong>
                    </span>
                  )}
                  {kycState?.reviewed_at && (
                    <span style={{ fontSize: 12, color: '#64748b' }}>
                      Reviewed: <strong style={{ color: '#94a3b8' }}>{new Date(kycState.reviewed_at).toLocaleDateString()}</strong>
                    </span>
                  )}
                </div>
                {status === 'approved' && (
                  <p style={{ fontSize: 13, color: '#4ade80', margin: '8px 0 0' }}>
                    Your identity has been verified. All trading features are unlocked.
                  </p>
                )}
                {status === 'under_review' && (
                  <p style={{ fontSize: 13, color: '#60a5fa', margin: '8px 0 0' }}>
                    Your documents are under review. This typically takes 1–2 business days.
                  </p>
                )}
                {status === 'pending' && (
                  <p style={{ fontSize: 13, color: '#f59e0b', margin: '8px 0 0' }}>
                    Submission received. Our compliance team will begin review shortly.
                  </p>
                )}
              </div>
            </div>
            {status === 'rejected' && kycState?.rejection_reason && (
              <div style={{ marginTop: 16, background: '#450a0a', border: '1px solid #7f1d1d', borderRadius: 8, padding: '12px 16px' }}>
                <div style={{ fontSize: 12, color: '#f87171', fontWeight: 700, marginBottom: 4 }}>Rejection Reason</div>
                <div style={{ fontSize: 13, color: '#fca5a5', lineHeight: 1.5 }}>{kycState.rejection_reason}</div>
                <div style={{ fontSize: 12, color: '#64748b', marginTop: 8 }}>Please re-upload corrected documents and resubmit.</div>
              </div>
            )}
          </div>

          {/* Previously uploaded docs */}
          {(kycState?.documents ?? []).length > 0 && (
            <div style={{ background: '#0d1421', border: '1px solid #1e293b', borderRadius: 12, padding: '18px 22px', marginBottom: 20 }}>
              <h3 style={{ fontSize: 14, fontWeight: 700, color: '#f1f5f9', margin: '0 0 14px', display: 'flex', alignItems: 'center', gap: 8 }}>
                <span>📄</span> Submitted Documents
              </h3>
              {kycState!.documents.map((doc, i) => {
                const docLabel = DOC_TYPES.find(d => d.id === doc.type)?.label ?? doc.type;
                const sc = doc.status === 'approved' ? '#4ade80' : doc.status === 'rejected' ? '#f87171' : '#f59e0b';
                return (
                  <div key={doc.type} style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    padding: '10px 0',
                    borderBottom: i < kycState!.documents.length - 1 ? '1px solid #1e293b' : 'none',
                  }}>
                    <div>
                      <span style={{ fontSize: 13, color: '#f1f5f9', fontWeight: 500 }}>{docLabel}</span>
                      {doc.uploaded_at && (
                        <span style={{ fontSize: 11, color: '#475569', marginLeft: 10 }}>
                          {new Date(doc.uploaded_at).toLocaleDateString()}
                        </span>
                      )}
                    </div>
                    <span style={{ fontSize: 11, fontWeight: 700, color: sc, background: `${sc}18`, border: `1px solid ${sc}44`, borderRadius: 6, padding: '2px 8px', textTransform: 'capitalize' }}>
                      {doc.status}
                    </span>
                  </div>
                );
              })}
            </div>
          )}

          {/* Upload form */}
          {canSubmit && (
            <div style={{ background: '#0d1421', border: '1px solid #1e293b', borderRadius: 12, padding: '22px 24px', marginBottom: 24 }}>
              <h3 style={{ fontSize: 16, fontWeight: 700, color: '#f1f5f9', margin: '0 0 6px', display: 'flex', alignItems: 'center', gap: 8 }}>
                <span>📤</span> Upload Documents
              </h3>
              <p style={{ fontSize: 13, color: '#64748b', margin: '0 0 20px', lineHeight: 1.5 }}>
                Upload at least a government-issued ID and proof of address. Files must be JPG, PNG, or PDF under 10 MB.
              </p>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {DOC_TYPES.map(doc => {
                  const isUploaded = uploadedDocs.includes(doc.id);
                  const hasFile    = !!uploads[doc.id];
                  const err        = uploadErrors[doc.id];
                  return (
                    <div key={doc.id} style={{
                      background: isUploaded ? '#05200e' : '#111827',
                      border: `1px solid ${isUploaded ? '#166534' : err ? '#7f1d1d' : '#1e293b'}`,
                      borderRadius: 10, padding: '14px 16px',
                    }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
                        <div>
                          <label style={{ fontSize: 13, fontWeight: 600, color: '#f1f5f9' }}>{doc.label}</label>
                          <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>{doc.desc}</div>
                        </div>
                        {isUploaded && (
                          <span style={{ fontSize: 11, color: '#4ade80', fontWeight: 700, background: '#14532d', border: '1px solid #166534', borderRadius: 6, padding: '2px 8px', flexShrink: 0 }}>
                            ✓ Uploaded
                          </span>
                        )}
                      </div>
                      <div style={{ display: 'flex', gap: 8 }}>
                        <input
                          type="file"
                          accept=".jpg,.jpeg,.png,.pdf"
                          ref={el => { fileRefs.current[doc.id] = el; }}
                          onChange={e => { if (e.target.files?.[0]) handleFileSelect(doc.id, e.target.files[0]); }}
                          style={{ display: 'none' }}
                        />
                        <button
                          onClick={() => fileRefs.current[doc.id]?.click()}
                          style={{
                            background: '#1e293b', border: '1px solid #334155', borderRadius: 8,
                            color: hasFile ? '#f1f5f9' : '#64748b', cursor: 'pointer',
                            fontSize: 12, padding: '8px 14px', flex: 1, textAlign: 'left',
                            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                          }}
                        >
                          {uploads[doc.id]?.name ?? 'Choose file…'}
                        </button>
                        <button
                          onClick={() => handleUpload(doc.id)}
                          disabled={!hasFile || uploading === doc.id}
                          style={{
                            background: hasFile ? '#1d4ed8' : '#1e293b',
                            border: `1px solid ${hasFile ? '#3b82f6' : '#334155'}`,
                            borderRadius: 8, color: hasFile ? '#93c5fd' : '#475569',
                            cursor: hasFile ? 'pointer' : 'not-allowed',
                            fontSize: 12, fontWeight: 600, padding: '8px 16px',
                            display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0,
                          }}
                        >
                          {uploading === doc.id ? <Spinner size="sm" /> : '↑'} Upload
                        </button>
                      </div>
                      {err && <div style={{ fontSize: 11, color: '#f87171', marginTop: 6 }}>{err}</div>}
                    </div>
                  );
                })}
              </div>

              {submitMsg && (
                <div style={{
                  background: submitOk ? '#052e16' : '#450a0a',
                  border: `1px solid ${submitOk ? '#166534' : '#7f1d1d'}`,
                  borderRadius: 8, color: submitOk ? '#4ade80' : '#f87171',
                  fontSize: 13, padding: '12px 16px', margin: '18px 0 0', lineHeight: 1.5,
                }}>
                  {submitMsg}
                </div>
              )}

              <button
                onClick={handleSubmit}
                disabled={submitting || uploadedDocs.length === 0}
                style={{
                  background: uploadedDocs.length > 0 ? '#1d4ed8' : '#1e293b',
                  border: `1px solid ${uploadedDocs.length > 0 ? '#3b82f6' : '#334155'}`,
                  borderRadius: 10, color: uploadedDocs.length > 0 ? '#fff' : '#475569',
                  cursor: uploadedDocs.length > 0 ? 'pointer' : 'not-allowed',
                  fontSize: 14, fontWeight: 700, padding: '13px 28px',
                  marginTop: 18, width: '100%',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
                }}
              >
                {submitting ? <><Spinner size="sm" /> Submitting…</> : `Submit for Review (${uploadedDocs.length} document${uploadedDocs.length !== 1 ? 's' : ''})`}
              </button>
            </div>
          )}

          {/* Info grid */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12, marginBottom: 28 }}>
            {[
              { icon: '🔒', title: 'AES-256 Encrypted',  body: 'All documents are encrypted at rest and in transit.' },
              { icon: '⏱️', title: '1–2 Business Days',  body: 'Most verifications are completed within 48 hours.' },
              { icon: '🌍', title: '180+ Countries',      body: 'We accept IDs from 180+ countries and territories.' },
              { icon: '🗑️', title: 'GDPR Compliant',     body: 'Documents are retained only as required by regulation.' },
            ].map(({ icon, title, body }) => (
              <div key={title} style={{ background: '#0d1421', border: '1px solid #1e293b', borderRadius: 10, padding: '14px 16px' }}>
                <div style={{ fontSize: 22, marginBottom: 8 }}>{icon}</div>
                <div style={{ fontSize: 13, fontWeight: 700, color: '#f1f5f9', marginBottom: 4 }}>{title}</div>
                <div style={{ fontSize: 12, color: '#64748b', lineHeight: 1.5 }}>{body}</div>
              </div>
            ))}
          </div>

          <CrossLinkBar title="Related" style={{ marginTop: 20 }} links={[
            { label: 'Profile',   href: '/profile',            icon: '👤', color: '#60a5fa' },
            { label: 'Security',  href: '/settings?tab=security', icon: '🔐', color: '#f87171' },
            { label: 'Wallet',    href: '/wallet',             icon: '💳', color: '#4ade80' },
            { label: 'Settings',  href: '/settings',           icon: '⚙️', color: '#94a3b8' },
          ]} />
        </>
      )}
    </div>
  );
};

export default KYCPage;
