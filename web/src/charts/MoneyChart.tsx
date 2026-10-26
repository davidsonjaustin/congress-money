import { useMemo, useState } from 'react'
import * as d3 from 'd3'
import { fmtMoney } from '../util'

export type Series = { key: string; label: string; color: string }
export type Bucket = { start: Date; end: Date; label: string; vals: Record<string, number> }
export type Band = { start: Date; end: Date; label: string }
export const MARGIN = { l: 56, r: 16 }

type Props = {
  buckets: Bucket[]; series: Series[]; x: d3.ScaleTime<number, number>; width: number; bands: Band[]
  yLabel: string; height?: number; ariaLabel: string
}

export default function MoneyChart({ buckets, series, x, width, bands, yLabel, height = 240, ariaLabel }: Props) {
  const top = 14, bottom = 26
  const [hover, setHover] = useState<{ i: number; px: number } | null>(null)
  const keys = series.map((s) => s.key)
  const keyStr = keys.join('|')

  const stacks = useMemo(
    () => d3.stack<Bucket>().keys(keys).value((b, k) => Math.max(0, b.vals[k] || 0))(buckets),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [buckets, keyStr],
  )
  const maxY = d3.max(buckets, (b) => d3.sum(keys, (k) => Math.max(0, b.vals[k] || 0))) || 1
  const y = d3.scaleLinear().domain([0, maxY]).nice().range([height - bottom, top])
  const [d0, d1] = x.domain()
  const spanYears = (d1.getTime() - d0.getTime()) / (365.25 * 864e5)
  const xTicks = x.ticks(Math.max(3, Math.floor(width / 90)))
  const fmtX = spanYears > 3 ? d3.timeFormat('%Y') : d3.timeFormat('%b %Y')
  const plotW = width - MARGIN.l - MARGIN.r

  function onMove(e: React.PointerEvent<SVGRectElement>) {
    const r = (e.currentTarget as SVGRectElement).getBoundingClientRect()
    const px = e.clientX - r.left + MARGIN.l
    const date = x.invert(px)
    const i = buckets.findIndex((b) => date >= b.start && date < b.end)
    setHover(i >= 0 ? { i, px } : null)
  }

  const hb = hover ? buckets[hover.i] : null
  const rowsForTip = hb
    ? series.map((s) => ({ s, v: hb.vals[s.key] || 0 })).filter((r) => r.v !== 0).sort((a, b) => b.v - a.v)
    : []
  const tipTotal = rowsForTip.reduce((a, r) => a + r.v, 0)

  return (
    <div className="chart">
      <svg width={width} height={height} role="img" aria-label={ariaLabel}>
        <clipPath id="plotclip"><rect x={MARGIN.l} y={0} width={plotW} height={height} /></clipPath>
        {y.ticks(4).map((t) => (
          <g key={t}>
            <line x1={MARGIN.l} x2={width - MARGIN.r} y1={y(t)} y2={y(t)} stroke="var(--grid)" strokeWidth={1} />
            <text x={MARGIN.l - 8} y={y(t) + 4} textAnchor="end" fontSize={11} fill="var(--muted)" style={{ fontVariantNumeric: 'tabular-nums' }}>{fmtMoney(t)}</text>
          </g>
        ))}
        <g clipPath="url(#plotclip)">
          {bands.map((b, i) => (
            <g key={i}>
              <rect x={x(b.start)} y={top} width={Math.max(0, x(b.end) - x(b.start))} height={height - bottom - top} fill="var(--band)" />
              <text x={x(b.start) + 4} y={top + 11} fontSize={10.5} fill="var(--ink-2)">{b.label}</text>
            </g>
          ))}
          {stacks.map((layer, li) =>
            layer.map((d, bi) => {
              const b = buckets[bi]
              const h = y(d[0]) - y(d[1]) - 1.5
              if (h < 0.6) return null
              const bw = Math.min(24, Math.max(1.2, x(b.end) - x(b.start) - 2))
              const cx = (x(b.start) + x(b.end)) / 2
              return <rect key={`${li}-${bi}`} x={cx - bw / 2} y={y(d[1])} width={bw} height={h} rx={Math.min(3, bw / 2)} fill={series[li].color} opacity={hover && hover.i !== bi ? 0.55 : 1} />
            }),
          )}
        </g>
        <line x1={MARGIN.l} x2={width - MARGIN.r} y1={height - bottom} y2={height - bottom} stroke="var(--axis)" />
        {xTicks.map((t) => (
          <text key={+t} x={x(t)} y={height - 8} textAnchor="middle" fontSize={11} fill="var(--muted)">{fmtX(t)}</text>
        ))}
        <text x={MARGIN.l} y={9} fontSize={11} fill="var(--muted)">{yLabel}</text>
        {hb && <line x1={(x(hb.start) + x(hb.end)) / 2} x2={(x(hb.start) + x(hb.end)) / 2} y1={top} y2={height - bottom} stroke="var(--ink-2)" strokeWidth={1} />}
        <rect x={MARGIN.l} y={top} width={plotW} height={height - bottom - top} fill="transparent" onPointerMove={onMove} onPointerLeave={() => setHover(null)} />
      </svg>
      {hover && hb && (
        <div className="tooltip" style={{ left: Math.min(Math.max(hover.px + 14, 0), width - 250), top: 6 }}>
          <div className="t-h">{hb.label}</div>
          {rowsForTip.length === 0 && <div className="t-d">No money in this period</div>}
          {rowsForTip.map((r) => (
            <div className="t-r" key={r.s.key}>
              <span className="k" style={{ background: r.s.color }} />
              <span className="n">{r.s.label}</span>
              <span className="v">{fmtMoney(r.v)}</span>
            </div>
          ))}
          {rowsForTip.length > 1 && <div className="t-r t-tot"><span className="n">Total</span><span className="v">{fmtMoney(tipTotal)}</span></div>}
        </div>
      )}
    </div>
  )
}
