const BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(detail?.detail ?? res.statusText);
  }
  return res.json() as Promise<T>;
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
}

export type ValuationStatus = 'ready' | 'unavailable';

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

export interface SimilarPlayersResponse {
  player_id: number;
  player_name: string;
  season: string;
  mode: SimilarPlayersMode;
  basis: string[];
  results: SimilarPlayerResult[];
  caveat: string;
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

export interface SimulatorRequest {
  player_id: number;
  aav_pct: number;
  years: number;
  guaranteed_years?: number | null;
  player_option_years?: number;
  team_option_years?: number;
  start_season?: string;
  valuation_season?: string | null;
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
  test_seasons: string[];
  mae_pct_of_cap: number;
  mae_usd: number;
  r2: number;
  interval_80_coverage: number;
  interval_80_half_width_pct: number;
  naive_mean_baseline_mae_pct: number;
  persistence_ref_mae_pct_midcontract: number;
  n_midcontract: number;
  calibration: BacktestCalibrationPoint[];
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

export interface ScoutRatingEvalResponse {
  mode: 'offline_fixture';
  report: ScoutRatingEvalReport;
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
}

export interface PlayerScoutRatingsResponse {
  player_id: number;
  player_name: string;
  source_mode: 'synthetic_fixture';
  report_count: number;
  traits: PlayerScoutTraitRating[];
  reports: PlayerScoutReport[];
  caveat: string;
}

// ---- API functions -------------------------------------------

export function searchPlayers(query?: string, limit = 20, signal?: AbortSignal): Promise<PlayerSummary[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (query) params.set('query', query);
  return apiFetch<PlayerSummary[]>(`/players?${params}`, { signal });
}

export function getPlayerCards(query?: string, limit = 40, signal?: AbortSignal): Promise<PlayerCardResponse[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (query) params.set('query', query);
  return apiFetch<PlayerCardResponse[]>(`/players/cards?${params}`, { signal });
}

export function getPlayerWatchlist(params: PlayerWatchlistParams = {}, signal?: AbortSignal): Promise<PlayerWatchlistResponse> {
  const qs = new URLSearchParams({
    limit: String(params.limit ?? 24),
    offset: String(params.offset ?? 0),
    bucket: params.bucket ?? 'all',
    sort: params.sort ?? 'mismatch',
    qualified_only: String(params.qualifiedOnly ?? true),
  });
  if (params.query) qs.set('query', params.query);
  if (params.season) qs.set('season', params.season);
  if (params.position) qs.set('position', params.position);
  if (params.team) qs.set('team', params.team);
  return apiFetch<PlayerWatchlistResponse>(`/players/watchlist?${qs}`, { signal });
}

export function getPlayer(id: number, signal?: AbortSignal): Promise<PlayerSummary> {
  return apiFetch<PlayerSummary>(`/players/${id}`, { signal });
}

export function getValuation(id: number, season?: string, signal?: AbortSignal): Promise<ValuationResponse> {
  const params = season ? `?season=${season}` : '';
  return apiFetch<ValuationResponse>(`/players/${id}/valuation${params}`, { signal });
}

export function getPlayerContract(id: number, signal?: AbortSignal): Promise<PlayerContractResponse> {
  return apiFetch<PlayerContractResponse>(`/players/${id}/contract`, { signal });
}

export function getSimilarPlayers(
  id: number,
  params: { mode?: SimilarPlayersMode; season?: string; limit?: number } = {},
  signal?: AbortSignal,
): Promise<SimilarPlayersResponse> {
  const qs = new URLSearchParams({
    mode: params.mode ?? 'twins',
    limit: String(params.limit ?? 8),
  });
  if (params.season) qs.set('season', params.season);
  return apiFetch<SimilarPlayersResponse>(`/players/${id}/similar?${qs}`, { signal });
}

export function simulateContract(req: SimulatorRequest, signal?: AbortSignal): Promise<SimulatorResponse> {
  return apiFetch<SimulatorResponse>('/simulate/contract', {
    method: 'POST',
    body: JSON.stringify(req),
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

export interface HealthResponse {
  status: string;
  service: string;
  current_season: string;
}

export function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return apiFetch<HealthResponse>('/health', { signal });
}

// Player headshot served via our backend proxy/cache instead of the NBA CDN directly.
export function headshotUrl(playerId: number): string {
  return `${BASE}/players/${playerId}/headshot`;
}
