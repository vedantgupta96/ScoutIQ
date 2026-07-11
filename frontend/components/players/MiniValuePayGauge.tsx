'use client';

import { useState } from 'react';
import { fmtPct, pctPosition } from '@/lib/utils';

interface MiniValuePayGaugeProps {
  valuePct: number | null;
  payPct: number | null;
  showLabels?: boolean;
  domainMaxPct?: number;
}

// Compact value-vs-pay read for dense rows/cards (no confidence interval).
// Teal value marker, tone pay marker, and a verdict-colored connector whose
// length is the gap — green when value sits above pay, red when pay leads.
export function MiniValuePayGauge({ valuePct, payPct, showLabels = false, domainMaxPct }: MiniValuePayGaugeProps) {
  const [hover, setHover] = useState<{ label: string; value: number; pct: number } | null>(null);
  if (valuePct == null && payPct == null) return null;

  const value = valuePct ?? 0;
  const pay = payPct;
  const domainMax = domainMaxPct ?? (Math.max(value, pay ?? 0) * 1.2 || 6);
  const pos = (x: number) => pctPosition(x, domainMax);
  const valuePos = pos(value);
  const payPos = pay != null ? pos(pay) : null;
  const underpaid = pay == null || value >= pay;
  const connector = pay == null
    ? 'var(--border-strong)'
    : underpaid ? 'var(--grad-positive)' : 'var(--grad-negative)';
  const payColor = underpaid ? 'var(--positive)' : 'var(--negative)';
  const ticks = [10, 20, 30].filter((tick) => tick < domainMax);

  return (
    <div className="siq-mini-gauge-root" onMouseLeave={() => setHover(null)}>
      <div className="siq-mini-gauge-track">
        {ticks.map((tick) => (
          <div
            key={tick}
            title={`${tick}% of cap`}
            className="siq-mini-gauge-tick"
            style={{ left: `${pos(tick).toFixed(2)}%` }}
          />
        ))}
        {payPos != null && (
          <div
            className="siq-mini-gauge-connector"
            style={{
              left: `${Math.min(valuePos, payPos).toFixed(2)}%`,
              width: `${Math.abs(valuePos - payPos).toFixed(2)}%`,
              background: connector,
            }}
          />
        )}
        <div
          title={`Model value: ${fmtPct(value)}`}
          onMouseEnter={() => setHover({ label: 'Value', value, pct: valuePos })}
          className="siq-mini-gauge-dot siq-mini-gauge-dot--value"
          style={{ left: `${valuePos.toFixed(2)}%` }}
        />
        {payPos != null && (
          <div
            title={`Pay: ${fmtPct(pay ?? 0)}`}
            onMouseEnter={() => setHover({ label: 'Pay', value: pay ?? 0, pct: payPos })}
            className="siq-mini-gauge-dot siq-mini-gauge-dot--pay"
            style={{
              left: `${payPos.toFixed(2)}%`,
              background: payColor,
            }}
          />
        )}
        {hover && (
          <div className="siq-mini-gauge-tooltip" style={{ left: `${hover.pct}%` }}>
            {hover.label}: {fmtPct(hover.value)}
          </div>
        )}
      </div>
      {showLabels && (
        <div className="siq-mini-gauge-labels">
          <span className="ds-tnum siq-mini-gauge-legend siq-mini-gauge-legend--value">
            <span className="siq-mini-gauge-legend-swatch siq-mini-gauge-legend-swatch--value" />
            Value {fmtPct(value)}
          </span>
          <span
            className="ds-tnum siq-mini-gauge-legend"
            style={{ color: pay == null ? 'var(--text-muted)' : payColor }}
          >
            <span
              className="siq-mini-gauge-legend-swatch"
              style={{ background: pay == null ? 'var(--border-strong)' : payColor }}
            />
            Pay {pay != null ? fmtPct(pay) : '—'}
          </span>
        </div>
      )}
    </div>
  );
}
