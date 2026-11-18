import { describe, expect, it } from 'vitest';

import { guaranteeLabel, remainingGuaranteedNote } from '@/lib/financialContext';

describe('guaranteeLabel', () => {
  it('shows nothing for a confirmed guaranteed year', () => {
    expect(guaranteeLabel(true, false, false)).toBeNull();
  });

  it('shows Non-gtd only for an explicit false', () => {
    expect(guaranteeLabel(false, false, false)).toBe('Non-gtd');
  });

  it('shows Guarantee unknown for null or undefined', () => {
    expect(guaranteeLabel(null, false, false)).toBe('Guarantee unknown');
    expect(guaranteeLabel(undefined, false, false)).toBe('Guarantee unknown');
  });

  it('keeps the option label and adds unknown when the guarantee is null', () => {
    expect(guaranteeLabel(null, true, false)).toBe('Player opt. · Guarantee unknown');
    expect(guaranteeLabel(null, false, true)).toBe('Team opt. · Guarantee unknown');
    expect(guaranteeLabel(true, false, true)).toBe('Team opt.');
    expect(guaranteeLabel(false, true, false)).toBe('Player opt.');
  });
});

describe('remainingGuaranteedNote', () => {
  it('explains the source total only when a year is unknown', () => {
    expect(remainingGuaranteedNote(3_876_529, [{ is_guaranteed: null }, { is_guaranteed: null }])).toBe(
      'Source lists $3.88M remaining guaranteed; per-year split unknown.',
    );
    expect(remainingGuaranteedNote(3_876_529, [{ is_guaranteed: true }])).toBeNull();
    expect(remainingGuaranteedNote(null, [{ is_guaranteed: null }])).toBeNull();
  });
});
