import { CSSProperties } from 'react';

interface SkeletonProps {
  width?: number | string;
  height?: number | string;
  /** Pill-shaped placeholder (avatars, badges). */
  round?: boolean;
  className?: string;
  style?: CSSProperties;
}

/** Loading placeholder block. Dimensions are data, so they stay inline. */
export function Skeleton({ width, height, round, className = '', style }: SkeletonProps) {
  return (
    <span
      className={`siq-skel ${className}`.trim()}
      style={{ width, height, borderRadius: round ? 'var(--radius-pill)' : undefined, ...style }}
    />
  );
}
