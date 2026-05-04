import axios from 'axios'

const BASE = import.meta.env.VITE_API_BASE ?? ''

const http = axios.create({ baseURL: BASE })

http.interceptors.request.use(cfg => {
  const token = localStorage.getItem('aegis_token')
  if (token) cfg.headers!['Authorization'] = `Bearer ${token}`
  return cfg
})

export const api = {
  // Auth
  login: (username: string, password: string, tenant = 'default') =>
    http.post('/auth/token', { username, password, tenant }).then(r => r.data),

  // Chain
  chainStatus: () => http.get('/chain/status').then(r => r.data),
  listBlocks:  (limit = 10, offset = 0) =>
    http.get('/chain/blocks', { params: { limit, offset } }).then(r => r.data),

  // Write
  writeData: (tx_type: string, actor: string, payload: object) =>
    http.post('/write', { tx_type, actor, payload }).then(r => r.data),

  // Diode
  diodeStats: () => http.get('/diode/stats').then(r => r.data),
}

export type ChainStatus = {
  chain_id:       number
  height:         number
  latest_hash:    string
  pending_txs:    number
  frozen:         boolean
  freeze_reason:  string | null
  chain_valid:    boolean
}

export type Block = {
  index:      number
  hash:       string
  validator:  string
  timestamp:  number
  tx_count:   number
  transactions: Transaction[]
}

export type Transaction = {
  tx_id:     string
  tx_type:   string
  actor:     string
  payload:   object
  timestamp: number
  hash:      string
}
