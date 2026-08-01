// superadmin/LogsSection.tsx — live system logs with level filter and export
import React, { useEffect, useState, useCallback, useRef } from 'react';
import { superadminApi } from '../../hooks/useApi';
import { usePolling } from '../../hooks/usePolling';
import {
  SectionCard, ActionBtn, Select, Input,
  ErrorState,
} from './ui';
import type { LogEntry } from './types';
import { asArray, extractApiError } from '../../lib/utils';
import { ActionBanner } from '../../components/ActionBanner';

const LEVEL_COLORS: Record<string, { color: string; bg: string }> = {
  DEBUG:    { color: '#94a3b8', bg: '#1e293b' },
  INFO:     { color: '#60a5fa', bg: '#0c1a2e' },
  WARNING:  { color: '#fbbf24', bg: '#1c1200' },
  ERROR:    { color: '#f87171', bg: '#1a0000' },
  CRITICAL: { color: '#fca5a5', bg: '#2d0000' },
};

const LogsSection: React.FC = () => {
  const [logs, setLogs]         = useState<LogEntry[]>([]);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState('');
  const [levelFilter, setLevelFilter] = useState('');
  const [loggerFilter, setLoggerFilter] = useState('');
  const [search, setSearch]     = useState('');
  const [autoScroll, setAutoScroll] = useState(true);
  const [logLevels, setLogLevels] = useState<Record<string, string>>({});
  const [savingLevel, setSavingLevel] = useState<string | null>(null);
  const [msg, setMsg]           = useState('');
  const [msgOk, setMsgOk] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);
  const mountedRef = useRef(true);
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const params: Record<string, string> = { limit: '200' };
      if (levelFilter)  params.level  = levelFilter;
      if (loggerFilter) params.logger = loggerFilter;
      if (search)       params.search = search;
      const [logRes, lvlRes] = await Promise.all([
        superadminApi.logs(params),
        superadminApi.logLevels(),
      ]);
      if (!mountedRef.current) return;
      setLogs(asArray(logRes.data, 'logs'));
      setLogLevels(lvlRes.data);
    } catch (e: unknown) {
      if (!mountedRef.current) return;
      setError(extractApiError(e, 'Failed to load logs'));
    } finally { if (mountedRef.current) setLoading(false); }
  }, [levelFilter, loggerFilter, search]);

  useEffect(() => { load(); }, [load]);

  // Auto-refresh every 10s — pauses when tab is hidden
  usePolling(load, 10_000);

  useEffect(() => {
    if (autoScroll && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs, autoScroll]);

  const setLevel = async (logger: string, level: string) => {
    setSavingLevel(logger); setMsg('');
    try {
      await superadminApi.setLogLevel(logger, level);
      setLogLevels(prev => ({ ...prev, [logger]: level }));
      setMsgOk(true);
      setMsg(`Log level for ${logger} set to ${level}`);
    } catch (e: unknown) {
      setMsgOk(false);
      setMsg(extractApiError(e, 'Failed to set log level'));
    } finally { setSavingLevel(null); }
  };

  const exportLogs = async () => {
    try {
      const params: Record<string, string> = {};
      if (levelFilter)  params.level  = levelFilter;
      if (loggerFilter) params.logger = loggerFilter;
      const res = await superadminApi.exportLogs(params);
      const url = URL.createObjectURL(new Blob([res.data]));
      const a = document.createElement('a');
      a.href = url; a.download = `hopefx-logs-${Date.now()}.txt`;
      a.click(); URL.revokeObjectURL(url);
    } catch { setMsgOk(false); setMsg('Export failed'); }
  };

  const filteredLogs = logs.filter(l => {
    if (search && !l.message.toLowerCase().includes(search.toLowerCase()) &&
        !l.logger.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  return (
    <div style={{ animation: 'sa-fadein 0.2s ease' }}>


      {/* Log level controls */}
      {Object.keys(logLevels).length > 0 && (
        <SectionCard title="Log Level Controls" icon="🎚️" accent="#8b5cf6"
          subtitle="Adjust verbosity per logger without restarting">
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
            {Object.entries(logLevels).map(([logger, level]) => (
              <div key={logger} style={{
                display: 'flex', alignItems: 'center', gap: 8,
                background: '#1e293b', borderRadius: 8, padding: '8px 12px',
              }}>
                <span style={{ fontSize: 12, color: '#94a3b8', minWidth: 120 }}>{logger}</span>
                <select
                  value={level}
                  onChange={e => setLevel(logger, e.target.value)}
                  disabled={savingLevel === logger}
                  style={{
                    background: '#0f172a', border: '1px solid #334155', borderRadius: 5,
                    color: LEVEL_COLORS[level]?.color ?? '#94a3b8',
                    fontSize: 12, padding: '4px 8px', cursor: 'pointer',
                  }}
                >
                  {['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'].map(l => (
                    <option key={l} value={l}>{l}</option>
                  ))}
                </select>
                {savingLevel === logger && (
                  <div style={{ width: 12, height: 12, border: '2px solid #334155', borderTopColor: '#60a5fa', borderRadius: '50%', animation: 'sa-spin 0.7s linear infinite' }} />
                )}
              </div>
            ))}
          </div>
          <ActionBanner message={msg} ok={msgOk} />
        </SectionCard>
      )}

      {/* Log viewer */}
      <SectionCard
        title="System Logs"
        icon="📋"
        accent="#3b82f6"
        subtitle={`${filteredLogs.length} entries · Auto-refresh 10s`}
        noPad
        actions={
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#64748b', cursor: 'pointer' }}>
              <input type="checkbox" checked={autoScroll} onChange={e => setAutoScroll(e.target.checked)} />
              Auto-scroll
            </label>
            <ActionBtn label="Export" onClick={exportLogs} icon="⬇️" size="sm" />
            <ActionBtn label="Refresh" onClick={load} icon="🔄" size="sm" />
          </div>
        }
      >
        {/* Filters */}
        <div style={{ display: 'flex', gap: 10, padding: '12px 16px', borderBottom: '1px solid #1e293b', flexWrap: 'wrap' }}>
          <Select
            value={levelFilter}
            onChange={e => setLevelFilter(e.target.value)}
            options={[
              { value: '', label: 'All Levels' },
              { value: 'DEBUG',    label: 'Debug' },
              { value: 'INFO',     label: 'Info' },
              { value: 'WARNING',  label: 'Warning' },
              { value: 'ERROR',    label: 'Error' },
              { value: 'CRITICAL', label: 'Critical' },
            ]}
            style={{ width: 130 }}
          />
          <Input
            placeholder="Filter by logger…"
            value={loggerFilter}
            onChange={e => setLoggerFilter(e.target.value)}
            style={{ width: 180 }}
          />
          <Input
            placeholder="Search messages…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            style={{ flex: 1, minWidth: 160 }}
          />
        </div>

        {/* Log output */}
        {error ? (
          <div style={{ padding: 16 }}><ErrorState message={error} onRetry={load} /></div>
        ) : (
          <div style={{
            height: 520, overflowY: 'auto', fontFamily: 'monospace',
            fontSize: 12, background: '#020817',
          }}>
            {loading && filteredLogs.length === 0 ? (
              <div style={{ padding: 20, color: '#475569' }}>Loading logs…</div>
            ) : filteredLogs.length === 0 ? (
              <div style={{ padding: 20, color: '#475569' }}>No log entries match the current filters.</div>
            ) : (
              filteredLogs.map((l, i) => {
                const lc = LEVEL_COLORS[l.level] ?? LEVEL_COLORS.INFO;
                return (
                  <div key={i} style={{
                    display: 'flex', gap: 0, padding: '3px 0',
                    background: i % 2 === 0 ? 'transparent' : '#0a0f1a',
                    borderLeft: `3px solid ${lc.color}33`,
                  }}>
                    <span style={{ color: '#334155', padding: '0 10px', flexShrink: 0, minWidth: 160 }}>
                      {new Date(l.ts).toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                    </span>
                    <span style={{
                      color: lc.color, background: lc.bg,
                      padding: '0 6px', borderRadius: 3, flexShrink: 0,
                      minWidth: 70, textAlign: 'center', fontWeight: 700,
                    }}>
                      {l.level}
                    </span>
                    <span style={{ color: '#475569', padding: '0 10px', flexShrink: 0, minWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {l.logger}
                    </span>
                    <span style={{ color: '#94a3b8', paddingRight: 12, flex: 1 }}>
                      {l.message}
                    </span>
                    {l.trace_id && (
                      <span style={{ color: '#334155', paddingRight: 12, flexShrink: 0, fontSize: 10 }}>
                        {l.trace_id.slice(0, 8)}
                      </span>
                    )}
                  </div>
                );
              })
            )}
            <div ref={bottomRef} />
          </div>
        )}
      </SectionCard>
    </div>
  );
};

export default LogsSection;
