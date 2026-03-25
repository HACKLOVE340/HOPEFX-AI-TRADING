import { useEffect } from 'react'
import { Routes, Route, useNavigate, useLocation, Navigate } from 'react-router-dom'
import { Layout } from './components/Layout'
import { Dashboard } from './pages/Dashboard'
import { Trading } from './pages/Trading'
import { CopyTrading } from './pages/CopyTrading'
import { Leaderboard } from './pages/Leaderboard'
import { Wallet } from './pages/Wallet'
import { Settings } from './pages/Settings'
import { Performance } from './pages/Performance'
import PropFirmTracker from './pages/PropFirmTracker'
import Onboarding from './pages/Onboarding'
import LandingPage from './pages/LandingPage'
import Marketplace from './pages/Marketplace'
import Affiliate from './pages/Affiliate'
import CryptoCheckout from './pages/CryptoCheckout'
import StatusPage from './pages/StatusPage'
import Login from './pages/Login'
import AuthGuard from './components/AuthGuard'
import AIStrategyGenerator from './pages/AIStrategyGenerator'
import TwoFactorSetup from './pages/TwoFactorSetup'
import EconomicCalendar from './pages/EconomicCalendar'

function App() {
  const navigate = useNavigate()
  const location = useLocation()

  // Redirect to onboarding on first visit (unless already done or on a public page)
  useEffect(() => {
    const publicPaths = ['/', '/landing', '/login', '/status', '/marketplace', '/affiliate', '/checkout']
    const done = localStorage.getItem('hopefx_onboarding_step')
    if (!done && !publicPaths.includes(location.pathname) && location.pathname !== '/onboarding') {
      navigate('/onboarding', { replace: true })
    }
  }, [])

  return (
    <Routes>
      {/* Public full-screen pages */}
      <Route path="/"        element={<LandingPage />} />
      <Route path="/landing" element={<LandingPage />} />
      <Route path="/login"   element={<Login />} />
      <Route path="/onboarding" element={<Onboarding />} />
      <Route path="/status"  element={<StatusPage />} />

      {/* Public pages inside Layout */}
      <Route path="/marketplace" element={<Layout><Marketplace /></Layout>} />
      <Route path="/affiliate"   element={<Layout><Affiliate /></Layout>} />
      <Route path="/checkout"    element={<Layout><CryptoCheckout /></Layout>} />

      {/* Authenticated pages inside Layout */}
      <Route path="/dashboard"    element={<AuthGuard><Layout><Dashboard /></Layout></AuthGuard>} />
      <Route path="/trading"      element={<AuthGuard><Layout><Trading /></Layout></AuthGuard>} />
      <Route path="/prop-firm"    element={<AuthGuard><Layout><PropFirmTracker /></Layout></AuthGuard>} />
      <Route path="/copy-trading" element={<AuthGuard><Layout><CopyTrading /></Layout></AuthGuard>} />
      <Route path="/leaderboard"  element={<AuthGuard><Layout><Leaderboard /></Layout></AuthGuard>} />
      <Route path="/wallet"       element={<AuthGuard><Layout><Wallet /></Layout></AuthGuard>} />
      <Route path="/performance"  element={<AuthGuard><Layout><Performance /></Layout></AuthGuard>} />
      <Route path="/settings"     element={<AuthGuard><Layout><Settings /></Layout></AuthGuard>} />
      <Route path="/ai-strategy"  element={<AuthGuard><Layout><AIStrategyGenerator /></Layout></AuthGuard>} />
      <Route path="/2fa-setup"    element={<AuthGuard><Layout><TwoFactorSetup /></Layout></AuthGuard>} />
      <Route path="/calendar"     element={<AuthGuard><Layout><EconomicCalendar /></Layout></AuthGuard>} />

      {/* Fallback */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default App
