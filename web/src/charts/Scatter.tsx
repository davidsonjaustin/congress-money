import { useMemo, useState } from 'react'
import * as d3 from 'd3'
import type { Scored } from '../types'
import { useWidth } from '../hooks'

const PARTY_VAR: Record<string, string> = { D: 'var(--dem)', R: 'var(--rep)', I: 'var(--muted)' }

export default function Scatter({ data, onOpen }: { data: Scored[]; onOpen: (id: string) => void }) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<Scored | null>(null)
  const H = 420, M = { l: 58, r: 18, t: 18, b: 46 }
  const pts = useMemo(() => data.map((m) => ({ m, lx: (m.loyalty ?? 0) * 100, ly: (m.lift ?? 0) * 100 })), [data])
  const x = useMemo(() => d3.scaleLinear().domain([0, 100]).range([M.l, width - M.r]), [width])
  const ext = d3.extent(pts, (p) => p.ly) as [number, number]
  const y = useMemo(() => d3.scaleLinear().domain([Math.min(-10, (ext[0] ?? -10) - 5), Math.max(10, (ext[1] ?? 10) + 5)]).nice().range([H - M.b, M.t]), [ext[0], ext[1]])
  const delaunay = useMemo(() => d3.Delaunay.from(pts, (p) => x(p.lx), (p) => y(p.ly)), [pts, x, y])
  const labeled = useMemo(() => {
    const byLift = [...pts].sort((a, b) => b.ly - a.ly)
    const cand = [...byLift.slice(0, 6), ...byLift.slice(-6)]
    const kept: { px: number; py: number; p: (typeof pts)[number] }[] = []
    for (const p of cand) {
      const px = x(p.lx), py = y(p.ly)
      if (kept.every((k) => Math.hypot(k.px - px, k.py - py) > 70)) kept.push({ px, py, p })
    }
    return kept
  }, [pts, x, y])

  function onMove(e: React.PointerEvent<SVGRectElement>) {
    if (!pts.length) return
    const r = (e.currentTarget as SVGRectElement).getBoundingClientRect()
    const mx = e.clientX - r.left + M.l, my = e.clientY - r.top + M.t
    const i = delaunay.find(mx, my)
    const p = pts[i]
    setHover(p && Math.hypot(x(p.lx) - mx, y(p.ly) - my) < 24 ? p.m : null)
  }
  const hp = hover ? pts.find((p) => p.m.id === hover.id) : undefined
  return (
    <div className="chart" ref={ref}>
      <svg width={width} height={H} role="img" aria-label="Scatter of ranked members: share of funded votes cast the donors' way against lift over same-party peers">
        {y.ticks(6).map((t) => (
          <g key={t}>
            <line x1={M.l} x2={width - M.r} y1={y(t)} y2={y(t)} stroke={t === 0 ? 'var(--axis)' : 'var(--grid)'} />
            <text x={M.l - 8} y={y(t) + 4} textAnchor="end" fontSize={11} fill="var(--muted)">{t > 0 ? `+${t}` : t}</text>
          </g>
        ))}
        {[0, 25, 50, 75, 100].map((t) => (
          <g key={t}>
            <line x1={x(t)} x2={x(t)} y1={M.t} y2={H - M.b} stroke="var(--grid)" />
            <text x={x(t)} y={H - M.b + 16} textAnchor="middle" fontSize={11} fill="var(--muted)">{t}%</text>
          </g>
        ))}
        <text x={(M.l + width - M.r) / 2} y={H - 6} textAnchor="middle" fontSize={12} fill="var(--ink-2)">Voted the donors’ way, share of votes weighted by sector money →</text>
        <text transform={`translate(14 ${(M.t + H - M.b) / 2}) rotate(-90)`} textAnchor="middle" fontSize={12} fill="var(--ink-2)">Points above same-party peers →</text>
        <text x={width - M.r - 6} y={M.t + 12} textAnchor="end" fontSize={11} fill="var(--ink-2)">More donor-loyal than peers</text>
        <text x={width - M.r - 6} y={H - M.b - 8} textAnchor="end" fontSize={11} fill="var(--ink-2)">Loyal, but so are their peers</text>
        <text x={M.l + 6} y={H - M.b - 8} fontSize={11} fill="var(--ink-2)">Votes against donors</text>
        {pts.map((p) => (
          <circle key={p.m.id} cx={x(p.lx)} cy={y(p.ly)} r={hover?.id === p.m.id ? 6 : 4} fill={PARTY_VAR[p.m.party]} stroke="var(--surface)" strokeWidth={2} opacity={hover && hover.id !== p.m.id ? 0.45 : 0.9} />
        ))}
        {labeled.map(({ px, py, p }) => (
          <text key={p.m.id} x={px + 8} y={py + 4} fontSize={11} fill="var(--ink)">{p.m.name.split(' ').slice(-1)[0].replace(',', '')}</text>
        ))}
        <rect x={M.l} y={M.t} width={width - M.l - M.r} height={H - M.t - M.b} fill="transparent" style={{ cursor: hover ? 'pointer' : 'default' }}
          onPointerMove={onMove} onPointerLeave={() => setHover(null)} onClick={() => hover && onOpen(hover.id)} />
      </svg>
      {hover && hp && (
        <div className="tooltip" style={{ left: Math.min(Math.max(x(hp.lx) + 14, 0), width - 280), top: Math.max(0, y(hp.ly) - 70) }}>
          <div className="t-title"><span className={`party ${hover.party}`}><i />{hover.party}</span> {hover.name} · {hover.state}</div>
          <div className="t-r"><span className="n">Voted donors’ way</span><span className="v">{hover.n_funded_aligned} of {hover.n_funded}</span></div>
          <div className="t-r"><span className="n">Same-party peers would</span><span className="v">≈ {(hover.peers_funded_aligned ?? 0).toFixed(1)}</span></div>
          <div className="t-r"><span className="n">Index (50 = peers)</span><span className="v">{hover.index?.toFixed(0)}</span></div>
          <div className="t-d">{hover.top_sectors}</div>
          <div className="t-d">Click for the case file</div>
        </div>
      )}
      <div className="legend"><span><i className="dot" style={{ background: 'var(--dem)' }} />Democrat</span><span><i className="dot" style={{ background: 'var(--rep)' }} />Republican</span><span><i className="dot" style={{ background: 'var(--muted)' }} />Independent</span></div>
    </div>
  )
}
