import { ReactNode } from 'react';

type Tone = 'warning' | 'confidence' | 'negative' | 'neutral';

const TONE_COLORS: Record<Tone, { bg: string; text: string; border: string }> = {
  warning:    { bg: 'var(--warning-soft)',    text: 'var(--warning-text)',    border: 'var(--amber-500)' },
  confidence: { bg: 'var(--confidence-soft)', text: 'var(--confidence-text)', border: 'var(--teal-500)' },
  negative:   { bg: 'var(--negative-soft)',   text: 'var(--negative-text)',   border: 'var(--red-500)' },
  neutral:    { bg: 'var(--bg-inset)',         text: 'var(--text-secondary)',  border: 'var(--border-default)' },
};

interface AssumptionFlagProps {
  children: ReactNode;
  title: string;
  tone?: Tone;
  icon?: ReactNode;
}

export function AssumptionFlag({ children, title, tone = 'warning', icon }: AssumptionFlagProps) {
  const c = TONE_COLORS[tone];

  return (
    <div style={{
      borderRadius: 'var(--radius-lg)',
      background: c.bg,
      border: `1px solid ${c.border}30`,
      boxShadow: `inset 0 0 0 1px ${c.border}20`,
      padding: '12px 14px',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 6 }}>
        {icon && <span style={{ color: c.text, display: 'flex', flexShrink: 0 }}>{icon}</span>}
        <span style={{ fontSize: 12, fontWeight: 700, color: c.text, letterSpacing: '0.01em' }}>{title}</span>
      </div>
      <p style={{ fontSize: 13, color: c.text, opacity: 0.85, lineHeight: 1.55, margin: 0 }}>
        {children}
      </p>
    </div>
  );
}
