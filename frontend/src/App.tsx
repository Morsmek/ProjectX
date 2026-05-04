import React, { useState } from 'react'
import { Routes, Route, Navigate, Link, useLocation } from 'react-router-dom'
import { Shield, LayoutDashboard, Database, ShieldAlert, Scale, Radio,
         Monitor, Package, LogOut, Key } from 'lucide-react'
import { useStore } from './store'
import StatusBar from './components/StatusBar'
import Dashboard from './components/Dashboard'
import { api } from './services/api'

// ── Login ─────────────────────────────────────────────────────────────────────

function Login() {
  const setToken = useStore(s => s.setToken)
  const [user, setUser] = useState('')
  const [pass, setPass] = useState('')
  const [err,  setErr]  = useState('')

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      const data = await api.login(user, pass)
      setToken(data.access_token)
    } catch {
      setErr('Authentication failed')
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-950">
      <div className="aegis-panel p-8 w-96 space-y-6">
        <div className="text-center space-y-2">
          <Shield className="mx-auto text-cyan-400" size={40} />
          <h1 className="text-cyan-400 font-bold text-xl tracking-widest">PROJECT AEGIS</h1>
          <p className="text-gray-500 text-xs">ZERO-TRUST ERP COMMAND CONSOLE</p>
        </div>
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="text-gray-500 text-xs block mb-1">IDENTITY</label>
            <input
              className="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-white text-sm
                         focus:outline-none focus:border-cyan-600"
              value={user}
              onChange={e => setUser(e.target.value)}
              placeholder="username"
              autoFocus
            />
          </div>
          <div>
            <label className="text-gray-500 text-xs block mb-1">PASSPHRASE</label>
            <input
              type="password"
              className="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-white text-sm
                         focus:outline-none focus:border-cyan-600"
              value={pass}
              onChange={e => setPass(e.target.value)}
              placeholder="••••••••"
            />
          </div>
          {err && <p className="text-red-400 text-xs">{err}</p>}
          <button
            type="submit"
            className="w-full py-2 bg-cyan-900 hover:bg-cyan-800 text-cyan-200 rounded font-bold text-sm
                       transition-colors"
          >
            AUTHENTICATE
          </button>
        </form>
        <p className="text-gray-700 text-xs text-center">
          All access is monitored · Zero-trust enforced
        </p>
      </div>
    </div>
  )
}

// ── Sidebar nav ───────────────────────────────────────────────────────────────

const NAV = [
  { to: '/',         icon: LayoutDashboard, label: 'Dashboard'   },
  { to: '/chain',    icon: Database,        label: 'Blockchain'  },
  { to: '/security', icon: ShieldAlert,     label: 'Security'    },
  { to: '/oracle',   icon: Scale,           label: 'Oracle'      },
  { to: '/mesh',     icon: Radio,           label: 'Mesh'        },
  { to: '/vdi',      icon: Monitor,         label: 'VDI'         },
  { to: '/modules',  icon: Package,         label: 'Modules'     },
]

function Sidebar() {
  const { pathname } = useLocation()
  const setToken = useStore(s => s.setToken)

  return (
    <nav className="w-16 bg-gray-900 border-r border-gray-800 flex flex-col items-center py-4 gap-2">
      <Shield className="text-cyan-400 mb-4" size={24} />
      {NAV.map(item => {
        const Icon = item.icon
        const active = pathname === item.to
        return (
          <Link
            key={item.to}
            to={item.to}
            title={item.label}
            className={`p-2 rounded transition-colors ${
              active ? 'bg-cyan-900 text-cyan-400' : 'text-gray-500 hover:text-white hover:bg-gray-800'
            }`}
          >
            <Icon size={18} />
          </Link>
        )
      })}
      <div className="flex-1" />
      <button
        onClick={() => setToken(null)}
        title="Logout"
        className="p-2 text-gray-600 hover:text-red-400 transition-colors"
      >
        <LogOut size={18} />
      </button>
    </nav>
  )
}

// ── Placeholder pages ─────────────────────────────────────────────────────────

function PlaceholderPage({ title }: { title: string }) {
  return (
    <div className="p-8 text-center text-gray-600">
      <div className="text-4xl mb-2">⬡</div>
      <div className="font-bold text-gray-400">{title}</div>
      <div className="text-sm mt-1">Full UI coming in next sprint</div>
    </div>
  )
}

// ── Root ──────────────────────────────────────────────────────────────────────

export default function App() {
  const token = useStore(s => s.token)

  if (!token) return <Login />

  return (
    <div className="flex flex-col h-screen">
      <StatusBar />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar />
        <main className="flex-1 overflow-y-auto scan-line">
          <Routes>
            <Route path="/"         element={<Dashboard />} />
            <Route path="/chain"    element={<PlaceholderPage title="BLOCKCHAIN EXPLORER" />} />
            <Route path="/security" element={<PlaceholderPage title="HERMES + SDBA CONSOLE" />} />
            <Route path="/oracle"   element={<PlaceholderPage title="ORACLE / SMART CONTRACTS" />} />
            <Route path="/mesh"     element={<PlaceholderPage title="BLE MESH NETWORK" />} />
            <Route path="/vdi"      element={<PlaceholderPage title="VDI SESSION MANAGER" />} />
            <Route path="/modules"  element={<PlaceholderPage title="MUNNIN NOTE + PLINXX" />} />
            <Route path="*"         element={<Navigate to="/" />} />
          </Routes>
        </main>
      </div>
    </div>
  )
}
