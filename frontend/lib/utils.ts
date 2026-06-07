export function fmtM(dollars: number): string {
  const m = dollars / 1_000_000;
  return `$${m.toFixed(1)}M`;
}

export function fmtPct(pct: number, decimals = 1): string {
  return `${pct.toFixed(decimals)}%`;
}

export function signed(v: number, decimals = 2): string {
  return (v >= 0 ? '+' : '') + v.toFixed(decimals);
}

export function gapTone(gap: number | null): 'positive' | 'negative' | 'neutral' {
  if (gap == null) return 'neutral';
  if (gap >= 1) return 'positive';
  if (gap <= -1) return 'negative';
  return 'neutral';
}

export function gapLabel(gap: number | null): string {
  if (gap == null) return 'No data';
  if (gap >= 3) return 'Significant bargain';
  if (gap >= 1) return 'Bargain';
  if (gap > -1) return 'Fair value';
  if (gap > -3) return 'Slight overpay';
  return 'Overpaid';
}

export function capTier(
  payroll: number,
  taxLine: number,
  firstApron: number,
  secondApron: number,
): 'below-tax' | 'taxpayer' | 'first-apron' | 'second-apron' {
  if (payroll >= secondApron) return 'second-apron';
  if (payroll >= firstApron) return 'first-apron';
  if (payroll >= taxLine) return 'taxpayer';
  return 'below-tax';
}
