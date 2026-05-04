import React, { useState } from 'react'
import { Scale, AlertTriangle, CheckCircle2, Lock } from 'lucide-react'
import axios from 'axios'

const BASE = import.meta.env.VITE_API_BASE ?? ''

type OracleResult = {
  status:      string
  invoice_id?: string
  violations?: { condition: string; description?: string }[]
  freeze_reason?: string
}

export default function OraclePanel() {
  const [projectId,   setProjectId]   = useState('')
  const [milestoneId, setMilestoneId] = useState('')
  const [amount,      setAmount]      = useState('')
  const [submittedBy, setSubmittedBy] = useState('')
  const [result,      setResult]      = useState<OracleResult | null>(null)
  const [loading,     setLoading]     = useState(false)

  const submit = async () => {
    if (!projectId || !milestoneId || !amount) return
    setLoading(true)
    try {
      const token = localStorage.getItem('aegis_token')
      const resp = await axios.post(
        `${BASE}/oracle/invoice`,
        { project_id: projectId, milestone_id: milestoneId,
          amount: parseFloat(amount), submitted_by: submittedBy || 'user' },
        { headers: { 'X-Internal-Key': localStorage.getItem('aegis_internal_key') ?? '' } }
      )
      setResult(resp.data)
    } catch (e: any) {
      setResult({ status: 'error', freeze_reason: e.message })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="aegis-panel p-4 space-y-4">
      <h2 className="flex items-center gap-2 text-purple-400 font-bold text-sm">
        <Scale size={16} /> ORACLE — SMART CONTRACT AUDITOR
      </h2>

      <div className="grid grid-cols-2 gap-2 text-xs">
        <div>
          <label className="text-gray-500 block mb-1">PROJECT ID</label>
          <input
            className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-white"
            value={projectId}
            onChange={e => setProjectId(e.target.value)}
            placeholder="proj-uuid"
          />
        </div>
        <div>
          <label className="text-gray-500 block mb-1">MILESTONE ID</label>
          <input
            className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-white"
            value={milestoneId}
            onChange={e => setMilestoneId(e.target.value)}
            placeholder="ms-uuid"
          />
        </div>
        <div>
          <label className="text-gray-500 block mb-1">AMOUNT</label>
          <input
            type="number"
            className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-white"
            value={amount}
            onChange={e => setAmount(e.target.value)}
            placeholder="0.00"
          />
        </div>
        <div>
          <label className="text-gray-500 block mb-1">SUBMITTED BY</label>
          <input
            className="w-full bg-gray-900 border border-gray-700 rounded px-2 py-1 text-white"
            value={submittedBy}
            onChange={e => setSubmittedBy(e.target.value)}
            placeholder="user@company.com"
          />
        </div>
      </div>

      <button
        onClick={submit}
        disabled={loading}
        className="w-full py-2 bg-purple-900 hover:bg-purple-800 text-purple-200
                   rounded text-xs font-bold disabled:opacity-50 transition-colors"
      >
        {loading ? 'VALIDATING…' : 'SUBMIT INVOICE FOR ORACLE VALIDATION'}
      </button>

      {result && (
        <div className={`p-3 rounded border text-xs space-y-2 ${
          result.status === 'approved'
            ? 'border-green-800 bg-green-950 text-green-400'
            : result.status === 'frozen'
            ? 'border-red-800 bg-red-950 text-red-400'
            : 'border-yellow-800 bg-yellow-950 text-yellow-400'
        }`}>
          <div className="flex items-center gap-2 font-bold">
            {result.status === 'approved' ? <CheckCircle2 size={14} /> :
             result.status === 'frozen'   ? <Lock size={14} />          :
                                            <AlertTriangle size={14} />}
            {result.status.toUpperCase()}
          </div>
          {result.invoice_id && (
            <div className="text-gray-400">Invoice: {result.invoice_id}</div>
          )}
          {result.freeze_reason && (
            <div>Reason: {result.freeze_reason}</div>
          )}
          {result.violations && result.violations.length > 0 && (
            <ul className="list-disc list-inside space-y-1">
              {result.violations.map((v, i) => (
                <li key={i}>{v.condition}: {v.description}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
