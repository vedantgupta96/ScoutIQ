import { apiFetch } from '@/lib/api';

export interface DatasetProvenance {
  key: string;
  name: string;
  source: string;
  record_count: number | null;
  player_count: number | null;
  season_count: number | null;
  earliest_season: string | null;
  latest_season: string | null;
  last_updated_utc: string | null;
  last_updated_basis: string | null;
  caveat: string;
}

export interface ProvenanceResponse {
  datasets: DatasetProvenance[];
  generated_at_utc: string;
  caveat: string;
}

export function getDataProvenance(signal?: AbortSignal): Promise<ProvenanceResponse> {
  return apiFetch<ProvenanceResponse>('/data-provenance', { signal });
}
