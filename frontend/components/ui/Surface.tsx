import { ReactNode, type CSSProperties } from 'react';

export type SurfaceVariant = 'plain' | 'dossier' | 'instrument' | 'board';

interface SurfaceProps {
  children: ReactNode;
  variant?: SurfaceVariant;
  eyebrow?: string;
  icon?: ReactNode;
  action?: ReactNode;
  /** Tint the surface's court accents with the active team color instead of the brand accent. */
  teamAccent?: boolean;
  className?: string;
  style?: CSSProperties;
}

/**
 * Console surface with basketball-native variants. Mirrors the `Card` header API
 * (eyebrow / icon / action) but swaps the flat white-card body for differentiated
 * panel language: an instrument readout, a comp board with a team rail, or a
 * clipped dossier. Decorative court elements live in globals.css; this component
 * only wires structure + the `--surface-accent` token.
 */
export function Surface({
  children,
  variant = 'plain',
  eyebrow,
  icon,
  action,
  teamAccent = false,
  className = '',
  style,
}: SurfaceProps) {
  const accentStyle = teamAccent
    ? ({ '--surface-accent': 'var(--team-primary, var(--accent))' } as CSSProperties)
    : undefined;

  return (
    <div
      className={`siq-surface siq-surface--${variant} ${className}`.trim()}
      style={{ ...accentStyle, ...style }}
    >
      {eyebrow && (
        <div className="siq-surface__head">
          <div className="siq-surface__head-l">
            {icon && <span className="siq-surface__icon">{icon}</span>}
            <span className="ds-eyebrow">{eyebrow}</span>
          </div>
          {action && <div>{action}</div>}
        </div>
      )}
      <div className="siq-surface__body">{children}</div>
    </div>
  );
}
