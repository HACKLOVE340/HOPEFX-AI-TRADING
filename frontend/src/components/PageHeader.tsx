/**
 * PageHeader — consistent page title, subtitle, breadcrumb trail,
 * status badge, right-aligned actions, and optional tab navigation.
 *
 * Mobile-first: on xs/sm the actions stack below the title row,
 * tabs scroll horizontally, breadcrumbs wrap gracefully.
 */

import React from 'react';
import { Link } from 'react-router-dom';
import type { LucideIcon } from 'lucide-react';
import { Breadcrumb, type BreadcrumbItem } from './Breadcrumb';

export interface PageTab {
  key: string;
  label: string;
  /** Lucide component preferred; a string is legacy emoji (F170). */
  icon?: LucideIcon | string;
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
  /** Lucide component preferred; a string is legacy emoji (F170). */
  icon?: LucideIcon | string;
  className?: string;
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
  className = '',
  style,
}) => (
  <div
    className={`border-b border-terminal-border ${tabs ? 'mb-0 pb-0' : 'mb-6 pb-4'} ${className}`}
    style={style}
  >
    {breadcrumbs && breadcrumbs.length > 0 && (
      <Breadcrumb items={breadcrumbs} />
    )}

    {/* Title row — stacks on mobile, side-by-side on sm+ */}
    <div className={`flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between ${tabs ? 'pb-3' : ''}`}>
      {/* Left: icon + title + subtitle */}
      <div className="flex items-start gap-3 min-w-0">
        {icon && (
          <div className="w-10 h-10 rounded-xl bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-lg text-blue-400 flex-shrink-0 mt-0.5">
            {typeof icon === 'string'
              ? icon                            /* legacy emoji call sites */
              : React.createElement(icon, { size: 18, strokeWidth: 1.75, 'aria-hidden': true })}
          </div>
        )}
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className="text-slate-100 text-lg sm:text-xl font-bold tracking-tight m-0 leading-tight">
              {title}
            </h1>
            {badge && badge}
          </div>
          {subtitle && (
            <p className="text-slate-500 text-xs sm:text-sm mt-1 leading-relaxed m-0">
              {subtitle}
            </p>
          )}
        </div>
      </div>

      {/* Right: actions — full-width on mobile, auto on sm+ */}
      {actions && (
        <div className="flex items-center gap-2 flex-wrap sm:flex-shrink-0">
          {actions}
        </div>
      )}
    </div>

    {/* Tabs — horizontal scroll on mobile */}
    {tabs && tabs.length > 0 && (
      <div
        role="tablist"
        className="flex gap-0 overflow-x-auto border-t border-terminal-border mt-1"
        style={{ scrollbarWidth: 'none', WebkitOverflowScrolling: 'touch' } as React.CSSProperties}
      >
        {tabs.map((tab) => {
          const isActive = tab.key === activeTab;

          const content = (
            <>
              {tab.icon && (
                typeof tab.icon === 'string'
                  ? <span className="text-xs">{tab.icon}</span>
                  : React.createElement(tab.icon, { size: 13, strokeWidth: 1.75, 'aria-hidden': true })
              )}
              <span>{tab.label}</span>
              {tab.badge !== undefined && (
                <span
                  className={`text-2xs font-bold px-1.5 py-0.5 rounded-full min-w-[18px] text-center ${
                    isActive
                      ? 'bg-blue-500/25 text-blue-400'
                      : 'bg-terminal-raised text-slate-500'
                  }`}
                >
                  {tab.badge}
                </span>
              )}
            </>
          );

          const sharedStyle: React.CSSProperties = {
            borderBottom: isActive ? '2px solid #3b82f6' : '2px solid transparent',
          };

          const sharedClass = `flex min-h-[44px] items-center gap-1.5 px-3 sm:px-4 py-2.5 text-xs sm:text-sm font-medium whitespace-nowrap cursor-pointer transition-colors duration-150 bg-transparent border-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500 focus-visible:ring-inset ${
            isActive ? 'text-blue-400' : 'text-slate-500 hover:text-slate-300'
          }`;

          if (tab.href) {
            return (
              <Link
                key={tab.key}
                to={tab.href}
                role="tab"
                aria-selected={isActive}
                className={`${sharedClass} no-underline`}
                style={sharedStyle}
              >
                {content}
              </Link>
            );
          }

          return (
            <button
              key={tab.key}
              type="button"
              role="tab"
              aria-selected={isActive}
              onClick={() => onTabChange?.(tab.key)}
              className={sharedClass}
              style={sharedStyle}
            >
              {content}
            </button>
          );
        })}
      </div>
    )}
  </div>
);
