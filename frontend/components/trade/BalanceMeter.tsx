'use client';

import type { TradeFairnessTier } from '@/lib/api';
import { fmtM } from '@/lib/utils';

// The Trade Lab's "who wins" instrument. A calibrated value scale — needle at
// fairness_pct, center = even — NOT an arcade accept meter. Direction (which
// side the needle leans to) and the text label carry the meaning, so the read
// never depends on color alone. The lean is tinted with a neutral accent, not
// red/green, because a lopsided trade isn't "bad" globally — it just has a winner.

interface BalanceMeterProps {
  fairnessPct: number;        // 0..100, 50 = even
  tier: TradeFairnessTier;
  label: string;              // fairness_label
  netUsd: number;             // A-relative: + favors A
  leftAbbr: string;           // Team A
  rightAbbr: string;          // Team B
  lowConfidence?: boolean;
}

function differentialLine(netUsd: number, leftAbbr: string, rightAbbr: string): string {
  if (netUsd === 0) return 'Even modeled asset value';
  const winner = netUsd > 0 ? leftAbbr : rightAbbr;
  return `${winner} gains +${fmtM(Math.abs(netUsd))} modeled value`;
}

export function BalanceMeter({
  fairnessPct,
  tier,
  label,
  netUsd,
  leftAbbr,
  rightAbbr,
  lowConfidence = false,
}: BalanceMeterProps) {
  const needleLeft = `clamp(2%, ${fairnessPct}%, 98%)`;
  const lean = tier === 'even' ? 'even' : tier.startsWith('lopsided') ? 'strong' : 'soft';

  return (
    <div className="siq-balance" data-lean={lean}>
      <div className="siq-balance__ends ds-eyebrow">
        <span>{leftAbbr}</span>
        <span className="siq-balance__tier">{label}</span>
        <span>{rightAbbr}</span>
      </div>
      <div
        className="siq-balance__track"
        role="meter"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(fairnessPct)}
        aria-label={`Trade balance: ${label}`}
      >
        <span className="siq-balance__center" aria-hidden="true" />
        <span className="siq-balance__needle" style={{ left: needleLeft }} aria-hidden="true" />
      </div>
      <div className="siq-balance__foot ds-tnum">
        <span>{differentialLine(netUsd, leftAbbr, rightAbbr)}</span>
        {lowConfidence ? (
          <span className="siq-balance__conf" title="Model valued only part of the players involved.">
            Low confidence
          </span>
        ) : null}
      </div>
    </div>
  );
}

// A calibrated per-side letter grade (A..F) from that team's modeled net asset
// value. Analytical chip, not an arcade grade — the tooltip states the basis.
const GRADE_TONE: Record<string, 'positive' | 'neutral' | 'negative'> = {
  A: 'positive', B: 'positive', C: 'neutral', D: 'negative', F: 'negative',
};

export function GradeChip({
  grade,
  teamAbbr,
  lowConfidence = false,
}: {
  grade: string;
  teamAbbr: string;
  lowConfidence?: boolean;
}) {
  const tone = GRADE_TONE[grade] ?? 'neutral';
  return (
    <div
      className={`siq-grade-chip siq-grade-chip--${tone}${lowConfidence ? ' is-tentative' : ''}`}
      title={`${teamAbbr} value grade — modeled net asset value received vs sent${lowConfidence ? ' (low model coverage)' : ''}.`}
    >
      <span className="ds-eyebrow">{teamAbbr}</span>
      <strong className="siq-grade-chip__mark">{grade}{lowConfidence ? '?' : ''}</strong>
    </div>
  );
}
