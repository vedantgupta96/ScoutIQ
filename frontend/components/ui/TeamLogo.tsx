import { teamLogoUrl } from '@/lib/api';

interface TeamLogoProps {
  teamId: number | null | undefined;
  abbreviation?: string | null;
  name?: string | null;
  size?: 'sm' | 'md' | 'lg' | 'xl';
  muted?: boolean;
}

const SIZE_PX = { sm: 24, md: 32, lg: 44, xl: 56 };

export function TeamLogo({ teamId, abbreviation, name, size = 'md', muted = false }: TeamLogoProps) {
  const px = SIZE_PX[size];
  const label = name ?? abbreviation ?? 'Team';

  return (
    <div
      title={label}
      role="img"
      aria-label={label}
      className="siq-team-logo"
      style={{
        width: px,
        height: px,
        boxShadow: muted ? undefined : '0 1px 3px rgba(16,24,40,0.08)',
      }}
    >
      <span
        className="ds-tnum siq-team-logo__abbr"
        style={{ fontSize: Math.max(9, px * 0.25) }}
      >
        {abbreviation ?? '—'}
      </span>
      {teamId != null && (
        <img
          src={teamLogoUrl(teamId)}
          alt=""
          aria-hidden="true"
          loading="lazy"
          draggable={false}
          onError={(e) => { e.currentTarget.style.display = 'none'; }}
          className="siq-team-logo__image"
          style={{
            inset: px <= 24 ? 2 : 3,
            width: `calc(100% - ${px <= 24 ? 4 : 6}px)`,
            height: `calc(100% - ${px <= 24 ? 4 : 6}px)`,
            filter: muted ? 'grayscale(1) saturate(0.25) opacity(0.72)' : undefined,
          }}
        />
      )}
    </div>
  );
}
