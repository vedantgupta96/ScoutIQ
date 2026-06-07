'use client';

interface ValueGaugeProps {
  valuePct: number;
  loPct: number;
  hiPct: number;
  actualPct: number | null;
}

// Scale to the larger of 40% or hi+5%, so high-value players don't clip.
function computeMax(hiPct: number, valuePct: number, actualPct: number | null): number {
  const topValue = Math.max(hiPct, valuePct, actualPct ?? 0);
  return Math.ceil(Math.max(40, topValue + 6) / 10) * 10;
}

function pctToX(pct: number, max: number, width: number): number {
  return Math.min(Math.max(pct / max, 0), 1) * width;
}

// Clamp label x so it doesn't overflow the SVG edges.
function clampLabelX(x: number, width: number, margin = 8): number {
  return Math.max(margin, Math.min(width - margin, x));
}

export function ValueGauge({ valuePct, loPct, hiPct, actualPct }: ValueGaugeProps) {
  const W = 100, H = 52;
  const trackY = 32;
  const trackH = 6;
  const MAX = computeMax(hiPct, valuePct, actualPct);

  const toX = (pct: number) => pctToX(pct, MAX, W);

  const loX  = toX(loPct);
  const hiX  = toX(hiPct);
  const valX = toX(valuePct);
  const actX = actualPct != null ? toX(actualPct) : null;

  // Ticks: 0%, 10%, ... up to MAX
  const ticks = Array.from({ length: MAX / 10 + 1 }, (_, i) => i * 10);

  // Separate labels if value and pay are too close (< 5% of width apart)
  const labelsOverlap = actX != null && Math.abs(valX - actX) < 8;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto', display: 'block' }} overflow="visible">
      {/* Track background */}
      <rect x={0} y={trackY} width={W} height={trackH} rx={3} fill="var(--bg-inset)" />

      {/* CI band */}
      <rect
        x={loX} y={trackY}
        width={Math.max(0, hiX - loX)} height={trackH} rx={2}
        fill="var(--confidence)" opacity={0.3}
      />

      {/* Tick marks + labels */}
      {ticks.map((t) => {
        const x = toX(t);
        return (
          <g key={t}>
            <line x1={x} y1={trackY - 2} x2={x} y2={trackY + trackH + 2}
                  stroke="var(--border-subtle)" strokeWidth={0.5} />
            <text x={clampLabelX(x, W)} y={H - 1}
                  fill="var(--text-muted)" fontSize="5.5"
                  fontFamily="var(--font-mono)" textAnchor="middle">
              {t}%
            </text>
          </g>
        );
      })}

      {/* Actual pay marker */}
      {actX != null && (
        <g>
          <line x1={actX} y1={trackY - 5} x2={actX} y2={trackY + trackH + 4}
                stroke="var(--text-muted)" strokeWidth={1} strokeDasharray="2 2" />
          <text
            x={clampLabelX(actX + (labelsOverlap ? -5 : 0), W)}
            y={trackY - 7}
            fill="var(--text-muted)" fontSize="5"
            fontFamily="var(--font-mono)"
            textAnchor={labelsOverlap ? 'end' : 'middle'}
          >
            pay
          </text>
        </g>
      )}

      {/* Value marker (orange dot) */}
      <circle cx={valX} cy={trackY + trackH / 2} r={5}
              fill="var(--accent)" stroke="var(--bg-panel)" strokeWidth={1.5} />
      <text
        x={clampLabelX(valX + (labelsOverlap ? 5 : 0), W)}
        y={trackY - 7}
        fill="var(--accent)" fontSize="5"
        fontFamily="var(--font-mono)"
        fontWeight="600"
        textAnchor={labelsOverlap ? 'start' : 'middle'}
      >
        value
      </text>
    </svg>
  );
}
