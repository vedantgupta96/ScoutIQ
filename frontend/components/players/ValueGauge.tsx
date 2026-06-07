'use client';

import type { CSSProperties } from 'react';

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

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function formatPct(value: number): string {
  return `${value.toFixed(1)}%`;
}

export function ValueGauge({ valuePct, loPct, hiPct, actualPct }: ValueGaugeProps) {
  const MAX = computeMax(hiPct, valuePct, actualPct);
  const toPosition = (v: number) => clamp((v / MAX) * 100, 0, 100);
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
  const combinedLabelPosition = actualPosition == null ? valuePosition : (valuePosition + actualPosition) / 2;
  const bandStart = toPosition(Math.min(loPct, hiPct));
  const bandEnd = toPosition(Math.max(loPct, hiPct));
  const overlap = actualPosition != null && Math.abs(valuePosition - actualPosition) < 14;
  const ariaLabel = actualPct == null
    ? `Estimated value ${formatPct(valuePct)}, confidence interval ${formatPct(loPct)} to ${formatPct(hiPct)}.`
    : `Estimated value ${formatPct(valuePct)}, actual pay ${formatPct(actualPct)}, confidence interval ${formatPct(loPct)} to ${formatPct(hiPct)}.`;

  return (
    <div
      role="img"
      aria-label={ariaLabel}
      style={{
        userSelect: 'none',
        paddingTop: overlap ? 42 : 30,
        paddingBottom: 26,
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
        <div
          style={{
            position: 'absolute',
            left: `${bandStart.toFixed(3)}%`,
            width: `${Math.max(0, bandEnd - bandStart).toFixed(3)}%`,
            top: 2,
            bottom: 2,
            borderRadius: 'var(--radius-pill)',
            background: 'var(--confidence)',
            opacity: 0.5,
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
              style={{
                position: 'absolute',
                left: toPct(actualPct),
                top: -4,
                bottom: -4,
                width: 2,
                transform: 'translateX(-1px)',
                borderRadius: 'var(--radius-pill)',
                background: 'repeating-linear-gradient(to bottom, var(--text-secondary) 0 4px, transparent 4px 7px)',
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
                  color: 'var(--text-muted)',
                  whiteSpace: 'nowrap',
                  ...labelPlacement(actualPosition ?? 0),
                }}
              >
                pay {formatPct(actualPct)}
              </span>
            )}
          </>
        )}

        <span
          aria-hidden="true"
          style={{
            position: 'absolute',
            left: toPct(valuePct),
            top: '50%',
            width: 16,
            height: 16,
            transform: 'translate(-50%, -50%)',
            borderRadius: 'var(--radius-pill)',
            background: 'var(--accent)',
            border: '2px solid var(--bg-panel)',
            boxShadow: '0 1px 4px rgba(16,24,40,0.18)',
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
            color: overlap ? 'var(--text-primary)' : 'var(--accent)',
            fontWeight: 600,
            whiteSpace: 'nowrap',
            ...labelPlacement(overlap ? combinedLabelPosition : valuePosition),
          }}
        >
          {overlap && actualPct != null
            ? `value ${formatPct(valuePct)} / pay ${formatPct(actualPct)}`
            : `value ${formatPct(valuePct)}`}
        </span>

        <div
          aria-hidden="true"
          style={{
            position: 'absolute',
            top: 'calc(100% + 8px)',
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
      </div>
    </div>
  );
}
