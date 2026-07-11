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
    <div
      className="siq-assumption"
      style={{
        background: c.bg,
        border: `1px solid ${c.border}30`,
        boxShadow: `inset 0 0 0 1px ${c.border}20`,
      }}
    >
      <div className="siq-assumption__header">
        {icon && <span className="siq-assumption__icon" style={{ color: c.text }}>{icon}</span>}
        <span className="siq-assumption__title" style={{ color: c.text }}>{title}</span>
      </div>
      <p className="ds-m0 siq-assumption__body" style={{ color: c.text }}>
        {children}
      </p>
    </div>
  );
}
