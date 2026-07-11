'use client';

import { useState } from 'react';
import { capTier, fmtM } from '@/lib/utils';

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
  'below-tax':    { fill: 'linear-gradient(90deg, var(--teal-500), var(--green-500))',   glow: '0 0 7px rgba(31,190,116,0.28)' },
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
  showLabels?: boolean;
  valueLabel?: string;
}

/**
 * A cap figure plotted against the tax line and the two aprons, with tinted
 * danger zones (amber tax→apron, red beyond the second apron) and a tier-colored
 * fill + glow. Shared by the cap simulator (per-year) and the team war room
 * (team payroll), so the threshold language is single-sourced.
 */
export function CapBar({
  value,
  taxLine,
  firstApron,
  secondApron,
  height = 12,
  showLabels = false,
  valueLabel = 'Current',
}: CapBarProps) {
  const [hover, setHover] = useState<{ label: string; value: number; pct: number } | null>(null);
  const MAX_USD = Math.max(secondApron * 1.06, value * 1.04);
  const pctOfMax = Math.min(value / MAX_USD, 1) * 100;
  const taxPct = (taxLine / MAX_USD) * 100;
  const ap1Pct = (firstApron / MAX_USD) * 100;
  const ap2Pct = (secondApron / MAX_USD) * 100;

  const tier = capTier(value, taxLine, firstApron, secondApron) as CapTierKey;
  const { fill, glow } = TIER_FILL[tier];
  const markerTop = -5;
  const markerHeight = height + 10;
  const labelLeft = `clamp(42px, ${pctOfMax}%, calc(100% - 42px))`;
  const hoverLeft = hover ? `clamp(48px, ${hover.pct}%, calc(100% - 48px))` : '0';
  const markers = [
    { label: 'Tax', value: taxLine, pct: taxPct, color: 'var(--amber-500)' },
    { label: '1st apron', value: firstApron, pct: ap1Pct, color: 'var(--orange-500)' },
    { label: '2nd apron', value: secondApron, pct: ap2Pct, color: 'var(--negative)' },
  ];

  return (
    <div
      className="siq-cap-bar-root"
      onMouseLeave={() => setHover(null)}
    >
      {showLabels && (
        <div className="siq-cap-bar-labels">
          {markers.map((marker) => (
            <span
              key={marker.label}
              title={`${marker.label}: ${fmtM(marker.value)}`}
              onMouseEnter={() => setHover({ label: marker.label, value: marker.value, pct: marker.pct })}
              className="siq-cap-bar-marker-trigger"
            >
              <span className="siq-cap-bar-marker-swatch" style={{ background: marker.color }} />
              <span className="ds-eyebrow siq-cap-bar-marker-text">
                {marker.label}
              </span>
            </span>
          ))}
        </div>
      )}

      <div className="siq-cap-bar-plot" style={{ paddingBottom: showLabels ? 18 : 0 }}>
        <div className="siq-cap-bar-track" style={{ height }}>
          {/* Tinted threshold zones */}
          <div className="siq-cap-bar-zone siq-cap-bar-zone--tax" style={{ left: `${taxPct}%`, width: `${Math.max(0, ap1Pct - taxPct)}%` }} />
          <div className="siq-cap-bar-zone siq-cap-bar-zone--first-apron" style={{ left: `${ap1Pct}%`, width: `${Math.max(0, ap2Pct - ap1Pct)}%` }} />
          <div className="siq-cap-bar-zone siq-cap-bar-zone--second-apron" style={{ left: `${ap2Pct}%` }} />
          <div className="siq-cap-bar-fill" style={{ width: `${pctOfMax}%`, background: fill, boxShadow: glow }} />
        </div>

        {/* Threshold markers ride above the track so they read at the edges */}
        {markers.map((marker) => (
          <div
            key={marker.label}
            title={`${marker.label}: ${fmtM(marker.value)}`}
            onMouseEnter={() => setHover({ label: marker.label, value: marker.value, pct: marker.pct })}
            className="siq-cap-bar-threshold"
            style={{
              left: `${marker.pct}%`,
              top: markerTop,
              height: markerHeight,
              background: marker.color,
            }}
          />
        ))}

        <div
          title={`${valueLabel}: ${fmtM(value)}`}
          onMouseEnter={() => setHover({ label: valueLabel, value, pct: pctOfMax })}
          className="siq-cap-bar-current-dot"
          style={{
            left: `${pctOfMax}%`,
            top: height / 2,
            width: height + 7,
            height: height + 7,
            background: fill,
            boxShadow: glow === 'none' ? '0 1px 5px rgba(16,24,40,0.25)' : `${glow}, 0 1px 5px rgba(16,24,40,0.25)`,
          }}
        />

        {showLabels && (
          <div
            className="ds-tnum siq-cap-bar-current-label"
            style={{
              left: labelLeft,
              top: height + 7,
            }}
          >
            {valueLabel} {fmtM(value)}
          </div>
        )}

        {hover && (
          <div
            className="siq-cap-bar-tooltip"
            style={{
              left: hoverLeft,
              top: height + 25,
            }}
          >
            {hover.label}: {fmtM(hover.value)}
          </div>
        )}
      </div>
    </div>
  );
}
