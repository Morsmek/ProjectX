import { create } from 'zustand'
import type { ChainStatus } from '../services/api'

interface SystemAlert {
  id:       string
  severity: 'info' | 'warning' | 'critical'
  message:  string
  ts:       number
}

interface AegisStore {
  token:       string | null
  chainStatus: ChainStatus | null
  alerts:      SystemAlert[]
  systemState: string
  meshActive:  boolean

  setToken:       (t: string | null) => void
  setChainStatus: (s: ChainStatus)   => void
  addAlert:       (a: SystemAlert)   => void
  clearAlerts:    ()                 => void
  setSystemState: (s: string)        => void
  setMeshActive:  (v: boolean)       => void
}

export const useStore = create<AegisStore>(set => ({
  token:       localStorage.getItem('aegis_token'),
  chainStatus: null,
  alerts:      [],
  systemState: 'nominal',
  meshActive:  false,

  setToken: t => {
    if (t) localStorage.setItem('aegis_token', t)
    else   localStorage.removeItem('aegis_token')
    set({ token: t })
  },
  setChainStatus: s  => set({ chainStatus: s }),
  addAlert:       a  => set(st => ({ alerts: [a, ...st.alerts].slice(0, 100) })),
  clearAlerts:    () => set({ alerts: [] }),
  setSystemState: s  => set({ systemState: s }),
  setMeshActive:  v  => set({ meshActive: v }),
}))
