import { describe, expect, it } from 'vitest';
import type { PlayerContractResponse, ValuationResponse } from '@/lib/api';
import {
  contractCoverageNote,
  contractHeading,
  contractStatusNote,
  extensionWindow,
  payContextNote,
  payLabel,
  verdictCaptionParts,
  simulateActionLabel,
  verdictCaption,
} from './financialContext';

const lal = { team_id: 1610612747, abbreviation: 'LAL', name: 'Los Angeles Lakers' };

const lebronValuation = {
  season: '2025-26',
  pay_season: '2025-26',
  pay_is_current_season: false,
  pay_team: lal,
  pay_team_is_current_team: false,
} as ValuationResponse;

const expiredContract = {
  coverage_status: 'expired',
  current_season: '2026-27',
  coverage_start_season: '2024-25',
  coverage_end_season: '2025-26',
  source: 'spotrac',
  scraped_at: '2026-06-08T12:00:00+00:00',
  extension_start_season: null,
} as PlayerContractResponse;

const currentContract = {
  ...expiredContract,
  coverage_status: 'current',
  coverage_start_season: '2025-26',
  coverage_end_season: '2027-28',
  extension_start_season: '2028-29',
} as PlayerContractResponse;

describe('LeBron case: prior-team pay and an expired contract', () => {
  it('labels pay by season and names the paying team', () => {
    expect(payLabel(lebronValuation)).toBe('2025-26 pay');
    expect(payContextNote(lebronValuation)).toBe('2025-26 cap hit with LAL');
    expect(verdictCaption(lebronValuation)).toBe('Verdict on 2025-26 pay');
    expect(verdictCaptionParts(lebronValuation)).toEqual({ prefix: 'Verdict on ', season: '2025-26', suffix: ' pay' });
  });

  it('presents the contract as history with no extension window', () => {
    expect(contractHeading(expiredContract)).toBe('Contract history');
    expect(contractStatusNote(expiredContract)).toBe(
      'Ended 2025-26 · no 2026-27 contract on file · spotrac, fetched 2026-06-08',
    );
    expect(extensionWindow(expiredContract)).toEqual({
      value: '—',
      sub: 'Ended 2025-26 · no 2026-27 contract on file',
    });
  });
});

describe('pay labels', () => {
  it('says Current pay only for the in-progress season', () => {
    expect(payLabel({ ...lebronValuation, pay_season: '2026-27', pay_is_current_season: true })).toBe('Current pay');
  });

  it('omits the team suffix when the pay team is unknown or matches', () => {
    expect(payContextNote({ ...lebronValuation, pay_team: null, pay_team_is_current_team: null })).toBe('2025-26 cap hit');
    expect(payContextNote({ ...lebronValuation, pay_team_is_current_team: true })).toBe('2025-26 cap hit');
    expect(payContextNote({ ...lebronValuation, pay_team_is_current_team: null })).toBe('2025-26 cap hit');
  });
});

describe('contract covering the current season', () => {
  it('keeps the current heading and extension window', () => {
    expect(contractHeading(currentContract)).toBe('Current contract');
    expect(contractStatusNote(currentContract)).toBe('Covers 2026-27 · spotrac, fetched 2026-06-08');
    expect(contractCoverageNote(currentContract)).toBe('Covers 2026-27');
    expect(extensionWindow(currentContract)).toEqual({ value: '2028-29', sub: 'First season after listed deal' });
  });

  it('omits the fetched date when scraped_at is null', () => {
    expect(contractStatusNote({ ...currentContract, scraped_at: null })).toBe('Covers 2026-27 · spotrac');
  });
});

describe('missing and degenerate contracts', () => {
  it('reports loading when there is no contract object', () => {
    expect(extensionWindow(null)).toEqual({ value: '—', sub: 'Contract data loading' });
    expect(extensionWindow(undefined)).toEqual({ value: '—', sub: 'Contract data loading' });
  });

  it('distinguishes loading, missing and unavailable contract states', () => {
    expect(extensionWindow(null, 'loading')).toEqual({ value: '—', sub: 'Contract data loading' });
    expect(extensionWindow(null, 'missing')).toEqual({ value: '—', sub: 'No contract on file' });
    expect(extensionWindow(null, 'unavailable')).toEqual({ value: '—', sub: 'Contract data unavailable' });
    expect(extensionWindow(currentContract, 'loaded')).toEqual({ value: '2028-29', sub: 'First season after listed deal' });
  });

  it('handles contracts with no year rows', () => {
    const noYears = { ...expiredContract, coverage_status: 'no_years', coverage_start_season: null, coverage_end_season: null } as PlayerContractResponse;
    expect(contractStatusNote(noYears)).toBe('No contract years on file · spotrac, fetched 2026-06-08');
    expect(contractCoverageNote(noYears)).toBe('No contract years on file');
    expect(extensionWindow(noYears)).toEqual({ value: '—', sub: 'No contract years on file' });
  });

  it('describes a deal that only starts after the current season', () => {
    const future = { ...expiredContract, coverage_status: 'future_only', coverage_start_season: '2027-28' } as PlayerContractResponse;
    expect(contractStatusNote(future)).toBe('Starts 2027-28 · no 2026-27 contract on file · spotrac, fetched 2026-06-08');
  });
});

describe('simulateActionLabel', () => {
  it('offers extension simulation only for a deal covering the current season', () => {
    expect(simulateActionLabel(currentContract)).toBe('Simulate extension');
  });

  it('falls back to the cap simulator otherwise', () => {
    expect(simulateActionLabel(expiredContract)).toBe('Open cap simulator');
    expect(simulateActionLabel(null)).toBe('Open cap simulator');
    expect(simulateActionLabel({ ...currentContract, extension_start_season: null })).toBe('Open cap simulator');
  });
});
