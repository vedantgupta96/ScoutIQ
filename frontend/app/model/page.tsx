'use client';

import { useEffect, useMemo, useState, type CSSProperties } from 'react';
import { useRouter } from 'next/navigation';
import { ClipboardCheck, Target, TrendingUp, TrendingDown, TriangleAlert } from 'lucide-react';
import {
  searchPlayers,
  getPlayerValuationCautions,
  PlayerCardResponse,
  PlayerSummary,
  getBacktest,
  BacktestResponse,
  getBacktestValuations,
  BacktestValuationRow,
  getScoutRatingEval,
  ScoutRatingEvalResponse,
  ScoutRatingRow,
} from '@/lib/api';
import { Card } from '@/components/ui/Card';
import { Surface } from '@/components/ui/Surface';
import { Badge } from '@/components/ui/Badge';
import { StatTile } from '@/components/ui/StatTile';
import { AssumptionFlag } from '@/components/ui/AssumptionFlag';
import { Avatar } from '@/components/ui/Avatar';
import { fmtPct, signed } from '@/lib/utils';

// Default leaderboard qualification floor: real rotation players only, so small-sample
// flukes (e.g. a high-MPG cameo over 5 games) don't top the bargain/overpay tables.
// The analyst can adjust both bars live via the sliders above the leaderboards.
const MIN_MPG = 20;
const MIN_GP = 40;

// Compact inline slider reusing the design-system `.siq-slider` track styling.
function MiniSlider({ label, value, onChange, min, max, step, suffix }: {
  label: string; value: number; onChange: (v: number) => void;
  min: number; max: number; step: number; suffix: string;
}) {
  const pct = max === min ? 0 : ((value - min) / (max - min)) * 100;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, flex: '1 1 200px', minWidth: 180 }}>
      <span style={{ fontSize: 12, color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>{label}</span>
      <input
        className="siq-slider"
        type="range" min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        style={{ '--siq-slider-pct': `${Math.min(100, Math.max(0, pct))}%`, flex: 1 } as CSSProperties}
      />
      <span className="ds-tnum" style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', width: 52, textAlign: 'right', whiteSpace: 'nowrap' }}>
        {value}{suffix}
      </span>
    </div>
  );
}

function compactSeasonRange(seasons: string[] | undefined): string {
  if (!seasons?.length) return 'test set';
  const first = seasons[0];
  const last = seasons[seasons.length - 1];
  if (first === last) return first;
  return `${first.slice(0, 4)}-${last.slice(2, 4)}`;
}

function CalRow({ nominal, empirical, halfWidthPct }: { nominal: number; empirical: number; halfWidthPct: number }) {
  const ok = Math.abs(empirical - nominal) <= 0.05;
  return (
    <tr style={{ borderBottom: '1px solid var(--border-subtle)' }}>
      <td style={{ padding: '7px 8px', fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--text-secondary)' }}>
        {(nominal * 100).toFixed(0)}%
      </td>
      <td style={{ padding: '7px 8px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{ flex: 1, height: 6, background: 'var(--bg-inset)', borderRadius: 999, overflow: 'hidden', minWidth: 70 }}>
            <div style={{
              width: `${empirical * 100}%`, height: '100%',
              background: ok ? 'var(--confidence)' : 'var(--warning)',
            }} />
          </div>
          <span className="ds-tnum" style={{ fontSize: 13, color: 'var(--text-primary)', width: 44, textAlign: 'right' }}>
            {(empirical * 100).toFixed(1)}%
          </span>
        </div>
      </td>
      <td className="ds-tnum" style={{ padding: '7px 8px', fontSize: 13, color: 'var(--text-muted)', textAlign: 'right' }}>
        ±{halfWidthPct.toFixed(1)}%
      </td>
    </tr>
  );
}

function fmtRate(value: number | undefined): string {
  return value == null ? '—' : `${(value * 100).toFixed(1)}%`;
}

function traitLabel(trait: string): string {
  if (trait === 'basketball_iq') return 'Basketball IQ';
  return trait
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function RatingPill({ rating }: { rating: ScoutRatingRow }) {
  return (
    <div style={{
      border: '1px solid var(--border-subtle)',
      borderRadius: 'var(--radius-md)',
      padding: '8px 10px',
      background: 'var(--bg-inset)',
      minWidth: 0,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, justifyContent: 'space-between', marginBottom: 5 }}>
        <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-primary)' }}>{traitLabel(rating.trait)}</span>
        <span className="ds-tnum" style={{ fontSize: 12, fontWeight: 700, color: 'var(--accent-text)' }}>
          {rating.score}/5
        </span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
        <Badge tone={rating.confidence === 'high' ? 'confidence' : rating.confidence === 'medium' ? 'neutral' : 'warning'} size="sm">
          {rating.confidence}
        </Badge>
        <span style={{ fontSize: 11, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          &quot;{rating.evidence_span}&quot;
        </span>
      </div>
    </div>
  );
}

function ScoutEvalPanel({ scoutEval }: { scoutEval: ScoutRatingEvalResponse | null }) {
  const report = scoutEval?.report;
  const metrics = [
    { label: 'Trait coverage', value: fmtRate(report?.trait_coverage), sub: report ? `${report.predicted_trait_count}/${report.expected_trait_count} traits` : 'Loading fixture' },
    { label: 'Exact agreement', value: fmtRate(report?.exact_score_agreement), sub: 'Score match' },
    { label: 'Within-1', value: fmtRate(report?.within_one_score_agreement), sub: 'Tolerant score match' },
    { label: 'Evidence hit', value: fmtRate(report?.evidence_hit_rate), sub: 'Span appears in note' },
  ];

  return (
    <Surface
      variant="dossier"
      eyebrow="AI extraction eval"
      icon={<ClipboardCheck size={15} />}
      action={<Badge tone="confidence" size="sm" dot>{scoutEval?.mode.replace('_', ' ') ?? 'loading'}</Badge>}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(145px, 1fr))', gap: 10 }}>
          {metrics.map((metric) => (
            <div key={metric.label} style={{
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-md)',
              padding: '10px 12px',
              background: 'var(--bg-inset)',
              minWidth: 0,
            }}>
              <div style={{ fontSize: 10, textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 700, marginBottom: 5 }}>
                {metric.label}
              </div>
              <div className="ds-tnum" style={{ fontSize: 22, fontWeight: 800, color: 'var(--text-primary)', lineHeight: 1 }}>
                {metric.value}
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 5 }}>{metric.sub}</div>
            </div>
          ))}
          <div style={{
            border: '1px solid var(--border-subtle)',
            borderRadius: 'var(--radius-md)',
            padding: '10px 12px',
            background: 'var(--bg-inset)',
            minWidth: 0,
          }}>
            <div style={{ fontSize: 10, textTransform: 'uppercase', color: 'var(--text-muted)', fontWeight: 700, marginBottom: 5 }}>
              Invalid rows
            </div>
            <div className="ds-tnum" style={{
              fontSize: 22,
              fontWeight: 800,
              color: report?.invalid_output_count ? 'var(--negative-text)' : 'var(--confidence-text)',
              lineHeight: 1,
            }}>
              {report?.invalid_output_count ?? '—'}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 5 }}>
              {scoutEval ? `${scoutEval.gold_count} synthetic notes` : 'Loading fixture'}
            </div>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 12 }}>
          {(scoutEval?.examples ?? []).map((example) => (
            <div key={example.note_id} style={{
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-md)',
              padding: 12,
              minWidth: 0,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, marginBottom: 8 }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)' }}>{example.player_name}</span>
                <span className="ds-tnum" style={{ fontSize: 11, color: 'var(--text-muted)' }}>{example.note_id}</span>
              </div>
              <p style={{ margin: '0 0 10px', fontSize: 12, lineHeight: 1.55, color: 'var(--text-secondary)' }}>
                {example.source_text}
              </p>
              <div style={{ display: 'grid', gap: 8 }}>
                {example.ratings.slice(0, 3).map((rating) => <RatingPill key={rating.trait} rating={rating} />)}
              </div>
            </div>
          ))}
        </div>

        <p style={{ fontSize: 11, color: 'var(--text-muted)', margin: 0, lineHeight: 1.5 }}>
          {scoutEval?.caveat ?? 'Offline fixture metrics are loading from the FastAPI eval endpoint.'}
          {' '}This is model-quality metadata for the scout-text extractor, not player-profile data yet.
          {scoutEval ? ` CLI artifact target: ${scoutEval.artifact_path}.` : ''}
        </p>
      </div>
    </Surface>
  );
}

// One leaderboard row, driven by a backtest valuation row. `summary` is an
// optional live-API lookup (by name) that enables click-through + position/team.
function LeaderRow({ row, summary, onPick }: {
  row: BacktestValuationRow;
  summary?: PlayerSummary | null;
  onPick?: () => void;
}) {
  const clickable = !!onPick;
  const team = summary?.current_team?.abbreviation ?? summary?.latest_stats_team?.abbreviation;
  return (
    <button
      onClick={onPick}
      disabled={!clickable}
      style={{
        display: 'flex', alignItems: 'center', gap: 12, padding: '10px 14px',
        width: '100%', textAlign: 'left', background: 'transparent',
        border: 'none', borderBottom: '1px solid var(--border-subtle)',
        cursor: clickable ? 'pointer' : 'default', transition: 'background var(--duration-fast) var(--ease-out)',
      }}
      onMouseEnter={(e) => { if (clickable) (e.currentTarget as HTMLElement).style.background = 'var(--bg-hover)'; }}
      onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = 'transparent'; }}
    >
      <Avatar name={row.full_name} size="sm" position={summary?.position} playerId={summary?.player_id} />
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {row.full_name}
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          {team ? `${team} · ` : ''}{row.next_season} · {row.min_per_g} MPG
        </div>
      </div>
      <div className="ds-tnum" style={{ fontSize: 13, color: 'var(--text-secondary)', textAlign: 'right' }}>
        {fmtPct(row.value_pct)} vs {fmtPct(row.actual_pct)}
      </div>
      <span className="ds-tnum" style={{
        fontSize: 14, fontWeight: 700, width: 64, textAlign: 'right',
        color: row.gap_pct >= 0 ? 'var(--positive-text)' : 'var(--negative-text)',
      }}>
        {signed(row.gap_pct)}%
      </span>
    </button>
  );
}

function CautionRow({ player, onPick }: { player: PlayerCardResponse; onPick: () => void }) {
  const valuation = player.valuation;
  const team = player.current_team?.abbreviation ?? player.latest_stats_team?.abbreviation;
  return (
    <button
      onClick={onPick}
      style={{
        display: 'flex', alignItems: 'center', gap: 12, padding: '10px 14px',
        width: '100%', textAlign: 'left', background: 'transparent',
        border: 'none', borderBottom: '1px solid var(--border-subtle)',
        cursor: 'pointer', transition: 'background var(--duration-fast) var(--ease-out)',
      }}
      onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--bg-hover)'; }}
      onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
    >
      <Avatar name={player.full_name} size="sm" position={player.position} playerId={player.player_id} />
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {player.full_name}
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {team ? `${team} · ` : ''}{valuation?.caution_flags.slice(0, 2).join(' · ') || 'Model caution'}
        </div>
      </div>
      <div className="ds-tnum" style={{ fontSize: 13, color: 'var(--text-secondary)', textAlign: 'right' }}>
        {valuation ? `${fmtPct(valuation.value_pct)} vs ${valuation.actual_pct != null ? fmtPct(valuation.actual_pct) : '—'}` : '—'}
      </div>
      <span className="ds-tnum" style={{ fontSize: 14, fontWeight: 700, width: 64, textAlign: 'right', color: 'var(--warning-text)' }}>
        {valuation?.gap_pct != null ? `${signed(valuation.gap_pct)}%` : '—'}
      </span>
    </button>
  );
}

type ScatterPoint = { name: string; actual: number; value: number };

// SVG scatter plot: predicted vs actual.
// The full test-set population renders as quiet ink; players surfaced in the
// leaderboards below are highlighted in accent orange so the two views connect.
function ScatterPlot({ points, highlight }: { points: ScatterPoint[]; highlight: Set<string> }) {
  const W = 320, H = 260, pad = 36, MAX = 40;
  const sx = (v: number) => pad + (Math.min(v, MAX) / MAX) * (W - pad - 8);
  const sy = (v: number) => H - pad - (Math.min(v, MAX) / MAX) * (H - pad - 8);
  const ticks = [0, 10, 20, 30, 40];
  const [hover, setHover] = useState<number | null>(null);

  const hp = hover != null ? points[hover] : null;

  const dot = (p: ScatterPoint, i: number, hot: boolean) => (
    <circle key={i}
      cx={sx(p.actual)} cy={sy(p.value)} r={hover === i ? (hot ? 6 : 4.5) : (hot ? 5 : 3)}
      fill={hot ? 'var(--accent)' : 'var(--text-muted)'}
      opacity={hot ? 0.95 : 0.4}
      stroke="var(--bg-panel)" strokeWidth={hot ? 1.5 : 0.75}
      style={{ cursor: 'pointer', transition: 'r var(--duration-fast) var(--ease-out)' }}
      onMouseEnter={() => setHover(i)}
      onMouseLeave={() => setHover((cur) => (cur === i ? null : cur))}
    />
  );

  return (
    <div style={{ position: 'relative' }}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto', display: 'block' }}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={sx(t)} y1={pad - 6} x2={sx(t)} y2={H - pad} stroke="var(--border-subtle)" />
            <line x1={pad} y1={sy(t)} x2={W - 8} y2={sy(t)} stroke="var(--border-subtle)" />
            <text x={sx(t)} y={H - pad + 14} fill="var(--text-muted)" fontSize="8" fontFamily="var(--font-mono)" textAnchor="middle">{t}</text>
            <text x={pad - 8} y={sy(t) + 3} fill="var(--text-muted)" fontSize="8" fontFamily="var(--font-mono)" textAnchor="end">{t}</text>
          </g>
        ))}
        {/* Diagonal parity line */}
        <line x1={sx(0)} y1={sy(0)} x2={sx(MAX)} y2={sy(MAX)}
              stroke="var(--accent)" strokeWidth="1.5" strokeDasharray="4 4" opacity="0.7" />
        {/* Population first (quiet ink), then highlighted players on top (accent) */}
        {points.map((p, i) => (!highlight.has(p.name) ? dot(p, i, false) : null))}
        {points.map((p, i) => (highlight.has(p.name) ? dot(p, i, true) : null))}
        <text x={W / 2} y={H - 4} fill="var(--text-secondary)" fontSize="9" fontFamily="var(--font-sans)" textAnchor="middle">
          Actual salary (% of cap)
        </text>
        <text x={12} y={H / 2} fill="var(--text-secondary)" fontSize="9" fontFamily="var(--font-sans)" textAnchor="middle"
              transform={`rotate(-90 12 ${H / 2})`}>
          Predicted (% of cap)
        </text>
      </svg>
      {hp && (
        <div style={{
          position: 'absolute',
          left: `${(sx(hp.actual) / W) * 100}%`,
          top: `${(sy(hp.value) / H) * 100}%`,
          transform: 'translate(-50%, calc(-100% - 10px))',
          pointerEvents: 'none',
          background: 'var(--bg-elevated, var(--bg-panel))',
          border: '1px solid var(--border-default, var(--border-subtle))',
          borderRadius: 8,
          padding: '6px 10px',
          fontSize: 12,
          whiteSpace: 'nowrap',
          boxShadow: '0 4px 16px rgba(0,0,0,0.4)',
          zIndex: 2,
        }}>
          <div style={{ fontWeight: 600, color: 'var(--text-primary)', marginBottom: 2 }}>{hp.name}</div>
          <div className="ds-tnum" style={{ color: 'var(--text-secondary)' }}>
            pay {fmtPct(hp.actual)} · value {fmtPct(hp.value)}
          </div>
        </div>
      )}
      <div style={{ display: 'flex', gap: 16, marginTop: 8, fontSize: 11, color: 'var(--text-muted)' }}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          <span style={{ width: 8, height: 8, borderRadius: 999, background: 'var(--accent)' }} />
          leaderboard player
        </span>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          <span style={{ width: 8, height: 8, borderRadius: 999, background: 'var(--text-muted)', opacity: 0.4 }} />
          test-set population
        </span>
      </div>
    </div>
  );
}

export default function ModelPage() {
  const router = useRouter();
  const [backtest, setBacktest] = useState<BacktestResponse | null>(null);
  const [backtestError, setBacktestError] = useState<string | null>(null);
  const [valRows, setValRows] = useState<BacktestValuationRow[]>([]);
  const [scoutEval, setScoutEval] = useState<ScoutRatingEvalResponse | null>(null);
  const [scoutEvalError, setScoutEvalError] = useState<string | null>(null);
  const [cautionRows, setCautionRows] = useState<PlayerCardResponse[]>([]);
  const [cautionError, setCautionError] = useState<string | null>(null);
  const [lookup, setLookup] = useState<Record<string, PlayerSummary | null>>({});
  const [minMpg, setMinMpg] = useState(MIN_MPG);
  const [minGp, setMinGp] = useState(MIN_GP);

  useEffect(() => {
    getBacktest()
      .then(setBacktest)
      .catch((e: unknown) => setBacktestError(e instanceof Error ? e.message : 'Backtest metadata unavailable.'));

    getBacktestValuations()
      .then(setValRows)
      .catch(() => {});

    getScoutRatingEval()
      .then(setScoutEval)
      .catch((e: unknown) => setScoutEvalError(e instanceof Error ? e.message : 'Scout-rating eval unavailable.'));

    getPlayerValuationCautions({ limit: 8 })
      .then((res) => setCautionRows(res.items))
      .catch((e: unknown) => setCautionError(e instanceof Error ? e.message : 'Valuation caution board unavailable.'));
  }, []);

  // Single source of truth: the committed held-out backtest rows drive both the
  // scatter and the leaderboards, so highlighted dots map exactly to the tables.
  // The scatter shows the full population; only the leaderboards are gated.
  const { scatterPoints, latest } = useMemo(() => {
    // One row per player — their latest test season.
    const latest = new Map<string, BacktestValuationRow>();
    for (const r of valRows) {
      const prev = latest.get(r.full_name);
      if (!prev || r.next_season > prev.next_season) latest.set(r.full_name, r);
    }
    return {
      scatterPoints: valRows.map((r) => ({ name: r.full_name, actual: r.actual_pct, value: r.value_pct })),
      latest,
    };
  }, [valRows]);

  // Leaderboards react live to the analyst's MPG/GP floor.
  const { bargains, overpays, highlightNames, leaderKey, qualifiedCount } = useMemo(() => {
    const qualified = [...latest.values()].filter((r) => r.min_per_g >= minMpg && r.gp >= minGp);
    const ranked = qualified.sort((a, b) => b.gap_pct - a.gap_pct);
    const bargains = ranked.filter((r) => r.gap_pct > 0).slice(0, 6);
    const overpays = [...ranked].reverse().filter((r) => r.gap_pct < 0).slice(0, 6);
    const leaders = [...bargains, ...overpays];
    return {
      bargains,
      overpays,
      qualifiedCount: qualified.length,
      highlightNames: new Set(leaders.map((r) => r.full_name)),
      leaderKey: leaders.map((r) => r.full_name).join('|'),
    };
  }, [latest, minMpg, minGp]);

  // Resolve player_id / position / team by name for the ~12 leaderboard players
  // (enables click-through to the profile + the avatar position badge).
  useEffect(() => {
    if (!leaderKey) return;
    for (const name of leaderKey.split('|')) {
      if (name in lookup) continue;
      searchPlayers(name, 5)
        .then((res) => setLookup((prev) => ({ ...prev, [name]: res.find((p) => p.full_name === name) ?? null })))
        .catch(() => setLookup((prev) => ({ ...prev, [name]: null })));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [leaderKey]);

  const loading = valRows.length === 0;
  const metrics = backtest?.metrics;
  const calibration = metrics?.calibration ?? [];
  const seasonRange = compactSeasonRange(metrics?.test_seasons);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--panel-gap)' }}>
      {/* Headline metrics */}
      {backtestError && (
        <AssumptionFlag tone="negative" title="Backtest metadata unavailable" icon={<TriangleAlert size={16} />}>
          {backtestError}
        </AssumptionFlag>
      )}

      <div className="siq-model-metrics-grid">
        {[
          { label: `R² (${seasonRange})`, value: metrics ? metrics.r2.toFixed(2) : '—', sub: metrics ? `${metrics.n_test} held-out rows` : 'Loading artifact' },
          { label: 'MAE', value: metrics ? metrics.mae_pct_of_cap.toFixed(1) : '—', unit: '%', sub: metrics ? `Mean baseline ${metrics.naive_mean_baseline_mae_pct.toFixed(1)}%` : 'Loading artifact' },
          {
            label: '80% coverage',
            value: metrics ? (metrics.interval_80_coverage * 100).toFixed(1) : '—',
            unit: '%',
            sub: 'Target 80.0%',
            delta: metrics ? `${((metrics.interval_80_coverage - 0.8) * 100).toFixed(1)}` : undefined,
            deltaDir: metrics && metrics.interval_80_coverage >= 0.8 ? 'up' as const : 'down' as const,
          },
          { label: 'Interval ±width', value: metrics ? `±${metrics.interval_80_half_width_pct.toFixed(1)}` : '—', unit: '%', sub: 'at 80% nominal' },
        ].map((m) => (
          <Card key={m.label} padded>
            <StatTile {...m} size="md" />
          </Card>
        ))}
      </div>

      <div className="siq-model-grid">
        {/* Scatter */}
        <Surface variant="instrument" eyebrow="Predicted vs. actual" icon={<Target size={15} />}
              action={scatterPoints.length > 0
                ? <Badge tone="accent" size="sm" dot>{scatterPoints.length} test-set rows</Badge>
                : <Badge tone="accent" size="sm" dot>loading…</Badge>}>
          {scatterPoints.length === 0
            ? <div style={{ height: 240, display: 'grid', placeItems: 'center', color: 'var(--text-muted)', fontSize: 13 }}>Loading…</div>
            : <ScatterPlot points={scatterPoints} highlight={highlightNames} />
          }
        </Surface>

        {/* Calibration table */}
        <Surface variant="board" eyebrow="Interval calibration" icon={<Target size={15} />}
              action={<Badge tone="confidence" variant="outline" size="sm">calibrated</Badge>}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                {['Nominal', 'Empirical', '± width'].map((h, i) => (
                  <th key={h} style={{
                    textAlign: i === 2 ? 'right' : 'left', padding: '0 8px 8px',
                    fontSize: 10, letterSpacing: '0.1em', textTransform: 'uppercase',
                    color: 'var(--text-muted)', fontWeight: 600,
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {calibration.length === 0 ? (
                <tr>
                  <td colSpan={3} style={{ padding: 24, textAlign: 'center', fontSize: 13, color: 'var(--text-muted)' }}>
                    Loading calibration artifact…
                  </td>
                </tr>
              ) : (
                calibration.map((c) => (
                  <CalRow
                    key={c.nominal}
                    nominal={c.nominal}
                    empirical={c.empirical}
                    halfWidthPct={c.half_width_pct}
                  />
                ))
              )}
            </tbody>
          </table>
          <p style={{ fontSize: 11, color: 'var(--text-muted)', margin: '12px 0 0', lineHeight: 1.5 }}>
            Conformal intervals are well-calibrated when empirical ≈ nominal. Coverage tracks the diagonal across all levels.
          </p>
        </Surface>
      </div>

      {scoutEvalError && (
        <AssumptionFlag tone="warning" title="AI extraction eval unavailable" icon={<TriangleAlert size={16} />}>
          {scoutEvalError}
        </AssumptionFlag>
      )}

      <ScoutEvalPanel scoutEval={scoutEval} />

      {cautionError && (
        <AssumptionFlag tone="warning" title="Caution board unavailable" icon={<TriangleAlert size={16} />}>
          {cautionError}
        </AssumptionFlag>
      )}

      <Surface
        variant="dossier"
        eyebrow="Live caution cases"
        icon={<TriangleAlert size={15} />}
        flush
        action={<Badge tone="warning" size="sm">{cautionRows.length || '—'} flagged</Badge>}
      >
        {cautionRows.length === 0
          ? <div style={{ padding: 24, textAlign: 'center', fontSize: 13, color: 'var(--text-muted)' }}>Loading caution board…</div>
          : cautionRows.map((player) => (
            <CautionRow
              key={player.player_id}
              player={player}
              onPick={() => router.push(`/players/${player.player_id}`)}
            />
          ))
        }
      </Surface>

      {/* Leaderboard qualification controls */}
      <Card padded>
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '16px 24px' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2, marginRight: 'auto' }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>Leaderboard qualification</span>
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
              {loading ? 'Loading…' : `${qualifiedCount} players clear the floor`}
            </span>
          </div>
          <MiniSlider label="Min MPG" value={minMpg} onChange={setMinMpg} min={0} max={40} step={1} suffix="" />
          <MiniSlider label="Min GP" value={minGp} onChange={setMinGp} min={0} max={82} step={1} suffix="" />
        </div>
      </Card>

      {/* Leaderboards */}
      <div className="siq-leader-grid">
        <Surface variant="board" eyebrow="Most underpaid" icon={<TrendingUp size={15} />} flush
              action={<Badge tone="positive" size="sm">test-set bargains</Badge>}>
          {loading
            ? <div style={{ padding: 24, textAlign: 'center', fontSize: 13, color: 'var(--text-muted)' }}>Loading…</div>
            : bargains.length === 0
              ? <div style={{ padding: 24, textAlign: 'center', fontSize: 13, color: 'var(--text-muted)' }}>No bargains in test set.</div>
              : bargains.map((p) => {
                const s = lookup[p.full_name];
                return (
                  <LeaderRow key={p.full_name + p.next_season} row={p} summary={s}
                    onPick={s ? () => router.push(`/players/${s.player_id}`) : undefined} />
                );
              })
          }
        </Surface>

        <Surface variant="board" eyebrow="Most overpaid" icon={<TrendingDown size={15} />} flush
              action={<Badge tone="negative" size="sm">test-set overpays</Badge>}>
          {loading
            ? <div style={{ padding: 24, textAlign: 'center', fontSize: 13, color: 'var(--text-muted)' }}>Loading…</div>
            : overpays.length === 0
              ? <div style={{ padding: 24, textAlign: 'center', fontSize: 13, color: 'var(--text-muted)' }}>No overpays in test set.</div>
              : overpays.map((p) => {
                const s = lookup[p.full_name];
                return (
                  <LeaderRow key={p.full_name + p.next_season} row={p} summary={s}
                    onPick={s ? () => router.push(`/players/${s.player_id}`) : undefined} />
                );
              })
          }
        </Surface>
      </div>

      <AssumptionFlag tone="warning" title="Honest caveat — salary stickiness" icon={<TriangleAlert size={16} />}>
        {backtest?.caveat ?? 'We exclude current salary on purpose so the model answers worth, not what is already on the books.'}
        {' '}The scatter, leaderboards, headline metrics, and calibration above are all drawn from the same committed held-out backtest artifact — each player&apos;s latest test season feeds the rankings. Leaderboards are limited to qualified players (≥{minMpg} MPG and ≥{minGp} games in the production season) so small-sample flukes don&apos;t crowd out real bargains and overpays — adjust both floors with the sliders above. The scatter still shows the full test-set population.
      </AssumptionFlag>
    </div>
  );
}
