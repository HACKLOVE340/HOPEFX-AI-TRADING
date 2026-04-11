// superadmin/AutoHealingSection.tsx
// Autonomous Healing Engine — Super Admin control panel
import React, { useEffect, useState, useCallback, useRef } from 'react';
import { superadminApi } from '../../hooks/useApi';
import {
  SectionCard, ActionBtn, KpiTile, StatusBadge,
  Toggle, Input, Select, Divider,
  ErrorState, LoadingRows, ConfirmDialog, SAStyles, Spinner,
} from './ui';

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
  enabled: true,
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
  const [confirmNuclear, setConfirmNuclear] = useState(false);
  const [pendingCfg, setPendingCfg]     = useState<HealingConfig | null>(null);

  const [liveStatus, setLiveStatus]     = useState<HealerLiveStatus | null>(null);
  const [testIndex, setTestIndex]       = useState<TestIndex | null>(null);
  const [cfg, setCfg]                   = useState<HealingConfig>(DEFAULT_CONFIG);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const showMsg = (text: string, type: 'ok' | 'err' = 'ok') => {
    setMsg(text); setMsgType(type);
    setTimeout(() => setMsg(''), 5000);
  };

  const loadStatus = useCallback(async () => {
    try {
      const [healRes, testRes] = await Promise.all([
        superadminApi.selfHealerStatus(),
        superadminApi.autoHealTestIndex(),
      ]);
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
    } catch {
      // status polling — silent fail
    }
  }, []);

  const loadConfig = useCallback(async () => {
    try {
      const res = await superadminApi.autoHealConfig();
      setCfg({ ...DEFAULT_CONFIG, ...res.data });
    } catch {
      // use defaults if config not yet saved
    }
  }, []);

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      await Promise.all([loadStatus(), loadConfig()]);
    } catch (e: unknown) {
      setError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to load healing configuration');
    } finally {
      setLoading(false);
    }
  }, [loadStatus, loadConfig]);

  useEffect(() => {
    load();
    pollRef.current = setInterval(loadStatus, 15_000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [load, loadStatus]);

  const handleRefresh = async () => {
    setRefreshing(true);
    await loadStatus();
    setRefreshing(false);
  };

  const handleRebuildBaseline = async () => {
    setRebuildBusy(true);
    try {
      await superadminApi.autoHealRebuildBaseline();
      showMsg('Baseline rebuild triggered — this may take a moment');
      setTimeout(loadStatus, 3000);
    } catch (e: unknown) {
      showMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Rebuild failed', 'err');
    } finally {
      setRebuildBusy(false); }
  };

  const handleReindex = async () => {
    setReindexBusy(true);
    try {
      await superadminApi.autoHealReindexTests();
      showMsg('Test re-scan started — index will update shortly');
      setTimeout(loadStatus, 4000);
    } catch (e: unknown) {
      showMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Re-scan failed', 'err');
    } finally {
      setReindexBusy(false); }
  };

  const handleSave = async (overrideCfg?: HealingConfig) => {
    const toSave = overrideCfg ?? cfg;
    if (toSave.aggressiveness === 'nuclear' && !overrideCfg) {
      setPendingCfg(toSave);
      setConfirmNuclear(true);
      return;
    }
    setSaving(true);
    try {
      await superadminApi.autoHealSaveConfig(toSave);
      showMsg('Auto-Healing configuration saved successfully');
    } catch (e: unknown) {
      showMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Save failed', 'err');
    } finally {
      setSaving(false); }
  };

  const patchCfg = (patch: Partial<HealingConfig>) => setCfg(prev => ({ ...prev, ...patch }));

  if (loading) return <><SAStyles /><LoadingRows rows={8} /></>;
  if (error)   return <><SAStyles /><ErrorState message={error} onRetry={load} /></>;

  return (
    <div style={{ animation: 'sa-fadein 0.2s ease' }}>
      <SAStyles />
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

      <LiveStatusCard
        status={liveStatus}
        testIndex={testIndex}
        onRefresh={handleRefresh}
        refreshing={refreshing}
      />

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
        border: '1px solid #1e293b', borderRadius: 12, marginTop: 4,
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
