import { classifyGap } from '@/lib/present';
import { signed } from '@/lib/utils';

interface VerdictPillProps {
  gapPct: number | null;
  size?: 'sm' | 'md' | 'lg';
  label?: string;
  tone?: 'positive' | 'negative' | 'neutral' | 'warning';
}

const SIZE = {
  sm: { label: 11, value: 12, pad: '3px 10px', gap: 5 },
  md: { label: 12, value: 14, pad: '5px 12px', gap: 6 },
  lg: { label: 12, value: 16, pad: '6px 14px', gap: 7 },
};

export function VerdictPill({ gapPct, size = 'md', label, tone: toneOverride }: VerdictPillProps) {
  const tone = toneOverride ?? classifyGap(gapPct).tone;
  const displayLabel = label ?? classifyGap(gapPct).label;
  const s = SIZE[size];

  const colors = {
    positive: { bg: 'var(--positive-soft)', text: 'var(--positive-text)' },
    negative: { bg: 'var(--negative-soft)', text: 'var(--negative-text)' },
    neutral:  { bg: 'var(--bg-inset)',       text: 'var(--text-secondary)' },
    warning:  { bg: 'var(--warning-soft)',   text: 'var(--warning-text)' },
  }[tone];

  return (
    <div
      className="siq-verdict-pill"
      style={{ padding: s.pad, background: colors.bg }}
    >
      <span
        className="siq-verdict-pill__label"
        style={{ fontSize: s.label, color: colors.text }}
      >{displayLabel}</span>
      {gapPct != null && (
        <span
          className="ds-tnum siq-verdict-pill__value"
          style={{ fontSize: s.value, color: colors.text }}
        >
          {signed(gapPct)}%
        </span>
      )}
    </div>
  );
}
