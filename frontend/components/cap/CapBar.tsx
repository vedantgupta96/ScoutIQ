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
      style={{ position: 'relative' }}
      onMouseLeave={() => setHover(null)}
    >
      {showLabels && (
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, flexWrap: 'wrap', marginBottom: 8 }}>
          {markers.map((marker) => (
            <button
              key={marker.label}
              title={`${marker.label}: ${fmtM(marker.value)}`}
              onMouseEnter={() => setHover({ label: marker.label, value: marker.value, pct: marker.pct })}
              onFocus={() => setHover({ label: marker.label, value: marker.value, pct: marker.pct })}
              onBlur={() => setHover(null)}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 5,
                padding: 0,
                border: 0,
                background: 'transparent',
                color: 'var(--text-muted)',
                font: 'inherit',
                cursor: 'help',
              }}
            >
              <span style={{ width: 6, height: 6, borderRadius: 'var(--radius-pill)', background: marker.color, boxShadow: '0 0 0 2px var(--bg-panel)' }} />
              <span className="ds-eyebrow" style={{ fontSize: 9, letterSpacing: '0.06em', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
                {marker.label}
              </span>
            </button>
          ))}
        </div>
      )}

      <div style={{ position: 'relative', paddingBottom: showLabels ? 18 : 0 }}>
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
        {markers.map((marker) => (
          <div
            key={marker.label}
            title={`${marker.label}: ${fmtM(marker.value)}`}
            onMouseEnter={() => setHover({ label: marker.label, value: marker.value, pct: marker.pct })}
            style={{
              position: 'absolute',
              left: `${marker.pct}%`,
              top: markerTop,
              width: 2,
              height: markerHeight,
              background: marker.color,
              opacity: 0.8,
              transform: 'translateX(-50%)',
              borderRadius: 'var(--radius-pill)',
              cursor: 'help',
              zIndex: 2,
            }}
          />
        ))}

        <div
          title={`${valueLabel}: ${fmtM(value)}`}
          onMouseEnter={() => setHover({ label: valueLabel, value, pct: pctOfMax })}
          style={{
            position: 'absolute',
            left: `${pctOfMax}%`,
            top: height / 2,
            transform: 'translate(-50%, -50%)',
            width: height + 7,
            height: height + 7,
            borderRadius: 'var(--radius-pill)',
            background: fill,
            border: '2px solid var(--bg-panel)',
            boxShadow: glow === 'none' ? '0 1px 5px rgba(16,24,40,0.25)' : `${glow}, 0 1px 5px rgba(16,24,40,0.25)`,
            cursor: 'help',
            zIndex: 4,
          }}
        />

        {showLabels && (
          <div
            className="ds-tnum"
            style={{
              position: 'absolute',
              left: labelLeft,
              top: height + 7,
              transform: 'translateX(-50%)',
              fontSize: 10,
              fontWeight: 700,
              color: 'var(--text-primary)',
              whiteSpace: 'nowrap',
            }}
          >
            {valueLabel} {fmtM(value)}
          </div>
        )}

        {hover && (
          <div
            style={{
              position: 'absolute',
              left: hoverLeft,
              top: height + 25,
              transform: 'translateX(-50%)',
              padding: '5px 7px',
              borderRadius: 'var(--radius-sm)',
              background: 'var(--ink-900)',
              color: '#fff',
              fontSize: 11,
              fontWeight: 700,
              whiteSpace: 'nowrap',
              boxShadow: 'var(--shadow-md)',
              zIndex: 20,
              pointerEvents: 'none',
            }}
          >
            {hover.label}: {fmtM(hover.value)}
          </div>
        )}
      </div>
    </div>
  );
}
