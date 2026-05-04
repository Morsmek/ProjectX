import React from 'react'
import { Shield, ShieldAlert, Wifi, WifiOff, Lock, Unlock } from 'lucide-react'
import { useStore } from '../store'

export default function StatusBar() {
  const { chainStatus, systemState, meshActive } = useStore()

  const stateColors: Record<string, string> = {
    nominal:   'text-green-400',
    elevated:  'text-yellow-400',
    lockdown:  'text-orange-400',
    blackout:  'text-red-400',
    emergency: 'text-red-600',
  }

  const frozen = chainStatus?.frozen ?? false

  return (
    <div className="flex items-center justify-between px-4 py-2 bg-gray-900 border-b border-gray-800 text-xs font-mono">
      {/* Left: Branding */}
      <div className="flex items-center gap-3">
        <Shield className="text-cyan-400" size={16} />
        <span className="text-cyan-400 font-bold tracking-widest">PROJECT AEGIS</span>
        <span className="text-gray-600">|</span>
        <span className="text-gray-400">ERP v1.0.0</span>
      </div>

      {/* Center: Chain */}
      <div className="flex items-center gap-4">
        {frozen ? (
          <span className="flex items-center gap-1 text-red-400 blink">
            <Lock size={12} /> CHAIN FROZEN
          </span>
        ) : (
          <span className="flex items-center gap-1 text-green-400">
            <Unlock size={12} /> CHAIN ACTIVE
          </span>
        )}
        <span className="text-gray-500">
          H: <span className="text-white">{chainStatus?.height ?? '—'}</span>
        </span>
        <span className="text-gray-500">
          HASH: <span className="text-gray-300 font-mono">
            {chainStatus?.latest_hash?.slice(0, 12) ?? '————————————'}…
          </span>
        </span>
      </div>

      {/* Right: System state + mesh */}
      <div className="flex items-center gap-4">
        <span className={`uppercase font-bold ${stateColors[systemState] ?? 'text-gray-400'}`}>
          {systemState}
        </span>
        <span className="text-gray-600">|</span>
        {meshActive ? (
          <span className="flex items-center gap-1 text-amber-400 blink">
            <Wifi size={12} /> BLE MESH
          </span>
        ) : (
          <span className="flex items-center gap-1 text-gray-500">
            <WifiOff size={12} /> PRIMARY NET
          </span>
        )}
      </div>
    </div>
  )
}
