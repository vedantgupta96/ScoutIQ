import { gapLabel, gapTone, signed } from '@/lib/utils';

interface VerdictPillProps {
  gapPct: number | null;
  size?: 'sm' | 'md' | 'lg';
}

const SIZE = {
  sm: { label: 11, value: 12, pad: '3px 10px', gap: 5 },
  md: { label: 12, value: 14, pad: '5px 12px', gap: 6 },
  lg: { label: 12, value: 16, pad: '6px 14px', gap: 7 },
};

export function VerdictPill({ gapPct, size = 'md' }: VerdictPillProps) {
  const tone = gapTone(gapPct);
  const label = gapLabel(gapPct);
  const s = SIZE[size];

  const colors = {
    positive: { bg: 'var(--positive-soft)', text: 'var(--positive-text)' },
    negative: { bg: 'var(--negative-soft)', text: 'var(--negative-text)' },
    neutral:  { bg: 'var(--bg-inset)',       text: 'var(--text-secondary)' },
  }[tone];

  return (
    <div style={{
      display: 'inline-flex', flexDirection: 'column', alignItems: 'center',
      padding: s.pad,
      borderRadius: 'var(--radius-pill)',
      background: colors.bg,
      gap: 1,
    }}>
      <span style={{ fontSize: s.label, fontWeight: 600, color: colors.text, lineHeight: 1 }}>{label}</span>
      {gapPct != null && (
        <span className="ds-tnum" style={{ fontSize: s.value, fontWeight: 700, color: colors.text, lineHeight: 1.2 }}>
          {signed(gapPct)}%
        </span>
      )}
    </div>
  );
}
