/**
 * KYC (Know Your Customer) — identity verification flow.
 *
 * Wires to:
 *   GET  /api/kyc/status          — current KYC status
 *   POST /api/kyc/submit          — submit documents
 *   POST /api/kyc/upload          — upload document file (multipart)
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { kycApi } from '../hooks/useApi';

type KYCStatus = 'not_started' | 'pending' | 'under_review' | 'approved' | 'rejected';

interface KYCState {
  status: KYCStatus;
  submitted_at: string | null;
  reviewed_at: string | null;
  rejection_reason: string | null;
  documents: { type: string; status: string; uploaded_at: string }[];
}

const STATUS_CONFIG: Record<KYCStatus, { label: string; color: string; bg: string; icon: string }> = {
  not_started:  { label: 'Not Started',   color: '#94a3b8', bg: '#1e293b', icon: '⬜' },
  pending:      { label: 'Pending',        color: '#f59e0b', bg: '#431407', icon: '⏳' },
  under_review: { label: 'Under Review',   color: '#60a5fa', bg: '#1e3a5f', icon: '🔍' },
  approved:     { label: 'Approved',       color: '#4ade80', bg: '#14532d', icon: '✅' },
  rejected:     { label: 'Rejected',       color: '#f87171', bg: '#450a0a', icon: '❌' },
};

const DOC_TYPES = [
  { id: 'passport',        label: 'Passport' },
  { id: 'national_id',     label: 'National ID' },
  { id: 'drivers_license', label: 'Driver\'s License' },
  { id: 'proof_of_address', label: 'Proof of Address' },
  { id: 'selfie',          label: 'Selfie with ID' },
];

const KYCPage: React.FC = () => {
  const [kycState, setKycState]     = useState<KYCState | null>(null);
  const [loading, setLoading]       = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [submitMsg, setSubmitMsg]   = useState('');
  const [uploads, setUploads]       = useState<Record<string, File>>({});
  const [uploading, setUploading]   = useState<string | null>(null);
  const [uploadedDocs, setUploadedDocs] = useState<string[]>([]);
  const fileRefs = useRef<Record<string, HTMLInputElement | null>>({});
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const loadStatus = useCallback(async () => {
    setLoading(true);
    try {
      const res = await kycApi.status();
      if (!mountedRef.current) return;
      setKycState(res.data as KYCState);
    } catch {
      if (!mountedRef.current) return;
      setKycState({ status: 'not_started', submitted_at: null, reviewed_at: null, rejection_reason: null, documents: [] });
    } finally { if (mountedRef.current) setLoading(false); }
  }, []);

  useEffect(() => { loadStatus(); }, [loadStatus]);

  const handleFileSelect = (docType: string, file: File) => {
    setUploads(prev => ({ ...prev, [docType]: file }));
  };

  const handleUpload = async (docType: string) => {
    const file = uploads[docType];
    if (!file) return;
    setUploading(docType);
    try {
      const form = new FormData();
      form.append('document_type', docType);
      form.append('file', file);
      await kycApi.uploadDocument(form);
      setUploadedDocs(prev => [...prev.filter(d => d !== docType), docType]);
      setUploads(prev => { const n = { ...prev }; delete n[docType]; return n; });
    } catch { /* non-fatal */ }
    finally { setUploading(null); }
  };

  const handleSubmit = async () => {
    setSubmitting(true);
    setSubmitMsg('');
    try {
      const form = new FormData();
      uploadedDocs.forEach(d => form.append('document_types[]', d));
      await kycApi.submit(form);
      setSubmitMsg('KYC documents submitted successfully. Review typically takes 1–2 business days.');
      await loadStatus();
    } catch (e: unknown) {
      setSubmitMsg(`Submission failed: ${e instanceof Error ? e.message : 'Unknown error'}`);
    } finally { setSubmitting(false); }
  };

  if (loading) return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: 300, color: '#64748b' }}>
      Loading KYC status…
    </div>
  );

  const status = kycState?.status ?? 'not_started';
  const cfg = STATUS_CONFIG[status];
  const canSubmit = status === 'not_started' || status === 'rejected';

  return (
    <div style={{ maxWidth: 680, margin: '0 auto', padding: '24px 16px' }}>
      {/* Header */}
      <div style={{ marginBottom: 28 }}>
        <h1 style={{ fontSize: 24, fontWeight: 800, color: '#f1f5f9', margin: 0 }}>Identity Verification (KYC)</h1>
        <p style={{ fontSize: 13, color: '#64748b', margin: '6px 0 0' }}>
          Complete identity verification to unlock full trading features and higher withdrawal limits.
        </p>
      </div>

      {/* Status card */}
      <div style={{ background: cfg.bg, border: `1px solid ${cfg.color}33`, borderRadius: 12, padding: '20px 24px', marginBottom: 24 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontSize: 32 }}>{cfg.icon}</span>
          <div>
            <div style={{ fontSize: 18, fontWeight: 700, color: cfg.color }}>{cfg.label}</div>
            {kycState?.submitted_at && (
              <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>
                Submitted: {new Date(kycState.submitted_at).toLocaleDateString()}
              </div>
            )}
            {kycState?.reviewed_at && (
              <div style={{ fontSize: 12, color: '#64748b' }}>
                Reviewed: {new Date(kycState.reviewed_at).toLocaleDateString()}
              </div>
            )}
          </div>
        </div>
        {status === 'rejected' && kycState?.rejection_reason && (
          <div style={{ marginTop: 14, background: '#450a0a', border: '1px solid #7f1d1d', borderRadius: 8, padding: '10px 14px' }}>
            <div style={{ fontSize: 12, color: '#f87171', fontWeight: 600, marginBottom: 4 }}>Rejection Reason</div>
            <div style={{ fontSize: 13, color: '#fca5a5' }}>{kycState.rejection_reason}</div>
          </div>
        )}
        {status === 'approved' && (
          <div style={{ marginTop: 12, fontSize: 13, color: '#4ade80' }}>
            ✅ Your identity has been verified. All trading features are unlocked.
          </div>
        )}
        {status === 'under_review' && (
          <div style={{ marginTop: 12, fontSize: 13, color: '#60a5fa' }}>
            🔍 Your documents are being reviewed. This typically takes 1–2 business days.
          </div>
        )}
      </div>

      {/* Previously uploaded docs */}
      {(kycState?.documents ?? []).length > 0 && (
        <div style={{ background: '#0d1421', border: '1px solid #1e293b', borderRadius: 10, padding: '16px 20px', marginBottom: 20 }}>
          <h3 style={{ fontSize: 14, fontWeight: 700, color: '#f1f5f9', margin: '0 0 12px' }}>Submitted Documents</h3>
          {kycState!.documents.map(doc => (
            <div key={doc.type} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid #1e293b', fontSize: 13 }}>
              <span style={{ color: '#94a3b8' }}>{DOC_TYPES.find(d => d.id === doc.type)?.label ?? doc.type}</span>
              <span style={{ color: doc.status === 'approved' ? '#4ade80' : doc.status === 'rejected' ? '#f87171' : '#f59e0b' }}>
                {doc.status}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Upload form */}
      {canSubmit && (
        <div style={{ background: '#0d1421', border: '1px solid #1e293b', borderRadius: 10, padding: '20px 24px', marginBottom: 20 }}>
          <h3 style={{ fontSize: 16, fontWeight: 700, color: '#f1f5f9', margin: '0 0 16px' }}>Upload Documents</h3>
          <p style={{ fontSize: 13, color: '#64748b', margin: '0 0 20px' }}>
            Upload at least a government-issued ID and proof of address. Files must be JPG, PNG, or PDF under 10MB.
          </p>
          {DOC_TYPES.map(doc => {
            const isUploaded = uploadedDocs.includes(doc.id);
            const hasFile    = !!uploads[doc.id];
            return (
              <div key={doc.id} style={{ marginBottom: 14 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                  <label style={{ fontSize: 13, fontWeight: 600, color: '#f1f5f9' }}>{doc.label}</label>
                  {isUploaded && <span style={{ fontSize: 12, color: '#4ade80' }}>✅ Uploaded</span>}
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
                    style={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8, color: '#94a3b8', cursor: 'pointer', fontSize: 13, padding: '8px 14px', flex: 1, textAlign: 'left' }}
                  >
                    {uploads[doc.id]?.name ?? 'Choose file…'}
                  </button>
                  <button
                    onClick={() => handleUpload(doc.id)}
                    disabled={!hasFile || uploading === doc.id}
                    style={{ background: hasFile ? '#1e3a5f' : '#1e293b', border: `1px solid ${hasFile ? '#3b82f6' : '#334155'}`, borderRadius: 8, color: hasFile ? '#60a5fa' : '#475569', cursor: hasFile ? 'pointer' : 'not-allowed', fontSize: 13, fontWeight: 600, padding: '8px 16px' }}
                  >
                    {uploading === doc.id ? '⟳' : '↑ Upload'}
                  </button>
                </div>
              </div>
            );
          })}

          {submitMsg && (
            <div style={{ background: submitMsg.includes('failed') ? '#450a0a' : '#14532d', border: `1px solid ${submitMsg.includes('failed') ? '#7f1d1d' : '#166534'}`, borderRadius: 8, color: submitMsg.includes('failed') ? '#f87171' : '#4ade80', fontSize: 13, padding: '10px 14px', margin: '16px 0' }}>
              {submitMsg}
            </div>
          )}

          <button
            onClick={handleSubmit}
            disabled={submitting || uploadedDocs.length === 0}
            style={{ background: uploadedDocs.length > 0 ? '#3b82f6' : '#1e293b', border: 'none', borderRadius: 10, color: uploadedDocs.length > 0 ? '#fff' : '#475569', cursor: uploadedDocs.length > 0 ? 'pointer' : 'not-allowed', fontSize: 15, fontWeight: 700, padding: '12px 28px', marginTop: 8, width: '100%' }}
          >
            {submitting ? 'Submitting…' : `Submit for Review (${uploadedDocs.length} document${uploadedDocs.length !== 1 ? 's' : ''})`}
          </button>
        </div>
      )}

      {/* Info boxes */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        {[
          { icon: '🔒', title: 'Secure & Encrypted', body: 'All documents are encrypted at rest and in transit using AES-256.' },
          { icon: '⏱️', title: 'Fast Review', body: 'Most verifications are completed within 1–2 business days.' },
          { icon: '🌍', title: 'Global Coverage', body: 'We accept IDs from 180+ countries and territories.' },
          { icon: '🗑️', title: 'Data Retention', body: 'Documents are retained only as required by regulation and deleted thereafter.' },
        ].map(({ icon, title, body }) => (
          <div key={title} style={{ background: '#0d1421', border: '1px solid #1e293b', borderRadius: 10, padding: '14px 16px' }}>
            <div style={{ fontSize: 20, marginBottom: 6 }}>{icon}</div>
            <div style={{ fontSize: 13, fontWeight: 700, color: '#f1f5f9', marginBottom: 4 }}>{title}</div>
            <div style={{ fontSize: 12, color: '#64748b', lineHeight: 1.5 }}>{body}</div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default KYCPage;
