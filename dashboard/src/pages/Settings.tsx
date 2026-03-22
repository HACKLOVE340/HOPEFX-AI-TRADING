import { useState } from 'react'
import { 
  Shield, 
  Bell, 
  Key, 
  Globe, 
  Smartphone,
  Save
} from 'lucide-react'

export function Settings() {
  const [activeSection, setActiveSection] = useState('security')

  const sections = [
    { id: 'security', label: 'Security', icon: Shield },
    { id: 'notifications', label: 'Notifications', icon: Bell },
    { id: 'api', label: 'API Keys', icon: Key },
    { id: 'trading', label: 'Trading', icon: Globe },
    { id: 'mobile', label: 'Mobile App', icon: Smartphone },
  ]

  return (
    <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
      {/* Sidebar */}
      <div className="lg:col-span-1">
        <div className="bg-slate-900 rounded-lg border border-slate-800 overflow-hidden">
          {sections.map((section) => {
            const Icon = section.icon
            return (
              <button
                key={section.id}
                onClick={() => setActiveSection(section.id)}
                className={`w-full flex items-center gap-3 px-4 py-3 text-left transition-colors ${
                  activeSection === section.id
                    ? 'bg-amber-500/10 text-amber-400 border-l-2 border-amber-500'
                    : 'text-slate-400 hover:bg-slate-800'
                }`}
              >
                <Icon className="w-5 h-5" />
                {section.label}
              </button>
            )
          })}
        </div>
      </div>

      {/* Content */}
      <div className="lg:col-span-3">
        <div className="bg-slate-900 rounded-lg border border-slate-800 p-6">
          {activeSection === 'security' && (
            <div className="space-y-6">
              <h3 className="text-lg font-semibold">Security Settings</h3>
              
              <div className="space-y-4">
                <div className="flex items-center justify-between py-4 border-b border-slate-800">
                  <div>
                    <p className="font-medium">Two-Factor Authentication</p>
                    <p className="text-sm text-slate-400">Secure your account with 2FA</p>
                  </div>
                  <button className="px-4 py-2 bg-amber-500 text-slate-950 rounded-lg font-medium">
                    Enable
                  </button>
                </div>
                
                <div className="flex items-center justify-between py-4 border-b border-slate-800">
                  <div>
                    <p className="font-medium">Login Notifications</p>
                    <p className="text-sm text-slate-400">Get alerted on new device logins</p>
                  </div>
                  <label className="relative inline-flex items-center cursor-pointer">
                    <input type="checkbox" className="sr-only peer" defaultChecked />
                    <div className="w-11 h-6 bg-slate-700 peer-focus:ring-2 peer-focus:ring-amber-500 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-amber-500"></div>
                  </label>
                </div>
                
                <div className="flex items-center justify-between py-4 border-b border-slate-800">
                  <div>
                    <p className="font-medium">Withdrawal Whitelist</p>
                    <p className="text-sm text-slate-400">Restrict withdrawals to approved addresses</p>
                  </div>
                  <button className="px-4 py-2 border border-slate-700 rounded-lg hover:bg-slate-800">
                    Manage
                  </button>
                </div>
                
                <div className="flex items-center justify-between py-4">
                  <div>
                    <p className="font-medium text-red-400">Danger Zone</p>
                    <p className="text-sm text-slate-400">Delete account and all data</p>
                  </div>
                  <button className="px-4 py-2 border border-red-500/50 text-red-400 rounded-lg hover:bg-red-500/10">
                    Delete Account
                  </button>
                </div>
              </div>
            </div>
          )}

          {activeSection === 'api' && (
            <div className="space-y-6">
              <h3 className="text-lg font-semibold">API Keys</h3>
              
              <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700">
                <div className="flex items-center justify-between mb-4">
                  <div>
                    <p className="font-medium">Trading API Key</p>
                    <p className="text-sm text-slate-400">Created: Jan 1, 2024</p>
                  </div>
                  <span className="px-2 py-1 bg-green-500/10 text-green-400 text-xs rounded">
                    Active
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <code className="flex-1 bg-slate-950 px-3 py-2 rounded text-sm font-mono">
                    hf_live_••••••••••••••••••••••••
                  </code>
                  <button className="px-3 py-2 bg-slate-800 rounded hover:bg-slate-700">
                    Show
                  </button>
                  <button className="px-3 py-2 bg-slate-800 rounded hover:bg-slate-700">
                    Revoke
                  </button>
                </div>
              </div>
              
              <button className="w-full py-3 border border-dashed border-slate-700 rounded-lg text-slate-400 hover:border-slate-500 hover:text-slate-300">
                + Generate New API Key
              </button>
              
              <div className="space-y-2 text-sm text-slate-400">
                <p>• Never share your API keys</p>
                <p>• Use IP whitelisting for production</p>
                <p>• Rotate keys every 90 days</p>
              </div>
            </div>
          )}

          {activeSection === 'trading' && (
            <div className="space-y-6">
              <h3 className="text-lg font-semibold">Trading Preferences</h3>
              
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm text-slate-400 mb-2">
                    Default Leverage
                  </label>
                  <select className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2">
                    <option>1:30 (Regulatory)</option>
                    <option>1:50</option>
                    <option>1:100</option>
                  </select>
                </div>
                
                <div>
                  <label className="block text-sm text-slate-400 mb-2">
                    Risk Per Trade (%)
                  </label>
                  <input 
                    type="number" 
                    defaultValue={1}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2"
                  />
                </div>
                
                <div>
                  <label className="block text-sm text-slate-400 mb-2">
                    Max Daily Loss (%)
                  </label>
                  <input 
                    type="number" 
                    defaultValue={2}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2"
                  />
                </div>
                
                <div>
                  <label className="block text-sm text-slate-400 mb-2">
                    Max Positions
                  </label>
                  <input 
                    type="number" 
                    defaultValue={5}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2"
                  />
                </div>
              </div>
              
              <div className="flex items-center gap-3 pt-4">
                <input type="checkbox" id="confirmations" defaultChecked className="w-4 h-4 rounded bg-slate-800 border-slate-700" />
                <label htmlFor="confirmations" className="text-sm">
                  Require confirmation for trades over $10,000
                </label>
              </div>
              
              <div className="flex items-center gap-3">
                <input type="checkbox" id="stop_loss" defaultChecked className="w-4 h-4 rounded bg-slate-800 border-slate-700" />
                <label htmlFor="stop_loss" className="text-sm">
                  Enforce stop-loss on all trades
                </label>
              </div>
            </div>
          )}

          <div className="mt-6 pt-6 border-t border-slate-800 flex justify-end">
            <button className="flex items-center gap-2 px-6 py-2 bg-amber-500 text-slate-950 rounded-lg font-medium hover:bg-amber-400">
              <Save className="w-4 h-4" />
              Save Changes
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
