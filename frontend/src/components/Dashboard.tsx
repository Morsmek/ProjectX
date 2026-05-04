import React from 'react'
import BlockchainExplorer from './BlockchainExplorer'
import SecurityPanel from './SecurityPanel'
import OraclePanel from './OraclePanel'
import MeshStatus from './MeshStatus'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { useStore } from '../store'

const MOCK_ACTIVITY = Array.from({ length: 20 }, (_, i) => ({
  t:        i,
  writes:   Math.floor(Math.random() * 30 + 5),
  threats:  Math.floor(Math.random() * 5),
}))

export default function Dashboard() {
  const { chainStatus, alerts } = useStore()

  return (
    <div className="p-4 space-y-4">
      {/* Top KPI strip */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: 'CHAIN HEIGHT',    value: chainStatus?.height ?? '—',    color: 'text-cyan-400'   },
          { label: 'PENDING TXs',     value: chainStatus?.pending_txs ?? 0, color: 'text-yellow-400' },
          { label: 'ACTIVE ALERTS',   value: alerts.length,                  color: 'text-red-400'    },
          { label: 'CHAIN INTEGRITY', value: chainStatus?.chain_valid ? '✓ VALID' : '✗ INVALID',
            color: chainStatus?.chain_valid ? 'text-green-400' : 'text-red-500' },
        ].map(kpi => (
          <div key={kpi.label} className="aegis-panel p-3 text-center">
            <div className={`text-2xl font-bold ${kpi.color}`}>{String(kpi.value)}</div>
            <div className="text-gray-500 text-xs mt-1">{kpi.label}</div>
          </div>
        ))}
      </div>

      {/* Activity chart */}
      <div className="aegis-panel p-4">
        <h2 className="text-green-400 font-bold text-sm mb-3">SYSTEM ACTIVITY — WRITES vs THREATS</h2>
        <ResponsiveContainer width="100%" height={120}>
          <AreaChart data={MOCK_ACTIVITY}>
            <XAxis dataKey="t" hide />
            <YAxis hide />
            <Tooltip
              contentStyle={{ background: '#0f172a', border: '1px solid #1e293b', fontSize: 11 }}
            />
            <Area type="monotone" dataKey="writes"  stroke="#0ea5e9" fill="#0c4a6e" strokeWidth={1.5} />
            <Area type="monotone" dataKey="threats" stroke="#ef4444" fill="#450a0a" strokeWidth={1.5} />
          </AreaChart>
        </ResponsiveContainer>
        <div className="flex gap-4 mt-2 text-xs text-gray-500">
          <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-cyan-500 inline-block" /> Writes</span>
          <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-red-500 inline-block" /> Threats</span>
        </div>
      </div>

      {/* Main panels */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <BlockchainExplorer />
        <SecurityPanel />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <OraclePanel />
        <MeshStatus />
      </div>
    </div>
  )
}
