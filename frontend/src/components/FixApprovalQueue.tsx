/**
 * FixApprovalQueue — review and approve/decline LLM-generated code fixes.
 *
 * Polls GET /api/security/fixes every 30 s.
 * Each fix shows the vulnerable endpoint, original code, and the LLM patch.
 * Approve → POST /api/security/fixes/approve
 * Decline → POST /api/security/fixes/decline
 */

import React, { useCallback, useEffect, useState } from 'react';
import { api } from '../hooks/useApi';

// ── Types ─────────────────────────────────────────────────────────────────────

export interface FixRecord {
  endpoint: string;
  original: string;
  fix: string;
  ts: string;
  status: 'pending' | 'approved' | 'declined';
}

// ── API helpers ───────────────────────────────────────────────────────────────

async function fetchFixes(): Promise<FixRecord[]> {
  const { data } = await api.get<FixRecord[]>('/security/fixes');
  return data;
}

async function approveFix(endpoint: string): Promise<void> {
  await api.post('/security/fixes/approve', { endpoint });
}

async function declineFix(endpoint: string): Promise<void> {
  await api.post('/security/fixes/decline', { endpoint });
}

// ── Component ─────────────────────────────────────────────────────────────────

export const FixApprovalQueue: React.FC = () => {
  const [fixes, setFixes] = useState<FixRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [acting, setActing] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await fetchFixes();
      setFixes(data);
      setError(null);
    } catch (err) {
      setError('Failed to load fix queue');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 30_000);
    return () => clearInterval(id);
  }, [load]);

  const handleApprove = async (endpoint: string) => {
    setActing(endpoint);
    try {
      await approveFix(endpoint);
      setFixes(prev =>
        prev.map(f => f.endpoint === endpoint ? { ...f, status: 'approved' } : f)
      );
    } catch {
      setError(`Failed to approve fix for ${endpoint}`);
    } finally {
      setActing(null);
    }
  };

  const handleDecline = async (endpoint: string) => {
    setActing(endpoint);
    try {
      await declineFix(endpoint);
      setFixes(prev =>
        prev.map(f => f.endpoint === endpoint ? { ...f, status: 'declined' } : f)
      );
    } catch {
      setError(`Failed to decline fix for ${endpoint}`);
    } finally {
      setActing(null);
    }
  };

  const pending = fixes.filter(f => f.status === 'pending');
  const resolved = fixes.filter(f => f.status !== 'pending');

  return (
    <div style={wrapperStyle}>
      <div style={headerStyle}>
        <span style={titleStyle}>LLM Fix Queue</span>
        <span style={badgeStyle(pending.length > 0)}>
          {pending.length} pending
        </span>
      </div>

      {error && (
        <div style={errorStyle}>{error}</div>
      )}

      {loading && fixes.length === 0 ? (
        <div style={emptyStyle}>Loading fixes…</div>
      ) : fixes.length === 0 ? (
        <div style={emptyStyle}>No fixes queued — system is clean.</div>
      ) : (
        <div style={listStyle}>
          {[...pending, ...resolved].map(fix => (
            <FixRow
              key={fix.endpoint + fix.ts}
              fix={fix}
              expanded={expanded === fix.endpoint + fix.ts}
              onToggle={() =>
                setExpanded(prev =>
                  prev === fix.endpoint + fix.ts ? null : fix.endpoint + fix.ts
                )
              }
              onApprove={() => handleApprove(fix.endpoint)}
              onDecline={() => handleDecline(fix.endpoint)}
              acting={acting === fix.endpoint}
            />
          ))}
        </div>
      )}
    </div>
  );
};

// ── FixRow ────────────────────────────────────────────────────────────────────

interface FixRowProps {
  fix: FixRecord;
  expanded: boolean;
  onToggle: () => void;
  onApprove: () => void;
  onDecline: () => void;
  acting: boolean;
}

const FixRow: React.FC<FixRowProps> = ({
  fix, expanded, onToggle, onApprove, onDecline, acting,
}) => {
  const time = fix.ts ? new Date(fix.ts).toLocaleString() : '—';
  const statusColour =
    fix.status === 'approved' ? '#4ade80'
    : fix.status === 'declined' ? '#f87171'
    : '#facc15';

  return (
    <div style={rowStyle}>
      {/* Row header */}
      <div style={rowHeaderStyle} onClick={onToggle} role="button" tabIndex={0}
        onKeyDown={e => e.key === 'Enter' && onToggle()}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 0 }}>
          <span style={{ color: statusColour, fontSize: 10 }}>⬤</span>
          <span style={endpointStyle}>{fix.endpoint}</span>
          <span style={timeStyle}>{time}</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ ...statusPillStyle, background: statusColour + '22', color: statusColour }}>
            {fix.status}
          </span>
          <span style={{ color: '#64748b', fontSize: 12 }}>{expanded ? '▲' : '▼'}</span>
        </div>
      </div>

      {/* Expanded diff view */}
      {expanded && (
        <div style={expandedStyle}>
          <div style={diffSectionStyle}>
            <div style={diffLabelStyle}>Original (vulnerable)</div>
            <pre style={{ ...codeStyle, borderLeft: '3px solid #ef4444' }}>{fix.original}</pre>
          </div>
          <div style={diffSectionStyle}>
            <div style={diffLabelStyle}>LLM Fix</div>
            <pre style={{ ...codeStyle, borderLeft: '3px solid #4ade80' }}>{fix.fix}</pre>
          </div>

          {fix.status === 'pending' && (
            <div style={actionsStyle}>
              <button
                style={btnStyle('#4ade80')}
                onClick={onApprove}
                disabled={acting}
              >
                {acting ? '…' : '✓ Approve'}
              </button>
              <button
                style={btnStyle('#f87171')}
                onClick={onDecline}
                disabled={acting}
              >
                {acting ? '…' : '✗ Decline'}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

// ── Styles ────────────────────────────────────────────────────────────────────

const wrapperStyle: React.CSSProperties = {
  background: 'var(--surface, #1e293b)',
  border: '1px solid var(--border, #334155)',
  borderRadius: 10,
  display: 'flex',
  flexDirection: 'column',
  overflow: 'hidden',
};

const headerStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  padding: '12px 16px',
  borderBottom: '1px solid var(--border, #334155)',
};

const titleStyle: React.CSSProperties = {
  color: 'var(--text, #f1f5f9)',
  fontSize: 13,
  fontWeight: 700,
};

const badgeStyle = (hasPending: boolean): React.CSSProperties => ({
  background: hasPending ? '#facc1522' : '#1e293b',
  color: hasPending ? '#facc15' : '#64748b',
  border: `1px solid ${hasPending ? '#facc15' : '#334155'}`,
  borderRadius: 12,
  fontSize: 11,
  fontWeight: 600,
  padding: '2px 8px',
});

const errorStyle: React.CSSProperties = {
  background: '#ef444422',
  border: '1px solid #ef4444',
  borderRadius: 6,
  color: '#f87171',
  fontSize: 12,
  margin: '8px 16px',
  padding: '8px 12px',
};

const emptyStyle: React.CSSProperties = {
  color: '#64748b',
  fontSize: 13,
  padding: '24px 16px',
  textAlign: 'center',
};

const listStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 0,
  maxHeight: 480,
  overflowY: 'auto',
};

const rowStyle: React.CSSProperties = {
  borderBottom: '1px solid var(--border, #334155)',
};

const rowHeaderStyle: React.CSSProperties = {
  alignItems: 'center',
  cursor: 'pointer',
  display: 'flex',
  gap: 8,
  justifyContent: 'space-between',
  padding: '10px 16px',
  userSelect: 'none',
};

const endpointStyle: React.CSSProperties = {
  color: 'var(--text, #f1f5f9)',
  fontFamily: 'monospace',
  fontSize: 12,
  fontWeight: 600,
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  whiteSpace: 'nowrap',
};

const timeStyle: React.CSSProperties = {
  color: '#64748b',
  fontSize: 11,
  flexShrink: 0,
};

const statusPillStyle: React.CSSProperties = {
  borderRadius: 10,
  fontSize: 10,
  fontWeight: 700,
  padding: '2px 7px',
  textTransform: 'capitalize',
};

const expandedStyle: React.CSSProperties = {
  borderTop: '1px solid var(--border, #334155)',
  display: 'flex',
  flexDirection: 'column',
  gap: 12,
  padding: '12px 16px',
};

const diffSectionStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 4,
};

const diffLabelStyle: React.CSSProperties = {
  color: '#94a3b8',
  fontSize: 10,
  fontWeight: 700,
  letterSpacing: 0.5,
  textTransform: 'uppercase',
};

const codeStyle: React.CSSProperties = {
  background: '#0f172a',
  borderRadius: 6,
  color: '#e2e8f0',
  fontFamily: 'monospace',
  fontSize: 11,
  lineHeight: 1.6,
  margin: 0,
  overflowX: 'auto',
  padding: '10px 12px',
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-word',
};

const actionsStyle: React.CSSProperties = {
  display: 'flex',
  gap: 8,
  justifyContent: 'flex-end',
  paddingTop: 4,
};

const btnStyle = (colour: string): React.CSSProperties => ({
  background: colour + '22',
  border: `1px solid ${colour}`,
  borderRadius: 6,
  color: colour,
  cursor: 'pointer',
  fontSize: 12,
  fontWeight: 700,
  padding: '6px 14px',
  transition: 'background 0.15s',
});
