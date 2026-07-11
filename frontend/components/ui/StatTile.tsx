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
  /** Live readout: each value change replays a brief repricing glint. */
  live?: boolean;
}

export function StatTile({ label, value, unit, sub, delta, deltaDir, size = 'md', labelIcon, valueTone, live = false }: StatTileProps) {
  return (
    <div className={`siq-stat siq-stat--${size}`}>
      <div className="siq-stat__label">
        {labelIcon && <span className="siq-stat__label-icon">{labelIcon}</span>}
        <span className="ds-eyebrow">{label}</span>
      </div>
      <div className="siq-stat__readout" aria-live={live ? 'polite' : undefined} aria-atomic={live || undefined}>
        <span
          key={live ? String(value) : undefined}
          className={`siq-stat__value ds-tnum${valueTone ? ` siq-stat__value--${valueTone}` : ''}${live ? ' siq-reprice' : ''}`}
        >
          {value}
        </span>
        {unit && <span className="siq-stat__unit ds-tnum">{unit}</span>}
        {delta && (
          <span className={`siq-stat__delta siq-stat__delta--${deltaDir === 'up' ? 'up' : 'down'} ds-tnum`}>
            {delta}
          </span>
        )}
      </div>
      {sub && <span className="siq-stat__sub">{sub}</span>}
    </div>
  );
}
