/**
 * FixApprovalQueue — review and approve/decline LLM-generated code fixes.
 *
 * Polls GET /api/security/fixes every 30 s.
 * Each fix shows the vulnerable endpoint, original code, and the LLM patch.
 * Approve → POST /api/security/fixes/approve
 * Decline → POST /api/security/fixes/decline
 */

import React, { useCallback, useEffect, useState } from 'react';
import { securityFixesApi } from '../hooks/useApi';
import { extractApiError } from '../lib/utils';
import { Check, X } from 'lucide-react';

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
  const res = await securityFixesApi.list() as { data: FixRecord[] | { fixes?: FixRecord[] } };
  return Array.isArray(res.data) ? res.data : ((res.data as { fixes?: FixRecord[] }).fixes ?? []);
}

async function approveFix(endpoint: string): Promise<void> {
  await securityFixesApi.approve(endpoint);
}

async function declineFix(endpoint: string): Promise<void> {
  await securityFixesApi.decline(endpoint);
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
      setFixes(Array.isArray(data) ? data : []);
      setError(null);
    } catch (err) {
      // The server's own explanation, not a generic line over the top of it.
      // Discarding it is F189: /correlation showed a blank card for ~20s while
      // the API had already sent the remedy in plain English.
      setError(extractApiError(err, 'Failed to load fix queue'));
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
      ) : error && fixes.length === 0 ? (
        /* An empty list after a FAILED fetch is not an empty queue — it is an
           unknown one. Rendering "system is clean" directly beneath the error
           banner told the operator the opposite of what had happened. */
        <div style={emptyStyle}>Queue unavailable — could not reach the server.</div>
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
        aria-expanded={expanded}
        aria-label={`Fix for ${fix.endpoint}`}
        onKeyDown={e => {
          // Space as well as Enter. A role="button" that ignores Space is not a
          // button to anyone using a keyboard, and the default Space action on a
          // focused div is to scroll the page away from the thing they pressed.
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onToggle(); }
        }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 0 }}>
          <span style={{ color: statusColour, fontSize: 'var(--fs-micro)'}}>⬤</span>
          <span style={endpointStyle}>{fix.endpoint}</span>
          <span style={timeStyle}>{time}</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ ...statusPillStyle, background: statusColour + '22', color: statusColour }}>
            {fix.status}
          </span>
          <span style={{ color: 'var(--text-muted)', fontSize: 'var(--fs-body)'}}>{expanded ? '▲' : '▼'}</span>
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
            <pre style={{ ...codeStyle, borderLeft: '3px solid var(--gain)' }}>{fix.fix}</pre>
          </div>

          {fix.status === 'pending' && (
            <div style={actionsStyle}>
              <button
                style={btnStyle('var(--gain)')}
                onClick={onApprove}
                disabled={acting}
              >
                {acting ? '…' : <><Check size={13} aria-hidden /> Approve</>}
              </button>
              <button
                style={btnStyle('var(--loss)')}
                onClick={onDecline}
                disabled={acting}
              >
                {acting ? '…' : <><X size={13} aria-hidden /> Decline</>}
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
  background: 'var(--surface, var(--raised))',
  border: '1px solid var(--border, var(--border-strong))',
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
  borderBottom: '1px solid var(--border, var(--border-strong))',
};

const titleStyle: React.CSSProperties = {
  color: 'var(--text, var(--text-strong))',
  fontSize: 'var(--fs-body)',
  fontWeight: 700,
};

const badgeStyle = (hasPending: boolean): React.CSSProperties => ({
  background: hasPending ? '#facc1522' : 'var(--raised)',
  color: hasPending ? '#facc15' : 'var(--text-muted)',
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
  color: 'var(--loss)',
  fontSize: 'var(--fs-body)',
  margin: '8px 16px',
  padding: '8px 12px',
};

const emptyStyle: React.CSSProperties = {
  color: 'var(--text-muted)',
  fontSize: 'var(--fs-body)',
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
  borderBottom: '1px solid var(--border, var(--border-strong))',
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
  color: 'var(--text, var(--text-strong))',
  fontFamily: 'monospace',
  fontSize: 'var(--fs-body)',
  fontWeight: 600,
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  whiteSpace: 'nowrap',
};

const timeStyle: React.CSSProperties = {
  color: 'var(--text-muted)',
  fontSize: 'var(--fs-label)',
  flexShrink: 0,
};

const statusPillStyle: React.CSSProperties = {
  borderRadius: 10,
  fontSize: 'var(--fs-micro)',
  fontWeight: 700,
  padding: '2px 7px',
  textTransform: 'capitalize',
};

const expandedStyle: React.CSSProperties = {
  borderTop: '1px solid var(--border, var(--border-strong))',
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
  color: 'var(--text-dim)',
  fontSize: 'var(--fs-micro)',
  fontWeight: 700,
  letterSpacing: 0.5,
  textTransform: 'uppercase',
};

const codeStyle: React.CSSProperties = {
  background: 'var(--surface)',
  borderRadius: 6,
  color: 'var(--text)',
  fontFamily: 'monospace',
  fontSize: 'var(--fs-label)',
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
