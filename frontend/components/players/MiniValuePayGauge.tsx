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
    <div style={{ position: 'relative' }} onMouseLeave={() => setHover(null)}>
      <div style={{
        position: 'relative',
        height: 12,
        borderRadius: 'var(--radius-pill)',
        background: 'var(--bg-inset)',
        border: '1px solid var(--border-subtle)',
        overflow: 'visible',
      }}>
        {ticks.map((tick) => (
          <div
            key={tick}
            title={`${tick}% of cap`}
            style={{
              position: 'absolute',
              top: 2,
              bottom: 2,
              left: `${pos(tick).toFixed(2)}%`,
              width: 1,
              transform: 'translateX(-50%)',
              background: 'var(--border-strong)',
              opacity: 0.45,
            }}
          />
        ))}
        {payPos != null && (
          <div style={{
            position: 'absolute',
            top: '50%',
            height: 5,
            transform: 'translateY(-50%)',
            left: `${Math.min(valuePos, payPos).toFixed(2)}%`,
            width: `${Math.abs(valuePos - payPos).toFixed(2)}%`,
            background: connector,
            borderRadius: 'var(--radius-pill)',
            opacity: 0.95,
          }} />
        )}
        <div
          title={`Model value: ${fmtPct(value)}`}
          onMouseEnter={() => setHover({ label: 'Value', value, pct: valuePos })}
          style={{
            position: 'absolute',
            top: '50%',
            left: `${valuePos.toFixed(2)}%`,
            transform: 'translate(-50%, -50%)',
            width: 10,
            height: 10,
            borderRadius: 'var(--radius-pill)',
            background: 'var(--confidence)',
            border: '2px solid var(--bg-panel)',
            boxShadow: '0 0 0 1px rgba(14,156,156,0.25)',
            cursor: 'help',
          }}
        />
        {payPos != null && (
          <div
            title={`Pay: ${fmtPct(pay ?? 0)}`}
            onMouseEnter={() => setHover({ label: 'Pay', value: pay ?? 0, pct: payPos })}
            style={{
              position: 'absolute',
              top: '50%',
              left: `${payPos.toFixed(2)}%`,
              transform: 'translate(-50%, -50%)',
              width: 10,
              height: 10,
              borderRadius: 'var(--radius-pill)',
              background: payColor,
              border: '2px solid var(--bg-panel)',
              boxShadow: '0 0 0 1px rgba(16,24,40,0.12)',
              cursor: 'help',
            }}
          />
        )}
        {hover && (
          <div style={{
            position: 'absolute',
            left: `${hover.pct}%`,
            bottom: 'calc(100% + 7px)',
            transform: 'translateX(-50%)',
            padding: '4px 6px',
            borderRadius: 'var(--radius-sm)',
            background: 'var(--ink-900)',
            color: '#fff',
            fontSize: 12,
            fontWeight: 700,
            whiteSpace: 'nowrap',
            boxShadow: 'var(--shadow-md)',
            zIndex: 12,
            pointerEvents: 'none',
          }}>
            {hover.label}: {fmtPct(hover.value)}
          </div>
        )}
      </div>
      {showLabels && (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginTop: 5 }}>
          <span className="ds-tnum" style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12, color: 'var(--confidence-text)', fontWeight: 700 }}>
            <span style={{ width: 7, height: 7, borderRadius: 'var(--radius-pill)', background: 'var(--confidence)' }} />
            Value {fmtPct(value)}
          </span>
          <span className="ds-tnum" style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12, color: pay == null ? 'var(--text-muted)' : payColor, fontWeight: 700 }}>
            <span style={{ width: 7, height: 7, borderRadius: 'var(--radius-pill)', background: pay == null ? 'var(--border-strong)' : payColor }} />
            Pay {pay != null ? fmtPct(pay) : '—'}
          </span>
        </div>
      )}
    </div>
  );
}
