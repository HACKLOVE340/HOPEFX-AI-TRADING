/**
 * PageHeader — consistent page title, subtitle, breadcrumb trail,
 * status badge, right-aligned actions, and optional tab navigation.
 *
 * Used at the top of every authenticated page.
 */

import React from 'react';
import { Link } from 'react-router-dom';
import { Breadcrumb, type BreadcrumbItem } from './Breadcrumb';

export interface PageTab {
  key: string;
  label: string;
  icon?: string;
  badge?: string | number;
  href?: string;
}

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  breadcrumbs?: BreadcrumbItem[];
  badge?: React.ReactNode;
  actions?: React.ReactNode;
  tabs?: PageTab[];
  activeTab?: string;
  onTabChange?: (key: string) => void;
  icon?: string;
  style?: React.CSSProperties;
}

export const PageHeader: React.FC<PageHeaderProps> = ({
  title,
  subtitle,
  breadcrumbs,
  badge,
  actions,
  tabs,
  activeTab,
  onTabChange,
  icon,
  style,
}) => (
  <div
    style={{
      borderBottom: '1px solid var(--border, #1e293b)',
      marginBottom: tabs ? 0 : 24,
      paddingBottom: tabs ? 0 : 16,
      ...style,
    }}
  >
    {breadcrumbs && breadcrumbs.length > 0 && (
      <Breadcrumb items={breadcrumbs} />
    )}

    <div
      style={{
        alignItems: 'flex-start',
        display: 'flex',
        gap: 12,
        justifyContent: 'space-between',
        paddingBottom: tabs ? 12 : 0,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
        {icon && (
          <div style={{
            width: 40, height: 40, borderRadius: 10,
            background: 'rgba(59,130,246,0.12)',
            border: '1px solid rgba(59,130,246,0.2)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 18, flexShrink: 0, marginTop: 2,
          }}>
            {icon}
          </div>
        )}
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <h1
              style={{
                color: 'var(--text, #f1f5f9)',
                fontSize: 20,
                fontWeight: 700,
                letterSpacing: -0.3,
                margin: 0,
              }}
            >
              {title}
            </h1>
            {badge && badge}
          </div>
          {subtitle && (
            <p
              style={{
                color: 'var(--text-muted, #64748b)',
                fontSize: 13,
                margin: '4px 0 0',
                lineHeight: 1.5,
              }}
            >
              {subtitle}
            </p>
          )}
        </div>
      </div>

      {actions && (
        <div style={{ alignItems: 'center', display: 'flex', flexShrink: 0, gap: 8, flexWrap: 'wrap' }}>
          {actions}
        </div>
      )}
    </div>

    {tabs && tabs.length > 0 && (
      <div style={{
        display: 'flex',
        gap: 0,
        overflowX: 'auto',
        scrollbarWidth: 'none',
        borderTop: '1px solid var(--border, #1e293b)',
        marginTop: 4,
      }}>
        {tabs.map((tab) => {
          const isActive = tab.key === activeTab;
          const content = (
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              {tab.icon && <span style={{ fontSize: 13 }}>{tab.icon}</span>}
              <span>{tab.label}</span>
              {tab.badge !== undefined && (
                <span style={{
                  fontSize: 10, fontWeight: 700,
                  padding: '1px 5px', borderRadius: 10,
                  background: isActive ? 'rgba(59,130,246,0.25)' : '#1e293b',
                  color: isActive ? '#60a5fa' : '#64748b',
                  minWidth: 18, textAlign: 'center',
                }}>
                  {tab.badge}
                </span>
              )}
            </div>
          );

          const tabStyle: React.CSSProperties = {
            display: 'flex', alignItems: 'center',
            padding: '10px 16px',
            fontSize: 13, fontWeight: isActive ? 600 : 500,
            color: isActive ? '#60a5fa' : '#64748b',
            cursor: 'pointer',
            whiteSpace: 'nowrap',
            transition: 'color 0.15s, border-color 0.15s',
            textDecoration: 'none',
            background: 'transparent',
            border: 'none',
            borderBottom: isActive ? '2px solid #3b82f6' : '2px solid transparent',
            outline: 'none',
          };

          if (tab.href) {
            return (
              <Link key={tab.key} to={tab.href} style={tabStyle}>
                {content}
              </Link>
            );
          }

          return (
            <button
              key={tab.key}
              onClick={() => onTabChange?.(tab.key)}
              style={tabStyle}
            >
              {content}
            </button>
          );
        })}
      </div>
    )}
  </div>
);
