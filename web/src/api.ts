import type { AllVotesSummary, Constituent, Definitions, DonorVote, MethodData, Scoreboard, TopVotes, SectorLine, LeaderRow, MemberRow, MoneyRow, Profile, Vote } from './types'

const cache = new Map<string, Promise<unknown>>()
function get<T>(url: string): Promise<T> {
  let p = cache.get(url)
  if (!p) {
    p = fetch(url).then((r) => {
      if (!r.ok) throw new Error(`${url}: ${r.status}`)
      return r.json()
    })
    p.catch(() => cache.delete(url))
    cache.set(url, p)
  }
  return p as Promise<T>
}

export const api = {
  members: () => get<MemberRow[]>('/api/members'),
  definitions: () => get<Definitions>('/api/definitions'),
  profile: (id: string) => get<Profile>(`/api/member/${id}`),
  money: (id: string) => get<MoneyRow[]>(`/api/member/${id}/money`),
  votes: (id: string) => get<Vote[]>(`/api/member/${id}/votes`),
  scoreboard: (variant = 'all', sector = 'All business') => get<Scoreboard>(`/api/scoreboard?variant=${variant}&sector=${encodeURIComponent(sector)}`),
  method: () => get<MethodData>('/api/method'),
  allVotesSummary: () => get<AllVotesSummary>('/api/allvotes/summary'),
  allVotesTop: (label: string, minT: number, limit: number) => get<TopVotes>(`/api/allvotes/top?label=${encodeURIComponent(label)}&min_t=${minT}&limit=${limit}`),
  sectors: (id: string) => get<SectorLine[]>(`/api/member/${id}/sectors`),
  donorVotes: (id: string) => get<DonorVote[]>(`/api/member/${id}/donor_votes`),
  constituents: (id: string) => get<Constituent[]>(`/api/member/${id}/constituents`),
  leaderboard: (q: { sector: string; source: string; chamber: string; from: number; to: number }) =>
    get<LeaderRow[]>(`/api/leaderboard?sector=${encodeURIComponent(q.sector)}&source=${q.source}&chamber=${q.chamber}&congress_from=${q.from}&congress_to=${q.to}&limit=25`),
}
