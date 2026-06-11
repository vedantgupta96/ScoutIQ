import { ReactNode } from 'react';

interface StatTileProps {
  label: string;
  value: string | number;
  unit?: string;
  sub?: string;
  delta?: string;
  deltaDir?: 'up' | 'down';
  size?: 'sm' | 'md' | 'lg';
  labelIcon?: ReactNode;
  /** Color the value by verdict; glides on change (live readouts). */
  valueTone?: 'positive' | 'negative' | 'neutral' | 'warning';
}

const SIZE = {
  sm: { label: 11, value: 20, unit: 13 },
  md: { label: 12, value: 28, unit: 14 },
  lg: { label: 13, value: 38, unit: 16 },
};

const TONE_COLOR = {
  positive: 'var(--positive-text)',
  negative: 'var(--negative-text)',
  warning: 'var(--warning-text)',
  neutral: 'var(--text-primary)',
};

export function StatTile({ label, value, unit, sub, delta, deltaDir, size = 'md', labelIcon, valueTone }: StatTileProps) {
  const s = SIZE[size];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
        {labelIcon && <span style={{ color: 'var(--text-muted)', display: 'flex' }}>{labelIcon}</span>}
        <span className="ds-eyebrow">{label}</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 4 }}>
        <span className="ds-tnum" style={{
          fontSize: s.value, fontWeight: 700,
          color: valueTone ? TONE_COLOR[valueTone] : 'var(--text-primary)',
          lineHeight: 1.1,
          fontFamily: 'var(--font-display)',
          transition: 'color var(--duration-slow) var(--ease-out)',
        }}>
          {value}
        </span>
        {unit && (
          <span className="ds-tnum" style={{ fontSize: s.unit, color: 'var(--text-muted)' }}>{unit}</span>
        )}
        {delta && (
          <span className="ds-tnum" style={{
            fontSize: 12, fontWeight: 600,
            color: deltaDir === 'up' ? 'var(--positive-text)' : 'var(--negative-text)',
            marginLeft: 2,
          }}>
            {delta}
          </span>
        )}
      </div>
      {sub && (
        <span style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.3 }}>{sub}</span>
      )}
    </div>
  );
}
