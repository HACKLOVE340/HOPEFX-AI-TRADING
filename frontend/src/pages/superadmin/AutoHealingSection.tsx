// superadmin/AutoHealingSection.tsx
// Autonomous Healing Engine — Super Admin control panel
import React, { useEffect, useState, useCallback, useMemo, useRef } from 'react';
import { usePolling } from '../../hooks/usePolling';
import { superadminApi } from '../../hooks/useApi';
import { EmptyState } from '../../components/EmptyState';
import {
  SectionCard, ActionBtn, KpiTile, StatusBadge,
  Toggle, Input, Select, Divider,
  ErrorState, LoadingRows, ConfirmDialog, Spinner,
} from './ui';
import { extractApiError } from '../../lib/utils';

// ── Types ─────────────────────────────────────────────────────────────────────

interface HealerLiveStatus {
  running: boolean;
  baseline_files: number;
  drift_events: number;
  patches_applied: number;
  patches_failed: number;
  last_scan: string | null;
}

interface TestCategory {
  key: string;
  label: string;
  description: string;
  accent: string;
  icon: string;
}

interface TestIndex {
  total: number;
  by_category: Record<string, number>;
  last_indexed: string | null;
  last_run: string | null;
  last_run_passed: number | null;
  last_run_failed: number | null;
}

interface HealingConfig {
  enabled: boolean;
  scan_interval_sec: number;
  patch_interval_sec: number;
  max_patch_bytes: number;
  aggressiveness: 'low' | 'medium' | 'aggressive' | 'nuclear';
  baseline_auto_rebuild: boolean;
  quarantine_enabled: boolean;
  quarantine_retention_days: number;
  tests_enabled: boolean;
  test_categories: Record<string, boolean>;
  test_execution_strategy: string[];
  test_timeout_sec: number;
  global_test_timeout_sec: number;
  parallel_tests: boolean;
  test_schedule_interval_min: number;
  require_approval_categories: string[];
  protected_paths: string;
  auto_rollback_sensitivity: 'low' | 'medium' | 'high';
  max_healing_attempts: number;
  healing_cooldown_sec: number;
  log_level: 'minimal' | 'standard' | 'verbose' | 'debug';
}

interface DriftEvent {
  path: string;
  type: 'modified' | 'deleted' | 'new_file';
  ts: string;
  expected?: string;
  actual?: string;
  protected?: boolean;
}

interface PatchRecord {
  endpoint: string;
  file: string;
  success: boolean;
  message: string;
  diff: string;
  applied_at: string;
}

interface QuarantineEntry {
  original: string;
  quarantined_to: string;
  ts: string;
}

interface PendingApproval {
  endpoint: string;
  fix: string;
  category?: string;
  queued_at: string;
}

interface TestRunResult {
  ok: boolean;
  ts?: string;
  passed?: number;
  failed?: number;
  errors?: number;
  duration_sec?: number;
  output?: string;
  status?: string;
  success?: boolean;
}

// ── Constants ─────────────────────────────────────────────────────────────────

const TEST_CATEGORIES: TestCategory[] = [
  { key: 'unit',        label: 'Core Unit Tests',            description: 'Fast isolated unit tests for core modules', accent: '#3b82f6', icon: '🔬' },
  { key: 'api',         label: 'API & Endpoint Tests',       description: 'FastAPI route and schema validation tests',  accent: '#8b5cf6', icon: '🌐' },
  { key: 'broker',      label: 'Broker Integration Tests',   description: 'Broker connector and order routing tests',   accent: '#f59e0b', icon: '🏦' },
  { key: 'risk',        label: 'Risk & Position Tests',      description: 'VaR, circuit breakers, position sizing',     accent: '#ef4444', icon: '⚡' },
  { key: 'ml',          label: 'ML Model & Signal Tests',    description: 'Model inference, drift, signal pipeline',    accent: '#a78bfa', icon: '🧠' },
  { key: 'security',    label: 'Security & Integrity Tests', description: 'Auth, JWT, self-healer, vault tests',        accent: '#f97316', icon: '🛡️' },
  { key: 'performance', label: 'Performance & Load Tests',   description: 'Latency, throughput, k6 load scenarios',     accent: '#06b6d4', icon: '📊' },
  { key: 'e2e',         label: 'End-to-End Trading Tests',   description: 'Full pipeline from signal to execution',     accent: '#22c55e', icon: '🔄' },
];

const STRATEGY_OPTIONS = [
  { value: 'on_drift',         label: 'Run on Drift Detection' },
  { value: 'before_patch',     label: 'Run Before Patch Application' },
  { value: 'after_patch',      label: 'Run After Patch Application' },
  { value: 'on_critical_alert',label: 'Run on Critical Alert Only' },
  { value: 'on_schedule',      label: 'Run on Schedule' },
];

const DEFAULT_CONFIG: HealingConfig = {
  // Defaults to OFF so that any path which mishandles this object fails closed.
  // Autonomous patching of a live trading platform is not a safe default, and
  // this object is what the form falls back to when the config cannot be read.
  enabled: false,
  scan_interval_sec: 120,
  patch_interval_sec: 60,
  max_patch_bytes: 65536,
  aggressiveness: 'medium',
  baseline_auto_rebuild: true,
  quarantine_enabled: true,
  quarantine_retention_days: 30,
  tests_enabled: true,
  test_categories: { unit: true, api: true, broker: true, risk: true, ml: true, security: true, performance: false, e2e: false },
  test_execution_strategy: ['after_patch', 'on_drift'],
  test_timeout_sec: 120,
  global_test_timeout_sec: 600,
  parallel_tests: true,
  test_schedule_interval_min: 60,
  require_approval_categories: ['nuclear', 'e2e'],
  protected_paths: 'live_trading.py,risk_manager.py,ml/models/,config/secrets/',
  auto_rollback_sensitivity: 'medium',
  max_healing_attempts: 3,
  healing_cooldown_sec: 300,
  log_level: 'standard',
};

// ── Helpers ───────────────────────────────────────────────────────────────────

const fmtDate = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—';

const fmtAgo = (iso: string | null): string => {
  if (!iso) return '—';
  const diff = Date.now() - new Date(iso).getTime();
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
};

// ── Live Status Card ──────────────────────────────────────────────────────────

const LiveStatusCard: React.FC<{
  status: HealerLiveStatus | null;
  testIndex: TestIndex | null;
  onRefresh: () => void;
  refreshing: boolean;
}> = ({ status, testIndex, onRefresh, refreshing }) => {
  const healerState = !status ? 'unknown'
    : status.running ? 'running'
    : 'stopped';

  const stateColor = healerState === 'running' ? '#4ade80'
    : healerState === 'stopped' ? '#f87171'
    : '#fbbf24';

  return (
    <div style={{
      background: 'linear-gradient(135deg, #0a1628 0%, #0f172a 100%)',
      border: '1px solid #1e293b',
      borderTop: `3px solid ${stateColor}`,
      borderRadius: 14,
      padding: '20px 24px',
      marginBottom: 20,
      position: 'relative',
      overflow: 'hidden',
    }}>
      <div style={{ position: 'absolute', top: 0, right: 0, width: 200, height: 200, background: `${stateColor}08`, borderRadius: '50%', transform: 'translate(60px, -60px)' }} />
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{
            width: 40, height: 40, borderRadius: 10,
            background: `${stateColor}22`, border: `1px solid ${stateColor}44`,
            display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 20,
          }}>🛡️</div>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: '#f1f5f9' }}>Autonomous Healing Engine</div>
            <div style={{ fontSize: 11, color: '#475569', marginTop: 1 }}>Real-time integrity monitor · Self-patching system</div>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <StatusBadge status={healerState === 'running' ? 'running' : healerState === 'stopped' ? 'stopped' : 'degraded'} />
          <ActionBtn label="Refresh" onClick={onRefresh} icon="🔄" size="sm" loading={refreshing} />
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12 }}>
        {[
          { label: 'Baseline Files',    value: status ? String(status.baseline_files) : '—',   icon: '📁', accent: '#3b82f6' },
          { label: 'Drift Events',      value: status ? String(status.drift_events) : '—',      icon: '⚠️', accent: status?.drift_events ? '#f59e0b' : '#22c55e' },
          { label: 'Patches Applied',   value: status ? String(status.patches_applied) : '—',   icon: '🔧', accent: '#22c55e' },
          { label: 'Patches Failed',    value: status ? String(status.patches_failed) : '—',    icon: '❌', accent: status?.patches_failed ? '#ef4444' : '#475569' },
          { label: 'Tests Indexed',     value: testIndex ? String(testIndex.total) : '—',       icon: '🧪', accent: '#8b5cf6' },
          { label: 'Last Scan',         value: fmtAgo(status?.last_scan ?? null),               icon: '🕐', accent: '#06b6d4' },
          { label: 'Last Test Run',     value: fmtAgo(testIndex?.last_run ?? null),             icon: '▶️', accent: '#a78bfa' },
          { label: 'Last Run Result',   value: testIndex?.last_run_passed != null ? `${testIndex.last_run_passed}✓ ${testIndex.last_run_failed ?? 0}✗` : '—', icon: '📋', accent: testIndex?.last_run_failed ? '#ef4444' : '#22c55e' },
        ].map(tile => (
          <KpiTile key={tile.label} label={tile.label} value={tile.value} icon={tile.icon} accent={tile.accent} />
        ))}
      </div>
    </div>
  );
};

// ── Healing Core Configuration ────────────────────────────────────────────────

const HealingCorePanel: React.FC<{
  cfg: HealingConfig;
  onChange: (patch: Partial<HealingConfig>) => void;
  onRebuildBaseline: () => void;
  rebuildBusy: boolean;
}> = ({ cfg, onChange, onRebuildBaseline, rebuildBusy }) => (
  <SectionCard title="Healing Core Configuration" icon="⚙️" accent="#3b82f6"
    subtitle="Master controls for the autonomous healing engine">
    <Toggle
      label="Enable Self-Healing System"
      description="Master switch — disabling stops all drift detection, patching, and test execution"
      checked={cfg.enabled}
      onChange={v => onChange({ enabled: v })}
      accent="#22c55e"
    />
    <Divider />

    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 16, marginTop: 12 }}>
      <Input
        label="Scan Frequency (seconds)"
        type="number"
        value={cfg.scan_interval_sec}
        onChange={e => onChange({ scan_interval_sec: Number(e.target.value) })}
        min={30}
      />
      <Input
        label="Patch Frequency (seconds)"
        type="number"
        value={cfg.patch_interval_sec}
        onChange={e => onChange({ patch_interval_sec: Number(e.target.value) })}
        min={30}
      />
      <Input
        label="Max Patch Size (bytes)"
        type="number"
        value={cfg.max_patch_bytes}
        onChange={e => onChange({ max_patch_bytes: Number(e.target.value) })}
        min={1024}
      />
    </div>

    <Divider />

    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginTop: 4 }}>
      <div>
        <Toggle
          label="Baseline Auto-Rebuild"
          description="Automatically rebuild the integrity baseline after confirmed safe patches"
          checked={cfg.baseline_auto_rebuild}
          onChange={v => onChange({ baseline_auto_rebuild: v })}
        />
      </div>
      <div style={{ display: 'flex', alignItems: 'center', paddingTop: 8 }}>
        <ActionBtn
          label={rebuildBusy ? 'Rebuilding…' : 'Manual Rebuild Now'}
          onClick={onRebuildBaseline}
          variant="warning"
          icon="🔨"
          loading={rebuildBusy}
        />
      </div>
    </div>

    <Divider />

    <Toggle
      label="Quarantine System"
      description="Copy suspicious files to quarantine before any modification or patch attempt"
      checked={cfg.quarantine_enabled}
      onChange={v => onChange({ quarantine_enabled: v })}
    />
    {cfg.quarantine_enabled && (
      <div style={{ marginTop: 8, paddingLeft: 0 }}>
        <Input
          label="Quarantine Retention (days)"
          type="number"
          value={cfg.quarantine_retention_days}
          onChange={e => onChange({ quarantine_retention_days: Number(e.target.value) })}
          min={1}
          max={365}
          style={{ maxWidth: 200 }}
        />
      </div>
    )}
  </SectionCard>
);

// ── Test Intelligence Panel ───────────────────────────────────────────────────

const TestIntelligencePanel: React.FC<{
  cfg: HealingConfig;
  testIndex: TestIndex | null;
  onChange: (patch: Partial<HealingConfig>) => void;
  onReindex: () => void;
  reindexBusy: boolean;
}> = ({ cfg, testIndex, onChange, onReindex, reindexBusy }) => {
  const allEnabled = TEST_CATEGORIES.every(c => cfg.test_categories[c.key]);
  const toggleAll = (v: boolean) => {
    const all: Record<string, boolean> = {};
    TEST_CATEGORIES.forEach(c => { all[c.key] = v; });
    onChange({ test_categories: all });
  };

  const toggleStrategy = (val: string) => {
    const cur = cfg.test_execution_strategy;
    onChange({
      test_execution_strategy: cur.includes(val)
        ? cur.filter(s => s !== val)
        : [...cur, val],
    });
  };

  return (
    <SectionCard title="Intelligent Test Orchestration" icon="🧪" accent="#8b5cf6"
      subtitle="Automated test discovery, categorization, and execution strategy"
      actions={
        <ActionBtn
          label={reindexBusy ? 'Scanning…' : 'Re-scan Tests'}
          onClick={onReindex}
          icon="🔍"
          size="sm"
          loading={reindexBusy}
          variant="primary"
        />
      }>

      {/* Index stats bar */}
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))',
        gap: 10, marginBottom: 20,
        padding: '14px 16px',
        background: '#0a1628', borderRadius: 10, border: '1px solid #1e293b',
      }}>
        <div>
          <div style={{ fontSize: 10, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.07em' }}>Total Tests</div>
          <div style={{ fontSize: 24, fontWeight: 800, color: '#f1f5f9', marginTop: 2 }}>{testIndex?.total ?? '—'}</div>
        </div>
        {TEST_CATEGORIES.map(cat => (
          <div key={cat.key}>
            <div style={{ fontSize: 10, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.07em' }}>{cat.label.split(' ')[0]}</div>
            <div style={{ fontSize: 18, fontWeight: 700, color: cat.accent, marginTop: 2 }}>
              {testIndex?.by_category?.[cat.key] ?? 0}
            </div>
          </div>
        ))}
        <div>
          <div style={{ fontSize: 10, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.07em' }}>Last Indexed</div>
          <div style={{ fontSize: 11, fontWeight: 600, color: '#94a3b8', marginTop: 4 }}>{fmtAgo(testIndex?.last_indexed ?? null)}</div>
        </div>
      </div>

      <Toggle
        label="Enable Automated Test Execution"
        description="Allow the healing engine to run tests automatically as part of its decision pipeline"
        checked={cfg.tests_enabled}
        onChange={v => onChange({ tests_enabled: v })}
        accent="#8b5cf6"
      />

      {cfg.tests_enabled && (
        <>
          <Divider />
          {/* Master toggle + category grid */}
          <div style={{ marginBottom: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                Test Categories
              </div>
              <ActionBtn
                label={allEnabled ? 'Disable All' : 'Enable All'}
                onClick={() => toggleAll(!allEnabled)}
                size="sm"
                variant={allEnabled ? 'danger' : 'success'}
              />
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 8 }}>
              {TEST_CATEGORIES.map(cat => {
                const count = testIndex?.by_category?.[cat.key] ?? 0;
                const enabled = cfg.test_categories[cat.key] ?? false;
                return (
                  <div key={cat.key} style={{
                    background: enabled ? `${cat.accent}11` : '#0f172a',
                    border: `1px solid ${enabled ? cat.accent + '33' : '#1e293b'}`,
                    borderRadius: 10, padding: '10px 14px',
                    transition: 'all 0.15s',
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ fontSize: 16 }}>{cat.icon}</span>
                        <div>
                          <div style={{ fontSize: 12, fontWeight: 600, color: enabled ? '#f1f5f9' : '#64748b' }}>{cat.label}</div>
                          <div style={{ fontSize: 10, color: '#475569', marginTop: 1 }}>{cat.description}</div>
                        </div>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0, marginLeft: 8 }}>
                        <span style={{
                          fontSize: 11, fontWeight: 700,
                          color: enabled ? cat.accent : '#334155',
                          background: enabled ? `${cat.accent}22` : '#1e293b',
                          padding: '2px 7px', borderRadius: 10,
                        }}>{count}</span>
                        <div
                          role="switch"
                          aria-checked={enabled}
                          tabIndex={0}
                          onClick={() => onChange({ test_categories: { ...cfg.test_categories, [cat.key]: !enabled } })}
                          onKeyDown={e => (e.key === 'Enter' || e.key === ' ') && onChange({ test_categories: { ...cfg.test_categories, [cat.key]: !enabled } })}
                          style={{
                            width: 36, height: 20, borderRadius: 10, flexShrink: 0,
                            background: enabled ? cat.accent : '#374151',
                            position: 'relative', cursor: 'pointer', transition: 'background 0.2s',
                          }}
                        >
                          <div style={{
                            position: 'absolute', top: 2, width: 16, height: 16, borderRadius: '50%',
                            background: '#fff', transition: 'transform 0.2s',
                            transform: enabled ? 'translateX(16px)' : 'translateX(2px)',
                            boxShadow: '0 1px 3px rgba(0,0,0,0.4)',
                          }} />
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <Divider />

          {/* Execution strategy */}
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }}>
              Test Execution Strategy
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {STRATEGY_OPTIONS.map(opt => {
                const active = cfg.test_execution_strategy.includes(opt.value);
                return (
                  <button
                    key={opt.value}
                    onClick={() => toggleStrategy(opt.value)}
                    style={{
                      padding: '6px 14px', borderRadius: 20, fontSize: 12, fontWeight: 600,
                      cursor: 'pointer', transition: 'all 0.15s',
                      background: active ? '#1e3a5f' : '#1e293b',
                      color: active ? '#60a5fa' : '#64748b',
                      border: `1px solid ${active ? '#1d4ed8' : '#334155'}`,
                    }}
                  >{opt.label}</button>
                );
              })}
            </div>
            {cfg.test_execution_strategy.includes('on_schedule') && (
              <div style={{ marginTop: 12 }}>
                <Input
                  label="Schedule Interval (minutes)"
                  type="number"
                  value={cfg.test_schedule_interval_min}
                  onChange={e => onChange({ test_schedule_interval_min: Number(e.target.value) })}
                  min={5}
                  style={{ maxWidth: 220 }}
                />
              </div>
            )}
          </div>

          <Divider />

          {/* Timeouts + parallelism */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            <Input
              label="Timeout Per Suite (seconds)"
              type="number"
              value={cfg.test_timeout_sec}
              onChange={e => onChange({ test_timeout_sec: Number(e.target.value) })}
              min={10}
            />
            <Input
              label="Global Test Timeout (seconds)"
              type="number"
              value={cfg.global_test_timeout_sec}
              onChange={e => onChange({ global_test_timeout_sec: Number(e.target.value) })}
              min={60}
            />
          </div>
          <div style={{ marginTop: 12 }}>
            <Toggle
              label="Run Tests in Parallel"
              description="Execute test suites concurrently — faster but uses more resources"
              checked={cfg.parallel_tests}
              onChange={v => onChange({ parallel_tests: v })}
            />
          </div>
        </>
      )}
    </SectionCard>
  );
};

// ── Safety Gates Panel ────────────────────────────────────────────────────────

const AGGRESSIVENESS_OPTS = [
  { value: 'low',        label: 'Low — Read-only analysis, no auto-patch',         color: '#4ade80' },
  { value: 'medium',     label: 'Medium — Patch safe files, skip critical paths',   color: '#fbbf24' },
  { value: 'aggressive', label: 'Aggressive — Patch all tracked files',             color: '#f97316' },
  { value: 'nuclear',    label: 'Nuclear — Full override, no approval gates',       color: '#ef4444' },
];

const SafetyGatesPanel: React.FC<{
  cfg: HealingConfig;
  onChange: (patch: Partial<HealingConfig>) => void;
}> = ({ cfg, onChange }) => {
  const toggleApproval = (cat: string) => {
    const cur = cfg.require_approval_categories;
    onChange({
      require_approval_categories: cur.includes(cat)
        ? cur.filter(c => c !== cat)
        : [...cur, cat],
    });
  };

  return (
    <SectionCard title="Healing Intelligence & Safety Gates" icon="🔒" accent="#ef4444"
      subtitle="Approval matrix, protected paths, rollback sensitivity, and operational limits">

      {/* Aggressiveness */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }}>
          Healing Aggressiveness
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {AGGRESSIVENESS_OPTS.map(opt => {
            const active = cfg.aggressiveness === opt.value;
            return (
              <div
                key={opt.value}
                onClick={() => onChange({ aggressiveness: opt.value as HealingConfig['aggressiveness'] })}
                style={{
                  display: 'flex', alignItems: 'center', gap: 12,
                  padding: '10px 14px', borderRadius: 10, cursor: 'pointer',
                  background: active ? `${opt.color}11` : '#0f172a',
                  border: `1px solid ${active ? opt.color + '44' : '#1e293b'}`,
                  transition: 'all 0.15s',
                }}
              >
                <div style={{
                  width: 16, height: 16, borderRadius: '50%', flexShrink: 0,
                  background: active ? opt.color : '#334155',
                  border: `2px solid ${active ? opt.color : '#475569'}`,
                  boxShadow: active ? `0 0 8px ${opt.color}66` : 'none',
                  transition: 'all 0.15s',
                }} />
                <span style={{ fontSize: 13, color: active ? '#f1f5f9' : '#64748b', fontWeight: active ? 600 : 400 }}>
                  {opt.label}
                </span>
                {opt.value === 'nuclear' && active && (
                  <span style={{
                    marginLeft: 'auto', fontSize: 10, fontWeight: 700,
                    color: '#ef4444', background: '#450a0a',
                    border: '1px solid #dc2626', borderRadius: 4, padding: '2px 7px',
                  }}>⚠️ DANGEROUS</span>
                )}
              </div>
            );
          })}
        </div>
      </div>

      <Divider />

      {/* Approval matrix */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>
          Smart Approval Matrix
        </div>
        <div style={{ fontSize: 11, color: '#475569', marginBottom: 10 }}>
          Categories that require manual approval before the healer applies a patch
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {TEST_CATEGORIES.map(cat => {
            const required = cfg.require_approval_categories.includes(cat.key);
            return (
              <button
                key={cat.key}
                onClick={() => toggleApproval(cat.key)}
                style={{
                  padding: '5px 12px', borderRadius: 20, fontSize: 11, fontWeight: 600,
                  cursor: 'pointer', transition: 'all 0.15s',
                  background: required ? '#450a0a' : '#1e293b',
                  color: required ? '#f87171' : '#64748b',
                  border: `1px solid ${required ? '#dc2626' : '#334155'}`,
                }}
              >{cat.icon} {cat.label.split(' ')[0]} {required ? '🔒' : ''}</button>
            );
          })}
        </div>
      </div>

      <Divider />

      {/* Protected paths */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>
          Protected Paths
        </div>
        <div style={{ fontSize: 11, color: '#475569', marginBottom: 8 }}>
          Comma-separated files/directories the healer is forbidden from modifying
        </div>
        <Input
          value={cfg.protected_paths}
          onChange={e => onChange({ protected_paths: e.target.value })}
          placeholder="live_trading.py,risk_manager.py,ml/models/"
        />
      </div>

      <Divider />

      {/* Operational limits */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 16, marginBottom: 16 }}>
        <Select
          label="Auto-Rollback Sensitivity"
          value={cfg.auto_rollback_sensitivity}
          onChange={e => onChange({ auto_rollback_sensitivity: e.target.value as HealingConfig['auto_rollback_sensitivity'] })}
          options={[
            { value: 'low',    label: 'Low — Rollback only on crash' },
            { value: 'medium', label: 'Medium — Rollback on test fail' },
            { value: 'high',   label: 'High — Rollback on any error' },
          ]}
        />
        <Input
          label="Max Healing Attempts / Incident"
          type="number"
          value={cfg.max_healing_attempts}
          onChange={e => onChange({ max_healing_attempts: Number(e.target.value) })}
          min={1}
          max={10}
        />
        <Input
          label="Healing Cooldown (seconds)"
          type="number"
          value={cfg.healing_cooldown_sec}
          onChange={e => onChange({ healing_cooldown_sec: Number(e.target.value) })}
          min={30}
        />
      </div>

      <Divider />

      <Select
        label="Healing Event Log Level"
        value={cfg.log_level}
        onChange={e => onChange({ log_level: e.target.value as HealingConfig['log_level'] })}
        options={[
          { value: 'minimal',  label: 'Minimal — Errors and critical events only' },
          { value: 'standard', label: 'Standard — All healing actions' },
          { value: 'verbose',  label: 'Verbose — Actions + decisions + diffs' },
          { value: 'debug',    label: 'Debug — Full trace (high volume)' },
        ]}
      />
    </SectionCard>
  );
};

// ── Drift Event Log ───────────────────────────────────────────────────────────

const DRIFT_TYPE_COLORS: Record<string, string> = {
  modified: '#f59e0b',
  deleted:  '#ef4444',
  new_file: '#3b82f6',
};

const DriftLogPanel: React.FC<{
  events: DriftEvent[];
  loading: boolean;
  onRefresh: () => void;
}> = ({ events, loading, onRefresh }) => (
  <SectionCard title="Drift Event Log" icon="⚠️" accent="#f59e0b"
    subtitle="File integrity violations detected by the scan loop"
    actions={<ActionBtn label="Refresh" onClick={onRefresh} icon="🔄" size="sm" loading={loading} />}>
    {events.length === 0 ? (
      <div style={{ textAlign: 'center', padding: '24px 0', color: '#475569', fontSize: 13 }}>
        No drift events — all tracked files match baseline
      </div>
    ) : (
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ borderBottom: '1px solid #1e293b' }}>
              {['Time', 'Type', 'File', 'Protected', 'Hash (expected→actual)'].map(h => (
                <th key={h} style={{ padding: '6px 10px', textAlign: 'left', color: '#475569', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', fontSize: 10, whiteSpace: 'nowrap' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {events.slice().reverse().map((e, i) => (
              <tr key={i} className="sa-row" style={{ borderBottom: '1px solid #0f172a' }}>
                <td style={{ padding: '7px 10px', color: '#64748b', whiteSpace: 'nowrap' }}>{fmtDate(e.ts)}</td>
                <td style={{ padding: '7px 10px' }}>
                  <span style={{
                    fontSize: 10, fontWeight: 700, padding: '2px 7px', borderRadius: 4,
                    background: `${DRIFT_TYPE_COLORS[e.type] ?? '#475569'}22`,
                    color: DRIFT_TYPE_COLORS[e.type] ?? '#94a3b8',
                    textTransform: 'uppercase',
                  }}>{e.type}</span>
                </td>
                <td style={{ padding: '7px 10px', color: '#e2e8f0', fontFamily: 'monospace', fontSize: 11 }}>{e.path}</td>
                <td style={{ padding: '7px 10px', textAlign: 'center' }}>
                  {e.protected && <span style={{ color: '#ef4444', fontSize: 11, fontWeight: 700 }}>🔒</span>}
                </td>
                <td style={{ padding: '7px 10px', color: '#64748b', fontFamily: 'monospace', fontSize: 10 }}>
                  {e.expected && e.actual ? `${e.expected}…→${e.actual}…` : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )}
  </SectionCard>
);

// ── Patch History Panel ───────────────────────────────────────────────────────

const PatchHistoryPanel: React.FC<{
  patches: PatchRecord[];
  loading: boolean;
  onRefresh: () => void;
}> = ({ patches, loading, onRefresh }) => {
  const [expandedDiff, setExpandedDiff] = useState<number | null>(null);
  return (
    <SectionCard title="Patch History" icon="🔧" accent="#22c55e"
      subtitle="All patch attempts — applied, rejected, and rolled back"
      actions={<ActionBtn label="Refresh" onClick={onRefresh} icon="🔄" size="sm" loading={loading} />}>
      {patches.length === 0 ? (
        <EmptyState compact icon="🩹" title="No patches applied yet" description="Auto-heal patches will appear here once the system detects and resolves issues." />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {patches.slice().reverse().map((p, i) => (
            <div key={i} style={{
              background: p.success ? '#052e1622' : '#450a0a22',
              border: `1px solid ${p.success ? '#16a34a33' : '#dc262633'}`,
              borderRadius: 8, padding: '10px 14px',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                    <span style={{ fontSize: 11, fontWeight: 700, color: p.success ? '#4ade80' : '#f87171' }}>
                      {p.success ? '✓ APPLIED' : '✗ REJECTED'}
                    </span>
                    <span style={{ fontSize: 11, color: '#64748b' }}>{fmtDate(p.applied_at)}</span>
                  </div>
                  <div style={{ fontSize: 12, color: '#e2e8f0', fontFamily: 'monospace', marginBottom: 2 }}>{p.file}</div>
                  <div style={{ fontSize: 11, color: '#64748b' }}>{p.message}</div>
                </div>
                {p.diff && (
                  <ActionBtn
                    label={expandedDiff === i ? 'Hide Diff' : 'View Diff'}
                    onClick={() => setExpandedDiff(expandedDiff === i ? null : i)}
                    size="sm" variant="ghost"
                  />
                )}
              </div>
              {expandedDiff === i && p.diff && (
                <pre style={{
                  marginTop: 10, padding: '10px 12px', borderRadius: 6,
                  background: '#020817', border: '1px solid #1e293b',
                  fontSize: 10, color: '#94a3b8', overflowX: 'auto',
                  maxHeight: 300, lineHeight: 1.5,
                }}>{p.diff}</pre>
              )}
            </div>
          ))}
        </div>
      )}
    </SectionCard>
  );
};

// ── Quarantine Viewer ─────────────────────────────────────────────────────────

const QuarantinePanel: React.FC<{
  entries: QuarantineEntry[];
  loading: boolean;
  onRefresh: () => void;
}> = ({ entries, loading, onRefresh }) => (
  <SectionCard title="Quarantine Log" icon="🔐" accent="#f97316"
    subtitle="Files copied to quarantine before any modification"
    actions={<ActionBtn label="Refresh" onClick={onRefresh} icon="🔄" size="sm" loading={loading} />}>
    {entries.length === 0 ? (
      <EmptyState compact icon="🔒" title="Quarantine is empty" description="Suspicious files and processes will be isolated here when detected." />
    ) : (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {entries.slice().reverse().map((e, i) => (
          <div key={i} style={{
            display: 'grid', gridTemplateColumns: '140px 1fr 1fr',
            gap: 12, padding: '8px 12px', borderRadius: 7,
            background: '#0f172a', border: '1px solid #1e293b',
            fontSize: 11, alignItems: 'center',
          }}>
            <span style={{ color: '#64748b', whiteSpace: 'nowrap' }}>{fmtDate(e.ts)}</span>
            <span style={{ color: '#e2e8f0', fontFamily: 'monospace', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{e.original}</span>
            <span style={{ color: '#475569', fontFamily: 'monospace', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>→ {e.quarantined_to}</span>
          </div>
        ))}
      </div>
    )}
  </SectionCard>
);

// ── Pending Approval Panel ────────────────────────────────────────────────────

const PendingApprovalPanel: React.FC<{
  patches: PendingApproval[];
  loading: boolean;
  onRefresh: () => void;
  onApprove: (idx: number) => void;
  approvingIdx: number | null;
}> = ({ patches, loading, onRefresh, onApprove, approvingIdx }) => (
  <SectionCard title="Pending Approval Queue" icon="📋" accent="#a78bfa"
    subtitle="Patches waiting for manual approval before the healer applies them"
    actions={<ActionBtn label="Refresh" onClick={onRefresh} icon="🔄" size="sm" loading={loading} />}>
    {patches.length === 0 ? (
      <div style={{ textAlign: 'center', padding: '24px 0', color: '#475569', fontSize: 13 }}>No patches awaiting approval</div>
    ) : (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {patches.map((p, i) => (
          <div key={i} style={{
            background: '#1e1040', border: '1px solid #4c1d9533',
            borderRadius: 8, padding: '12px 14px',
            display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12,
          }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                {p.category && (
                  <span style={{ fontSize: 10, fontWeight: 700, color: '#a78bfa', background: '#2e1065', padding: '2px 7px', borderRadius: 4, textTransform: 'uppercase' }}>
                    {p.category}
                  </span>
                )}
                <span style={{ fontSize: 11, color: '#64748b' }}>Queued {fmtDate(p.queued_at)}</span>
              </div>
              <div style={{ fontSize: 12, color: '#e2e8f0', fontFamily: 'monospace' }}>{p.endpoint}</div>
            </div>
            <ActionBtn
              label={approvingIdx === i ? 'Approving…' : 'Approve'}
              onClick={() => onApprove(i)}
              variant="success"
              size="sm"
              loading={approvingIdx === i}
            />
          </div>
        ))}
      </div>
    )}
  </SectionCard>
);

// ── Test Run Panel ────────────────────────────────────────────────────────────

const TestRunPanel: React.FC<{
  onRunTests: () => void;
  running: boolean;
  lastResult: TestRunResult | null;
}> = ({ onRunTests, running, lastResult }) => {
  const [showOutput, setShowOutput] = useState(false);
  return (
    <SectionCard title="Manual Test Trigger" icon="▶️" accent="#06b6d4"
      subtitle="Run the enabled test suites immediately and see results">
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: lastResult ? 16 : 0 }}>
        <ActionBtn
          label={running ? 'Running Tests…' : 'Run Tests Now'}
          onClick={onRunTests}
          variant="primary"
          icon="▶️"
          loading={running}
        />
        {lastResult && !running && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{
              fontSize: 12, fontWeight: 700,
              color: lastResult.success ? '#4ade80' : '#f87171',
            }}>
              {lastResult.success ? '✓ PASSED' : '✗ FAILED'}
            </span>
            {lastResult.passed != null && (
              <span style={{ fontSize: 12, color: '#4ade80' }}>{lastResult.passed} passed</span>
            )}
            {lastResult.failed != null && lastResult.failed > 0 && (
              <span style={{ fontSize: 12, color: '#f87171' }}>{lastResult.failed} failed</span>
            )}
            {lastResult.duration_sec != null && (
              <span style={{ fontSize: 11, color: '#64748b' }}>{lastResult.duration_sec}s</span>
            )}
            {lastResult.ts && (
              <span style={{ fontSize: 11, color: '#475569' }}>{fmtAgo(lastResult.ts)}</span>
            )}
          </div>
        )}
      </div>
      {lastResult?.output && (
        <>
          <ActionBtn
            label={showOutput ? 'Hide Output' : 'Show Output'}
            onClick={() => setShowOutput(v => !v)}
            size="sm" variant="ghost"
          />
          {showOutput && (
            <pre style={{
              marginTop: 10, padding: '12px 14px', borderRadius: 8,
              background: '#020817', border: '1px solid #1e293b',
              fontSize: 10, color: '#94a3b8', overflowX: 'auto',
              maxHeight: 400, lineHeight: 1.6, whiteSpace: 'pre-wrap',
            }}>{lastResult.output}</pre>
          )}
        </>
      )}
    </SectionCard>
  );
};

// ── Main Component ────────────────────────────────────────────────────────────

// ── Tab navigation for the live panels ───────────────────────────────────────

type LiveTab = 'drift' | 'patches' | 'quarantine' | 'approval';

const LIVE_TABS: { id: LiveTab; label: string; icon: string; accent: string }[] = [
  { id: 'drift',     label: 'Drift Events',      icon: '⚠️', accent: '#f59e0b' },
  { id: 'patches',   label: 'Patch History',      icon: '🔧', accent: '#22c55e' },
  { id: 'quarantine',label: 'Quarantine',         icon: '🔐', accent: '#f97316' },
  { id: 'approval',  label: 'Pending Approval',   icon: '📋', accent: '#a78bfa' },
];

// ── Main Component ────────────────────────────────────────────────────────────

const AutoHealingSection: React.FC = () => {
  const [loading, setLoading]           = useState(true);
  const [saving, setSaving]             = useState(false);
  const [error, setError]               = useState('');
  const [msg, setMsg]                   = useState('');
  const [msgType, setMsgType]           = useState<'ok' | 'err'>('ok');
  const [refreshing, setRefreshing]     = useState(false);
  const [rebuildBusy, setRebuildBusy]   = useState(false);
  const [reindexBusy, setReindexBusy]   = useState(false);
  const [testRunBusy, setTestRunBusy]   = useState(false);
  const [confirmNuclear, setConfirmNuclear] = useState(false);
  const [pendingCfg, setPendingCfg]     = useState<HealingConfig | null>(null);
  const [configLoadFailed, setConfigLoadFailed] = useState(false);
  const [approvalFailed, setApprovalFailed]     = useState(false);
  const [confirmEnable, setConfirmEnable]       = useState(false);
  const [activeTab, setActiveTab]       = useState<LiveTab>('drift');
  const [approvingIdx, setApprovingIdx] = useState<number | null>(null);

  // Live data
  const [liveStatus, setLiveStatus]     = useState<HealerLiveStatus | null>(null);
  const [testIndex, setTestIndex]       = useState<TestIndex | null>(null);
  const [cfg, setCfg]                   = useState<HealingConfig>(DEFAULT_CONFIG);
  const [driftEvents, setDriftEvents]   = useState<DriftEvent[]>([]);
  const [patchHistory, setPatchHistory] = useState<PatchRecord[]>([]);
  const [quarantine, setQuarantine]     = useState<QuarantineEntry[]>([]);
  const [pendingApproval, setPendingApproval] = useState<PendingApproval[]>([]);
  const [lastTestResult, setLastTestResult]   = useState<TestRunResult | null>(null);

  // Loading states per panel
  const [driftLoading, setDriftLoading]       = useState(false);
  const [patchLoading, setPatchLoading]       = useState(false);
  const [quarLoading, setQuarLoading]         = useState(false);
  const [approvalLoading, setApprovalLoading] = useState(false);

  const mountedRef = useRef(true);
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

  const errDetail = (e: unknown, fb: string) => extractApiError(e, fb);

  const showMsg = (text: string, type: 'ok' | 'err' = 'ok') => {
    setMsg(text); setMsgType(type);
    setTimeout(() => setMsg(''), 6000);
  };

  // ── Loaders ────────────────────────────────────────────────────────────────

  const loadStatus = useCallback(async () => {
    try {
      const [healRes, testRes] = await Promise.all([
        superadminApi.autoHealStatus(),
        superadminApi.autoHealTestIndex(),
      ]);
      if (!mountedRef.current) return;
      const h = healRes.data;
      setLiveStatus({
        running:         h.running ?? h.status === 'running',
        baseline_files:  h.baseline_files ?? h.tracked_files ?? 0,
        drift_events:    h.drift_events ?? 0,
        patches_applied: h.patches_applied ?? 0,
        patches_failed:  h.patches_failed ?? 0,
        last_scan:       h.last_scan ?? null,
      });
      const t = testRes.data;
      setTestIndex({
        total:            t.total ?? 0,
        by_category:      t.by_category ?? {},
        last_indexed:     t.last_indexed ?? null,
        last_run:         t.last_run ?? null,
        last_run_passed:  t.last_run_passed ?? null,
        last_run_failed:  t.last_run_failed ?? null,
      });
    } catch { /* silent poll */ }
  }, []);

  const loadDrift = useCallback(async () => {
    setDriftLoading(true);
    try {
      const res = await superadminApi.autoHealDrift(200);
      if (!mountedRef.current) return;
      setDriftEvents(res.data.events ?? []);
    } catch { /* silent */ } finally { if (mountedRef.current) setDriftLoading(false); }
  }, []);

  const loadPatches = useCallback(async () => {
    setPatchLoading(true);
    try {
      const res = await superadminApi.autoHealPatches(100);
      if (!mountedRef.current) return;
      setPatchHistory(res.data.patches ?? []);
    } catch { /* silent */ } finally { if (mountedRef.current) setPatchLoading(false); }
  }, []);

  const loadQuarantine = useCallback(async () => {
    setQuarLoading(true);
    try {
      const res = await superadminApi.autoHealQuarantine();
      if (!mountedRef.current) return;
      setQuarantine(res.data.entries ?? []);
    } catch { /* silent */ } finally { if (mountedRef.current) setQuarLoading(false); }
  }, []);

  const loadApproval = useCallback(async () => {
    setApprovalLoading(true);
    try {
      const res = await superadminApi.autoHealPendingApproval();
      if (!mountedRef.current) return;
      setPendingApproval(res.data.patches ?? []);
      setApprovalFailed(false);
    } catch {
      // "Unavailable" and "nothing pending" are different answers. Failing
      // silently here renders an empty approvals queue, and a superadmin
      // concludes no patches are waiting when some may be queued against
      // production.
      if (!mountedRef.current) return;
      setApprovalFailed(true);
    } finally { if (mountedRef.current) setApprovalLoading(false); }
  }, []);

  const loadConfig = useCallback(async () => {
    try {
      const res = await superadminApi.autoHealConfig();
      if (!mountedRef.current) return;
      setCfg({ ...DEFAULT_CONFIG, ...res.data });
      setConfigLoadFailed(false);
    } catch {
      // Do NOT fall back to defaults and carry on. This form is saved wholesale,
      // so rendering a plausible default configuration after a failed read lets
      // a superadmin change one unrelated toggle, hit Save, and switch on
      // automated patching, quarantine and rollback of a live trading system
      // that was deliberately off.
      if (!mountedRef.current) return;
      setConfigLoadFailed(true);
    }
  }, []);

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      await Promise.all([loadStatus(), loadConfig(), loadDrift(), loadPatches(), loadQuarantine(), loadApproval()]);
    } catch (e: unknown) {
      if (!mountedRef.current) return;
      setError(errDetail(e, 'Failed to load healing configuration'));
    } finally { if (mountedRef.current) setLoading(false); }
  }, [loadStatus, loadConfig, loadDrift, loadPatches, loadQuarantine, loadApproval]);

  useEffect(() => { load(); }, [load]);

  // Refresh status + pending approvals every 15s — pauses when tab is hidden
  usePolling(() => { loadStatus(); loadApproval(); }, 15_000);

  // Reload active tab data when tab changes
  useEffect(() => {
    if (activeTab === 'drift')     loadDrift();
    if (activeTab === 'patches')   loadPatches();
    if (activeTab === 'quarantine') loadQuarantine();
    if (activeTab === 'approval')  loadApproval();
  }, [activeTab, loadDrift, loadPatches, loadQuarantine, loadApproval]);

  // ── Handlers ───────────────────────────────────────────────────────────────

  const handleRefresh = async () => {
    setRefreshing(true);
    await Promise.all([loadStatus(), loadDrift(), loadPatches(), loadQuarantine(), loadApproval()]);
    setRefreshing(false);
  };

  const handleRebuildBaseline = async () => {
    setRebuildBusy(true);
    try {
      await superadminApi.autoHealRebuildBaseline();
      showMsg('Baseline rebuild triggered — this may take a moment');
      setTimeout(loadStatus, 3000);
    } catch (e: unknown) {
      showMsg(errDetail(e, 'Rebuild failed'), 'err');
    } finally { setRebuildBusy(false); }
  };

  const handleReindex = async () => {
    setReindexBusy(true);
    try {
      await superadminApi.autoHealReindexTests();
      showMsg('Test re-scan started — index will update shortly');
      setTimeout(loadStatus, 4000);
    } catch (e: unknown) {
      showMsg(errDetail(e, 'Re-scan failed'), 'err');
    } finally { setReindexBusy(false); }
  };

  const handleRunTests = async () => {
    setTestRunBusy(true);
    try {
      const res = await superadminApi.autoHealRunTests();
      setLastTestResult(res.data);
      showMsg(res.data.success ? `Tests passed: ${res.data.passed ?? 0} ✓` : `Tests failed: ${res.data.failed ?? 0} ✗`, res.data.success ? 'ok' : 'err');
      setTimeout(loadStatus, 2000);
    } catch (e: unknown) {
      showMsg(errDetail(e, 'Test run failed'), 'err');
    } finally { setTestRunBusy(false); }
  };

  const handleApprove = async (idx: number) => {
    setApprovingIdx(idx);
    try {
      await superadminApi.autoHealApprovePatch(idx);
      showMsg('Patch approved and queued for application');
      await loadApproval();
    } catch (e: unknown) {
      showMsg(errDetail(e, 'Approval failed'), 'err');
    } finally { setApprovingIdx(null); }
  };

  const handleSave = async (overrideCfg?: HealingConfig) => {
    const toSave = overrideCfg ?? cfg;
    if (toSave.aggressiveness === 'nuclear' && !overrideCfg) {
      setPendingCfg(toSave); setConfirmNuclear(true); return;
    }
    // Turning autonomous patching ON deserves the same confirmation as nuclear
    // mode — it is the switch that lets the system modify production code
    // without a human in the loop.
    if (toSave.enabled && !overrideCfg) {
      setPendingCfg(toSave); setConfirmEnable(true); return;
    }
    setSaving(true);
    try {
      await superadminApi.autoHealSaveConfig(toSave);
      showMsg('Configuration saved and applied to live engine');
    } catch (e: unknown) {
      showMsg(errDetail(e, 'Save failed'), 'err');
    } finally { setSaving(false); }
  };

  const patchCfg = (patch: Partial<HealingConfig>) => setCfg(prev => ({ ...prev, ...patch }));

  // Pending approval badge count
  const approvalCount = useMemo(() => pendingApproval.length, [pendingApproval]);

  if (loading) return <><LoadingRows rows={8} /></>;
  if (error)   return <><ErrorState message={error} onRetry={load} /></>;
  // An editable configuration we could not read is worse than none: it looks
  // like the real one and saving it applies it to the live healing engine.
  if (configLoadFailed) return (
    <ErrorState
      message="Couldn't load the auto-healing configuration. Nothing has been changed — retry before making any edits."
      onRetry={load}
    />
  );

  return (
    <div style={{ animation: 'sa-fadein 0.2s ease' }}>

      <style>{`
        @keyframes heal-pulse {
          0%, 100% { box-shadow: 0 0 0 0 rgba(34,197,94,0.4); }
          50%       { box-shadow: 0 0 0 6px rgba(34,197,94,0); }
        }
      `}</style>

      {confirmNuclear && pendingCfg && (
        <ConfirmDialog
          title="⚠️ Nuclear Aggressiveness Mode"
          message="Nuclear mode disables all approval gates and allows the healer to patch any file without confirmation. This can cause irreversible changes to production code. Are you absolutely sure?"
          confirmLabel="Enable Nuclear Mode"
          variant="danger"
          onConfirm={() => { setConfirmNuclear(false); handleSave(pendingCfg); setPendingCfg(null); }}
          onCancel={() => { setConfirmNuclear(false); setPendingCfg(null); }}
        />
      )}

      {confirmEnable && pendingCfg && (
        <ConfirmDialog
          title="⚠️ Enable autonomous self-healing"
          message={
            'This lets the healer patch production code, quarantine components and roll back changes ' +
            'on the live trading platform without a human in the loop. Only categories listed under ' +
            'approval gates will still require sign-off. Enable it?'
          }
          confirmLabel="Enable self-healing"
          variant="danger"
          onConfirm={() => { setConfirmEnable(false); handleSave(pendingCfg); setPendingCfg(null); }}
          onCancel={() => { setConfirmEnable(false); setPendingCfg(null); }}
        />
      )}

      {/* Live status card */}
      <LiveStatusCard
        status={liveStatus}
        testIndex={testIndex}
        onRefresh={handleRefresh}
        refreshing={refreshing}
      />

      {/* Configuration panels */}
      <HealingCorePanel
        cfg={cfg}
        onChange={patchCfg}
        onRebuildBaseline={handleRebuildBaseline}
        rebuildBusy={rebuildBusy}
      />

      <TestIntelligencePanel
        cfg={cfg}
        testIndex={testIndex}
        onChange={patchCfg}
        onReindex={handleReindex}
        reindexBusy={reindexBusy}
      />

      <SafetyGatesPanel cfg={cfg} onChange={patchCfg} />

      {/* Save bar */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '16px 20px', background: '#0a1628',
        border: '1px solid #1e293b', borderRadius: 12, marginTop: 4, marginBottom: 24,
      }}>
        <div style={{ fontSize: 12, color: '#475569' }}>
          Changes are applied immediately to the live healing engine
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <ActionBtn label="Reset to Defaults" onClick={() => setCfg(DEFAULT_CONFIG)} variant="ghost" size="sm" />
          <ActionBtn
            label={saving ? 'Saving…' : 'Save Configuration'}
            onClick={() => handleSave()}
            variant="primary"
            loading={saving}
            icon="💾"
          />
        </div>
      </div>

      {/* Manual test trigger */}
      <TestRunPanel
        onRunTests={handleRunTests}
        running={testRunBusy}
        lastResult={lastTestResult}
      />

      {/* Live data tabs */}
      <div style={{
        background: '#0a1628', border: '1px solid #1e293b',
        borderRadius: 14, overflow: 'hidden', marginTop: 4,
      }}>
        {/* Tab bar */}
        <div style={{
          display: 'flex', borderBottom: '1px solid #1e293b',
          background: '#060f1e', overflowX: 'auto',
        }}>
          {LIVE_TABS.map(tab => {
            const active = activeTab === tab.id;
            const badge = tab.id === 'approval' && approvalCount > 0 ? approvalCount : null;
            return (
              <button
                key={tab.id}
                className="sa-tab-btn"
                onClick={() => setActiveTab(tab.id)}
                style={{
                  display: 'flex', alignItems: 'center', gap: 7,
                  padding: '12px 18px', border: 'none', cursor: 'pointer',
                  background: active ? '#0f172a' : 'transparent',
                  borderBottom: `2px solid ${active ? tab.accent : 'transparent'}`,
                  color: active ? '#f1f5f9' : '#64748b',
                  fontSize: 12, fontWeight: active ? 700 : 500,
                  whiteSpace: 'nowrap', transition: 'all 0.15s',
                }}
              >
                <span>{tab.icon}</span>
                <span>{tab.label}</span>
                {badge != null && (
                  <span style={{
                    background: '#a78bfa', color: '#0f0a1e',
                    borderRadius: 10, fontSize: 10, fontWeight: 800,
                    padding: '1px 6px', minWidth: 18, textAlign: 'center',
                  }}>{badge}</span>
                )}
              </button>
            );
          })}
        </div>

        {/* Tab content */}
        <div style={{ padding: '16px 20px' }}>
          {activeTab === 'drift' && (
            <DriftLogPanel
              events={driftEvents}
              loading={driftLoading}
              onRefresh={loadDrift}
            />
          )}
          {activeTab === 'patches' && (
            <PatchHistoryPanel
              patches={patchHistory}
              loading={patchLoading}
              onRefresh={loadPatches}
            />
          )}
          {activeTab === 'quarantine' && (
            <QuarantinePanel
              entries={quarantine}
              loading={quarLoading}
              onRefresh={loadQuarantine}
            />
          )}
          {activeTab === 'approval' && (
            approvalFailed ? (
              <ErrorState
                message="Couldn't load pending approvals. This is NOT the same as none pending — patches may be queued against production."
                onRetry={loadApproval}
              />
            ) : (
              <PendingApprovalPanel
                patches={pendingApproval}
                loading={approvalLoading}
                onRefresh={loadApproval}
                onApprove={handleApprove}
                approvingIdx={approvingIdx}
              />
            )
          )}
        </div>
      </div>

      {msg && (
        <div style={{
          marginTop: 12, padding: '12px 16px', borderRadius: 8,
          background: msgType === 'ok' ? '#052e16' : '#450a0a',
          color: msgType === 'ok' ? '#4ade80' : '#f87171',
          border: `1px solid ${msgType === 'ok' ? '#16a34a' : '#dc2626'}`,
          fontSize: 13, fontWeight: 600,
        }}>{msg}</div>
      )}
    </div>
  );
};

export default AutoHealingSection;
