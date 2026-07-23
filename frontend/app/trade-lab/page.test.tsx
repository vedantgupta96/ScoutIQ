import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { fmtSignedM } from '@/lib/present';
import { fmtM } from '@/lib/utils';
import type { SurplusPlayerDetail, TradeResponse } from '@/lib/api';
import { SurplusBreakdown, TradeVerdictBar, pctText, surplusSignClass } from './page';

// Bam-for-Zion is the canonical case from issue #117: a negative-surplus contract with a
// trailing player-option year that must never be silently counted as guaranteed.
const bamDetail: SurplusPlayerDetail = {
  total_surplus_usd: -32_124_910,
  total_surplus_committed_usd: -32_124_910,
  total_surplus_all_usd: -49_362_313,
  scenario: 'committed',
  has_uncertain_years: true,
  expiring: false,
  years: [
    { season: '2026-27', cap_hit_usd: 49_488_300, cap_hit_pct: 30.62, value_pct: 20.99, surplus_pct: -9.63, discount_factor: 1.0, discounted_surplus_usd: -15_562_669, status: 'guaranteed', committed: true },
    { season: '2027-28', cap_hit_usd: 53_447_364, cap_hit_pct: 31.65, value_pct: 20.99, surplus_pct: -10.66, discount_factor: 0.92, discounted_surplus_usd: -16_562_241, status: 'guaranteed', committed: true },
    { season: '2028-29', cap_hit_usd: 57_406_428, cap_hit_pct: 32.53, value_pct: 20.99, surplus_pct: -11.54, discount_factor: 0.8464, discounted_surplus_usd: -17_237_403, status: 'player_option', committed: false },
  ],
};

describe('pctText', () => {
  it('formats to one decimal with a percent sign', () => {
    expect(pctText(20.99)).toBe('21.0%');
  });
  it('adds an explicit sign for surplus percentages', () => {
    expect(pctText(-9.63, true)).toBe('-9.6%');
    expect(pctText(4.2, true)).toBe('+4.2%');
  });
  it('renders an em dash when the value is unavailable', () => {
    expect(pctText(null)).toBe('—');
  });
});

describe('surplusSignClass', () => {
  it('maps sign to the shared tone classes and stays empty at zero/absent', () => {
    expect(surplusSignClass(-5)).toBe('is-negative');
    expect(surplusSignClass(5)).toBe('is-positive');
    expect(surplusSignClass(0)).toBe('');
    expect(surplusSignClass(null)).toBe('');
    expect(surplusSignClass(undefined)).toBe('');
  });
});

describe('SurplusBreakdown', () => {
  it('renders one auditable row per contract season plus a totals row', () => {
    render(<SurplusBreakdown detail={bamDetail} />);
    // header + 3 season rows + tfoot total.
    expect(screen.getAllByRole('row')).toHaveLength(5);
    expect(screen.getByText('2026-27')).toBeInTheDocument();
    expect(screen.getByText('2027-28')).toBeInTheDocument();
    expect(screen.getByText('2028-29')).toBeInTheDocument();
  });

  it('labels the option year and marks its row uncertain', () => {
    render(<SurplusBreakdown detail={bamDetail} />);
    const optionLabel = screen.getByText('Player option');
    const row = optionLabel.closest('tr');
    expect(row).not.toBeNull();
    expect(row).toHaveClass('is-uncertain');
    // The two guaranteed years carry the neutral 'Guaranteed' label, not an option flag.
    expect(screen.getAllByText('Guaranteed')).toHaveLength(2);
  });

  it('shows the visible discounted-dollar rows that reconcile to the total', () => {
    const { container } = render(<SurplusBreakdown detail={bamDetail} />);
    const text = container.textContent ?? '';
    // Each year's discounted surplus is displayed with a negative (Unicode-minus) format.
    expect(text).toContain(fmtSignedM(-15_562_669));
    expect(text).toContain(fmtSignedM(-16_562_241));
    // Under the committed scenario the footer total is the two guaranteed years only.
    expect(screen.getByText('Committed years total')).toBeInTheDocument();
    expect(text).toContain(fmtSignedM(-32_124_910));
  });

  it('explains that option years are excluded rather than silently counted', () => {
    const { container } = render(<SurplusBreakdown detail={bamDetail} />);
    const text = container.textContent ?? '';
    expect(text).toMatch(/excluded from the committed total, not silently counted as guaranteed/i);
    // Both the committed and all-listed figures are surfaced side by side.
    expect(text).toContain(fmtSignedM(-32_124_910));
    expect(text).toContain(fmtSignedM(-49_362_313));
  });

  it('omits the committed-vs-all note when every year is guaranteed', () => {
    const cleanDetail: SurplusPlayerDetail = {
      ...bamDetail,
      has_uncertain_years: false,
      total_surplus_all_usd: bamDetail.total_surplus_committed_usd,
      years: bamDetail.years.slice(0, 2),
    };
    render(<SurplusBreakdown detail={cleanDetail} />);
    expect(screen.queryByText(/excluded from the committed total/i)).toBeNull();
    expect(screen.queryByText('Player option')).toBeNull();
  });
});

// Minimal response covering only what TradeVerdictBar reads, cast to the full type.
function verdictResult(overrides: Partial<TradeResponse> = {}): TradeResponse {
  return {
    overall_status: 'needs-review',
    overall_label: 'Manual review required',
    summary: 'At least one package needs review.',
    review_reasons: [
      'NOP: Roster would hold ~17 standard-salaried players (+2), above the 15-man limit — a waiver or additional outgoing player is required. Count is approximate.',
    ],
    surplus_scenario: 'committed',
    cap_reference: { season: '2026-27', salary_cap_usd: 161_606_115, is_projected: true },
    balance: {
      net_usd: 23_502_645,
      fairness_pct: 42.7,
      fairness_tier: 'lopsided-a',
      fairness_label: 'Lopsided toward Team A',
      team_a_grade: 'A',
      team_b_grade: 'F',
      team_a_value_in_usd: 0, team_a_value_out_usd: 0,
      team_b_value_in_usd: 0, team_b_value_out_usd: 0,
      low_confidence: false,
      coverage: { a_valued: 1, a_selected: 1, b_valued: 1, b_selected: 1 },
      reasons: [],
    },
    team_a: { team: { team_id: 1, abbreviation: 'MIA', name: 'Miami Heat' } },
    team_b: { team: { team_id: 2, abbreviation: 'NOP', name: 'New Orleans Pelicans' } },
    ...overrides,
  } as unknown as TradeResponse;
}

describe('TradeVerdictBar', () => {
  it('renders the exact needs-review trigger, not a generic possibilities list', () => {
    render(<TradeVerdictBar result={verdictResult()} stale={false} />);
    expect(
      screen.getByText(/Roster would hold ~17 standard-salaried players/i),
    ).toBeInTheDocument();
  });

  it('surfaces the cap season, value and independence of the checks', () => {
    const { container } = render(<TradeVerdictBar result={verdictResult()} stale={false} />);
    const text = container.textContent ?? '';
    expect(text).toContain(`Priced against the 2026-27 projected cap of ${fmtM(161_606_115)}`);
    expect(text).toMatch(/Salary matching, contract surplus, and roster legality are independent checks/i);
  });

  it('shows no review reasons for a clean, compliant deal', () => {
    render(
      <TradeVerdictBar
        result={verdictResult({
          overall_status: 'modeled-compliant',
          overall_label: 'Salary-compliant under modeled rules',
          review_reasons: [],
        })}
        stale={false}
      />,
    );
    expect(screen.queryByText(/Roster would hold/i)).toBeNull();
  });
});
