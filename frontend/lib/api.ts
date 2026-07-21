// Normalize NEXT_PUBLIC_API_URL so common misconfigurations still work:
// a schemeless host ("api.example.com") would otherwise be fetched as a
// RELATIVE path against the frontend origin, and a trailing slash would
// produce double-slash paths. Assume https when no scheme is given.
function normalizeBase(raw: string): string {
  const trimmed = raw.trim().replace(/\/+$/, '');
  if (!trimmed) return 'http://localhost:8000';
  return /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
}

const BASE = normalizeBase(process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000');

function formatApiError(detail: unknown, fallback: string): string {
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (!Array.isArray(detail)) return fallback;

  const messages = detail.flatMap((issue) => {
    if (typeof issue !== 'object' || issue == null) return [];
    const record = issue as { loc?: unknown; msg?: unknown };
    if (typeof record.msg !== 'string') return [];
    const location = Array.isArray(record.loc)
      ? record.loc.filter((part) => part !== 'body').map(String).join('.')
      : '';
    const message = record.msg.replace(/^Value error,\s*/i, '');
    return [location ? `${location}: ${message}` : message];
  });
  return messages.length > 0 ? messages.join(' ') : fallback;
}

// Valuation-backed reads only change when the backend republishes (≈ daily), so GETs
// are cached in memory for a few minutes: tab switches, filter round-trips, and
// back-navigation render instantly instead of refetching. POSTs (simulator, trades,
// offseason plans) are user-specific what-ifs and are never cached.
const GET_CACHE_TTL_MS = 5 * 60 * 1000;
const getCache = new Map<string, { expires: number; data: unknown }>();

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers,
  });
  if (!res.ok) {
    const body: unknown = await res.json().catch(() => null);
    const detail = typeof body === 'object' && body != null && 'detail' in body
      ? (body as { detail: unknown }).detail
      : null;
    throw new Error(formatApiError(detail, res.statusText));
  }
  return res.json() as Promise<T>;
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  if ((init?.method ?? 'GET') !== 'GET') return requestJson<T>(path, init);

  const cached = getCache.get(path);
  if (cached && cached.expires > Date.now()) return cached.data as T;

  const data = await requestJson<T>(path, init);
  getCache.set(path, { expires: Date.now() + GET_CACHE_TTL_MS, data });
  return data;
}

type QueryValue = string | number | boolean | null | undefined;

function queryString(params: Record<string, QueryValue>): string {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value == null || value === '') continue;
    qs.set(key, String(value));
  }
  const query = qs.toString();
  return query ? `?${query}` : '';
}

// ---- Types (mirroring FastAPI response shapes) ----------------

export interface TeamSummary {
  team_id: number;
  abbreviation: string | null;
  name: string | null;
}

export interface PlayerSummary {
  player_id: number;
  full_name: string;
  position: string | null;
  latest_season: string | null;
  latest_stats_team: TeamSummary | null;
  current_team: TeamSummary | null;
  current_team_source: string | null;
  team_data_note: string | null;
}

export interface ValuationResponse {
  player_id: number;
  player_name: string;
  position: string | null;
  current_team: TeamSummary | null;
  season: string;
  value_pct: number;
  lo_pct: number;
  hi_pct: number;
  actual_pct: number | null;
  actual_usd: number | null;
  gap_pct: number | null;
  salary_cap: number | null;
  value_usd: number | null;
  model_version: string;
  features: Record<string, number> | null;
  attribution: ValuationAttribution[] | null;
  verdict_label: string;
  verdict_tone: 'positive' | 'negative' | 'neutral' | 'warning';
  caution_flags: string[];
  caveat: string | null;
  /** When the served valuation was published; null when computed live on request. */
  computed_at: string | null;
}

export interface ValuationAttribution {
  group: string;
  label: string;
  delta_pct: number;
}

export type ValuationStatus = 'ready' | 'unavailable';

export interface PlayerCardStats {
  gp: number | null;
  mpg: number | null;
  pts_pg: number | null;
  reb_pg: number | null;
  ast_pg: number | null;
  ts_pct: number | null;
  bpm: number | null;
  /** League percentile (0-100) per stat key; present on watchlist payloads. */
  pctl?: Record<string, number> | null;
}

export interface PlayerCardValuation {
  season: string;
  value_pct: number;
  lo_pct: number;
  hi_pct: number;
  actual_pct: number | null;
  actual_usd: number | null;
  gap_pct: number | null;
  salary_cap: number | null;
  model_version: string;
  verdict_label: string;
  verdict_tone: 'positive' | 'negative' | 'neutral' | 'warning';
  caution_flags: string[];
  caveat: string | null;
  stats?: PlayerCardStats | null;
}

export interface PlayerCardResponse extends PlayerSummary {
  valuation_status: ValuationStatus;
  valuation: PlayerCardValuation | null;
}

export interface PlayerContractYear {
  season: string;
  cap_hit_usd: number | null;
  cap_hit_pct: number | null;
  salary_cap: number | null;
  is_guaranteed: boolean;
  is_player_option: boolean;
  is_team_option: boolean;
  value_pct: number | null;
  value_gap_pct: number | null;
}

export interface PlayerContractResponse {
  player_id: number;
  player_name: string;
  contract_id: number;
  season_start: string;
  years: number;
  total_value: number | null;
  source: string;
  scraped_at: string | null;
  extension_start_season: string | null;
  years_detail: PlayerContractYear[];
  caveat: string;
}

export interface PlayerExtensionResponse {
  player_id: number;
  eligible: boolean;
  ineligible_reason: string | null;
  value_season: string;
  value_pct: number | null;
  value_lo_pct: number | null;
  value_hi_pct: number | null;
  current_pay_pct: number | null;
  final_contract_season: string | null;
  entering_season: string | null;
  projected_aav_usd: number | null;
  projected_aav_lo_usd: number | null;
  projected_aav_hi_usd: number | null;
  projected_cap_usd: number | null;
  gap_pct: number | null;
  verdict: string;
  tone: string;
  rationale: string;
  trajectory_note: string | null;
  caveat: string;
}

export type SimilarPlayersMode = 'twins' | 'contract_comps' | 'replacements';

export interface SimilarPlayerResult {
  player: PlayerSummary;
  similarity_score: number;
  value_pct: number | null;
  salary_pct: number | null;
  actual_usd: number | null;
  gap_pct: number | null;
  age: number | null;
  explanation_tags: string[];
  deltas: Record<string, number>;
}

export interface CompSynthesis {
  n_comps: number;
  model_value_pct: number | null;
  market_low_pct: number;
  market_median_pct: number;
  market_high_pct: number;
  suggested_pct: number | null;
  market_low_usd: number | null;
  market_median_usd: number | null;
  market_high_usd: number | null;
  suggested_usd: number | null;
  basis_note: string;
}

export interface SimilarPlayersResponse {
  player_id: number;
  player_name: string;
  season: string;
  mode: SimilarPlayersMode;
  basis: string[];
  results: SimilarPlayerResult[];
  caveat: string;
  comp_synthesis: CompSynthesis | null;
}

export type WatchlistBucket = 'all' | 'underpaid' | 'overpaid';
export type WatchlistSort = 'mismatch' | 'gap' | 'value' | 'pay' | 'name';

export interface PlayerWatchlistResponse {
  items: PlayerCardResponse[];
  total: number;
  limit: number;
  offset: number;
  bucket: WatchlistBucket;
  sort: WatchlistSort;
  season: string | null;
  qualified_only: boolean;
  caveat: string;
}

export interface PlayerWatchlistParams {
  query?: string;
  bucket?: WatchlistBucket;
  sort?: WatchlistSort;
  season?: string;
  position?: string;
  team?: string;
  qualifiedOnly?: boolean;
  limit?: number;
  offset?: number;
}

export interface PlayerValuationCautionsResponse {
  items: PlayerCardResponse[];
  total: number;
  limit: number;
  season: string;
  caveat: string;
}

export interface SimulatorRequest {
  player_id: number;
  aav_pct: number;
  years: number;
  guaranteed_years?: number | null;
  player_option_years?: number;
  team_option_years?: number;
  start_season?: string;
  valuation_season?: string | null;
  /** If set, overlay the first-year cap hit on this team's payroll for apron consequences. */
  team_id?: number | null;
}

export interface ContractYearResponse {
  season: string;
  cap_hit_usd: number;
  cap_hit_pct: number;
  is_guaranteed: boolean;
  is_player_option: boolean;
  is_team_option: boolean;
  salary_cap: number;
  tax_line: number;
  first_apron: number;
  second_apron: number;
  is_projected_cap: boolean;
}

export interface SimulatorAssumptions {
  standalone_contract_only: boolean;
  simplified_cba: boolean;
  cap_projection_rate: number;
  not_modeled: string[];
}

/** Where a proposed first-year cap hit lands a real team against the tax/apron lines. */
export interface ApronOutlookResponse {
  team_id: number;
  team_name: string | null;
  season: string;
  existing_payroll_usd: number;
  replaces_existing_usd: number;
  proposed_cap_hit_usd: number;
  payroll_after_usd: number;
  tier_before: CapTier;
  tier_after: CapTier;
  crosses_a_line: boolean;
  room_to_tax_after: number | null;
  room_to_first_apron_after: number | null;
  room_to_second_apron_after: number | null;
  consequences: string[];
}

export interface SimulatorResponse {
  player_id: number;
  player_name: string;
  proposed_aav_pct: number;
  proposed_aav_usd: number;
  value_pct: number | null;
  value_usd: number | null;
  lo_pct: number | null;
  hi_pct: number | null;
  value_gap_pct: number | null;
  model_version: string | null;
  assumptions: SimulatorAssumptions;
  years: ContractYearResponse[];
  valuation_season: string;
  disclaimer: string;
  apron_outlook?: ApronOutlookResponse | null;
}

export interface ScenarioDelta {
  label: string;
  total_cap_hit_usd: number;
  guaranteed_cap_hit_usd: number;
  value_gap_pct: number | null;
  apron_tier_after: CapTier | null;
}

export interface CompareResponse {
  scenarios: SimulatorResponse[];
  deltas: ScenarioDelta[];
  best_value_index: number | null;
  cheapest_index: number;
  note: string;
}

export interface BacktestCalibrationPoint {
  nominal: number;
  empirical: number;
  half_width_pct: number;
}

export interface BacktestMetrics {
  model_version: string;
  n_train: number;
  n_calibration: number;
  n_test: number;
  interval_calibration: string;
  n_decision_calibration: number;
  global_cqr_qhat_pct: number;
  decision_cqr_qhat_pct: number;
  test_seasons: string[];
  mae_pct_of_cap: number;
  mae_usd: number;
  r2: number;
  interval_80_coverage: number;
  interval_80_half_width_pct: number;
  naive_mean_baseline_mae_pct: number;
  persistence_ref_mae_pct_midcontract: number;
  n_midcontract: number;
  segments: {
    decision_point: BacktestSegment;
    mid_contract: BacktestSegment;
  };
  calibration: BacktestCalibrationPoint[];
}

export interface BacktestSegment {
  n: number;
  mae_pct_of_cap: number;
  r2: number | null;
  interval_80_coverage: number;
  persistence_mae_pct: number | null;
}

export interface BacktestResponse {
  model_version: string | null;
  metrics: BacktestMetrics;
  report_path: string;
  artifacts: string[];
  caveat: string;
}

export interface BacktestValuationRow {
  full_name: string;
  next_season: string;
  actual_pct: number;
  value_pct: number;
  gap_pct: number;
  gp: number;
  min_per_g: number;
}

export type ScoutTrait =
  | 'leadership'
  | 'coachability'
  | 'work_ethic'
  | 'athleticism'
  | 'discipline'
  | 'basketball_iq';

export type ScoutConfidence = 'low' | 'medium' | 'high';

export interface ScoutRatingRow {
  trait: ScoutTrait;
  score: number;
  confidence: ScoutConfidence;
  evidence_span: string;
}

export interface ScoutRatingEvalReport {
  total_notes: number;
  expected_trait_count: number;
  predicted_trait_count: number;
  trait_coverage: number;
  exact_score_agreement: number;
  within_one_score_agreement: number;
  evidence_hit_rate: number;
  invalid_output_count: number;
  validation_errors: Record<string, unknown>[];
}

export interface ScoutRatingEvalExample {
  note_id: string;
  player_name: string;
  source_text: string;
  ratings: ScoutRatingRow[];
}

export interface ScoutRatingEvalMeta {
  mode: string;
  model: string | null;
  gold: string;
  generated_at: string;
}

export interface ScoutCorpusStats {
  report_count: number;
  cited_report_count: number;
  rated_player_count: number;
  rating_count: number;
  latest_fetched_at: string | null;
}

export interface ScoutRatingEvalResponse {
  mode: 'live_artifact' | 'offline_fixture';
  report: ScoutRatingEvalReport;
  meta: ScoutRatingEvalMeta | null;
  corpus: ScoutCorpusStats | null;
  traits: ScoutTrait[];
  gold_count: number;
  fixture_prediction_count: number;
  artifact_path: string;
  caveat: string;
  examples: ScoutRatingEvalExample[];
}

export interface ConfidenceMix {
  low: number;
  medium: number;
  high: number;
}

export interface PlayerScoutTraitRating {
  trait: ScoutTrait;
  average_score: number;
  report_count: number;
  confidence_mix: ConfidenceMix;
  evidence: string[];
}

export interface PlayerScoutReport {
  report_id: string;
  player_id: number;
  player_name: string;
  source_label: string;
  source_text: string;
  ratings: ScoutRatingRow[];
  citations?: string[];
  fetched_at?: string | null;
}

export interface PlayerScoutRatingsResponse {
  player_id: number;
  player_name: string;
  source_mode: 'synthetic_fixture' | 'sonar_claude_db';
  report_count: number;
  traits: PlayerScoutTraitRating[];
  reports: PlayerScoutReport[];
  caveat: string;
  citations?: string[];
  last_fetched?: string | null;
}

// ---- Team war room -------------------------------------------

export interface TeamListItem {
  team_id: number;
  abbreviation: string | null;
  name: string | null;
  conference: string | null;
  division: string | null;
}

export type CapTier = 'below-tax' | 'taxpayer' | 'first-apron' | 'second-apron';

export interface TeamCapContext {
  season: string;
  salary_cap: number | null;
  tax_line: number | null;
  first_apron: number | null;
  second_apron: number | null;
  tier: CapTier;
  room_to_tax: number | null;
  room_to_first_apron: number | null;
  room_to_second_apron: number | null;
}

export interface TeamCapTotals {
  total_payroll_usd: number;
  payroll_pct: number | null;
  total_value_usd: number;
  surplus_usd: number;
  surplus_pct: number | null;
  roster_size: number;
  payroll_player_count: number;
  valued_player_count: number;
  bargain_count: number;
  overpay_count: number;
}

export interface TeamCapSheetPlayer extends PlayerSummary {
  age: number | null;
  cap_hit_usd: number | null;
  salary_pct: number | null;
  value_pct: number | null;
  value_usd: number | null;
  gap_pct: number | null;
  valuation_status: ValuationStatus;
  pay_source: 'contract' | 'salary' | null;
}

export interface TeamCapSheetResponse {
  team: TeamSummary;
  season: string;
  cap_context: TeamCapContext;
  totals: TeamCapTotals;
  players: TeamCapSheetPlayer[];
  top_bargain: TeamCapSheetPlayer | null;
  top_overpay: TeamCapSheetPlayer | null;
  caveat: string;
}

// ---- Free agency ---------------------------------------------

export type FaType = 'expiring' | 'player-option' | 'team-option';

export interface OptionDecision {
  fa_type: FaType;
  deciding_party: 'player' | 'team';
  option_cap_pct: number;
  value_pct: number | null;
  gap_pct: number | null;
  verdict: string;
  tone: 'positive' | 'negative' | 'neutral';
  rationale: string;
}

export interface FreeAgentEntry extends PlayerSummary {
  age: number | null;
  fa_type: FaType;
  rfa_estimate: boolean;
  seasons_played: number;
  expiring_season: string;
  entering_season: string;
  expiring_aav_usd: number | null;
  expiring_cap_pct: number | null;
  value_pct: number | null;
  lo_pct: number | null;
  hi_pct: number | null;
  value_usd: number | null;
  valuation_season: string | null;
  valuation_status: ValuationStatus;
  option: OptionDecision | null;
  fa_status: 'ufa' | 'rfa';
  fa_status_source: 'spotrac' | 'estimated';
  rights_team: TeamSummary | null;
  bird_rights: 'bird' | 'early-bird' | 'non-bird' | 'two-way' | null;
  qualifying_offer_usd: number | null;
  cap_hold_usd: number | null;
}

export interface FreeAgencyBoardResponse {
  entering_season: string;
  type: string;
  items: FreeAgentEntry[];
  total: number;
  limit: number;
  offset: number;
  caveat: string;
}

export interface FreeAgencyOptionsResponse {
  entering_season: string;
  items: FreeAgentEntry[];
  total: number;
  limit: number;
  offset: number;
  caveat: string;
}

export interface ProjectedCapContext {
  season: string;
  is_projected: boolean;
  salary_cap: number | null;
  tax_line: number | null;
  first_apron: number | null;
  second_apron: number | null;
  committed_payroll_usd: number;
  contract_payroll_usd: number;
  cap_holds_usd: number;
  incomplete_roster_charges_usd: number;
  incomplete_roster_spots: number;
  tier: CapTier;
  room_to_cap: number | null;
  room_to_tax: number | null;
  room_to_first_apron: number | null;
  room_to_second_apron: number | null;
}

export type FitConfidence = 'high' | 'medium' | 'low';
export type RosterNeedStatus = 'critical' | 'need' | 'covered';

export interface RosterNeed {
  key: string;
  label: string;
  coverage_pct: number;
  deficit_pct: number;
  status: RosterNeedStatus;
  caution: string | null;
}

export interface TeamNeedsResponse {
  role_season: string;
  roster_player_count: number;
  profiled_player_count: number;
  confidence: FitConfidence;
  needs: RosterNeed[];
  caveat: string;
}

export interface CandidateFill {
  key: string;
  label: string;
  coverage_gain_pct: number;
  deficit_reduction_pct: number;
}

export interface CandidateFit {
  fit_score: number;
  confidence: FitConfidence;
  fills: CandidateFill[];
  reasons: string[];
}

export interface TeamFaTarget extends FreeAgentEntry {
  fits_room: boolean | null;
  fit: CandidateFit;
}

export interface TeamFaTargetsResponse {
  team: TeamSummary;
  entering_season: string;
  cap_context: ProjectedCapContext;
  committed_player_count: number;
  needs: TeamNeedsResponse;
  targets: TeamFaTarget[];
  limit: number;
  caveat: string;
}

export interface ExtensionCandidateItem {
  player: PlayerSummary;
  value_pct: number;
  current_pay_pct: number;
  gap_pct: number;
  verdict: string;
  tone: 'positive' | 'negative' | 'neutral';
  final_contract_season: string | null;
}

export interface ExtensionsBoardResponse {
  season: string;
  total: number;
  items: ExtensionCandidateItem[];
  caveat: string;
}

// ---- Offseason planning --------------------------------------

export interface ProposedOffseasonContract {
  player_id: number;
  aav_pct: number;
  years: number;
  guaranteed_years?: number | null;
  player_option_years?: number;
  team_option_years?: number;
}

export interface OffseasonPlanRequest {
  team_id: number;
  start_season: string;
  horizon?: number;
  valuation_season?: string | null;
  contracts: ProposedOffseasonContract[];
  option_declines: number[];
  renounced_rights: number[];
}

export interface OffseasonContractYear {
  season: string;
  cap_hit_usd: number;
  cap_hit_pct: number;
  is_guaranteed: boolean;
  is_player_option: boolean;
  is_team_option: boolean;
  is_projected_cap: boolean;
}

export type OffseasonMoveKind =
  | 'signing'
  | 're-sign'
  | 'team-option-decline'
  | 'player-option-opt-out';

export interface OffseasonMoveResponse {
  player_id: number;
  player_name: string;
  kind: OffseasonMoveKind;
  value_pct: number | null;
  value_gap_pct: number | null;
  removed_existing_usd: number;
  years: OffseasonContractYear[];
}

export interface OffseasonPlanSeason {
  season: string;
  salary_cap: number;
  tax_line: number;
  first_apron: number;
  second_apron: number;
  is_projected_cap: boolean;
  baseline_payroll_usd: number;
  payroll_after_usd: number;
  payroll_delta_usd: number;
  baseline_roster_count: number;
  roster_count_after: number;
  tier_before: CapTier;
  tier_after: CapTier;
  crosses_a_line: boolean;
  room_to_cap_after: number;
  room_to_tax_after: number;
  room_to_first_apron_after: number;
  room_to_second_apron_after: number;
  baseline_contract_payroll_usd: number;
  contract_payroll_after_usd: number;
  baseline_cap_holds_usd: number;
  cap_holds_after_usd: number;
  baseline_incomplete_roster_charges_usd: number;
  incomplete_roster_charges_after_usd: number;
  baseline_team_salary_player_count: number;
  team_salary_player_count_after: number;
}

export interface OffseasonRight {
  player_id: number;
  player_name: string;
  fa_status: 'ufa' | 'rfa' | null;
  bird_rights: 'bird' | 'early-bird' | 'non-bird' | 'two-way' | null;
  cap_hold_usd: number | null;
  qualifying_offer_usd: number | null;
  retained: boolean;
  source: string;
}

export interface OffseasonPlanResponse {
  team: TeamSummary;
  start_season: string;
  valuation_season: string;
  moves: OffseasonMoveResponse[];
  seasons: OffseasonPlanSeason[];
  needs_before: TeamNeedsResponse;
  needs_after: TeamNeedsResponse;
  rights: OffseasonRight[];
  caveat: string;
}

export interface LeagueTeamRow {
  team: TeamSummary;
  tier: CapTier;
  total_payroll_usd: number;
  payroll_pct: number | null;
  room_to_cap_usd: number | null;
  room_to_tax_usd: number | null;
  room_to_first_apron_usd: number | null;
  room_to_second_apron_usd: number | null;
  total_value_usd: number;
  surplus_usd: number;
  surplus_pct: number | null;
  expiring_usd: number;
  expiring_pct: number | null;
  roster_size: number;
  payroll_player_count: number;
}

export interface LeagueCapContext {
  season: string;
  salary_cap: number | null;
  tax_line: number | null;
  first_apron: number | null;
  second_apron: number | null;
}

export interface LeagueCapResponse {
  context: LeagueCapContext;
  tier_counts: Record<CapTier, number>;
  teams_with_cap_room: number;
  league_expiring_usd: number;
  team_count: number;
  teams: LeagueTeamRow[];
  caveat: string;
}

// ---- API functions -------------------------------------------

export function getTeams(signal?: AbortSignal): Promise<TeamListItem[]> {
  return apiFetch<TeamListItem[]>('/teams', { signal });
}

export function getTeamCapSheet(teamId: number, season?: string, signal?: AbortSignal): Promise<TeamCapSheetResponse> {
  return apiFetch<TeamCapSheetResponse>(`/teams/${teamId}/cap-sheet${queryString({ season })}`, { signal });
}

export function getLeagueCapLandscape(season?: string, signal?: AbortSignal): Promise<LeagueCapResponse> {
  return apiFetch<LeagueCapResponse>(`/league/cap-landscape${queryString({ season })}`, { signal });
}

export function getTeamNeeds(teamId: number, season?: string, signal?: AbortSignal): Promise<TeamNeedsResponse> {
  return apiFetch<TeamNeedsResponse>(`/teams/${teamId}/needs${queryString({ season })}`, { signal });
}

export interface FreeAgencyBoardParams {
  season?: string;
  type?: FaType;
  position?: string;
  limit?: number;
  offset?: number;
}

export function getFreeAgencyBoard(params: FreeAgencyBoardParams = {}, signal?: AbortSignal): Promise<FreeAgencyBoardResponse> {
  return apiFetch<FreeAgencyBoardResponse>(`/free-agency/board${queryString({
    season: params.season,
    type: params.type,
    position: params.position,
    limit: params.limit ?? 25,
    offset: params.offset ?? 0,
  })}`, { signal });
}

export function getFreeAgencyOptions(
  params: { season?: string; limit?: number; offset?: number } = {},
  signal?: AbortSignal,
): Promise<FreeAgencyOptionsResponse> {
  return apiFetch<FreeAgencyOptionsResponse>(`/free-agency/options${queryString({
    season: params.season,
    limit: params.limit ?? 25,
    offset: params.offset ?? 0,
  })}`, { signal });
}

export function getExtensionsBoard(limit: number = 30, signal?: AbortSignal): Promise<ExtensionsBoardResponse> {
  return apiFetch<ExtensionsBoardResponse>(`/free-agency/extensions${queryString({ limit })}`, { signal });
}

export function getTeamFaTargets(
  teamId: number,
  params: {
    season?: string;
    position?: string;
    sort?: 'fit' | 'value';
    addPlayerIds?: number[];
    removePlayerIds?: number[];
    limit?: number;
  } = {},
  signal?: AbortSignal,
): Promise<TeamFaTargetsResponse> {
  return apiFetch<TeamFaTargetsResponse>(`/free-agency/teams/${teamId}/targets${queryString({
    season: params.season,
    position: params.position,
    sort: params.sort ?? 'fit',
    add: params.addPlayerIds?.join(','),
    remove: params.removePlayerIds?.join(','),
    limit: params.limit ?? 15,
  })}`, { signal });
}

export function buildOffseasonPlan(
  request: OffseasonPlanRequest,
  signal?: AbortSignal,
): Promise<OffseasonPlanResponse> {
  return apiFetch<OffseasonPlanResponse>('/offseason/plan', {
    method: 'POST',
    body: JSON.stringify(request),
    signal,
  });
}

export function searchPlayers(query?: string, limit = 20, signal?: AbortSignal): Promise<PlayerSummary[]> {
  return apiFetch<PlayerSummary[]>(`/players${queryString({ limit, query })}`, { signal });
}

export function getPlayerWatchlist(params: PlayerWatchlistParams = {}, signal?: AbortSignal): Promise<PlayerWatchlistResponse> {
  return apiFetch<PlayerWatchlistResponse>(`/players/watchlist${queryString({
    limit: params.limit ?? 24,
    offset: params.offset ?? 0,
    bucket: params.bucket ?? 'all',
    sort: params.sort ?? 'mismatch',
    qualified_only: params.qualifiedOnly ?? true,
    query: params.query,
    season: params.season,
    position: params.position,
    team: params.team,
  })}`, { signal });
}

export function getPlayerValuationCautions(
  params: { season?: string; qualifiedOnly?: boolean; limit?: number } = {},
  signal?: AbortSignal,
): Promise<PlayerValuationCautionsResponse> {
  return apiFetch<PlayerValuationCautionsResponse>(`/players/valuation-cautions${queryString({
    limit: params.limit ?? 12,
    qualified_only: params.qualifiedOnly ?? true,
    season: params.season,
  })}`, { signal });
}

export function getPlayer(id: number, signal?: AbortSignal): Promise<PlayerSummary> {
  return apiFetch<PlayerSummary>(`/players/${id}`, { signal });
}

export function getValuation(id: number, season?: string, signal?: AbortSignal): Promise<ValuationResponse> {
  return apiFetch<ValuationResponse>(`/players/${id}/valuation${queryString({ season })}`, { signal });
}

export function getPlayerContract(id: number, signal?: AbortSignal): Promise<PlayerContractResponse> {
  return apiFetch<PlayerContractResponse>(`/players/${id}/contract`, { signal });
}

export function getPlayerExtension(id: number, signal?: AbortSignal): Promise<PlayerExtensionResponse> {
  return apiFetch<PlayerExtensionResponse>(`/players/${id}/extension`, { signal });
}

export function getSimilarPlayers(
  id: number,
  params: { mode?: SimilarPlayersMode; season?: string; limit?: number } = {},
  signal?: AbortSignal,
): Promise<SimilarPlayersResponse> {
  return apiFetch<SimilarPlayersResponse>(`/players/${id}/similar${queryString({
    mode: params.mode ?? 'twins',
    limit: params.limit ?? 8,
    season: params.season,
  })}`, { signal });
}

export function simulateContract(req: SimulatorRequest, signal?: AbortSignal): Promise<SimulatorResponse> {
  return apiFetch<SimulatorResponse>('/simulate/contract', {
    method: 'POST',
    body: JSON.stringify(req),
    signal,
  });
}

export function compareContracts(scenarios: SimulatorRequest[], signal?: AbortSignal): Promise<CompareResponse> {
  return apiFetch<CompareResponse>('/simulate/compare', {
    method: 'POST',
    body: JSON.stringify({ scenarios }),
    signal,
  });
}

export function getBacktest(): Promise<BacktestResponse> {
  return apiFetch<BacktestResponse>('/backtest');
}

export function getBacktestValuations(): Promise<BacktestValuationRow[]> {
  return apiFetch<BacktestValuationRow[]>('/backtest/valuations');
}

export function getScoutRatingEval(): Promise<ScoutRatingEvalResponse> {
  return apiFetch<ScoutRatingEvalResponse>('/llm/scout-ratings/eval');
}

export function getPlayerScoutRatings(id: number): Promise<PlayerScoutRatingsResponse> {
  return apiFetch<PlayerScoutRatingsResponse>(`/players/${id}/scout-ratings`);
}

export type RationaleMode = 'fusion' | 'multi_source';

export interface PlayerRationaleResponse {
  player_id: number;
  player_name: string;
  consensus_mode: RationaleMode;
  rationale: string;
  citations: string[];
  cost: {
    input_tokens: number;
    output_tokens: number;
    est_cost_usd: number;
    sonar_cost_usd: number;
  };
  grounding_issues: string[];
  model: string | null;
  generated_at: string | null;
  cached: boolean;
  caveat: string;
}

export function getPlayerRationale(id: number, mode: RationaleMode): Promise<PlayerRationaleResponse> {
  return apiFetch<PlayerRationaleResponse>(`/players/${id}/rationale?consensus=${mode}`);
}

export interface HealthResponse {
  status: string;
  service: string;
  current_season: string;
}

export function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return apiFetch<HealthResponse>('/health', { signal });
}

export type TradeTeamState = 'contending' | 'neutral' | 'rebuilding';
export interface TradeRequest {
  season: string; team_a_id: number; team_b_id: number;
  team_a_sends: number[]; team_b_sends: number[];
  team_a_sends_picks?: number[]; team_b_sends_picks?: number[];
  team_a_state?: TradeTeamState; team_b_state?: TradeTeamState;
  /** Optional expected-pick-number overrides keyed by draft_picks.id. */
  expected_picks?: Record<number, number>;
}
export interface TradePickAsset {
  pick_id: number; draft_year: number; round: number;
  original_team: TeamSummary | null; protected_top: number | null;
  swap_rights_team: TeamSummary | null; converts_to: string | null;
  source: string; notes: string | null; label: string;
  expected_pick: number; conveyed_pick: number; years_out: number; deferral_years: number;
  raw_pct: number; discounted_pct: number; value_usd: number | null;
}
export interface TradeTeamPicksResponse {
  team: TeamSummary; upcoming_draft_year: number; team_state: TradeTeamState;
  picks: TradePickAsset[]; caveat: string;
}
export interface TradePickLegality { status: 'pass' | 'fail' | 'needs-review' | 'not-applicable'; reasons: string[] }
export interface TradeRosterLegality {
  status: 'pass' | 'needs-review';
  standard_before: number; standard_after: number;
  net_change: number; two_way_count: number; reasons: string[];
}
export interface TradeAssetLedger {
  player_surplus_sent_usd: number; player_surplus_received_usd: number;
  player_surplus_coverage_sent: number; player_surplus_coverage_received: number;
  players_detail: Record<string, { total_surplus_usd: number; expiring: boolean; years: unknown[] }>;
  picks_sent_usd: number; picks_received_usd: number; net_usd: number;
}
export interface TradeCapContext { salary_cap: number; tax_line: number; first_apron: number; second_apron: number }
export interface TradeWorkspacePlayer { player_id: number; full_name: string; position: string | null; cap_hit_usd: number | null; salary_pct: number | null; pay_source: string | null }
export interface TradeTeamWorkspace {
  team: TeamSummary; season: string; is_projected_cap: boolean; cap_context: TradeCapContext;
  payroll_before_usd: number; tier_before: CapTier; roster_count: number;
  players: TradeWorkspacePlayer[]; caveat: string;
}
export interface TradeTeamAnalysis {
  team: TeamSummary; cap_context: TradeCapContext; selected_outgoing: TradeWorkspacePlayer[];
  selected_outgoing_ids: number[]; selected_incoming_ids: number[];
  payroll_before_usd: number; payroll_after_usd: number;
  tier_before: CapTier; tier_after: CapTier;
  roster_count_before: number; roster_count_after: number; roster_legality: TradeRosterLegality;
  outgoing_salary_usd: number; incoming_salary_usd: number; salary_delta_usd: number;
  salary_match: { status: 'pass'|'fail'|'needs-review'|'incomplete'; method: string|null; rule_label: string; incoming: number; outgoing: number; allowed_incoming: number; margin: number; reasons: string[] };
  value: { sent_usd: number; received_usd: number; delta_usd: number; sent_coverage: number; received_coverage: number; sent_selected: number; received_selected: number };
  fit_before: TeamNeedsResponse; fit_after: TeamNeedsResponse;
  fit_changes: Array<{ key: string; label: string; before_pct: number; after_pct: number; delta_pct: number }>;
  team_state: TradeTeamState;
  picks_outgoing: TradePickAsset[]; picks_incoming: TradePickAsset[];
  pick_legality: TradePickLegality | null;
  assets: TradeAssetLedger;
}
export type TradeFairnessTier = 'even' | 'favors-a' | 'favors-b' | 'lopsided-a' | 'lopsided-b';
export interface TradeBalance {
  net_usd: number;            // A-relative: + favors Team A, − favors Team B
  fairness_pct: number;       // needle 0..100 (50 = even)
  fairness_tier: TradeFairnessTier;
  fairness_label: string;
  team_a_grade: string; team_b_grade: string;
  team_a_value_in_usd: number; team_a_value_out_usd: number;
  team_b_value_in_usd: number; team_b_value_out_usd: number;
  low_confidence: boolean;
  coverage: { a_valued: number; a_selected: number; b_valued: number; b_selected: number };
  reasons: string[];
}
export interface TradeResponse { season: string; role_season: string; is_projected_cap: boolean; overall_status: string; overall_label: string; summary: string; balance: TradeBalance; team_a: TradeTeamAnalysis; team_b: TradeTeamAnalysis; assumptions: string[]; not_modeled: string[] }
export function getTradeWorkspace(teamId: number, season: string, signal?: AbortSignal): Promise<TradeTeamWorkspace> {
  return apiFetch<TradeTeamWorkspace>(`/trades/teams/${teamId}/workspace${queryString({ season })}`, { signal });
}
export function getTeamPicks(teamId: number, teamState: TradeTeamState = 'neutral', signal?: AbortSignal): Promise<TradeTeamPicksResponse> {
  return apiFetch<TradeTeamPicksResponse>(`/trades/teams/${teamId}/picks${queryString({ team_state: teamState })}`, { signal });
}
export function analyzeTrade(request: TradeRequest, signal?: AbortSignal): Promise<TradeResponse> {
  return apiFetch<TradeResponse>('/trades/analyze', { method: 'POST', body: JSON.stringify(request), signal });
}

// ---- Strategy Lab / backtesting (docs/10) ----
export type StrategySignal = 'gap' | 'value' | 'bpm' | 'ws' | 'vorp';
export interface StrategyRequest {
  min_mpg?: number; min_gp?: number;
  min_age?: number | null; max_age?: number | null;
  positions?: string[] | null;
  min_bpm?: number | null;
  require_undervalued?: boolean;
  min_value_pct?: number | null;
  signal?: StrategySignal;
  portfolio_size?: number;
  horizon?: number;
  start_season?: string | null; end_season?: string | null;
}
export interface StrategyPreset { id: string; name: string; description: string; spec: StrategyRequest }
export interface StrategyBenchmark { n_picks: number; total_surplus_pct: number; surplus_per_slot_pct: number; hit_rate: number }
export interface BacktestPick {
  player_id: number; full_name: string; decision_season: string;
  signal_value: number; value_pct: number | null; actual_pct: number | null;
  realized_surplus_pct: number; seasons_realized: number; hit: boolean;
}
export interface BacktestEquityPoint { season: string; cohort_surplus_pct: number; cumulative_surplus_pct: number }
export interface CurrentTarget {
  player_id: number; full_name: string; position: string | null;
  age: number | null; mpg: number;
  value_pct: number | null; actual_pct: number | null; gap_pct: number | null; signal_value: number | null;
}
export interface BacktestResult {
  spec: Record<string, unknown>;
  decision_seasons: string[];
  equity_curve: BacktestEquityPoint[];
  n_picks: number;
  total_surplus_pct: number;
  surplus_per_slot_pct: number;
  hit_rate: number;
  surplus_std_pct: number;
  sharpe: number;
  max_drawdown_pct: number;
  benchmarks: Record<string, StrategyBenchmark>;
  alpha_per_slot_pct: number;
  alpha_lo_pct: number;
  alpha_hi_pct: number;
  edge_conclusive: boolean;
  current_season: string | null;
  current_targets: CurrentTarget[];
  picks: BacktestPick[];
  caveat: string;
  reference_cap_usd: number | null;
  reference_season: string;
}
export interface StrategyMeta { seasons: string[]; decision_seasons: string[]; signals: StrategySignal[]; n_player_seasons: number }
export function getStrategyPresets(signal?: AbortSignal): Promise<{ presets: StrategyPreset[]; signals: StrategySignal[] }> {
  return apiFetch('/strategy/presets', { signal });
}
export function getStrategyMeta(signal?: AbortSignal): Promise<StrategyMeta> {
  return apiFetch('/strategy/meta', { signal });
}
export function runBacktest(request: StrategyRequest, signal?: AbortSignal): Promise<BacktestResult> {
  return apiFetch('/strategy/backtest', { method: 'POST', body: JSON.stringify(request), signal });
}

// Player headshot served via our backend proxy/cache instead of the NBA CDN directly.
export function headshotUrl(playerId: number): string {
  return `${BASE}/players/${playerId}/headshot`;
}

export function teamLogoUrl(teamId: number): string {
  return `${BASE}/teams/${teamId}/logo`;
}
