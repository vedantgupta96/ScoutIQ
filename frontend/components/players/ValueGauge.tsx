'use client';

interface ValueGaugeProps {
  valuePct: number;
  loPct: number;
  hiPct: number;
  actualPct: number | null;
}

const MAX_PCT = 40;

function pctToX(pct: number, width: number): number {
  return Math.min(Math.max(pct / MAX_PCT, 0), 1) * width;
}

export function ValueGauge({ valuePct, loPct, hiPct, actualPct }: ValueGaugeProps) {
  const W = 100, H = 48;
  const trackY = 28;
  const trackH = 6;
  const loX = pctToX(loPct, W);
  const hiX = pctToX(hiPct, W);
  const valX = pctToX(valuePct, W);
  const actX = actualPct != null ? pctToX(actualPct, W) : null;

  const ticks = [0, 10, 20, 30, 40];

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto', display: 'block' }}>
      {/* Track */}
      <rect x={0} y={trackY} width={W} height={trackH} rx={3} fill="var(--bg-inset)" />

      {/* CI band */}
      <rect
        x={loX} y={trackY}
        width={Math.max(0, hiX - loX)} height={trackH} rx={2}
        fill="var(--confidence)" opacity={0.25}
      />

      {/* Tick labels */}
      {ticks.map((t) => (
        <g key={t}>
          <line
            x1={pctToX(t, W)} y1={trackY - 3}
            x2={pctToX(t, W)} y2={trackY + trackH + 2}
            stroke="var(--border-subtle)" strokeWidth={0.5}
          />
          <text
            x={pctToX(t, W)} y={H - 2}
            fill="var(--text-muted)" fontSize="6"
            fontFamily="var(--font-mono)" textAnchor="middle"
          >
            {t}%
          </text>
        </g>
      ))}

      {/* Actual pay marker */}
      {actX != null && (
        <g>
          <line x1={actX} y1={trackY - 6} x2={actX} y2={trackY + trackH + 6}
                stroke="var(--text-muted)" strokeWidth={1} strokeDasharray="2 2" />
          <text x={actX} y={trackY - 8} fill="var(--text-muted)" fontSize="5.5"
                fontFamily="var(--font-mono)" textAnchor="middle">
            pay
          </text>
        </g>
      )}

      {/* Value marker */}
      <circle cx={valX} cy={trackY + trackH / 2} r={5}
              fill="var(--accent)" stroke="var(--bg-panel)" strokeWidth={1.5} />
      <text x={valX} y={trackY - 8} fill="var(--accent)" fontSize="5.5"
            fontFamily="var(--font-mono)" textAnchor="middle" fontWeight="600">
        value
      </text>
    </svg>
  );
}
