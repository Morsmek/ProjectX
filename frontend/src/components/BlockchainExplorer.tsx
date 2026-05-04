import React, { useEffect, useState } from 'react'
import { Database, CheckCircle2, XCircle, Clock } from 'lucide-react'
import { api, type Block } from '../services/api'
import { useStore } from '../store'

export default function BlockchainExplorer() {
  const { chainStatus, setChainStatus } = useStore()
  const [blocks, setBlocks] = useState<Block[]>([])
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<Block | null>(null)

  const refresh = async () => {
    try {
      const [status, chain] = await Promise.all([api.chainStatus(), api.listBlocks(15)])
      setChainStatus(status)
      setBlocks(chain.blocks ?? [])
    } catch {
      // gateway may not be reachable in static dev preview
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, 5000)
    return () => clearInterval(id)
  }, [])

  return (
    <div className="aegis-panel p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-cyan-400 font-bold">
          <Database size={16} /> PoA BLOCKCHAIN EXPLORER
        </h2>
        <div className="flex items-center gap-3 text-xs">
          {chainStatus?.chain_valid ? (
            <span className="flex items-center gap-1 text-green-400">
              <CheckCircle2 size={12} /> VALID
            </span>
          ) : (
            <span className="flex items-center gap-1 text-red-400">
              <XCircle size={12} /> INVALID
            </span>
          )}
          <span className="text-gray-400">
            HEIGHT <span className="text-white">{chainStatus?.height ?? '—'}</span>
          </span>
          <span className="text-gray-400">
            PENDING <span className="text-yellow-400">{chainStatus?.pending_txs ?? 0}</span>
          </span>
        </div>
      </div>

      {loading && <div className="text-gray-500 text-xs animate-pulse">Loading chain…</div>}

      <div className="space-y-1 max-h-80 overflow-y-auto">
        {[...blocks].reverse().map(block => (
          <div
            key={block.index}
            onClick={() => setSelected(block)}
            className="flex items-center justify-between p-2 rounded cursor-pointer
                       hover:bg-gray-800 border border-transparent hover:border-gray-700
                       transition-colors text-xs"
          >
            <span className="text-cyan-500 w-12">#{block.index}</span>
            <span className="text-gray-300 font-mono flex-1 mx-2 truncate">{block.hash}</span>
            <span className="text-gray-500 w-20 text-right">
              {block.transactions?.length ?? 0} tx
            </span>
            <span className="text-gray-600 w-24 text-right">
              {new Date(block.timestamp * 1000).toLocaleTimeString()}
            </span>
          </div>
        ))}
      </div>

      {selected && (
        <div className="border border-cyan-900 rounded p-3 text-xs space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-cyan-400 font-bold">BLOCK #{selected.index}</span>
            <button onClick={() => setSelected(null)} className="text-gray-500 hover:text-white">✕</button>
          </div>
          <div className="grid grid-cols-2 gap-1 text-gray-400">
            <span>Hash:</span>
            <span className="text-gray-200 font-mono truncate">{selected.hash}</span>
            <span>Validator:</span>
            <span className="text-green-400">{selected.validator}</span>
            <span>Timestamp:</span>
            <span className="text-gray-200">
              {new Date(selected.timestamp * 1000).toISOString()}
            </span>
            <span>Transactions:</span>
            <span className="text-yellow-400">{selected.transactions?.length ?? 0}</span>
          </div>
          <div className="space-y-1 max-h-40 overflow-y-auto">
            {selected.transactions?.map(tx => (
              <div key={tx.tx_id} className="bg-gray-900 rounded p-2">
                <span className="text-purple-400">{tx.tx_type}</span>
                <span className="text-gray-500 mx-2">by</span>
                <span className="text-gray-300">{tx.actor}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
