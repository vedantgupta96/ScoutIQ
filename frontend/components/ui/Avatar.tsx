import { headshotUrl } from '@/lib/api';

const SIZE_PX = { sm: 28, md: 36, lg: 48, xl: 64 };

function initials(name: string): string {
  return name
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0].toUpperCase())
    .join('');
}

interface AvatarProps {
  name: string;
  size?: 'sm' | 'md' | 'lg' | 'xl';
  position?: string | null;
  playerId?: number | null;
}

export function Avatar({ name, size = 'md', position, playerId }: AvatarProps) {
  const px = SIZE_PX[size];
  const abbrev = initials(name);

  return (
    <div
      title={name}
      role="img"
      aria-label={name}
      className="siq-avatar"
      style={{
        width: px,
        height: px,
      }}
    >
      <span className="siq-avatar__initials" style={{ fontSize: px * 0.36 }}>
        {abbrev}
      </span>
      {playerId != null && (
        // Overlays initials; on load error it hides itself, revealing the fallback.
        <img
          src={headshotUrl(playerId)}
          alt=""
          aria-hidden="true"
          loading="lazy"
          draggable={false}
          onError={(e) => { e.currentTarget.style.display = 'none'; }}
          className="siq-avatar__image"
        />
      )}
      {position && (
        <span className="siq-avatar__position">
          {position}
        </span>
      )}
    </div>
  );
}
