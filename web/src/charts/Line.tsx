import * as d3 from 'd3'
import { useWidth } from '../hooks'

export type Series = { name: string; color: string; pts: [number, number][] }

/** Multi-line chart over years. One axis, a legend that names every line, light grid. */
export default function Line({ series, fmt, height = 190 }: { series: Series[]; fmt: (v: number) => string; height?: number }) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const M = { l: 52, r: 12, t: 10, b: 24 }
  const xs = series.flatMap((s) => s.pts.map((p) => p[0]))
  const ys = series.flatMap((s) => s.pts.map((p) => p[1]))
  if (!xs.length) return <div ref={ref} className="hint">Loading…</div>
  const x = d3.scaleLinear().domain([d3.min(xs)!, d3.max(xs)!]).range([M.l, width - M.r])
  const y = d3.scaleLinear().domain([0, d3.max(ys)! * 1.08]).nice().range([height - M.b, M.t])
  const line = d3.line<[number, number]>().x((p) => x(p[0])).y((p) => y(p[1]))
  return (
    <div ref={ref}>
      <svg width={width} height={height} role="img" aria-label={series.map((s) => s.name).join(', ')}>
        {y.ticks(4).map((t) => (
          <g key={t}><line x1={M.l} x2={width - M.r} y1={y(t)} y2={y(t)} stroke="var(--grid)" /><text x={M.l - 6} y={y(t) + 4} textAnchor="end" fontSize={11} fill="var(--ink-2)">{fmt(t)}</text></g>
        ))}
        {x.ticks(6).map((t) => <text key={t} x={x(t)} y={height - 6} textAnchor="middle" fontSize={11} fill="var(--ink-2)">{t}</text>)}
        {series.map((s) => <path key={s.name} d={line(s.pts) ?? ''} fill="none" stroke={s.color} strokeWidth={2} />)}
      </svg>
      <div className="legend3">{series.map((s) => <span key={s.name}><i style={{ background: s.color }} /> {s.name}</span>)}</div>
    </div>
  )
}
