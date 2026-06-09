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
      style={{
        width: px,
        height: px,
        borderRadius: '50%',
        background: 'var(--accent-soft)',
        border: '1.5px solid var(--accent)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexShrink: 0,
        position: 'relative',
      }}
    >
      <span style={{
        fontFamily: 'var(--font-display)',
        fontWeight: 700,
        fontSize: px * 0.36,
        color: 'var(--accent-text)',
        lineHeight: 1,
        letterSpacing: '-0.01em',
      }}>
        {abbrev}
      </span>
      {playerId != null && (
        // Overlays initials; on load error it hides itself, revealing the fallback.
        <img
          src={headshotUrl(playerId)}
          alt={name}
          loading="lazy"
          onError={(e) => { e.currentTarget.style.display = 'none'; }}
          style={{
            position: 'absolute',
            inset: 0,
            width: '100%',
            height: '100%',
            borderRadius: '50%',
            objectFit: 'cover',
            objectPosition: 'center 12%',
            background: 'var(--bg-panel)',
          }}
        />
      )}
      {position && (
        <span style={{
          position: 'absolute',
          bottom: -2,
          right: -2,
          background: 'var(--bg-panel)',
          border: '1px solid var(--border-subtle)',
          borderRadius: 'var(--radius-sm)',
          fontSize: 9,
          fontWeight: 700,
          fontFamily: 'var(--font-mono)',
          color: 'var(--text-muted)',
          padding: '0 3px',
          lineHeight: '14px',
        }}>
          {position}
        </span>
      )}
    </div>
  );
}
