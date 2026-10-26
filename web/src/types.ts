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
