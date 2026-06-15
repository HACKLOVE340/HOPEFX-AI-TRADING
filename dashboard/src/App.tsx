import { useEffect } from 'react'
import { Routes, Route, useNavigate, useLocation, Navigate } from 'react-router-dom'
import { Layout } from './components/Layout'

// ── Core pages ────────────────────────────────────────────────────────────────
import { Dashboard }        from './pages/Dashboard'
import { Trading }          from './pages/Trading'
import Positioning          from './pages/Positioning'
import { Leaderboard }      from './pages/Leaderboard'
import { Wallet }           from './pages/Wallet'
import { Settings }         from './pages/Settings'
import { Performance }      from './pages/Performance'
import { PnLDashboard }     from './pages/PnLDashboard'
import PropFirmTracker      from './pages/PropFirmTracker'
import Onboarding           from './pages/Onboarding'
import LandingPage          from './pages/LandingPage'
import Marketplace          from './pages/Marketplace'
import Affiliate            from './pages/Affiliate'
import CryptoCheckout       from './pages/CryptoCheckout'
import StatusPage           from './pages/StatusPage'
import Login                from './pages/Login'
import Register             from './pages/Register'
import AIStrategyGenerator  from './pages/AIStrategyGenerator'
import TwoFactorSetup       from './pages/TwoFactorSetup'
import EconomicCalendar     from './pages/EconomicCalendar'
import WatchlistPage        from './pages/Watchlist'
import PriceAlerts          from './pages/PriceAlerts'
import TradeJournal         from './pages/TradeJournal'

// ── Extended pages ────────────────────────────────────────────────────────────
import RiskCalculator       from './pages/RiskCalculator'
import WalkForward          from './pages/WalkForward'
import Profile              from './pages/Profile'
import SocialFeed           from './pages/SocialFeed'
import AdminPanel           from './pages/AdminPanel'
import ABTesting            from './pages/ABTesting'
import CorrelationDashboard from './pages/CorrelationDashboard'
import CustomIndicators     from './pages/CustomIndicators'
import WhitelabelAdmin      from './pages/WhitelabelAdmin'
import SuperAdminDashboard  from './pages/SuperAdminDashboard'
import ReliabilityDashboard from './pages/ReliabilityDashboard'

// ── Auth guard ────────────────────────────────────────────────────────────────
import AuthGuard from './components/AuthGuard'
import { ErrorBoundary } from './components/ErrorBoundary'

function App() {
  const navigate = useNavigate()
  const location = useLocation()

  // Redirect to onboarding on first visit (unless already done or on a public/admin page)
  useEffect(() => {
    const skipOnboarding = [
      // Public pages
      '/', '/landing', '/login', '/register', '/status',
      '/marketplace', '/affiliate', '/checkout',
      // Admin/superadmin home pages — these users don't need the trader onboarding wizard
      '/admin', '/superadmin', '/whitelabel',
    ]
    const done = localStorage.getItem('hopefx_onboarding_step')
    if (
      !done &&
      !skipOnboarding.includes(location.pathname) &&
      !location.pathname.startsWith('/admin') &&
      !location.pathname.startsWith('/superadmin') &&
      location.pathname !== '/onboarding'
    ) {
      navigate('/onboarding', { replace: true })
    }
  }, [])

  return (
    <ErrorBoundary label="App">
      <Routes>
        {/* ── Public full-screen pages ───────────────────────────────────── */}
        <Route path="/"           element={<LandingPage />} />
        <Route path="/landing"    element={<LandingPage />} />
        <Route path="/login"      element={<Login />} />
        <Route path="/register"   element={<Register />} />
        <Route path="/onboarding" element={<Onboarding />} />
        <Route path="/status"     element={<StatusPage />} />

        {/* ── Public pages inside Layout ─────────────────────────────────── */}
        <Route path="/marketplace" element={<Layout><ErrorBoundary label="Marketplace"><Marketplace /></ErrorBoundary></Layout>} />
        <Route path="/affiliate"   element={<Layout><ErrorBoundary label="Affiliate"><Affiliate /></ErrorBoundary></Layout>} />
        <Route path="/checkout"    element={<Layout><ErrorBoundary label="Checkout"><CryptoCheckout /></ErrorBoundary></Layout>} />
        <Route path="/leaderboard" element={<Layout><ErrorBoundary label="Leaderboard"><Leaderboard /></ErrorBoundary></Layout>} />
        <Route path="/profile/:id" element={<Layout><ErrorBoundary label="Profile"><Profile /></ErrorBoundary></Layout>} />

        {/* ── Authenticated pages inside Layout ─────────────────────────── */}
        <Route path="/dashboard"    element={<AuthGuard><Layout><ErrorBoundary label="Dashboard"><Dashboard /></ErrorBoundary></Layout></AuthGuard>} />
        <Route path="/trading"      element={<AuthGuard><Layout><ErrorBoundary label="Trading"><Trading /></ErrorBoundary></Layout></AuthGuard>} />
        <Route path="/positions"    element={<AuthGuard><Layout><ErrorBoundary label="Positions"><Positioning /></ErrorBoundary></Layout></AuthGuard>} />
        <Route path="/prop-firm"    element={<AuthGuard><Layout><ErrorBoundary label="Prop Firm"><PropFirmTracker /></ErrorBoundary></Layout></AuthGuard>} />
        <Route path="/wallet"       element={<AuthGuard><Layout><ErrorBoundary label="Wallet"><Wallet /></ErrorBoundary></Layout></AuthGuard>} />
        <Route path="/performance"  element={<AuthGuard><Layout><ErrorBoundary label="Performance"><Performance /></ErrorBoundary></Layout></AuthGuard>} />
        <Route path="/pnl"          element={<AuthGuard><Layout><ErrorBoundary label="P&L Dashboard"><PnLDashboard /></ErrorBoundary></Layout></AuthGuard>} />
        <Route path="/settings"     element={<AuthGuard><Layout><ErrorBoundary label="Settings"><Settings /></ErrorBoundary></Layout></AuthGuard>} />
        <Route path="/ai-strategy"  element={<AuthGuard><Layout><ErrorBoundary label="AI Strategy"><AIStrategyGenerator /></ErrorBoundary></Layout></AuthGuard>} />
        <Route path="/2fa-setup"    element={<AuthGuard><Layout><ErrorBoundary label="2FA Setup"><TwoFactorSetup /></ErrorBoundary></Layout></AuthGuard>} />
        <Route path="/calendar"     element={<AuthGuard><Layout><ErrorBoundary label="Calendar"><EconomicCalendar /></ErrorBoundary></Layout></AuthGuard>} />
        <Route path="/watchlist"    element={<AuthGuard><Layout><ErrorBoundary label="Watchlist"><WatchlistPage /></ErrorBoundary></Layout></AuthGuard>} />
        <Route path="/alerts"       element={<AuthGuard><Layout><ErrorBoundary label="Alerts"><PriceAlerts /></ErrorBoundary></Layout></AuthGuard>} />
        <Route path="/journal"      element={<AuthGuard><Layout><ErrorBoundary label="Journal"><TradeJournal /></ErrorBoundary></Layout></AuthGuard>} />

        {/* ── Extended pages ─────────────────────────────────────────────── */}
        <Route path="/risk-calc"    element={<AuthGuard><Layout><ErrorBoundary label="Risk Calculator"><RiskCalculator /></ErrorBoundary></Layout></AuthGuard>} />
        <Route path="/walk-forward" element={<AuthGuard><Layout><ErrorBoundary label="Walk Forward"><WalkForward /></ErrorBoundary></Layout></AuthGuard>} />
        <Route path="/profile"      element={<AuthGuard><Layout><ErrorBoundary label="Profile"><Profile /></ErrorBoundary></Layout></AuthGuard>} />
        <Route path="/feed"         element={<AuthGuard><Layout><ErrorBoundary label="Social Feed"><SocialFeed /></ErrorBoundary></Layout></AuthGuard>} />
        {/* Admin routes */}
        <Route path="/admin"        element={<AuthGuard requiredRole="admin"><Layout><ErrorBoundary label="Admin"><AdminPanel /></ErrorBoundary></Layout></AuthGuard>} />
        <Route path="/ab-testing"   element={<AuthGuard><Layout><ErrorBoundary label="A/B Testing"><ABTesting /></ErrorBoundary></Layout></AuthGuard>} />
        <Route path="/correlation"  element={<AuthGuard><Layout><ErrorBoundary label="Correlation"><CorrelationDashboard /></ErrorBoundary></Layout></AuthGuard>} />
        <Route path="/indicators"   element={<AuthGuard><Layout><ErrorBoundary label="Indicators"><CustomIndicators /></ErrorBoundary></Layout></AuthGuard>} />
        {/* Superadmin-only routes */}
        <Route path="/superadmin"   element={<AuthGuard requiredRole="superadmin"><Layout><ErrorBoundary label="SuperAdmin"><SuperAdminDashboard /></ErrorBoundary></Layout></AuthGuard>} />
        <Route path="/superadmin/reliability" element={<AuthGuard requiredRole="superadmin"><Layout><ErrorBoundary label="Reliability"><ReliabilityDashboard /></ErrorBoundary></Layout></AuthGuard>} />
        <Route path="/whitelabel"   element={<AuthGuard requiredRole="superadmin"><Layout><ErrorBoundary label="Whitelabel"><WhitelabelAdmin /></ErrorBoundary></Layout></AuthGuard>} />

        {/* ── Fallback ───────────────────────────────────────────────────── */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </ErrorBoundary>
  )
}

export default App
