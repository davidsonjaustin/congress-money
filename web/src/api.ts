import type { AllVotesSummary, CompanyRevolving, MemberTrades, PresidentialData, RevolvingOverview, TradesOverview, MemberEarmarks, PledgeData, MoneyCoverage, CompanyDetail, CompanyRow, FreshRow, MemberOutside, OutsideOverview, LobOverview, LobSector, PromisesData, WarData, DefMember, DefOverview, DefRevolving, DefState, MemberInferred, Constituent, Definitions, DonorVote, MethodData, Scoreboard, TopVotes, SectorLine, LeaderRow, MemberRow, MoneyRow, Profile, Vote } from './types'

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
  lobOverview: () => get<LobOverview>('/api/lobbying/overview'),
  lobSector: (sector: string) => get<LobSector>(`/api/lobbying/sector?sector=${encodeURIComponent(sector)}`),
  companies: () => get<CompanyRow[]>('/api/companies'),
  company: (slug: string) => get<CompanyDetail>(`/api/company/${slug}`),
  outside: () => get<OutsideOverview>('/api/outside/overview'),
  memberOutside: (id: string) => get<MemberOutside>(`/api/member/${id}/outside`),
  moneyCoverage: () => get<MoneyCoverage[]>('/api/moneycoverage'),
  pledges: () => get<PledgeData>('/api/pledges'),
  memberEarmarks: (id: string) => get<MemberEarmarks>(`/api/member/${id}/earmarks`),
  presidential: () => get<PresidentialData>('/api/presidential'),
  trades: () => get<TradesOverview>('/api/trades/overview'),
  memberTrades: (id: string) => get<MemberTrades>(`/api/member/${id}/trades`),
  revolving: () => get<RevolvingOverview>('/api/revolving/overview'),
  companyRevolving: (slug: string) => get<CompanyRevolving>(`/api/company/${slug}/revolving`),
  freshness: () => get<{ sources: FreshRow[] }>('/api/freshness'),
  definitions: () => get<Definitions>('/api/definitions'),
  profile: (id: string) => get<Profile>(`/api/member/${id}`),
  money: (id: string) => get<MoneyRow[]>(`/api/member/${id}/money`),
  votes: (id: string) => get<Vote[]>(`/api/member/${id}/votes`),
  scoreboard: (variant = 'all', sector = 'All business') => get<Scoreboard>(`/api/scoreboard?variant=${variant}&sector=${encodeURIComponent(sector)}`),
  method: () => get<MethodData>('/api/method'),
  inferred: (id: string) => get<MemberInferred>(`/api/member/${id}/inferred`),
  defOverview: () => get<DefOverview>('/api/defense/overview'),
  defStates: () => get<DefState[]>('/api/defense/states'),
  defMembers: () => get<DefMember[]>('/api/defense/members'),
  defRevolving: () => get<DefRevolving>('/api/defense/revolving'),
  defWar: () => get<WarData>('/api/defense/war'),
  defPromises: () => get<PromisesData>('/api/defense/promises'),
  allVotesSummary: () => get<AllVotesSummary>('/api/allvotes/summary'),
  allVotesTop: (label: string, minT: number, limit: number, scope: 'linked' | 'all' = 'linked') => get<TopVotes>(`/api/allvotes/top?label=${encodeURIComponent(label)}&min_t=${minT}&limit=${limit}&scope=${scope}`),
  sectors: (id: string) => get<SectorLine[]>(`/api/member/${id}/sectors`),
  donorVotes: (id: string) => get<DonorVote[]>(`/api/member/${id}/donor_votes`),
  constituents: (id: string) => get<Constituent[]>(`/api/member/${id}/constituents`),
  leaderboard: (q: { sector: string; source: string; chamber: string; from: number; to: number }) =>
    get<LeaderRow[]>(`/api/leaderboard?sector=${encodeURIComponent(q.sector)}&source=${q.source}&chamber=${q.chamber}&congress_from=${q.from}&congress_to=${q.to}&limit=25`),
}
