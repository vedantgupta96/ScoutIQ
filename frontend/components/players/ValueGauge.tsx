'use client';

import { useState } from 'react';
import type { CSSProperties } from 'react';
import { fmtPct, pctPosition } from '@/lib/utils';

interface ValueGaugeProps {
  valuePct: number;
  loPct: number;
  hiPct: number;
  actualPct: number | null;
}

function computeMax(hiPct: number, valuePct: number, actualPct: number | null): number {
  const top = Math.max(hiPct, valuePct, actualPct ?? 0);
  return Math.ceil(Math.max(40, top + 6) / 10) * 10;
}

export function ValueGauge({ valuePct, loPct, hiPct, actualPct }: ValueGaugeProps) {
  const [hover, setHover] = useState<{ label: string; value: number; position: number } | null>(null);
  const MAX = computeMax(hiPct, valuePct, actualPct);
  const toPosition = (v: number) => pctPosition(v, MAX);
  const toPct = (v: number) => `${toPosition(v).toFixed(3)}%`;
  const labelPlacement = (position: number, shift: 'left' | 'center' | 'right' = 'center'): CSSProperties => {
    let transform = 'translateX(-50%)';
    let textAlign: CSSProperties['textAlign'] = 'center';

    if (shift === 'left') {
      transform = 'translateX(calc(-100% - 8px))';
      textAlign = 'right';
    } else if (shift === 'right') {
      transform = 'translateX(8px)';
      textAlign = 'left';
    }

    if (position <= 6) {
      transform = 'translateX(0)';
      textAlign = 'left';
    } else if (position >= 94) {
      transform = 'translateX(-100%)';
      textAlign = 'right';
    }

    return { left: `${position.toFixed(3)}%`, transform, textAlign };
  };

  const ticks = Array.from({ length: MAX / 10 + 1 }, (_, i) => i * 10);
  const valuePosition = toPosition(valuePct);
  const actualPosition = actualPct == null ? null : toPosition(actualPct);
  const payColor = actualPct == null
    ? 'var(--text-muted)'
    : valuePct >= actualPct ? 'var(--positive)' : 'var(--negative)';
  const combinedLabelPosition = actualPosition == null ? valuePosition : (valuePosition + actualPosition) / 2;
  const bandStart = toPosition(Math.min(loPct, hiPct));
  const bandEnd = toPosition(Math.max(loPct, hiPct));
  const overlap = actualPosition != null && Math.abs(valuePosition - actualPosition) < 14;
  const ariaLabel = actualPct == null
    ? `Estimated value ${fmtPct(valuePct)}, confidence interval ${fmtPct(loPct)} to ${fmtPct(hiPct)}.`
    : `Estimated value ${fmtPct(valuePct)}, actual pay ${fmtPct(actualPct)}, confidence interval ${fmtPct(loPct)} to ${fmtPct(hiPct)}.`;

  return (
    <div
      role="img"
      aria-label={ariaLabel}
      onMouseLeave={() => setHover(null)}
      className="siq-value-gauge-root"
      style={{ paddingTop: overlap ? 42 : 30 }}
    >
      <div className="siq-value-gauge-track">
        {actualPct != null && actualPosition != null && (
          <div
            aria-hidden="true"
            className="siq-value-gauge-connector"
            style={{
              left: `${Math.min(valuePosition, actualPosition).toFixed(3)}%`,
              width: `${Math.abs(valuePosition - actualPosition).toFixed(3)}%`,
              background: valuePct >= actualPct ? 'var(--grad-positive)' : 'var(--grad-negative)',
            }}
          />
        )}

        <div
          title={`80% interval ${fmtPct(loPct)}–${fmtPct(hiPct)} — calibrated so roughly 8 in 10 true values land inside; see the backtest.`}
          className="siq-value-gauge-band"
          style={{
            left: `${bandStart.toFixed(3)}%`,
            width: `${Math.max(0, bandEnd - bandStart).toFixed(3)}%`,
          }}
        />
        <span
          className="siq-gauge-bound"
          aria-hidden="true"
          style={{ left: `${bandStart.toFixed(3)}%` }}
        />
        <span
          className="siq-gauge-bound"
          aria-hidden="true"
          style={{ left: `${bandEnd.toFixed(3)}%` }}
        />

        {ticks.map((t) => (
          <span
            key={`tick-${t}`}
            aria-hidden="true"
            className="siq-value-gauge-tick"
            style={{ left: toPct(t) }}
          />
        ))}

        {actualPct != null && (
          <>
            <span
              aria-hidden="true"
              onMouseEnter={() => setHover({ label: 'Pay', value: actualPct, position: actualPosition ?? 0 })}
              className="siq-value-gauge-pay-line"
              style={{
                left: toPct(actualPct),
                background: payColor,
                boxShadow: `0 0 0 1px color-mix(in srgb, ${payColor} 22%, transparent)`,
              }}
            />
            <span
              aria-hidden="true"
              title={`Pay: ${fmtPct(actualPct)}`}
              onMouseEnter={() => setHover({ label: 'Pay', value: actualPct, position: actualPosition ?? 0 })}
              className="siq-value-gauge-dot siq-value-gauge-dot--pay"
              style={{
                left: toPct(actualPct),
                background: payColor,
              }}
            />
            {!overlap && (
              <span
                className="ds-tnum siq-value-gauge-label siq-value-gauge-label--pay"
                style={{
                  color: payColor,
                  ...labelPlacement(actualPosition ?? 0),
                }}
              >
                pay {fmtPct(actualPct)}
              </span>
            )}
          </>
        )}

        <span
          aria-hidden="true"
          title={`Value: ${fmtPct(valuePct)}`}
          onMouseEnter={() => setHover({ label: 'Value', value: valuePct, position: valuePosition })}
          className="siq-value-gauge-dot siq-value-gauge-dot--value"
          style={{ left: toPct(valuePct) }}
        />
        <span
          className="ds-tnum siq-value-gauge-label siq-value-gauge-label--value"
          style={{
            maxWidth: overlap ? 180 : 104,
            fontSize: overlap ? 10 : 11,
            color: overlap ? 'var(--text-primary)' : 'var(--confidence-text)',
            ...labelPlacement(overlap ? combinedLabelPosition : valuePosition),
          }}
        >
          {overlap && actualPct != null
            ? `value ${fmtPct(valuePct)} / pay ${fmtPct(actualPct)}`
            : `value ${fmtPct(valuePct)}`}
        </span>

        <div
          aria-hidden="true"
          className="siq-value-gauge-axis"
        >
          {ticks.map((t) => (
            <span
              key={`label-${t}`}
              className="ds-tnum siq-value-gauge-axis-label"
              style={{
                left: toPct(t),
                transform: t === 0 ? 'translateX(0)' : t === MAX ? 'translateX(-100%)' : 'translateX(-50%)',
              }}
            >
              {t}%
            </span>
          ))}
        </div>

        {hover && (
          <div
            className="siq-value-gauge-tooltip"
            style={{ left: `${hover.position.toFixed(3)}%` }}
          >
            {hover.label}: {fmtPct(hover.value)}
          </div>
        )}
      </div>
    </div>
  );
}
