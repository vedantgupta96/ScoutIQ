import {
  getValuation,
  getPlayerContract,
  getSimilarPlayers,
  ValuationResponse,
  PlayerContractResponse,
  CompSynthesis,
} from '@/lib/api';

export interface PlayerComparisonData {
  playerId: number;
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
  const [valuationResult, contractResult, marketResult] = await Promise.allSettled([
    getValuation(playerId, undefined, signal),
    getPlayerContract(playerId, signal),
    getSimilarPlayers(playerId, { mode: 'contract_comps' }, signal),
  ]);

  return {
    playerId,
    valuation: valuationResult.status === 'fulfilled' ? valuationResult.value : null,
    valuationError: settledError(valuationResult, 'Failed to load valuation.'),
    contract: contractResult.status === 'fulfilled' ? contractResult.value : null,
    contractError: settledError(contractResult, 'Failed to load contract.'),
    compSynthesis: marketResult.status === 'fulfilled' ? marketResult.value.comp_synthesis : null,
    marketError: settledError(marketResult, 'Failed to load market comps.'),
  };
}
