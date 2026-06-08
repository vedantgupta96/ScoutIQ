'use client';

import { capTier } from '@/lib/utils';

export type CapTierKey = 'below-tax' | 'taxpayer' | 'first-apron' | 'second-apron';

export const CAP_TIER_LABEL: Record<CapTierKey, string> = {
  'below-tax': 'Under tax',
  'taxpayer': 'Over tax',
  'first-apron': 'First apron',
  'second-apron': 'Second apron',
};

export function capTierBadgeTone(tier: CapTierKey): 'positive' | 'warning' | 'negative' {
  return tier === 'below-tax' ? 'positive' : tier === 'taxpayer' ? 'warning' : 'negative';
}

// Vivid fill + danger glow that intensifies as the figure climbs through the
// tax line and the two aprons. Chrome stays quiet; the bar carries the alarm.
const TIER_FILL: Record<CapTierKey, { fill: string; glow: string }> = {
  'below-tax':    { fill: 'var(--grad-positive)',                                       glow: 'none' },
  'taxpayer':     { fill: 'linear-gradient(90deg, var(--amber-500), var(--amber-600))',  glow: '0 0 8px rgba(236,178,46,0.40)' },
  'first-apron':  { fill: 'linear-gradient(90deg, var(--amber-500), var(--orange-500))', glow: '0 0 9px rgba(244,98,31,0.42)' },
  'second-apron': { fill: 'var(--grad-negative)',                                       glow: '0 0 11px rgba(238,71,71,0.50)' },
};

interface CapBarProps {
  /** The figure being read against the lines — a single cap hit or a whole team payroll. */
  value: number;
  taxLine: number;
  firstApron: number;
  secondApron: number;
  height?: number;
}

/**
 * A cap figure plotted against the tax line and the two aprons, with tinted
 * danger zones (amber tax→apron, red beyond the second apron) and a tier-colored
 * fill + glow. Shared by the cap simulator (per-year) and the team war room
 * (team payroll), so the threshold language is single-sourced.
 */
export function CapBar({ value, taxLine, firstApron, secondApron, height = 12 }: CapBarProps) {
  const MAX_USD = secondApron * 1.05;
  const pctOfMax = Math.min(value / MAX_USD, 1) * 100;
  const taxPct = (taxLine / MAX_USD) * 100;
  const ap1Pct = (firstApron / MAX_USD) * 100;
  const ap2Pct = (secondApron / MAX_USD) * 100;

  const tier = capTier(value, taxLine, firstApron, secondApron) as CapTierKey;
  const { fill, glow } = TIER_FILL[tier];

  return (
    <div style={{ position: 'relative' }}>
      <div style={{
        height, background: 'var(--bg-inset)', borderRadius: 'var(--radius-pill)',
        position: 'relative', overflow: 'hidden',
      }}>
        {/* Tinted threshold zones */}
        <div style={{ position: 'absolute', top: 0, bottom: 0, left: `${taxPct}%`, width: `${Math.max(0, ap1Pct - taxPct)}%`, background: 'rgba(236,178,46,0.10)' }} />
        <div style={{ position: 'absolute', top: 0, bottom: 0, left: `${ap1Pct}%`, width: `${Math.max(0, ap2Pct - ap1Pct)}%`, background: 'rgba(236,178,46,0.18)' }} />
        <div style={{ position: 'absolute', top: 0, bottom: 0, left: `${ap2Pct}%`, right: 0, background: 'rgba(238,71,71,0.13)' }} />
        <div style={{
          width: `${pctOfMax}%`, height: '100%',
          background: fill, borderRadius: 'var(--radius-pill)', boxShadow: glow,
        }} />
      </div>
      {/* Threshold markers ride above the track so they read at the edges */}
      {[taxPct, ap1Pct, ap2Pct].map((pct, i) => (
        <div key={i} style={{
          position: 'absolute', left: `${pct}%`, top: -3, bottom: -3, width: 1.5,
          background: i === 0 ? 'var(--amber-500)' : i === 1 ? 'var(--orange-500)' : 'var(--negative)',
          opacity: 0.7,
        }} />
      ))}
    </div>
  );
}
