import type { PlayerContractResponse, ValuationResponse } from '@/lib/api';

type PayFields = Pick<ValuationResponse, 'season' | 'pay_season' | 'pay_is_current_season' | 'pay_team' | 'pay_team_is_current_team'>;
type ContractFields = Pick<
  PlayerContractResponse,
  'coverage_status' | 'current_season' | 'coverage_start_season' | 'coverage_end_season' | 'source' | 'scraped_at' | 'extension_start_season'
>;

function paySeason(val: Pick<PayFields, 'season' | 'pay_season'>): string {
  return val.pay_season ?? val.season;
}

export function payLabel(val: PayFields): string {
  return val.pay_is_current_season ? 'Current pay' : `${paySeason(val)} pay`;
}

export function payContextNote(val: PayFields): string {
  const base = `${paySeason(val)} cap hit`;
  const abbreviation = val.pay_team?.abbreviation;
  if (abbreviation && val.pay_team_is_current_team === false) return `${base} with ${abbreviation}`;
  return base;
}

export function verdictCaption(val: PayFields): string {
  return `Verdict on ${paySeason(val)} pay`;
}

export function contractHeading(contract: Pick<ContractFields, 'coverage_status'>): string {
  return contract.coverage_status === 'current' ? 'Current contract' : 'Contract history';
}

export type ContractFetchState = 'loading' | 'loaded' | 'missing' | 'unavailable';

export function contractCoverageNote(contract: ContractFields): string {
  switch (contract.coverage_status) {
    case 'current':
      return `Covers ${contract.current_season}`;
    case 'expired':
      return `Ended ${contract.coverage_end_season} · no ${contract.current_season} contract on file`;
    case 'future_only':
      return `Starts ${contract.coverage_start_season} · no ${contract.current_season} contract on file`;
    default:
      return 'No contract years on file';
  }
}

export function contractStatusNote(contract: ContractFields): string {
  const fetched = contract.scraped_at ? `, fetched ${contract.scraped_at.slice(0, 10)}` : '';
  return `${contractCoverageNote(contract)} · ${contract.source}${fetched}`;
}

export function extensionWindow(
  contract: ContractFields | null | undefined,
  state: ContractFetchState = 'loading',
): { value: string; sub: string } {
  if (!contract) {
    if (state === 'missing') return { value: '—', sub: 'No contract on file' };
    if (state === 'unavailable') return { value: '—', sub: 'Contract data unavailable' };
    return { value: '—', sub: 'Contract data loading' };
  }
  if (contract.coverage_status === 'current') {
    return { value: contract.extension_start_season ?? '—', sub: 'First season after listed deal' };
  }
  return { value: '—', sub: contractCoverageNote(contract) };
}

export function simulateActionLabel(contract: ContractFields | null | undefined): string {
  return contract?.coverage_status === 'current' && contract.extension_start_season
    ? 'Simulate extension'
    : 'Open cap simulator';
}
