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
      style={{
        userSelect: 'none',
        paddingTop: overlap ? 42 : 30,
        paddingBottom: 34,
      }}
    >
      <div
        style={{
          position: 'relative',
          height: 16,
          borderRadius: 'var(--radius-pill)',
          background: 'var(--bg-inset)',
          border: '1px solid var(--border-subtle)',
          boxShadow: 'inset 0 1px 2px rgba(16,24,40,0.06)',
        }}
      >
        {actualPct != null && actualPosition != null && (
          <div
            aria-hidden="true"
            style={{
              position: 'absolute',
              left: `${Math.min(valuePosition, actualPosition).toFixed(3)}%`,
              width: `${Math.abs(valuePosition - actualPosition).toFixed(3)}%`,
              top: 4,
              bottom: 4,
              borderRadius: 'var(--radius-pill)',
              background: valuePct >= actualPct ? 'var(--grad-positive)' : 'var(--grad-negative)',
              opacity: 0.62,
              zIndex: 2,
            }}
          />
        )}

        <div
          style={{
            position: 'absolute',
            left: `${bandStart.toFixed(3)}%`,
            width: `${Math.max(0, bandEnd - bandStart).toFixed(3)}%`,
            top: 2,
            bottom: 2,
            borderRadius: 'var(--radius-pill)',
            background: 'var(--grad-confidence)',
            opacity: 0.85,
            boxShadow: 'var(--glow-confidence)',
            zIndex: 3,
          }}
        />

        {ticks.map((t) => (
          <span
            key={`tick-${t}`}
            aria-hidden="true"
            style={{
              position: 'absolute',
              left: toPct(t),
              top: 3,
              bottom: 3,
              width: 1,
              transform: 'translateX(-0.5px)',
              background: 'var(--border-subtle)',
            }}
          />
        ))}

        {actualPct != null && (
          <>
            <span
              aria-hidden="true"
              onMouseEnter={() => setHover({ label: 'Pay', value: actualPct, position: actualPosition ?? 0 })}
              style={{
                position: 'absolute',
                left: toPct(actualPct),
                top: -4,
                bottom: -4,
                width: 2,
                transform: 'translateX(-1px)',
                borderRadius: 'var(--radius-pill)',
                background: `repeating-linear-gradient(to bottom, ${payColor} 0 4px, transparent 4px 7px)`,
                cursor: 'help',
              }}
            />
            <span
              aria-hidden="true"
              title={`Pay: ${fmtPct(actualPct)}`}
              onMouseEnter={() => setHover({ label: 'Pay', value: actualPct, position: actualPosition ?? 0 })}
              style={{
                position: 'absolute',
                left: toPct(actualPct),
                top: '50%',
                width: 14,
                height: 14,
                transform: 'translate(-50%, -50%)',
                borderRadius: 'var(--radius-pill)',
                background: payColor,
                border: '2px solid var(--bg-panel)',
                boxShadow: '0 0 0 1px rgba(16,24,40,0.16)',
                cursor: 'help',
                zIndex: 3,
              }}
            />
            {!overlap && (
              <span
                className="ds-tnum"
                style={{
                  position: 'absolute',
                  bottom: 'calc(100% + 8px)',
                  maxWidth: 92,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  fontSize: 11,
                  lineHeight: 1.1,
                  color: payColor,
                  fontWeight: 700,
                  whiteSpace: 'nowrap',
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
          style={{
            position: 'absolute',
            left: toPct(valuePct),
            top: '50%',
            width: 16,
            height: 16,
            transform: 'translate(-50%, -50%)',
            borderRadius: 'var(--radius-pill)',
            background: 'var(--confidence)',
            border: '2px solid var(--bg-panel)',
            boxShadow: 'var(--glow-confidence)',
            cursor: 'help',
            zIndex: 4,
          }}
        />
        <span
          className="ds-tnum"
          style={{
            position: 'absolute',
            bottom: 'calc(100% + 8px)',
            maxWidth: overlap ? 180 : 104,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            fontSize: overlap ? 10 : 11,
            lineHeight: 1.1,
            color: overlap ? 'var(--text-primary)' : 'var(--confidence-text)',
            fontWeight: 600,
            whiteSpace: 'nowrap',
            ...labelPlacement(overlap ? combinedLabelPosition : valuePosition),
          }}
        >
          {overlap && actualPct != null
            ? `value ${fmtPct(valuePct)} / pay ${fmtPct(actualPct)}`
            : `value ${fmtPct(valuePct)}`}
        </span>

        <div
          aria-hidden="true"
          style={{
            position: 'absolute',
            top: 'calc(100% + 16px)',
            left: 0,
            right: 0,
            height: 18,
          }}
        >
          {ticks.map((t) => (
            <span
              key={`label-${t}`}
              className="ds-tnum"
              style={{
                position: 'absolute',
                left: toPct(t),
                transform: t === 0 ? 'translateX(0)' : t === MAX ? 'translateX(-100%)' : 'translateX(-50%)',
                fontSize: 10,
                lineHeight: 1,
                color: 'var(--text-muted)',
                whiteSpace: 'nowrap',
              }}
            >
              {t}%
            </span>
          ))}
        </div>

        {hover && (
          <div
            style={{
              position: 'absolute',
              left: `${hover.position.toFixed(3)}%`,
              top: 'calc(100% + 29px)',
              transform: 'translateX(-50%)',
              padding: '5px 7px',
              borderRadius: 'var(--radius-sm)',
              background: 'var(--ink-900)',
              color: '#fff',
              fontSize: 11,
              fontWeight: 700,
              whiteSpace: 'nowrap',
              boxShadow: 'var(--shadow-md)',
              zIndex: 20,
              pointerEvents: 'none',
            }}
          >
            {hover.label}: {fmtPct(hover.value)}
          </div>
        )}
      </div>
    </div>
  );
}
