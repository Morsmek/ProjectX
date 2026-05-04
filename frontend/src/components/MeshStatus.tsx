import React, { useState } from 'react'
import { Radio, Zap, AlertOctagon } from 'lucide-react'
import { useStore } from '../store'

type MeshPeer = { node_id: string; online: boolean; last_seen: number }

export default function MeshStatus() {
  const { meshActive, systemState } = useStore()
  const [peers] = useState<MeshPeer[]>([
    { node_id: 'node-0', online: true,  last_seen: Date.now() / 1000 },
    { node_id: 'node-1', online: true,  last_seen: Date.now() / 1000 - 15 },
    { node_id: 'node-2', online: false, last_seen: Date.now() / 1000 - 180 },
  ])

  return (
    <div className="aegis-panel p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-amber-400 font-bold text-sm">
          <Radio size={16} /> BLE MESH NETWORK
        </h2>
        <span className={`text-xs px-2 py-1 rounded font-bold ${
          meshActive ? 'bg-amber-900 text-amber-400 blink' : 'bg-gray-800 text-gray-500'
        }`}>
          {meshActive ? 'BLACKOUT MODE' : 'STANDBY'}
        </span>
      </div>

      <div className="text-xs space-y-2">
        <div className="flex justify-between text-gray-500">
          <span>NETWORK MODE</span>
          <span className={meshActive ? 'text-amber-400' : 'text-green-400'}>
            {meshActive ? 'BLE MESH ONLY' : 'PRIMARY (ETH/WIFI)'}
          </span>
        </div>
        <div className="flex justify-between text-gray-500">
          <span>PEERS ONLINE</span>
          <span className="text-white">{peers.filter(p => p.online).length}/{peers.length}</span>
        </div>
        <div className="flex justify-between text-gray-500">
          <span>CHANNEL</span>
          <span className="text-gray-300 font-mono">aegis:ble-mesh</span>
        </div>
      </div>

      <div className="space-y-1">
        {peers.map(peer => (
          <div key={peer.node_id} className="flex items-center justify-between p-2 bg-gray-900 rounded text-xs">
            <div className="flex items-center gap-2">
              <div className={`w-2 h-2 rounded-full ${peer.online ? 'bg-green-400' : 'bg-red-600'}`} />
              <span className="text-gray-300">{peer.node_id}</span>
            </div>
            <span className="text-gray-600">
              {peer.online
                ? `${Math.round(Date.now() / 1000 - peer.last_seen)}s ago`
                : 'OFFLINE'}
            </span>
          </div>
        ))}
      </div>

      {systemState === 'emergency' && (
        <div className="flex items-center gap-2 p-2 bg-red-950 border border-red-700 rounded text-xs text-red-400 blink">
          <AlertOctagon size={14} />
          EMERGENCY MODE — KILL SWITCH ACTIVE
        </div>
      )}

      {meshActive && (
        <div className="flex items-center gap-2 p-2 bg-amber-950 border border-amber-700 rounded text-xs text-amber-400">
          <Zap size={14} />
          Blackout Protocol active — all traffic routing via BLE mesh
        </div>
      )}
    </div>
  )
}
