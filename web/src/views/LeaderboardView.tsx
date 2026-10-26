import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { Definitions, LeaderRow } from '../types'
import { SECTOR_SLOT, SOURCES, fmtMoney, ordinal } from '../util'

export default function LeaderboardView({ defs, onOpen }: { defs: Definitions; onOpen: (id: string) => void }) {
  const sectors = useMemo(
    () => Object.entries(defs.category).filter(([s, c]) => c !== 'unknown' && s !== 'Business (sector not yet assigned)').map(([s]) => s)
      .sort((a, b) => (SECTOR_SLOT[a] || 99) - (SECTOR_SLOT[b] || 99) || a.localeCompare(b)),
    [defs],
  )
  const [sector, setSector] = useState('Energy & Natural Resources')
  const [source, setSource] = useState('pac_direct')
  const [chamber, setChamber] = useState('')
  const [from, setFrom] = useState(109)
  const [to, setTo] = useState(119)
  const [rows, setRows] = useState<LeaderRow[] | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let alive = true
    setBusy(true)
    api.leaderboard({ sector, source, chamber, from, to }).then((r) => { if (alive) { setRows(r); setBusy(false) } }).catch(() => alive && setBusy(false))
    return () => { alive = false }
  }, [sector, source, chamber, from, to])

  const max = rows?.[0]?.amount || 1
  const congresses = Array.from({ length: 11 }, (_, i) => 109 + i)
  return (
    <div className="page">
      <div className="card">
        <h2>Who receives the most from a sector</h2>
        <div className="sub">Ranks members by money from the chosen sector. A big total mostly reflects a long career, a safe seat or a committee post, so use it to find where to look, not as a finding.</div>
        <div className="controls">
          <div className="ctl">Sector
            <select value={sector} onChange={(e) => setSector(e.target.value)}>{sectors.map((s) => <option key={s}>{s}</option>)}</select>
          </div>
          <div className="ctl">Money source
            <select value={source} onChange={(e) => setSource(e.target.value)}>{SOURCES.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}</select>
          </div>
          <div className="ctl">Chamber
            <select value={chamber} onChange={(e) => setChamber(e.target.value)}><option value="">Both</option><option>House</option><option>Senate</option></select>
          </div>
          <div className="ctl">From
            <select value={from} onChange={(e) => setFrom(Math.min(+e.target.value, to))}>{congresses.map((c) => <option key={c} value={c}>{ordinal(c)} ({2005 + 2 * (c - 109)})</option>)}</select>
          </div>
          <div className="ctl">To
            <select value={to} onChange={(e) => setTo(Math.max(+e.target.value, from))}>{congresses.map((c) => <option key={c} value={c}>{ordinal(c)} ({2006 + 2 * (c - 109)})</option>)}</select>
          </div>
        </div>
      </div>
      <div className={`card ${busy ? 'reloading' : ''}`}>
        {rows && rows.length === 0 && <div className="hint">No money found for these settings.</div>}
        <div className="bars">
          {rows?.map((r, i) => (
            <button key={r.id} className="bar-row" onClick={() => onOpen(r.id)} title="Open this member">
              <span className="hint">{i + 1}</span>
              <span><span className={`party ${r.party}`}><i />{r.party}</span> {r.name} <span className="hint">· {r.state}{r.chamber === 'Senate' ? ' Sen.' : ''}</span></span>
              <span className="track"><div className="fill" style={{ width: `${(100 * r.amount) / max}%` }} /></span>
              <span className="amt">{fmtMoney(r.amount)}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
