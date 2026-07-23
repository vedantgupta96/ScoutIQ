import { apiFetch, queryString } from '@/lib/api';

export type QueuePriority = 'high' | 'medium' | 'low';
export type QueueItemType = 'option' | 'extension' | 'expiring' | 'cap_tier' | 'roster_need';

export interface QueueItem {
  id: string;
  type: QueueItemType;
  priority: QueuePriority;
  priority_reason: string;
  title: string;
  detail: string;
  player_id: number | null;
  team_id: number;
  value_pct: number | null;
  pay_pct: number | null;
  gap_pct: number | null;
  value_usd: number | null;
  pay_usd: number | null;
  destination: string;
  season: string;
  as_of: string;
  caution: string | null;
}

export interface DecisionQueueResponse {
  team_id: number;
  team_name: string | null;
  season: string;
  generated_from: string;
  items: QueueItem[];
  caveat: string;
  model_unavailable: boolean;
}

export function getDecisionQueue(teamId: number, season?: string, signal?: AbortSignal): Promise<DecisionQueueResponse> {
  return apiFetch<DecisionQueueResponse>(`/decision-queue${queryString({ team_id: teamId, season })}`, { signal });
}
