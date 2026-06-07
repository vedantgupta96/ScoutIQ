'use client';

interface MiniValuePayGaugeProps {
  valuePct: number | null;
  payPct: number | null;
}

// Compact value-vs-pay read for dense rows/cards (no confidence interval).
// Teal value marker, tone pay marker, and a verdict-colored connector whose
// length is the gap — green when value sits above pay, red when pay leads.
export function MiniValuePayGauge({ valuePct, payPct }: MiniValuePayGaugeProps) {
  if (valuePct == null && payPct == null) return null;

  const value = valuePct ?? 0;
  const pay = payPct;
  const domainMax = Math.max(value, pay ?? 0) * 1.15 || 6;
  const pos = (x: number) => Math.max(0, Math.min(100, (x / domainMax) * 100));
  const valuePos = pos(value);
  const payPos = pay != null ? pos(pay) : null;
  const underpaid = pay == null || value >= pay;
  const connector = pay == null
    ? 'var(--border-strong)'
    : underpaid ? 'var(--grad-positive)' : 'var(--grad-negative)';
  const payColor = underpaid ? 'var(--positive)' : 'var(--negative)';

  return (
    <div style={{
      position: 'relative', height: 8, borderRadius: 'var(--radius-pill)',
      background: 'var(--bg-inset)', border: '1px solid var(--border-subtle)', overflow: 'hidden',
    }}>
      {payPos != null && (
        <div style={{
          position: 'absolute', top: '50%', height: 4, transform: 'translateY(-50%)',
          left: `${Math.min(valuePos, payPos).toFixed(2)}%`,
          width: `${Math.abs(valuePos - payPos).toFixed(2)}%`,
          background: connector, borderRadius: 'var(--radius-pill)', opacity: 0.9,
        }} />
      )}
      <div style={{
        position: 'absolute', top: 0, bottom: 0, left: `calc(${valuePos.toFixed(2)}% - 1px)`,
        width: 2, background: 'var(--confidence)',
      }} />
      {payPos != null && (
        <div style={{
          position: 'absolute', top: 0, bottom: 0, left: `calc(${payPos.toFixed(2)}% - 1px)`,
          width: 2, background: payColor,
        }} />
      )}
    </div>
  );
}
