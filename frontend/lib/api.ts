const BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
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

// ---- API functions -------------------------------------------

export function searchPlayers(query?: string, limit = 20): Promise<PlayerSummary[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (query) params.set('query', query);
  return apiFetch<PlayerSummary[]>(`/players?${params}`);
}

export function getPlayer(id: number): Promise<PlayerSummary> {
  return apiFetch<PlayerSummary>(`/players/${id}`);
}

export function getValuation(id: number, season?: string): Promise<ValuationResponse> {
  const params = season ? `?season=${season}` : '';
  return apiFetch<ValuationResponse>(`/players/${id}/valuation${params}`);
}

export function simulateContract(req: SimulatorRequest): Promise<SimulatorResponse> {
  return apiFetch<SimulatorResponse>('/simulate/contract', {
    method: 'POST',
    body: JSON.stringify(req),
  });
}

export function getBacktest(): Promise<BacktestResponse> {
  return apiFetch<BacktestResponse>('/backtest');
}
