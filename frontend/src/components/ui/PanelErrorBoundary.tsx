/**
 * components/ui/PanelErrorBoundary.tsx
 * Panel-scoped error boundary — catches render errors in a single panel
 * without crashing the whole dashboard. Shows an inline error state with
 * a retry button that resets the boundary.
 */

import React, { Component } from 'react';

interface Props {
  title?:    string;
  children:  React.ReactNode;
}

interface State {
  hasError: boolean;
  message:  string;
}

export class PanelErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, message: '' };

  static getDerivedStateFromError(err: Error): State {
    return { hasError: true, message: err.message };
  }

  componentDidCatch(err: Error, info: React.ErrorInfo) {
    console.error(`[PanelErrorBoundary] ${this.props.title ?? 'Panel'} crashed:`, err, info);
  }

  reset = () => this.setState({ hasError: false, message: '' });

  render() {
    if (!this.state.hasError) return this.props.children;

    return (
      <div className="flex flex-col items-center justify-center h-full gap-3 p-4 bg-[var(--surface)] border border-[#ff3b5c]/20 rounded-lg">
        <div className="flex items-center gap-2">
          <span className="text-[#ff3b5c] text-sm">⚠</span>
          <span className="text-[11px] font-semibold text-[#ff3b5c] uppercase tracking-wider">
            {this.props.title ?? 'Panel'} Error
          </span>
        </div>
        <p className="text-[10px] text-slate-600 text-center max-w-[200px] font-mono leading-relaxed">
          {this.state.message || 'An unexpected error occurred'}
        </p>
        <button
          onClick={this.reset}
          className="px-3 py-1 text-[10px] font-semibold uppercase tracking-wider rounded border border-[var(--border)] text-slate-400 hover:text-slate-200 hover:border-[#2d4a6b] transition-colors"
        >
          Retry
        </button>
      </div>
    );
  }
}
