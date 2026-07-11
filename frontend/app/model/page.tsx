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
import { Panel } from '@/components/ui/Panel';
import { Badge } from '@/components/ui/Badge';
import { DecisionStrip } from '@/components/ui/DecisionStrip';
import { LoadingNote } from '@/components/ui/LoadingNote';
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
    <div className="siq-row siq-row--10 siq-model-slider-group">
      <span className="siq-model-slider-label">{label}</span>
      <input
        className="siq-slider siq-model-slider-input"
        type="range" min={min} max={max} step={step} value={value}
        aria-label={label}
        onChange={(e) => onChange(Number(e.target.value))}
        style={{ '--siq-slider-pct': `${Math.min(100, Math.max(0, pct))}%` } as CSSProperties}
      />
      <span className="ds-tnum ds-right siq-model-slider-value">
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
    <tr className="siq-model-cal-row">
      <td className="siq-model-cal-label">
        {(nominal * 100).toFixed(0)}%
      </td>
      <td className="siq-model-cal-cell">
        <div className="siq-row">
          <div className="siq-model-cal-track">
            <div
              className="siq-model-cal-fill"
              style={{
                width: `${empirical * 100}%`,
                background: ok ? 'var(--confidence)' : 'var(--warning)',
              }}
            />
          </div>
          <span className="ds-tnum ds-right siq-model-cal-empirical">
            {(empirical * 100).toFixed(1)}%
          </span>
        </div>
      </td>
      <td className="ds-tnum ds-note ds-note--13 ds-right siq-model-cal-half-width">
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
    <div className="siq-min0 siq-model-rating-pill">
      <div className="siq-row siq-model-rating-heading">
        <span className="siq-model-rating-label">{traitLabel(rating.trait)}</span>
        <span className="ds-tnum siq-model-rating-score">
          {rating.score}/5
        </span>
      </div>
      <div className="siq-row siq-min0">
        <Badge tone={rating.confidence === 'high' ? 'confidence' : rating.confidence === 'medium' ? 'neutral' : 'warning'} size="sm">
          {rating.confidence}
        </Badge>
        <span className="ds-note siq-model-rating-evidence">
          &quot;{rating.evidence_span}&quot;
        </span>
      </div>
    </div>
  );
}

function ScoutEvalPanel({ scoutEval }: { scoutEval: ScoutRatingEvalResponse | null }) {
  const report = scoutEval?.report;
  const meta = scoutEval?.meta ?? null;
  const corpus = scoutEval?.corpus ?? null;
  const live = scoutEval?.mode === 'live_artifact';
  const metrics = [
    { label: 'Trait coverage', value: fmtRate(report?.trait_coverage), sub: report ? `${report.predicted_trait_count}/${report.expected_trait_count} traits` : 'Loading' },
    { label: 'Exact agreement', value: fmtRate(report?.exact_score_agreement), sub: 'Score match' },
    { label: 'Within-1', value: fmtRate(report?.within_one_score_agreement), sub: 'Tolerant score match' },
    { label: 'Evidence hit', value: fmtRate(report?.evidence_hit_rate), sub: 'Span appears in note' },
  ];
  const fmtDay = (iso: string) =>
    new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });

  return (
    <Panel
      variant="dossier"
      eyebrow="AI extraction eval"
      icon={<ClipboardCheck size={15} />}
      action={
        !scoutEval ? <Badge tone="neutral" size="sm">loading</Badge>
        : live ? <Badge tone="confidence" size="sm" dot>live eval · {meta?.model ?? 'model'}</Badge>
        : <Badge tone="warning" size="sm" dot>offline fixture</Badge>
      }
    >
      <div className="siq-model-eval-stack">
        {/* Receipts for the real pipeline: what Sonar fetched and Claude
            extracted, served from Postgres — distinct from the gold-set eval. */}
        {corpus && (
          <div className="siq-model-corpus-receipt">
            <span className="ds-eyebrow siq-model-corpus-eyebrow">
              Live corpus · Sonar → Claude → Postgres
            </span>
            <span className="ds-tnum siq-model-corpus-count">
              {corpus.rated_player_count} players
            </span>
            <span className="ds-tnum siq-model-corpus-count">
              {corpus.cited_report_count} cited reports
            </span>
            <span className="ds-tnum siq-model-corpus-count">
              {corpus.rating_count} extracted ratings
            </span>
            {corpus.latest_fetched_at && (
              <span className="ds-tnum ds-note">
                refreshed {fmtDay(corpus.latest_fetched_at)}
              </span>
            )}
          </div>
        )}

        <div className="ds-eyebrow siq-model-gold-label">
          Gold-set eval{live && meta ? ` — ${meta.model}, ${fmtDay(meta.generated_at)}` : ''}
        </div>
        <div className="siq-model-metric-grid">
          {metrics.map((metric) => (
            <div key={metric.label} className="siq-min0 siq-model-metric-card">
              <div className="ds-note siq-model-metric-label">
                {metric.label}
              </div>
              <div className="ds-tnum siq-model-metric-value">
                {metric.value}
              </div>
              <div className="ds-note siq-model-metric-subtext">{metric.sub}</div>
            </div>
          ))}
          <div className="siq-min0 siq-model-metric-card">
            <div className="ds-note siq-model-metric-label">
              Invalid rows
            </div>
            <div
              className="ds-tnum siq-model-metric-value"
              style={{ color: report?.invalid_output_count ? 'var(--negative-text)' : 'var(--confidence-text)' }}
            >
              {report?.invalid_output_count ?? '—'}
            </div>
            <div className="ds-note siq-model-metric-subtext">
              {scoutEval ? `${scoutEval.gold_count} synthetic notes` : 'Loading fixture'}
            </div>
          </div>
        </div>

        <div className="siq-model-example-grid">
          {(scoutEval?.examples ?? []).map((example) => (
            <div key={example.note_id} className="siq-min0 siq-model-example-card">
              <div className="siq-row siq-row--10 siq-model-example-header">
                <span className="siq-model-example-player">{example.player_name}</span>
                <span className="siq-model-inline-row">
                  <Badge tone="neutral" variant="outline" size="sm">synthetic gold note</Badge>
                  <span className="ds-tnum ds-note">{example.note_id}</span>
                </span>
              </div>
              <p className="siq-model-example-source">
                {example.source_text}
              </p>
              <div className="siq-model-rating-list">
                {example.ratings.slice(0, 3).map((rating) => <RatingPill key={rating.trait} rating={rating} />)}
              </div>
            </div>
          ))}
        </div>

        <p className="ds-note ds-m0 siq-model-eval-caveat">
          {scoutEval?.caveat ?? 'Eval metrics are loading from the FastAPI eval endpoint.'}
          {scoutEval ? ` CLI artifact: ${scoutEval.artifact_path}.` : ''}
        </p>
      </div>
    </Panel>
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
      className="siq-row siq-row--12 siq-model-list-row"
      onClick={onPick}
      disabled={!clickable}
      style={{ cursor: clickable ? 'pointer' : 'default' }}
      onMouseEnter={(e) => { if (clickable) (e.currentTarget as HTMLElement).style.background = 'var(--bg-hover)'; }}
      onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = 'transparent'; }}
    >
      <Avatar name={row.full_name} size="sm" position={summary?.position} playerId={summary?.player_id} />
      <div className="siq-min0 siq-model-player-cell">
        <div className="siq-model-player-name">
          {row.full_name}
        </div>
        <div className="ds-note">
          {team ? `${team} · ` : ''}{row.next_season} · {row.min_per_g} MPG
        </div>
      </div>
      <div className="ds-tnum ds-right siq-model-comparison">
        {fmtPct(row.value_pct)} vs {fmtPct(row.actual_pct)}
      </div>
      <span
        className="ds-tnum ds-right siq-model-gap"
        style={{ color: row.gap_pct >= 0 ? 'var(--positive-text)' : 'var(--negative-text)' }}
      >
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
      className="siq-row siq-row--12 siq-model-list-row siq-model-list-row--clickable"
      onClick={onPick}
      onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--bg-hover)'; }}
      onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
    >
      <Avatar name={player.full_name} size="sm" position={player.position} playerId={player.player_id} />
      <div className="siq-min0 siq-model-player-cell">
        <div className="siq-model-player-name">
          {player.full_name}
        </div>
        <div className="ds-note siq-model-player-meta--truncate">
          {team ? `${team} · ` : ''}{valuation?.caution_flags.slice(0, 2).join(' · ') || 'Model caution'}
        </div>
      </div>
      <div className="ds-tnum ds-right siq-model-comparison">
        {valuation ? `${fmtPct(valuation.value_pct)} vs ${valuation.actual_pct != null ? fmtPct(valuation.actual_pct) : '—'}` : '—'}
      </div>
      <span className="ds-tnum ds-right siq-model-gap siq-model-gap--warning">
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
      className="siq-model-scatter-dot"
      onMouseEnter={() => setHover(i)}
      onMouseLeave={() => setHover((cur) => (cur === i ? null : cur))}
    />
  );

  return (
    <div className="siq-model-scatter">
      <svg className="siq-model-scatter-svg" viewBox={`0 0 ${W} ${H}`}>
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
        <div
          className="siq-model-scatter-tooltip"
          style={{
            left: `${(sx(hp.actual) / W) * 100}%`,
            top: `${(sy(hp.value) / H) * 100}%`,
          }}
        >
          <div className="siq-model-tooltip-name">{hp.name}</div>
          <div className="ds-tnum siq-model-tooltip-detail">
            pay {fmtPct(hp.actual)} · value {fmtPct(hp.value)}
          </div>
        </div>
      )}
      <div className="ds-note siq-model-scatter-legend">
        <span className="siq-model-scatter-legend-item">
          <span className="siq-model-scatter-swatch siq-model-scatter-swatch--accent" />
          leaderboard player
        </span>
        <span className="siq-model-scatter-legend-item">
          <span className="siq-model-scatter-swatch siq-model-scatter-swatch--population" />
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
    const missingNames = leaderKey.split('|').filter((name) => !(name in lookup));
    if (missingNames.length === 0) return;

    const controller = new AbortController();
    Promise.all(
      missingNames.map(async (name) => {
        try {
          const res = await searchPlayers(name, 5, controller.signal);
          return [name, res.find((p) => p.full_name === name) ?? null] as const;
        } catch {
          if (controller.signal.aborted) return null;
          return [name, null] as const;
        }
      }),
    ).then((entries) => {
      if (controller.signal.aborted) return;
      setLookup((prev) => {
        const next = { ...prev };
        for (const entry of entries) {
          if (entry) next[entry[0]] = entry[1];
        }
        return next;
      });
    });

    return () => controller.abort();
  }, [leaderKey, lookup]);

  const loading = valRows.length === 0;
  const metrics = backtest?.metrics;
  const calibration = metrics?.calibration ?? [];
  const decisionCoverage = metrics?.segments?.decision_point.interval_80_coverage;
  const seasonRange = compactSeasonRange(metrics?.test_seasons);

  return (
    <div className="siq-stack">
      <h1 className="siq-sr-only">Model performance</h1>
      {/* Headline metrics */}
      {backtestError && (
        <AssumptionFlag tone="negative" title="Backtest metadata unavailable" icon={<TriangleAlert size={16} />}>
          {backtestError}
        </AssumptionFlag>
      )}

      <DecisionStrip
        ariaLabel="Model decision readiness"
        lead={{
          label: 'Contract-setting test',
          value: metrics ? `${metrics.segments.decision_point.mae_pct_of_cap.toFixed(1)}% MAE` : 'Loading artifact',
          detail: metrics ? `Beats ${metrics.segments.decision_point.persistence_mae_pct?.toFixed(1) ?? '—'}% salary persistence across ${metrics.segments.decision_point.n} held-out decisions` : 'Evaluating decision-point performance',
          tone: metrics && metrics.segments.decision_point.persistence_mae_pct != null && metrics.segments.decision_point.mae_pct_of_cap < metrics.segments.decision_point.persistence_mae_pct ? 'positive' : 'warning',
        }}
        items={[
          {
            label: 'Decision coverage',
            value: decisionCoverage != null ? `${(decisionCoverage * 100).toFixed(1)}%` : '—',
            detail: 'Nominal 80% interval at contract starts',
            tone: decisionCoverage != null && decisionCoverage >= 0.8 ? 'confidence' : 'warning',
          },
          {
            label: `Explanatory fit · ${seasonRange}`,
            value: metrics ? `R² ${metrics.r2.toFixed(2)}` : '—',
            detail: metrics ? `${metrics.n_test} held-out rows · ${metrics.mae_pct_of_cap.toFixed(1)}% overall MAE` : 'Loading artifact',
            tone: 'neutral',
          },
          {
            label: 'Uncertainty cost',
            value: metrics ? `±${metrics.interval_80_half_width_pct.toFixed(1)}% cap` : '—',
            detail: metrics ? `${(metrics.interval_80_coverage * 100).toFixed(1)}% conservative all-row coverage` : 'Adaptive interval width',
            tone: 'confidence',
          },
        ]}
      />

      <div className="siq-model-grid">
        {/* Scatter */}
        <Panel variant="instrument" eyebrow="Predicted vs. actual" icon={<Target size={15} />}
              action={scatterPoints.length > 0
                ? <Badge tone="accent" size="sm" dot>{scatterPoints.length} test-set rows</Badge>
                : <Badge tone="accent" size="sm" dot>loading…</Badge>}>
          {scatterPoints.length === 0
            ? <LoadingNote className="siq-loading-note--tall">Loading…</LoadingNote>
            : <ScatterPlot points={scatterPoints} highlight={highlightNames} />
          }
        </Panel>

        {/* Calibration table */}
        <Panel variant="board" eyebrow="Interval calibration" icon={<Target size={15} />}
              action={<Badge tone="confidence" variant="outline" size="sm">calibrated</Badge>}>
          <table className="siq-model-cal-table">
            <thead>
              <tr>
                {['Nominal', 'Empirical', '± width'].map((h, i) => (
                  <th
                    key={h}
                    className="siq-model-cal-heading"
                    style={{ textAlign: i === 2 ? 'right' : 'left' }}
                  >{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {calibration.length === 0 ? (
                <tr>
                  <td colSpan={3}>
                    <LoadingNote className="siq-loading-note--row">Loading calibration artifact…</LoadingNote>
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
          <p className="ds-note siq-model-cal-note">
            The published 80% interval is calibrated on historical contract starts. Other levels are diagnostics, not separate production guarantees.
          </p>
        </Panel>
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

      <Panel
        variant="dossier"
        eyebrow="Live caution cases"
        icon={<TriangleAlert size={15} />}
        flush
        action={<Badge tone="warning" size="sm">{cautionRows.length || '—'} flagged</Badge>}
      >
        {cautionRows.length === 0
          ? <div className="ds-note ds-note--13 siq-model-board-message">Loading caution board…</div>
          : cautionRows.map((player) => (
            <CautionRow
              key={player.player_id}
              player={player}
              onPick={() => router.push(`/players/${player.player_id}`)}
            />
          ))
        }
      </Panel>

      {/* Leaderboard qualification controls */}
      <Panel variant="card" padded>
        <div className="siq-row siq-model-qualification">
          <div className="siq-model-qualification-copy">
            <span className="siq-model-qualification-title">Leaderboard qualification</span>
            <span className="ds-note">
              {loading ? 'Loading…' : `${qualifiedCount} players clear the floor`}
            </span>
          </div>
          <MiniSlider label="Min MPG" value={minMpg} onChange={setMinMpg} min={0} max={40} step={1} suffix="" />
          <MiniSlider label="Min GP" value={minGp} onChange={setMinGp} min={0} max={82} step={1} suffix="" />
        </div>
      </Panel>

      {/* Leaderboards */}
      <div className="siq-leader-grid">
        <Panel variant="board" eyebrow="Most underpaid" icon={<TrendingUp size={15} />} flush
              action={<Badge tone="positive" size="sm">test-set bargains</Badge>}>
          {loading
            ? <div className="ds-note ds-note--13 siq-model-board-message">Loading…</div>
            : bargains.length === 0
              ? <div className="ds-note ds-note--13 siq-model-board-message">No bargains in test set.</div>
              : bargains.map((p) => {
                const s = lookup[p.full_name];
                return (
                  <LeaderRow key={p.full_name + p.next_season} row={p} summary={s}
                    onPick={s ? () => router.push(`/players/${s.player_id}`) : undefined} />
                );
              })
          }
        </Panel>

        <Panel variant="board" eyebrow="Most overpaid" icon={<TrendingDown size={15} />} flush
              action={<Badge tone="negative" size="sm">test-set overpays</Badge>}>
          {loading
            ? <div className="ds-note ds-note--13 siq-model-board-message">Loading…</div>
            : overpays.length === 0
              ? <div className="ds-note ds-note--13 siq-model-board-message">No overpays in test set.</div>
              : overpays.map((p) => {
                const s = lookup[p.full_name];
                return (
                  <LeaderRow key={p.full_name + p.next_season} row={p} summary={s}
                    onPick={s ? () => router.push(`/players/${s.player_id}`) : undefined} />
                );
              })
          }
        </Panel>
      </div>

      <AssumptionFlag tone="warning" title="Honest caveat — salary stickiness" icon={<TriangleAlert size={16} />}>
        {backtest?.caveat ?? 'We exclude current salary on purpose so the model answers worth, not what is already on the books.'}
        {' '}The scatter, leaderboards, headline metrics, and calibration above are all drawn from the same committed held-out backtest artifact — each player&apos;s latest test season feeds the rankings. Leaderboards are limited to qualified players (≥{minMpg} MPG and ≥{minGp} games in the production season) so small-sample flukes don&apos;t crowd out real bargains and overpays — adjust both floors with the sliders above. The scatter still shows the full test-set population.
      </AssumptionFlag>
    </div>
  );
}
