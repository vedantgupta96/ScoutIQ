import { ReactNode, type CSSProperties } from 'react';

export type PanelVariant = 'card' | 'plain' | 'dossier' | 'instrument' | 'board';

interface PanelProps {
  children: ReactNode;
  variant?: PanelVariant;
  eyebrow?: string;
  icon?: ReactNode;
  action?: ReactNode;
  /** Tint the panel's accents with the active team color instead of the brand accent. */
  teamAccent?: boolean;
  /** Remove body padding so child rows can run edge-to-edge. */
  flush?: boolean;
  /** Even 16px body padding for metric-tile bodies. */
  padded?: boolean;
  className?: string;
  style?: CSSProperties;
  headingLevel?: 'h2' | 'h3';
}

/**
 * The one console panel. Merges the former `Card` (flat card, `variant="card"`)
 * and `Surface` (plain/dossier/instrument/board) primitives behind a single
 * head/body contract. `plain`, `dossier`, and `instrument` currently share the
 * base look; the modifier classes stay on the root as semantic hooks.
 */
export function Panel({
  children,
  variant = 'plain',
  eyebrow,
  icon,
  action,
  teamAccent = false,
  flush = false,
  padded = false,
  className = '',
  style,
  headingLevel = 'h2',
}: PanelProps) {
  const Heading = headingLevel;
  const accentStyle = teamAccent
    ? ({ '--panel-accent': 'var(--team-primary, var(--accent))' } as CSSProperties)
    : undefined;

  return (
    <div
      className={`siq-panel siq-panel--${variant} ${className}`.trim()}
      style={{ ...accentStyle, ...style }}
    >
      {eyebrow && (
        <div className="siq-panel__head">
          <div className="siq-panel__head-l">
            {icon && <span className="siq-panel__icon">{icon}</span>}
            <Heading className="ds-eyebrow">{eyebrow}</Heading>
          </div>
          {action && <div className="siq-panel__action">{action}</div>}
        </div>
      )}
      <div className={`siq-panel__body${flush ? ' siq-panel__body--flush' : padded ? ' siq-panel__body--padded' : ''}`}>{children}</div>
    </div>
  );
}
