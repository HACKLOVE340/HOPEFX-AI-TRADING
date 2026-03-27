import { useEffect } from 'react'
import { Routes, Route, useNavigate, useLocation, Navigate } from 'react-router-dom'
import { Layout } from './components/Layout'

// ── Core pages ────────────────────────────────────────────────────────────────
import { Dashboard }        from './pages/Dashboard'
import { Trading }          from './pages/Trading'
import { CopyTrading }      from './pages/CopyTrading'
import { Leaderboard }      from './pages/Leaderboard'
import { Wallet }           from './pages/Wallet'
import { Settings }         from './pages/Settings'
import { Performance }      from './pages/Performance'
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

// ── Auth guard ────────────────────────────────────────────────────────────────
import AuthGuard from './components/AuthGuard'

function App() {
  const navigate = useNavigate()
  const location = useLocation()

  // Redirect to onboarding on first visit (unless already done or on a public page)
  useEffect(() => {
    const publicPaths = ['/', '/landing', '/login', '/register', '/status', '/marketplace', '/affiliate', '/checkout']
    const done = localStorage.getItem('hopefx_onboarding_step')
    if (!done && !publicPaths.includes(location.pathname) && location.pathname !== '/onboarding') {
      navigate('/onboarding', { replace: true })
    }
  }, [])

  return (
    <Routes>
      {/* ── Public full-screen pages ─────────────────────────────────────── */}
      <Route path="/"           element={<LandingPage />} />
      <Route path="/landing"    element={<LandingPage />} />
      <Route path="/login"      element={<Login />} />
      <Route path="/register"   element={<Register />} />
      <Route path="/onboarding" element={<Onboarding />} />
      <Route path="/status"     element={<StatusPage />} />

      {/* ── Public pages inside Layout ───────────────────────────────────── */}
      <Route path="/marketplace" element={<Layout><Marketplace /></Layout>} />
      <Route path="/affiliate"   element={<Layout><Affiliate /></Layout>} />
      <Route path="/checkout"    element={<Layout><CryptoCheckout /></Layout>} />
      <Route path="/leaderboard" element={<Layout><Leaderboard /></Layout>} />
      <Route path="/profile/:id" element={<Layout><Profile /></Layout>} />

      {/* ── Authenticated pages inside Layout ───────────────────────────── */}
      <Route path="/dashboard"    element={<AuthGuard><Layout><Dashboard /></Layout></AuthGuard>} />
      <Route path="/trading"      element={<AuthGuard><Layout><Trading /></Layout></AuthGuard>} />
      <Route path="/prop-firm"    element={<AuthGuard><Layout><PropFirmTracker /></Layout></AuthGuard>} />
      <Route path="/copy-trading" element={<AuthGuard><Layout><CopyTrading /></Layout></AuthGuard>} />
      <Route path="/wallet"       element={<AuthGuard><Layout><Wallet /></Layout></AuthGuard>} />
      <Route path="/performance"  element={<AuthGuard><Layout><Performance /></Layout></AuthGuard>} />
      <Route path="/settings"     element={<AuthGuard><Layout><Settings /></Layout></AuthGuard>} />
      <Route path="/ai-strategy"  element={<AuthGuard><Layout><AIStrategyGenerator /></Layout></AuthGuard>} />
      <Route path="/2fa-setup"    element={<AuthGuard><Layout><TwoFactorSetup /></Layout></AuthGuard>} />
      <Route path="/calendar"     element={<AuthGuard><Layout><EconomicCalendar /></Layout></AuthGuard>} />
      <Route path="/watchlist"    element={<AuthGuard><Layout><WatchlistPage /></Layout></AuthGuard>} />
      <Route path="/alerts"       element={<AuthGuard><Layout><PriceAlerts /></Layout></AuthGuard>} />
      <Route path="/journal"      element={<AuthGuard><Layout><TradeJournal /></Layout></AuthGuard>} />

      {/* ── Extended pages ───────────────────────────────────────────────── */}
      <Route path="/risk-calc"    element={<AuthGuard><Layout><RiskCalculator /></Layout></AuthGuard>} />
      <Route path="/walk-forward" element={<AuthGuard><Layout><WalkForward /></Layout></AuthGuard>} />
      <Route path="/profile"      element={<AuthGuard><Layout><Profile /></Layout></AuthGuard>} />
      <Route path="/feed"         element={<AuthGuard><Layout><SocialFeed /></Layout></AuthGuard>} />
      <Route path="/admin"        element={<AuthGuard><Layout><AdminPanel /></Layout></AuthGuard>} />
      <Route path="/ab-testing"   element={<AuthGuard><Layout><ABTesting /></Layout></AuthGuard>} />
      <Route path="/correlation"  element={<AuthGuard><Layout><CorrelationDashboard /></Layout></AuthGuard>} />
      <Route path="/indicators"   element={<AuthGuard><Layout><CustomIndicators /></Layout></AuthGuard>} />
      <Route path="/whitelabel"   element={<AuthGuard><Layout><WhitelabelAdmin /></Layout></AuthGuard>} />

      {/* ── Fallback ─────────────────────────────────────────────────────── */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default App
