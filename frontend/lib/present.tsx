// Presentation helpers shared across routes: how a value gap and a cap tier
// are shown. classifyGap mirrors the server verdict ladder
// (scoutiq.api.valuation.classify_gap) for surfaces that ship a raw gap
// without a verdict; where the API already sends verdict_tone/verdict_label,
// render those directly instead.

import { CircleAlert, CircleCheck, TriangleAlert } from 'lucide-react';
import type { CapTier } from '@/lib/api';
import { fmtM } from '@/lib/utils';

export type Tone = 'positive' | 'negative' | 'neutral' | 'warning';

export function classifyGap(gap: number | null): { label: string; tone: Tone } {
  if (gap == null) return { label: 'No data', tone: 'neutral' };
  if (gap >= 3) return { label: 'Significant bargain', tone: 'positive' };
  if (gap >= 1) return { label: 'Bargain', tone: 'positive' };
  if (gap > -1) return { label: 'Fair value', tone: 'neutral' };
  if (gap > -3) return { label: 'Slight overpay', tone: 'negative' };
  return { label: 'Overpaid', tone: 'negative' };
}

const TONE_COLOR: Record<Tone, string> = {
  positive: 'var(--positive)',
  negative: 'var(--negative)',
  neutral: 'var(--text-secondary)',
  warning: 'var(--warning)',
};

export function toneColor(tone: Tone): string {
  return TONE_COLOR[tone];
}

const TONE_TEXT: Record<Tone, string> = {
  positive: 'var(--positive-text)',
  negative: 'var(--negative-text)',
  neutral: 'var(--text-secondary)',
  warning: 'var(--warning-text)',
};

export function toneText(tone: Tone): string {
  return TONE_TEXT[tone];
}

export function gapColor(gap: number | null): string {
  return gap == null ? 'var(--text-muted)' : toneText(classifyGap(gap).tone);
}

export const CAP_TIER_LABEL: Record<CapTier, string> = {
  'below-tax': 'Under tax',
  'taxpayer': 'Over tax',
  'first-apron': 'First apron',
  'second-apron': 'Second apron',
};

const TIER_TONE: Record<CapTier, Tone> = {
  'below-tax': 'positive',
  'taxpayer': 'warning',
  'first-apron': 'negative',
  'second-apron': 'negative',
};

export function tierTone(tier: CapTier): Tone {
  return TIER_TONE[tier];
}

export function tierIcon(tier: CapTier) {
  if (tier === 'below-tax') return <CircleCheck size={14} />;
  if (tier === 'second-apron') return <CircleAlert size={14} />;
  return <TriangleAlert size={14} />;
}

export const TIER_RANK: Record<CapTier, number> = {
  'below-tax': 0,
  taxpayer: 1,
  'first-apron': 2,
  'second-apron': 3,
};

// Client-side tier of a moving slider value; mirrors the server
// classify_tier. The server ships tier on static payloads — use that; this
// is only for values the user is dragging.
export function capTier(
  payroll: number,
  taxLine: number,
  firstApron: number,
  secondApron: number,
): CapTier {
  if (payroll >= secondApron) return 'second-apron';
  if (payroll >= firstApron) return 'first-apron';
  if (payroll >= taxLine) return 'taxpayer';
  return 'below-tax';
}

export function fmtSignedM(value: number): string {
  if (value === 0) return '$0';
  return `${value > 0 ? '+' : '−'}${fmtM(Math.abs(value))}`;
}

export function traitLabel(trait: string): string {
  if (trait === 'basketball_iq') return 'Basketball IQ';
  return trait
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}
