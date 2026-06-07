'use client';

import { useEffect, useState, use } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { ArrowLeft, Scale, Activity, BarChart3, SlidersHorizontal, Info } from 'lucide-react';
import { getValuation, ValuationResponse } from '@/lib/api';
import { Card } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { StatTile } from '@/components/ui/StatTile';
import { VerdictPill } from '@/components/ui/VerdictPill';
import { AssumptionFlag } from '@/components/ui/AssumptionFlag';
import { Avatar } from '@/components/ui/Avatar';
import { ValueGauge } from '@/components/players/ValueGauge';
import { fmtM, fmtPct, signed } from '@/lib/utils';

function StatRow({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'baseline', justifyContent: 'space-between',
      padding: '8px 0', borderBottom: '1px solid var(--border-subtle)',
    }}>
      <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>{label}</span>
      <span className="ds-tnum" style={{
        fontSize: 14, fontWeight: 600,
        color: warn ? 'var(--warning-text)' : 'var(--text-primary)',
      }}>
        {value}
      </span>
    </div>
  );
}

// Feature metadata: label + how to format the raw value from the API.
// Keys match the actual column names in features.py (some are uppercase NBA_ADV keys).
const FEATURE_META: Record<string, { label: string; fmt: (v: number) => string }> = {
  // Base
  age:        { label: 'Age',              fmt: (v) => v.toFixed(0) },
  gp:         { label: 'Games played',     fmt: (v) => v.toFixed(0) },
  minutes:    { label: 'Season minutes',   fmt: (v) => Math.round(v).toLocaleString() },
  // Per-game box (API returns _pg suffix)
  pts_pg:     { label: 'Points / game',    fmt: (v) => v.toFixed(1) },
  reb_pg:     { label: 'Rebounds / game',  fmt: (v) => v.toFixed(1) },
  ast_pg:     { label: 'Assists / game',   fmt: (v) => v.toFixed(1) },
  stl_pg:     { label: 'Steals / game',    fmt: (v) => v.toFixed(1) },
  blk_pg:     { label: 'Blocks / game',    fmt: (v) => v.toFixed(1) },
  tov_pg:     { label: 'Turnovers / game', fmt: (v) => v.toFixed(1) },
  fg3m_pg:    { label: '3PM / game',       fmt: (v) => v.toFixed(1) },
  // NBA.com Advanced (uppercase keys from API)
  TS_PCT:     { label: 'True shooting',    fmt: (v) => (v * 100).toFixed(1) + '%' },
  EFG_PCT:    { label: 'eFG%',             fmt: (v) => (v * 100).toFixed(1) + '%' },
  USG_PCT:    { label: 'Usage rate',       fmt: (v) => (v * 100).toFixed(1) + '%' },
  PIE:        { label: 'PIE',              fmt: (v) => (v * 100).toFixed(1) + '%' },
  OFF_RATING: { label: 'Off. rating',      fmt: (v) => v.toFixed(1) },
  DEF_RATING: { label: 'Def. rating',      fmt: (v) => v.toFixed(1) },
  NET_RATING: { label: 'Net rating',       fmt: (v) => (v >= 0 ? '+' : '') + v.toFixed(1) },
  AST_PCT:    { label: 'Ast. %',           fmt: (v) => (v * 100).toFixed(1) + '%' },
  OREB_PCT:   { label: 'OReb. %',          fmt: (v) => (v * 100).toFixed(1) + '%' },
  DREB_PCT:   { label: 'DReb. %',          fmt: (v) => (v * 100).toFixed(1) + '%' },
  REB_PCT:    { label: 'Reb. %',           fmt: (v) => (v * 100).toFixed(1) + '%' },
  TM_TOV_PCT: { label: 'Team TOV %',       fmt: (v) => (v * 100).toFixed(1) + '%' },
  PACE:       { label: 'Pace',             fmt: (v) => v.toFixed(1) },
  // BBRef advanced (uppercase)
  BPM:        { label: 'BPM',              fmt: (v) => (v >= 0 ? '+' : '') + v.toFixed(1) },
  OBPM:       { label: 'Off. BPM',         fmt: (v) => (v >= 0 ? '+' : '') + v.toFixed(1) },
  DBPM:       { label: 'Def. BPM',         fmt: (v) => (v >= 0 ? '+' : '') + v.toFixed(1) },
  VORP:       { label: 'VORP',             fmt: (v) => v.toFixed(1) },
  WS:         { label: 'Win Shares',       fmt: (v) => v.toFixed(1) },
  WS48:       { label: 'WS / 48',          fmt: (v) => v.toFixed(3) },
  PER:        { label: 'PER',              fmt: (v) => v.toFixed(1) },
};

function formatFeatureValue(key: string, value: number): { label: string; formatted: string } {
  const meta = FEATURE_META[key];
  if (meta) return { label: meta.label, formatted: meta.fmt(value) };
  return { label: key.replace(/_/g, ' '), formatted: value.toFixed(2) };
}

export default function PlayerPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const playerId = Number(id);
  const router = useRouter();

  const [val, setVal] = useState<ValuationResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    getValuation(playerId)
      .then(setVal)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Failed to load valuation.'))
      .finally(() => setLoading(false));
  }, [playerId]);

  if (loading) {
    return <div style={{ padding: 48, textAlign: 'center', color: 'var(--text-muted)' }}>Loading…</div>;
  }

  if (error || !val) {
    return (
      <div>
        <Link href="/players" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, marginBottom: 16, textDecoration: 'none', fontSize: 13, color: 'var(--text-secondary)' }}>
          <ArrowLeft size={15} /> All players
        </Link>
        <div style={{ padding: '12px 16px', borderRadius: 'var(--radius-lg)', background: 'var(--negative-soft)', color: 'var(--negative-text)', fontSize: 13 }}>
          {error ?? 'Player not found.'}
        </div>
      </div>
    );
  }

  const capM = val.salary_cap ?? 140_588_000;
  const valueUsd = val.value_usd ?? Math.round(val.value_pct / 100 * capM);
  const actualUsd = val.actual_usd;

  // Feature entries — raw stat values from the model input
  const featureEntries = val.features
    ? Object.entries(val.features).slice(0, 8)
    : [];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--panel-gap)' }}>
      {/* Back */}
      <Link href="/players" style={{
        display: 'inline-flex', alignItems: 'center', gap: 6,
        padding: '5px 10px', borderRadius: 'var(--radius-md)',
        border: '1px solid var(--border-subtle)', background: 'var(--bg-panel)',
        textDecoration: 'none', color: 'var(--text-secondary)', fontSize: 13, fontWeight: 500,
        alignSelf: 'flex-start',
      }}>
        <ArrowLeft size={15} /> All players
      </Link>

      {/* Player header card */}
      <Card padded>
        <div className="siq-player-card-row">
          <Avatar name={val.player_name} size="xl" position={val.position} />
          <div style={{ minWidth: 0, flex: 1 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
              <h2 style={{
                fontFamily: 'var(--font-display)', fontWeight: 600, fontSize: 28,
                color: 'var(--text-primary)', margin: 0, lineHeight: 1.15,
              }}>
                {val.player_name}
              </h2>
              <Badge tone="neutral" size="sm">{val.season}</Badge>
            </div>
            <div style={{ marginTop: 4, fontSize: 14, color: 'var(--text-secondary)' }}>
              {val.position} · {val.current_team?.name ?? '—'}
            </div>
          </div>
          <VerdictPill gapPct={val.gap_pct} size="lg" />
          <button
            onClick={() => router.push(`/simulator?player=${playerId}`)}
            className="siq-primary-button"
          >
            <SlidersHorizontal size={15} />
            Run cap simulation
          </button>
        </div>
      </Card>

      <div className="siq-profile-grid">
        {/* Left column */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--panel-gap)' }}>
          {/* Valuation card */}
          <Card
            eyebrow="Production-implied value"
            icon={<Scale size={15} />}
            action={<Badge tone="confidence" variant="outline" size="sm">80% interval</Badge>}
          >
            <div style={{ display: 'flex', gap: 28, flexWrap: 'wrap', marginBottom: 20 }}>
              <StatTile
                label="Model value"
                value={fmtM(valueUsd)}
                unit={` · ${fmtPct(val.value_pct)}`}
                delta={val.gap_pct != null ? signed(val.gap_pct) + '%' : undefined}
                deltaDir={val.gap_pct != null ? (val.gap_pct >= 0 ? 'up' : 'down') : undefined}
                sub={`80% CI: ${fmtPct(val.lo_pct)}–${fmtPct(val.hi_pct)} of cap`}
                size="md"
              />
              {actualUsd && (
                <StatTile
                  label="Actual pay"
                  value={fmtM(actualUsd)}
                  unit={val.actual_pct != null ? ` · ${fmtPct(val.actual_pct)}` : undefined}
                  sub={`${val.season} cap hit`}
                  size="md"
                />
              )}
            </div>
            <ValueGauge
              valuePct={val.value_pct}
              loPct={val.lo_pct}
              hiPct={val.hi_pct}
              actualPct={val.actual_pct}
            />
          </Card>

          {/* Rationale placeholder */}
          <Card eyebrow="How to read this" icon={<Info size={15} />}>
            <p style={{ font: '14px/1.6 var(--font-sans)', color: 'var(--text-primary)', margin: 0 }}>
              Value is what production says the player is worth — the model never sees their current salary,
              so the gap to pay is the signal. The 80% conformal interval is calibrated on held-out seasons;
              coverage holds 85% of the time in the backtest.
            </p>
          </Card>

          <AssumptionFlag tone="confidence" title="Calibrated honesty" icon={<Info size={16} />}>
            This is a production-implied valuation, not a market-value estimate. It does not account for
            injury risk, defensive impact beyond box-score proxies, or gravity effects. Check the Model &amp;
            backtest view for full performance metrics.
          </AssumptionFlag>
        </div>

        {/* Right column */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--panel-gap)' }}>
          {/* Model input stats */}
          <Card eyebrow="Model inputs" icon={<Activity size={15} />}>
            {featureEntries.length > 0 ? (
              <>
                {featureEntries.map(([key, value]) => {
                  const { label, formatted } = formatFeatureValue(key, value);
                  return <StatRow key={key} label={label} value={formatted} />;
                })}
                <p style={{ fontSize: 11, color: 'var(--text-muted)', margin: '10px 0 0', lineHeight: 1.5 }}>
                  Raw feature values fed to the model for this season.
                </p>
              </>
            ) : (
              <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: 0 }}>
                Feature data not available for this player-season.
              </p>
            )}
          </Card>

          {/* Model metadata */}
          <Card eyebrow="Model info" icon={<BarChart3 size={15} />}>
            <StatRow label="Model version" value={val.model_version ?? '—'} />
            <StatRow label="Season" value={val.season} />
            <StatRow label="Value" value={`${fmtPct(val.value_pct)} of cap`} />
            <StatRow label="80% interval" value={`${fmtPct(val.lo_pct)} – ${fmtPct(val.hi_pct)}`} />
            {val.gap_pct != null && (
              <StatRow
                label="Gap to pay"
                value={`${signed(val.gap_pct)}%`}
              />
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
