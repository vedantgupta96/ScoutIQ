import { ReactNode } from 'react';

type Tone = 'neutral' | 'accent' | 'positive' | 'negative' | 'warning' | 'confidence';
type Variant = 'solid' | 'outline';
type Size = 'sm' | 'md';

interface BadgeProps {
  children: ReactNode;
  tone?: Tone;
  variant?: Variant;
  size?: Size;
  dot?: boolean;
  icon?: ReactNode;
}

export function Badge({ children, tone = 'neutral', variant = 'solid', size = 'sm', dot, icon }: BadgeProps) {
  return (
    <span className={`siq-badge siq-badge--${tone} siq-badge--${variant} siq-badge--${size}`}>
      {dot && <span className="siq-badge__dot" />}
      {icon && <span className="siq-badge__icon">{icon}</span>}
      {children}
    </span>
  );
}
