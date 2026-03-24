import { useEffect } from 'react'
import { Routes, Route, useNavigate, useLocation } from 'react-router-dom'
import { Layout } from './components/Layout'
import { Dashboard } from './pages/Dashboard'
import { Trading } from './pages/Trading'
import { CopyTrading } from './pages/CopyTrading'
import { Leaderboard } from './pages/Leaderboard'
import { Wallet } from './pages/Wallet'
import { Settings } from './pages/Settings'
import PropFirmTracker from './pages/PropFirmTracker'
import Onboarding from './pages/Onboarding'

function App() {
  const navigate = useNavigate()
  const location = useLocation()

  // Redirect to onboarding on first visit (unless already done or already there)
  useEffect(() => {
    const done = localStorage.getItem('hopefx_onboarding_step')
    if (!done && location.pathname !== '/onboarding') {
      navigate('/onboarding', { replace: true })
    }
  }, [])

  return (
    <Routes>
      {/* Onboarding has its own full-screen layout */}
      <Route path="/onboarding" element={<Onboarding />} />

      {/* All other pages use the sidebar Layout */}
      <Route path="/*" element={
        <Layout>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/trading" element={<Trading />} />
            <Route path="/prop-firm" element={<PropFirmTracker />} />
            <Route path="/copy-trading" element={<CopyTrading />} />
            <Route path="/leaderboard" element={<Leaderboard />} />
            <Route path="/wallet" element={<Wallet />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </Layout>
      } />
    </Routes>
  )
}

export default App
