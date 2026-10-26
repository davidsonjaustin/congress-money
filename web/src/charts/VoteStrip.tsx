import { useEffect, useMemo, useRef, useState } from 'react'
import * as d3 from 'd3'
import type { Vote } from '../types'
import { cssVar } from '../hooks'
import { ordinal } from '../util'
import { MARGIN } from './MoneyChart'

type Pt = { v: Vote; px: number; py: number; kind: 'with' | 'against' | 'open' }
type Props = { votes: Vote[]; x: d3.ScaleTime<number, number>; width: number; congresses: { c: number; start: Date; end: Date }[]; height?: number }

// Deterministic vertical jitter so overlapping votes fan out instead of stacking on one pixel.
const jitter = (rn: number, c: number) => {
  const h = Math.sin(rn * 12.9898 + c * 78.233) * 43758.5453
  return (h - Math.floor(h)) * 2 - 1
}

export default function VoteStrip({ votes, x, width, congresses, height = 170 }: Props) {
  const ref = useRef<HTMLCanvasElement>(null)
  const [hover, setHover] = useState<{ pt: Pt; mx: number } | null>(null)
  const [themeTick, setThemeTick] = useState(0)
  const top = 18, bottom = 6
  const laneH = (height - top - bottom) / 2

  useEffect(() => {
    const bump = () => setThemeTick((t) => t + 1)
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    mq.addEventListener('change', bump)
    const mo = new MutationObserver(bump)
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => { mq.removeEventListener('change', bump); mo.disconnect() }
  }, [])

  const pts: Pt[] = useMemo(
    () => votes.map((v) => {
      const lane = v.vote === 'Y' ? 0 : 1
      const cy = top + laneH * lane + laneH / 2
      return {
        v, px: x(new Date(v.d + 'T12:00:00')), py: cy + jitter(v.rn, v.congress) * laneH * 0.38,
        kind: v.unity ? (v.defect === 1 ? 'against' : 'with') : 'open',
      } as Pt
    }),
    [votes, x, laneH],
  )
  const delaunay = useMemo(() => d3.Delaunay.from(pts, (p) => p.px, (p) => p.py), [pts])

  useEffect(() => {
    const cv = ref.current
    if (!cv) return
    const dpr = window.devicePixelRatio || 1
    cv.width = width * dpr; cv.height = height * dpr
    cv.style.width = `${width}px`; cv.style.height = `${height}px`
    const g = cv.getContext('2d')!
    g.setTransform(dpr, 0, 0, dpr, 0, 0)
    g.clearRect(0, 0, width, height)
    const ghost = cssVar('--ghost'), axis = cssVar('--axis'), muted = cssVar('--muted'), ink2 = cssVar('--ink-2'), s2 = cssVar('--s2')
    const [d0, d1] = x.domain()
    // Congress bands, alternating
    congresses.forEach((c, i) => {
      const x0 = Math.max(MARGIN.l, x(c.start)), x1 = Math.min(width - MARGIN.r, x(c.end))
      if (x1 <= x0) return
      if (i % 2 === 0) { g.fillStyle = ghost; g.fillRect(x0, top, x1 - x0, height - top - bottom) }
      if (x1 - x0 > 34) { g.fillStyle = muted; g.font = '11px system-ui, sans-serif'; g.textAlign = 'center'; g.fillText(ordinal(c.c), (x0 + x1) / 2, 12) }
    })
    g.strokeStyle = axis; g.lineWidth = 1
    g.beginPath(); g.moveTo(MARGIN.l, top + laneH); g.lineTo(width - MARGIN.r, top + laneH); g.stroke()
    g.fillStyle = muted; g.font = '11px system-ui, sans-serif'; g.textAlign = 'right'
    g.fillText('Yea', MARGIN.l - 8, top + laneH / 2 + 4); g.fillText('Nay', MARGIN.l - 8, top + laneH * 1.5 + 4)
    g.save()
    g.beginPath(); g.rect(MARGIN.l, 0, width - MARGIN.l - MARGIN.r, height); g.clip()
    const inView = pts.filter((p) => p.v.d >= d3.timeFormat('%Y-%m-%d')(d0) && p.v.d <= d3.timeFormat('%Y-%m-%d')(d1))
    const dense = inView.length > 3000
    const r = dense ? 2.2 : 3.4
    for (const kind of ['with', 'open', 'against'] as const) {
      for (const p of inView) {
        if (p.kind !== kind) continue
        g.beginPath(); g.arc(p.px, p.py, kind === 'against' ? r + 0.6 : r, 0, Math.PI * 2)
        if (kind === 'open') { g.strokeStyle = muted; g.globalAlpha = 0.6; g.lineWidth = 1; g.stroke() }
        else { g.fillStyle = kind === 'against' ? s2 : muted; g.globalAlpha = kind === 'against' ? 0.95 : (dense ? 0.35 : 0.6); g.fill() }
      }
    }
    g.globalAlpha = 1; g.strokeStyle = ink2; g.lineWidth = 1.2
    for (const p of inView) {
      if (p.v.p != null && p.v.p < 0.25) { g.beginPath(); g.arc(p.px, p.py, r + 3, 0, Math.PI * 2); g.stroke() }
    }
    g.restore()
  }, [pts, width, height, x, congresses, laneH, themeTick])

  function onMove(e: React.PointerEvent<HTMLCanvasElement>) {
    if (!pts.length) return
    const rect = e.currentTarget.getBoundingClientRect()
    const mx = e.clientX - rect.left, my = e.clientY - rect.top
    const i = delaunay.find(mx, my)
    const p = pts[i]
    setHover(p && Math.hypot(p.px - mx, p.py - my) < 14 ? { pt: p, mx } : null)
  }

  const hv = hover?.pt.v
  return (
    <div className="chart">
      <canvas ref={ref} role="img" aria-label="Every vote as a dot by date: Yea on top, Nay below; orange dots voted against their own party's majority" onPointerMove={onMove} onPointerLeave={() => setHover(null)} />
      {hover && hv && (
        <div className="tooltip" style={{ left: Math.min(Math.max(hover.mx + 14, 0), width - 350), top: Math.max(0, hover.pt.py - 20) }}>
          <div className="t-h">{hv.d} · {hv.chamber} roll call {hv.rn}</div>
          <div className="t-title">{hv.title || hv.desc || hv.q}</div>
          {hv.title && hv.desc && <div className="t-d">{hv.desc}</div>}
          <div className="t-d">{hv.q}{hv.result ? ` → ${hv.result}` : ''}{hv.pa ? ` · ${hv.pa}` : ''}</div>
          <div className="t-r" style={{ marginTop: 6 }}><span className="n">Voted</span><span className="v">{hv.vote === 'Y' ? 'Yea' : 'Nay'}</span></div>
          {hv.unity && <div className="t-r"><span className="n">Own party majority</span><span className="v">{hv.pm === 1 ? 'Yea' : 'Nay'}{hv.defect === 1 ? ' (broke from it)' : ''}</span></div>}
          {!hv.unity && <div className="t-r"><span className="n">Not a party-line vote</span><span className="v" /></div>}
          {hv.p != null && <div className="t-r"><span className="n">Model chance of this vote</span><span className="v">{Math.round(hv.p * 100)}%</span></div>}
        </div>
      )}
    </div>
  )
}
