import { useEffect, useMemo, useState } from 'react'
import { api } from './api'
import type { Definitions, MemberRow } from './types'
import { useTheme } from './hooks'
import { fmtMoney } from './util'
import Scoreboard from './views/Scoreboard'
import CaseFile from './views/CaseFile'
import MemberView from './views/MemberView'
import LeaderboardView from './views/LeaderboardView'
import MethodView from './views/MethodView'
import AllVotesView from './views/AllVotesView'
import DefenseView from './views/DefenseView'

type Route = { page: 'score' | 'case' | 'explore' | 'sectors' | 'method' | 'votes' | 'defense'; id: string }

function parse(hash: string): Route {
  const [, page, id] = hash.replace(/^#/, '').split('/')
  if (page === 'case' && id) return { page: 'case', id }
  if (page === 'explore') return { page: 'explore', id: id ?? '' }
  if (page === 'sectors') return { page: 'sectors', id: '' }
  if (page === 'method') return { page: 'method', id: '' }
  if (page === 'votes') return { page: 'votes', id: '' }
  if (page === 'defense') return { page: 'defense', id: '' }
  return { page: 'score', id: '' }
}

export default function App() {
  const [route, setRoute] = useState<Route>(() => parse(location.hash))
  const [members, setMembers] = useState<MemberRow[]>([])
  const [defs, setDefs] = useState<Definitions | null>(null)
  const [q, setQ] = useState('')
  const [chamber, setChamber] = useState('')
  const [era, setEra] = useState('')
  const [err, setErr] = useState('')
  const [theme, cycleTheme] = useTheme()

  useEffect(() => {
    const on = () => setRoute(parse(location.hash))
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  useEffect(() => {
    Promise.all([api.members(), api.definitions()]).then(([m, d]) => { setMembers(m); setDefs(d) }).catch((e) => setErr(String(e)))
  }, [])

  const go = (hash: string) => { location.hash = hash }
  const shown = useMemo(() => {
    const t = q.trim().toLowerCase()
    return members.filter((m) =>
      (!t || m.name.toLowerCase().includes(t) || m.state.toLowerCase() === t) && (!chamber || m.chambers.includes(chamber)) &&
      (!era || (era === 'now' ? m.last_congress === 119 : m.last_congress < 119)))
  }, [members, q, chamber, era])
  const exploreId = route.page === 'explore' ? (route.id || [...members].filter((r) => r.last_congress === 119).sort((a, b) => b.money - a.money)[0]?.id || '') : ''

  if (err) return <div className="card" style={{ margin: 24 }}>Could not reach the data server ({err}). Start it with <code>run.bat</code>.</div>

  const tabs: [Route['page'], string, string][] = [['score', 'Scoreboard', '#/'], ['case', 'Case file', route.id ? `#/case/${route.id}` : '#/'], ['defense', 'Defense', '#/defense'], ['votes', 'Every vote', '#/votes'], ['explore', 'Explore the data', '#/explore'],
    ['sectors', 'Sector money', '#/sectors'], ['method', 'Findings & method', '#/method']]
  return (
    <div className="app">
      <header className="topbar">
        <h1>Congress Money Tracker</h1>
        <nav className="tabs" role="tablist">
          {tabs.filter(([k]) => k !== 'case' || route.page === 'case').map(([k, l, h]) => (
            <button key={k} role="tab" className="tab" aria-selected={route.page === k} onClick={() => go(h)}>{l}</button>
          ))}
        </nav>
        <span className="spacer" />
        <button className="iconbtn" onClick={cycleTheme} title="Switch light / dark / follow system">Theme: {theme}</button>
      </header>
      <div className="banner"><strong>Patterns, not proof.</strong> These numbers show how members voted next to the money they took and what their districts wanted. They show the pattern, not intent: a member may vote that way because they agree. “Findings & method” says what the data can and can’t show.</div>

      {route.page === 'score' && <main className="main"><Scoreboard onOpen={(id) => go(`#/case/${id}`)} onMethod={() => go('#/method')} /></main>}
      {route.page === 'case' && defs && <main className="main"><CaseFile key={route.id} id={route.id} defs={defs} onExplore={(id) => go(`#/explore/${id}`)} /></main>}
      {route.page === 'explore' && defs && (
        <div className="layout">
          <aside className="sidebar">
            <div className="filters">
              <input className="search" placeholder="Search name or state (e.g. TX)" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search members" />
              <div className="row2">
                <select value={chamber} onChange={(e) => setChamber(e.target.value)} aria-label="Chamber"><option value="">Both chambers</option><option>House</option><option>Senate</option></select>
                <select value={era} onChange={(e) => setEra(e.target.value)} aria-label="Era"><option value="">All since 2005</option><option value="now">Serving now</option><option value="past">Former</option></select>
              </div>
              <div className="hint">{shown.length.toLocaleString()} members</div>
            </div>
            <div className="list">
              {shown.slice(0, 400).map((m) => (
                <button key={m.id} className="member-item" aria-current={m.id === exploreId} onClick={() => go(`#/explore/${m.id}`)}>
                  <span className={`party ${m.party}`}><i />{m.party}</span>
                  <span className="nm">{m.name}</span>
                  <span className="meta">{m.state}{m.chamber === 'Senate' ? ' Sen' : ''} · {fmtMoney(m.money)}</span>
                </button>
              ))}
              {shown.length > 400 && <div className="hint" style={{ padding: 12 }}>Showing the first 400. Type to narrow.</div>}
            </div>
          </aside>
          <main className="main">{exploreId && <MemberView id={exploreId} defs={defs} />}</main>
        </div>
      )}
      {route.page === 'sectors' && defs && <main className="main"><LeaderboardView defs={defs} onOpen={(id) => go(`#/case/${id}`)} /></main>}
      {route.page === 'defense' && <main className="main"><DefenseView onOpen={(id) => go(`#/case/${id}`)} /></main>}
      {route.page === 'votes' && <main className="main"><AllVotesView /></main>}
      {route.page === 'method' && defs && <main className="main"><MethodView defs={defs} /></main>}
    </div>
  )
}
