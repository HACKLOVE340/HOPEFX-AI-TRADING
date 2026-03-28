import { Component, ErrorInfo, ReactNode } from 'react'
import { AlertTriangle, RefreshCw } from 'lucide-react'

interface Props {
  children: ReactNode
  /** Optional label shown in the error card (e.g. "Dashboard") */
  label?: string
}

interface State {
  hasError: boolean
  error: Error | null
}

/**
 * Catches render errors in the subtree and shows a recovery UI instead
 * of a blank screen. Each major page section should be wrapped independently
 * so one broken panel doesn't take down the whole app.
 */
export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // In production this would go to Sentry / your error tracker
    console.error('[ErrorBoundary]', this.props.label ?? 'unknown', error, info)
  }

  private reset = () => this.setState({ hasError: false, error: null })

  render() {
    if (!this.state.hasError) return this.props.children

    return (
      <div className="flex flex-col items-center justify-center min-h-[200px] gap-4 p-6 bg-slate-900 rounded-lg border border-red-500/20">
        <AlertTriangle className="w-8 h-8 text-red-400" />
        <div className="text-center">
          <p className="font-semibold text-red-400">
            {this.props.label ? `${this.props.label} failed to render` : 'Something went wrong'}
          </p>
          <p className="text-xs text-slate-500 mt-1 max-w-sm">
            {this.state.error?.message ?? 'An unexpected error occurred.'}
          </p>
        </div>
        <button
          onClick={this.reset}
          className="flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 rounded-lg text-sm text-slate-300 transition-colors"
        >
          <RefreshCw className="w-4 h-4" /> Try again
        </button>
      </div>
    )
  }
}
