import { Routes, Route } from 'react-router-dom'
import { Layout } from './components/Layout'
import { Dashboard } from './pages/Dashboard'
import { Trading } from './pages/Trading'
import { CopyTrading } from './pages/CopyTrading'
import { Leaderboard } from './pages/Leaderboard'
import { Wallet } from './pages/Wallet'
import { Settings } from './pages/Settings'
import PropFirmTracker from './pages/PropFirmTracker'

function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/trading" element={<Trading />} />
        <Route path="/copy-trading" element={<CopyTrading />} />
        <Route path="/leaderboard" element={<Leaderboard />} />
        <Route path="/wallet" element={<Wallet />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/prop-firm" element={<PropFirmTracker />} />
      </Routes>
    </Layout>
  )
}

export default App
