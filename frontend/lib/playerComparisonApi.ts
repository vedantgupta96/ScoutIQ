import {
  getPlayer,
  getValuation,
  getPlayerContract,
  getSimilarPlayers,
  PlayerSummary,
  ValuationResponse,
  PlayerContractResponse,
  CompSynthesis,
} from '@/lib/api';

export interface PlayerComparisonData {
  playerId: number;
  /** Identity independent of the model: name, team, position, latest season.
   *  Composed separately so identity survives a valuation failure (ADR-0001). */
  summary: PlayerSummary | null;
  summaryError: string | null;
  valuation: ValuationResponse | null;
  valuationError: string | null;
  contract: PlayerContractResponse | null;
  contractError: string | null;
  compSynthesis: CompSynthesis | null;
  marketError: string | null;
}

function settledError(result: PromiseSettledResult<unknown>, fallback: string): string | null {
  if (result.status === 'fulfilled') return null;
  const reason = result.reason;
  if (reason instanceof DOMException && reason.name === 'AbortError') throw reason;
  return reason instanceof Error ? reason.message : fallback;
}

export async function loadPlayerComparison(playerId: number, signal?: AbortSignal): Promise<PlayerComparisonData> {
  const [summaryResult, valuationResult, contractResult, marketResult] = await Promise.allSettled([
    getPlayer(playerId, signal),
    getValuation(playerId, undefined, signal),
    getPlayerContract(playerId, signal),
    getSimilarPlayers(playerId, { mode: 'contract_comps' }, signal),
  ]);

  return {
    playerId,
    summary: summaryResult.status === 'fulfilled' ? summaryResult.value : null,
    summaryError: settledError(summaryResult, 'Failed to load player.'),
    valuation: valuationResult.status === 'fulfilled' ? valuationResult.value : null,
    valuationError: settledError(valuationResult, 'Failed to load valuation.'),
    contract: contractResult.status === 'fulfilled' ? contractResult.value : null,
    contractError: settledError(contractResult, 'Failed to load contract.'),
    compSynthesis: marketResult.status === 'fulfilled' ? marketResult.value.comp_synthesis : null,
    marketError: settledError(marketResult, 'Failed to load market comps.'),
  };
}
