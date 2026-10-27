export type MemberRow = {
  id: string; name: string; party: 'D' | 'R' | 'I'; state: string; chamber: 'House' | 'Senate'
  first_congress: number; last_congress: number; chambers: string[]; money: number
}
export type Term = {
  congress: number; chamber: string; state: string; district: number; party_code: number; nominate_dim1: number | null
  demshare_pres: number | null; mrp_ideology: number | null; lines_match: string | null; start: number; end: number
}
export type CongressStat = { congress: number; chamber: string; votes: number; unity_votes: number; defect_pct: number | null; surprising_pct: number | null }
export type CommitteeRow = { congress: number; chamber: string; committee_name: string; start_date: string | null; end_date: string | null; majority: boolean; rank: number | null; source: string }
export type MoneyTotal = { source: string; sector: string; amount: number }
export type Profile = { id: string; name: string; terms: Term[]; stats: CongressStat[]; committees: CommitteeRow[]; money_totals: MoneyTotal[] }
export type MoneyRow = { m: string; source: string; sector: string; amt: number; n: number }
export type Vote = {
  d: string; congress: number; chamber: string; rn: number; vote: 'Y' | 'N'; p: number | null; unity: boolean; defect: number | null
  pm: number | null; q: string | null; desc: string | null; pa: string | null; title: string | null; bill: string | null; result: string | null
}
export type Definitions = {
  policy_sector: { policy_area: string; sector: string; tier: 'strict' | 'broad'; note: string }[]
  committee_sector: { chamber: string; committee_pattern: string; sector: string; tier: 'strict' | 'broad'; note: string }[]
  direction: { congress: string; chamber: string; rollnumber: string; bill: string; date: string; sector: string; subsector: string; helps_vote: string; evidence_level: string; evidence: string; source_url: string }[]
  category: Record<string, string>
  lock: string[]
}
export type LeaderRow = { id: string; name: string; party: string; state: string; chamber: string; amount: number }
export type Constituent = {
  d: string; congress: number; chamber: string; rn: number; state: string; district: number; bill: string; note: string; item: string
  match: 'direct' | 'related'; yea: number; voted_for_item: number; est: number | null; sd: number | null; p_support: number | null
  district_view: 'supports' | 'opposes' | 'uncertain' | 'unknown'; with_district: number | null; n_resp: number | null
}
export type DonorVote = {
  d: string; congress: number; chamber: string; rn: number; bill: string; sector: string; subsector: string; helps_vote: 'Yea' | 'Nay'
  evidence_level: 'documented' | 'reported'; yea: number; aligned: number; pac_6y: number; pac_2y: number; share_6y: number | null
  q: string | null; desc: string | null; evidence: string; source_url: string
  district_view: 'supports' | 'opposes' | 'uncertain' | 'unknown' | null; with_district: number | null; est: number | null; item: string | null; district_match?: 'direct' | 'proxy' | 'related' | null
}
export type Scored = {
  id: string; name: string; party: 'D' | 'R' | 'I'; state: string; chamber: 'House' | 'Senate'; last_congress: number; first_congress: number
  votes_coded: number | null; weight: number | null; n_funded: number | null; n_funded_aligned: number | null; peers_funded_aligned: number | null
  loyalty: number | null; peers: number | null; lift: number | null; se: number | null; z: number | null; index: number | null
  money_at_stake: number | null; top_sectors: string | null; ranked: boolean
  const_votes: number | null; const_against: number | null; const_rate: number | null; const_lift: number | null
  donors_over_district: number | null; district_over_donors: number | null
  donor_district_votes?: number | null; proxy_donors_over?: number | null; proxy_district_over?: number | null; proxy_votes?: number | null; fossil_const_votes?: number | null; fossil_const_against?: number | null
}
export type Coverage = { coded_votes: number; roll_calls: number; bill_votes: number; ranked_members: number; landmark_votes: number; votes_since_2008: number; coded_since_2008: number }
export type SectorOption = { label: string; votes: number; members_ranked: number }
export type Scoreboard = { members: Scored[]; coverage: Coverage; sectors: SectorOption[] }
export type TimingRow = { group: string; spec: string; term: string; effect_pts: number; se_pts: number; n: number }
export type SectorLine = {
  sector: string; subsector: string; label: string; votes: number; weight: number; money: number; n_funded: number; n_aligned: number
  peers_aligned: number; lift: number; se: number | null; z: number | null; series: [string, number][]
}
export type PlaceboRow = { vote_group: string; money_from: string; is_own: boolean; effect_pts: number; se_pts: number; n: number }
export type CommitteeRow2 = { industry: string; outcome: string; effect: number; se: number; joiners: number; n: number }
export type MethodData = { timing: TimingRow[]; placebo: PlaceboRow[]; committee: CommitteeRow2[] }
export type AllVotesIndustry = { label: string; votes: number; strong_only: number; link_only: number; link_only_null: number; link_before: number | null; link_before_null: number | null; link_after: number | null }
export type AllVotesSummary = { thresholds: { only: number; joint_b: number; joint_a: number }; industries: AllVotesIndustry[]; tested: number; all_votes: number; validation: { tier: string; n: number; agree: number }[]; funded: { label: string; votes: number; member_votes: number; aligned: number; expected: number }[]; dose: { k: string; member_votes: number; aligned: number; expected: number }[] }
export type TopVote = {
  congress: number; chamber: string; rollnumber: number; d: string; label: string; n: number; b_only: number; t_only: number; t_before: number | null; t_after: number | null
  q: string | null; descr: string | null; title: string | null; bill: string | null; policy_area: string | null; result: string | null; yeas: number | null; nays: number | null; coded_side: 'Yea' | 'Nay' | null
}
export type TopVotes = { rows: TopVote[]; total: number }
export type InferredLine = { label: string; votes_coded: number; weight: number; n_funded: number; n_funded_aligned: number; expected: number; lift: number; se: number | null; z: number | null; money: number }
export type InferredVote = { d: string | null; congress: number; chamber: string; rollnumber: number; label: string; aligned: number; p_exp: number; pac_6y: number; pull_yea: number; t_only: number; bill: string | null; q: string | null; descr: string | null; result: string | null }
export type MemberInferred = { summary: InferredLine[]; with_money: InferredVote[]; against_money: InferredVote[] }
export type DefFy = { fy: number; scope: 'dod' | 'all'; amount: number }
export type DefCompanyYear = { company: string; kind: string; year: number; contracts_dod: number | null; contracts_all: number | null; revenue: number | null; lobbying: number | null; pac: number | null; indiv: number | null }
export type DefTracked = { year: number; dod: number | null; allc: number | null; lobbying: number | null; pac: number | null; indiv: number | null }
export type DefReported = { company: string; year: number; share: number; basis: string; source_url: string; how_obtained: string }
export type DefOverview = { fy: DefFy[]; companies: DefCompanyYear[]; tracked: DefTracked[]; member_money: { y: number; source: string; amount: number }[]; reported: DefReported[] }
export type DefState = { state: string; dod: number; pop: number; per_capita: number }
export type DefMember = {
  bioguide: string; name: string; party: 'D' | 'R' | 'I'; state: string; chamber: string; last_congress: number; n: number; aligned: number; p_exp: number | null
  pac_all: number | null; pac_6y: number | null; ind_all: number | null; state_pc: number | null; district_dod: number | null; district_pc: number | null
}
export type DefRevolving = {
  per_company: { company: string; lobbyists: number; with_position: number; congress_roles: number; executive_roles: number }[]
  spend: { company: string; firms: number; filings: number; spend: number | null }[]
  by_year: { year: number; lobbyists: number; with_position: number; congress_roles: number }[]
  common_positions: { position: string; people: number }[]
  entities: { entity: string; filings: number }[]
  door_facts: { date: string; text: string; source_name: string; source_url: string }[]
}
export type WarVote = { congress: number; chamber: string; rollnumber: number; d: string; bill: string; q: string; descr: string; yeas: number; nays: number; result: string }
export type WarMember = { id: string; name: string; party: 'D' | 'R'; state: string; chamber: string; n: number; constrain: number; pac_6y: number }
export type WarData = { votes: WarVote[]; by_party: { chamber: string; party: 'D' | 'R'; members: number; share: number }[]; members: WarMember[]; association: { party: string; chamber: string; members: number; corr: number }[] }
export type PromiseItem = {
  bioguide: string; name: string; date: string; topic: string; statement: string; source_name: string; source_url: string
  record: { war: { n: number; constrain: number; n119: number; constrain119: number } | null; defense: { n: number; aligned: number } | null; pac_all: number | null; member: { name: string; party: string; state: string; last_congress: number } | null }
}
export type ExecItem = { date: string; kind: 'said' | 'did'; text: string; source_name: string; source_url: string }
export type PromisesData = { items: PromiseItem[]; executive: ExecItem[] }
