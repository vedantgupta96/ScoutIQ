import { headshotUrl } from '@/lib/api';

interface PlayerCutoutProps {
  playerId: number | null;
  name: string;
  variant?: 'hero' | 'card';
}

export function PlayerCutout({ playerId, name, variant = 'hero' }: PlayerCutoutProps) {
  if (playerId == null) return null;

  return (
    <img
      src={headshotUrl(playerId)}
      alt=""
      aria-hidden="true"
      loading="lazy"
      className={`siq-player-cutout siq-player-cutout-${variant}`}
      onError={(e) => { e.currentTarget.style.display = 'none'; }}
      title={name}
    />
  );
}
