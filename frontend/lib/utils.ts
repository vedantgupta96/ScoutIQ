export function fmtM(dollars: number): string {
  const m = dollars / 1_000_000;
  return `$${m.toFixed(1)}M`;
}

export function fmtPct(pct: number, decimals = 1): string {
  return `${pct.toFixed(decimals)}%`;
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export function pctPosition(value: number, domainMax: number): number {
  return clamp((value / domainMax) * 100, 0, 100);
}

export function roundedDomainMax(values: Array<number | null | undefined>, floor = 10, headroom = 1.15, step = 5): number {
  const max = Math.max(0, ...values.map((value) => value ?? 0));
  return Math.max(floor, Math.ceil((max * headroom) / step) * step);
}

export function signed(v: number, decimals = 2): string {
  return (v >= 0 ? '+' : '') + v.toFixed(decimals);
}
