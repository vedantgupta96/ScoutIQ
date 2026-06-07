import { ReactNode } from 'react';

type Tone = 'neutral' | 'accent' | 'positive' | 'negative' | 'warning' | 'confidence';
type Variant = 'solid' | 'outline';
type Size = 'sm' | 'md';

const TONE_STYLES: Record<Tone, { bg: string; text: string; border: string }> = {
  neutral:    { bg: 'var(--bg-inset)',       text: 'var(--text-secondary)', border: 'var(--border-subtle)' },
  accent:     { bg: 'var(--accent-soft)',    text: 'var(--accent-text)',    border: 'transparent' },
  positive:   { bg: 'var(--positive-soft)',  text: 'var(--positive-text)',  border: 'transparent' },
  negative:   { bg: 'var(--negative-soft)',  text: 'var(--negative-text)',  border: 'transparent' },
  warning:    { bg: 'var(--warning-soft)',   text: 'var(--warning-text)',   border: 'transparent' },
  confidence: { bg: 'var(--confidence-soft)', text: 'var(--confidence-text)', border: 'transparent' },
};

interface BadgeProps {
  children: ReactNode;
  tone?: Tone;
  variant?: Variant;
  size?: Size;
  dot?: boolean;
  icon?: ReactNode;
}

export function Badge({ children, tone = 'neutral', variant = 'solid', size = 'sm', dot, icon }: BadgeProps) {
  const s = TONE_STYLES[tone];
  const isOutline = variant === 'outline';

  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5,
      padding: size === 'sm' ? '2px 8px' : '4px 10px',
      borderRadius: 'var(--radius-pill)',
      fontSize: size === 'sm' ? 11 : 12,
      fontWeight: 600,
      fontFamily: 'var(--font-sans)',
      background: isOutline ? 'transparent' : s.bg,
      color: s.text,
      border: `1px solid ${isOutline ? s.text + '40' : s.border}`,
      letterSpacing: '0.01em',
      whiteSpace: 'nowrap',
    }}>
      {dot && (
        <span style={{
          width: 5, height: 5, borderRadius: '50%',
          background: 'currentColor', flexShrink: 0,
        }} />
      )}
      {icon && <span style={{ display: 'flex', opacity: 0.8 }}>{icon}</span>}
      {children}
    </span>
  );
}
