import React, { useEffect, useState } from 'react'
import { ShieldAlert, Activity, Eye, EyeOff } from 'lucide-react'
import { useStore } from '../store'

type Alert = {
  id:       string
  severity: string
  message:  string
  ts:       number
  score?:   number
}

const severityColor: Record<string, string> = {
  info:     'text-blue-400 border-blue-800',
  warning:  'text-yellow-400 border-yellow-800',
  critical: 'text-red-400 border-red-800',
  fatal:    'text-red-600 border-red-600 blink',
}

export default function SecurityPanel() {
  const { alerts, systemState } = useStore()
  const [show, setShow] = useState(true)

  const stateGauge: Record<string, number> = {
    nominal:   20,
    elevated:  50,
    lockdown:  75,
    blackout:  90,
    emergency: 100,
  }
  const gaugeWidth = stateGauge[systemState] ?? 0
  const gaugeColor = gaugeWidth < 50 ? '#00ff9d' : gaugeWidth < 75 ? '#f59e0b' : '#ef4444'

  return (
    <div className="aegis-panel p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-red-400 font-bold">
          <ShieldAlert size={16} /> HERMES-2 GUARDIAN · SDBA
        </h2>
        <button onClick={() => setShow(s => !s)} className="text-gray-500 hover:text-white">
          {show ? <EyeOff size={14} /> : <Eye size={14} />}
        </button>
      </div>

      {/* Threat gauge */}
      <div className="space-y-1">
        <div className="flex justify-between text-xs text-gray-500">
          <span>THREAT POSTURE</span>
          <span className="uppercase font-bold" style={{ color: gaugeColor }}>{systemState}</span>
        </div>
        <div className="w-full h-2 bg-gray-800 rounded overflow-hidden">
          <div
            className="h-full rounded transition-all duration-700"
            style={{ width: `${gaugeWidth}%`, background: gaugeColor }}
          />
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-2 text-xs">
        <div className="aegis-panel p-2 text-center">
          <div className="text-2xl font-bold text-yellow-400">{alerts.length}</div>
          <div className="text-gray-500">TOTAL ALERTS</div>
        </div>
        <div className="aegis-panel p-2 text-center">
          <div className="text-2xl font-bold text-red-400">
            {alerts.filter(a => a.severity === 'critical' || a.severity === 'fatal').length}
          </div>
          <div className="text-gray-500">CRITICAL</div>
        </div>
        <div className="aegis-panel p-2 text-center">
          <div className="text-2xl font-bold text-green-400">
            <Activity size={20} className="mx-auto" />
          </div>
          <div className="text-gray-500">MONITORING</div>
        </div>
      </div>

      {/* Alert feed */}
      {show && (
        <div className="space-y-1 max-h-64 overflow-y-auto">
          {alerts.length === 0 && (
            <div className="text-gray-600 text-xs text-center py-4">No alerts</div>
          )}
          {alerts.map(alert => (
            <div
              key={alert.id}
              className={`flex items-start gap-2 p-2 rounded border text-xs ${severityColor[alert.severity] ?? 'text-gray-400 border-gray-800'}`}
            >
              <ShieldAlert size={12} className="mt-0.5 flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <div className="truncate">{alert.message}</div>
                <div className="text-gray-600 mt-0.5">
                  {new Date(alert.ts).toLocaleTimeString()}
                  {alert.score !== undefined && ` · score: ${alert.score.toFixed(3)}`}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
