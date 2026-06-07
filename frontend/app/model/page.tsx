'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Target, TrendingUp, TrendingDown, TriangleAlert } from 'lucide-react';
import {
  searchPlayers,
  PlayerSummary,
  getValuation,
  ValuationResponse,
  getBacktest,
  BacktestResponse,
} from '@/lib/api';
import { Card } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { StatTile } from '@/components/ui/StatTile';
import { AssumptionFlag } from '@/components/ui/AssumptionFlag';
import { Avatar } from '@/components/ui/Avatar';
import { fmtPct, signed } from '@/lib/utils';

type PlayerWithVal = PlayerSummary & { valuation?: ValuationResponse };

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

function LeaderRow({ player, onPick }: { player: PlayerWithVal; onPick: () => void }) {
  const val = player.valuation;
  return (
    <button
      onClick={onPick}
      style={{
        display: 'flex', alignItems: 'center', gap: 12, padding: '10px 14px',
        width: '100%', textAlign: 'left', background: 'transparent',
        border: 'none', borderBottom: '1px solid var(--border-subtle)',
        cursor: 'pointer', transition: 'background var(--duration-fast) var(--ease-out)',
      }}
      onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = 'var(--bg-hover)'; }}
      onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = 'transparent'; }}
    >
      <Avatar name={player.full_name} size="sm" position={player.position} />
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {player.full_name}
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          {player.current_team?.abbreviation ?? player.latest_stats_team?.abbreviation ?? '—'} · {player.latest_season ?? '—'}
        </div>
      </div>
      {val && (
        <>
          <div className="ds-tnum" style={{ fontSize: 13, color: 'var(--text-secondary)', textAlign: 'right' }}>
            {fmtPct(val.value_pct)} vs {val.actual_pct != null ? fmtPct(val.actual_pct) : '—'}
          </div>
          <span className="ds-tnum" style={{
            fontSize: 14, fontWeight: 700, width: 64, textAlign: 'right',
            color: val.gap_pct != null && val.gap_pct >= 0 ? 'var(--positive-text)' : 'var(--negative-text)',
          }}>
            {val.gap_pct != null ? signed(val.gap_pct) + '%' : '—'}
          </span>
        </>
      )}
    </button>
  );
}

// SVG scatter plot: predicted vs actual
function ScatterPlot({ players }: { players: PlayerWithVal[] }) {
  const W = 320, H = 260, pad = 36, MAX = 40;
  const sx = (v: number) => pad + (Math.min(v, MAX) / MAX) * (W - pad - 8);
  const sy = (v: number) => H - pad - (Math.min(v, MAX) / MAX) * (H - pad - 8);
  const ticks = [0, 10, 20, 30, 40];

  const points = players
    .filter((p) => p.valuation?.actual_pct != null && p.valuation?.value_pct != null)
    .map((p) => ({
      name: p.full_name,
      actual: p.valuation!.actual_pct!,
      value: p.valuation!.value_pct,
    }));

  return (
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
      {points.map((p, i) => (
        <circle key={i}
          cx={sx(p.actual)} cy={sy(p.value)} r={4}
          fill="var(--accent)" opacity={0.8}
          stroke="var(--bg-panel)" strokeWidth={1.5}
        >
          <title>{p.name}: pay {fmtPct(p.actual)}, value {fmtPct(p.value)}</title>
        </circle>
      ))}
      <text x={W / 2} y={H - 4} fill="var(--text-secondary)" fontSize="9" fontFamily="var(--font-sans)" textAnchor="middle">
        Actual salary (% of cap)
      </text>
      <text x={12} y={H / 2} fill="var(--text-secondary)" fontSize="9" fontFamily="var(--font-sans)" textAnchor="middle"
            transform={`rotate(-90 12 ${H / 2})`}>
        Predicted (% of cap)
      </text>
    </svg>
  );
}

export default function ModelPage() {
  const router = useRouter();
  const [players, setPlayers] = useState<PlayerWithVal[]>([]);
  const [loading, setLoading] = useState(true);
  const [backtest, setBacktest] = useState<BacktestResponse | null>(null);
  const [backtestError, setBacktestError] = useState<string | null>(null);

  useEffect(() => {
    getBacktest()
      .then(setBacktest)
      .catch((e: unknown) => setBacktestError(e instanceof Error ? e.message : 'Backtest metadata unavailable.'));

    searchPlayers(undefined, 50).then((list) => {
      const withVal: PlayerWithVal[] = list.map((p) => ({ ...p }));
      setPlayers(withVal);
      setLoading(false);
      // Hydrate valuations
      list.forEach((p) => {
        getValuation(p.player_id).then((val) => {
          setPlayers((prev) =>
            prev.map((r) => r.player_id === p.player_id ? { ...r, valuation: val } : r)
          );
        }).catch(() => {});
      });
    }).catch(() => setLoading(false));
  }, []);

  const withVals = players.filter((p) => p.valuation?.gap_pct != null);
  const sorted = [...withVals].sort((a, b) => (b.valuation!.gap_pct ?? 0) - (a.valuation!.gap_pct ?? 0));
  const bargains = sorted.filter((p) => (p.valuation?.gap_pct ?? 0) > 0).slice(0, 6);
  const overpays = [...sorted].reverse().filter((p) => (p.valuation?.gap_pct ?? 0) < 0).slice(0, 6);
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
        <Card eyebrow="Predicted vs. actual" icon={<Target size={15} />}
              action={<Badge tone="accent" size="sm" dot>{withVals.length}-player sample</Badge>}>
          {loading
            ? <div style={{ height: 240, display: 'grid', placeItems: 'center', color: 'var(--text-muted)', fontSize: 13 }}>Loading…</div>
            : <ScatterPlot players={players} />
          }
        </Card>

        {/* Calibration table */}
        <Card eyebrow="Interval calibration" icon={<Target size={15} />}
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
        </Card>
      </div>

      {/* Leaderboards */}
      <div className="siq-leader-grid">
        <Card eyebrow="Most underpaid" icon={<TrendingUp size={15} />} flushBody
              action={<Badge tone="positive" size="sm">sample bargains</Badge>}>
          {loading || withVals.length === 0
            ? <div style={{ padding: 24, textAlign: 'center', fontSize: 13, color: 'var(--text-muted)' }}>Loading…</div>
            : bargains.length === 0
              ? <div style={{ padding: 24, textAlign: 'center', fontSize: 13, color: 'var(--text-muted)' }}>No bargains in loaded sample.</div>
              : bargains.map((p) => (
              <LeaderRow key={p.player_id} player={p}
                onPick={() => router.push(`/players/${p.player_id}`)} />
            ))
          }
        </Card>

        <Card eyebrow="Most overpaid" icon={<TrendingDown size={15} />} flushBody
              action={<Badge tone="negative" size="sm">sample overpays</Badge>}>
          {loading || withVals.length === 0
            ? <div style={{ padding: 24, textAlign: 'center', fontSize: 13, color: 'var(--text-muted)' }}>Loading…</div>
            : overpays.length === 0
              ? <div style={{ padding: 24, textAlign: 'center', fontSize: 13, color: 'var(--text-muted)' }}>No overpays in loaded sample.</div>
              : overpays.map((p) => (
              <LeaderRow key={p.player_id} player={p}
                onPick={() => router.push(`/players/${p.player_id}`)} />
            ))
          }
        </Card>
      </div>

      <AssumptionFlag tone="warning" title="Honest caveat — salary stickiness" icon={<TriangleAlert size={16} />}>
        {backtest?.caveat ?? 'We exclude current salary on purpose so the model answers worth, not what is already on the books.'}
        {' '}The scatter and leaderboards above use the currently loaded player sample; headline metrics and calibration come from the committed backtest artifact.
      </AssumptionFlag>
    </div>
  );
}
