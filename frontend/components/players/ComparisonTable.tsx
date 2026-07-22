import { Fragment, type ReactNode } from 'react';
import { PlayerContractYear } from '@/lib/api';
import { PlayerComparisonData } from '@/lib/playerComparisonApi';
import { VerdictPill } from '@/components/ui/VerdictPill';
import { Badge } from '@/components/ui/Badge';
import { Alert } from '@/components/ui/Alert';
import { fmtM, fmtPct, signed } from '@/lib/utils';

/** Missing values are labelled in place rather than shown as a bare dash, so an
 *  absent field is never mistaken for a rendered value. */
const NA_TEXT = 'Not available';
const NA = <span className="ds-note siq-compare-na">{NA_TEXT}</span>;

function pct(value: number | null | undefined, decimals = 1): ReactNode {
  return value != null ? fmtPct(value, decimals) : NA;
}

function usd(value: number | null | undefined): ReactNode {
  return value != null ? fmtM(value) : undefined;
}

function signedPct(value: number | null | undefined, decimals = 1): ReactNode {
  return value != null ? `${signed(value, decimals)}%` : NA;
}

function Cell({ primary, secondary }: { primary: ReactNode; secondary?: ReactNode }) {
  return (
    <div className="siq-compare-cell">
      <div className="ds-tnum siq-compare-cell__primary">{primary}</div>
      {secondary != null && <div className="ds-tnum ds-note siq-compare-cell__secondary">{secondary}</div>}
    </div>
  );
}

function contractYearLabel(year: PlayerContractYear): string | null {
  if (year.is_player_option) return 'Player opt.';
  if (year.is_team_option) return 'Team opt.';
  if (!year.is_guaranteed) return 'Non-gtd';
  return null;
}

interface Row {
  label: string;
  a: ReactNode;
  b: ReactNode;
}

// Identity falls back to the standalone player summary so team/position/season
// survive a valuation failure — the contract and roster facts stay useful when
// the model is unavailable (ADR-0001). Age only exists in model features, so it
// is the one identity field that legitimately degrades.
function playerIdentityCells(data: PlayerComparisonData) {
  const val = data.valuation;
  const sum = data.summary;
  const age = val?.features?.age;
  const team =
    val?.current_team?.name ??
    sum?.current_team?.name ??
    sum?.latest_stats_team?.name ??
    val?.current_team?.abbreviation ??
    sum?.current_team?.abbreviation ??
    null;
  return {
    team: team ?? NA,
    position: val?.position ?? sum?.position ?? NA,
    age: age != null ? age.toFixed(0) : NA,
    season: val?.season ?? sum?.latest_season ?? NA,
  };
}

function identitySection(a: PlayerComparisonData, b: PlayerComparisonData): Row[] {
  const ia = playerIdentityCells(a);
  const ib = playerIdentityCells(b);
  return [
    { label: 'Team', a: ia.team, b: ib.team },
    { label: 'Position', a: ia.position, b: ib.position },
    { label: 'Age', a: <span className="ds-tnum">{ia.age}</span>, b: <span className="ds-tnum">{ib.age}</span> },
    { label: 'Season', a: <span className="ds-tnum">{ia.season}</span>, b: <span className="ds-tnum">{ib.season}</span> },
  ];
}

function valuationCell(data: PlayerComparisonData): ReactNode {
  const val = data.valuation;
  return (
    <Cell
      primary={pct(val?.value_pct)}
      secondary={val?.lo_pct != null && val?.hi_pct != null ? `80% range ${pct(val.lo_pct)}–${pct(val.hi_pct)}` : undefined}
    />
  );
}

function verdictCell(data: PlayerComparisonData): ReactNode {
  const val = data.valuation;
  if (!val) return NA;
  return <VerdictPill gapPct={val.gap_pct} label={val.verdict_label} tone={val.verdict_tone} size="sm" />;
}

function cautionFlagsCell(data: PlayerComparisonData): ReactNode {
  const val = data.valuation;
  if (!val) return NA;
  if (val.caution_flags.length === 0) return 'None';
  return (
    <div className="siq-compact-tags">
      {val.caution_flags.map((flag) => <Badge key={flag} tone="warning" variant="outline" size="sm">{flag}</Badge>)}
    </div>
  );
}

function valuationSection(a: PlayerComparisonData, b: PlayerComparisonData): Row[] {
  const missingA = !a.valuation && a.valuationError;
  const missingB = !b.valuation && b.valuationError;
  return [
    {
      label: 'Model value',
      a: missingA ? <span className="ds-note">Not available — {a.valuationError}</span> : valuationCell(a),
      b: missingB ? <span className="ds-note">Not available — {b.valuationError}</span> : valuationCell(b),
    },
    { label: 'Verdict', a: verdictCell(a), b: verdictCell(b) },
    { label: 'Value gap', a: <span className="ds-tnum">{signedPct(a.valuation?.gap_pct)}</span>, b: <span className="ds-tnum">{signedPct(b.valuation?.gap_pct)}</span> },
    { label: 'Caution flags', a: cautionFlagsCell(a), b: cautionFlagsCell(b) },
    { label: 'Caveat', a: <span className="ds-note">{a.valuation?.caveat ?? NA_TEXT}</span>, b: <span className="ds-note">{b.valuation?.caveat ?? NA_TEXT}</span> },
  ];
}

// Only seasons from the current one onward — years_detail also carries elapsed
// seasons of an in-progress contract, which the "Future contract years" label
// must not present as upcoming. Season labels are "YYYY-YY" so they sort
// lexicographically. Without a known current season we cannot filter, so we
// fall back to showing the full detail rather than guessing.
function futureYearsCell(data: PlayerComparisonData, currentSeason: string | null): ReactNode {
  const all = data.contract?.years_detail ?? [];
  const years = currentSeason ? all.filter((y) => y.season >= currentSeason) : all;
  if (years.length === 0) return NA;
  return (
    <div className="siq-compare-years">
      {years.map((year) => {
        const label = contractYearLabel(year);
        return (
          <div key={year.season} className="siq-compare-year-row">
            <span className="ds-tnum siq-compare-year-season">{year.season}</span>
            <Cell primary={pct(year.cap_hit_pct)} secondary={usd(year.cap_hit_usd)} />
            {label && (
              <Badge tone={year.is_player_option || year.is_team_option ? 'warning' : 'neutral'} variant="outline" size="sm">
                {label}
              </Badge>
            )}
          </div>
        );
      })}
    </div>
  );
}

/** The season a player's own rows are anchored to. Never borrow the other slot's
 *  season — the two can differ, and using one for both mislabels the other's
 *  contract ledger and cap hit. */
function effectiveSeason(data: PlayerComparisonData): string | null {
  return data.valuation?.season ?? data.summary?.latest_season ?? null;
}

// Pay is a contract fact, not a model output: when the valuation is unavailable
// fall back to the current season's contract year so the cap hit still renders.
function currentCapHitCell(data: PlayerComparisonData): ReactNode {
  const val = data.valuation;
  if (val?.actual_pct != null || val?.actual_usd != null) {
    return <Cell primary={pct(val.actual_pct)} secondary={usd(val.actual_usd)} />;
  }
  const season = effectiveSeason(data);
  const year = data.contract?.years_detail?.find((y) => y.season === season);
  if (year && (year.cap_hit_pct != null || year.cap_hit_usd != null)) {
    return <Cell primary={pct(year.cap_hit_pct)} secondary={usd(year.cap_hit_usd)} />;
  }
  return NA;
}

function paySection(a: PlayerComparisonData, b: PlayerComparisonData): Row[] {
  const missingA = !a.contract && a.contractError;
  const missingB = !b.contract && b.contractError;
  // Each player is anchored to their own season — see effectiveSeason.
  return [
    {
      label: 'Current cap hit',
      a: currentCapHitCell(a),
      b: currentCapHitCell(b),
    },
    {
      label: 'Future contract years',
      a: missingA ? <span className="ds-note">Not available — {a.contractError}</span> : futureYearsCell(a, effectiveSeason(a)),
      b: missingB ? <span className="ds-note">Not available — {b.contractError}</span> : futureYearsCell(b, effectiveSeason(b)),
    },
  ];
}

function marketBandCell(data: PlayerComparisonData): ReactNode {
  const comp = data.compSynthesis;
  if (!comp) return <span className="ds-note">{data.marketError ? `${NA_TEXT} — ${data.marketError}` : 'No comp synthesis available.'}</span>;
  // Percent of cap leads; the dollar range is the secondary display value.
  const usdRange =
    comp.market_low_usd != null && comp.market_high_usd != null
      ? `${fmtM(comp.market_low_usd)}–${fmtM(comp.market_high_usd)}`
      : undefined;
  return (
    <Cell primary={<>{pct(comp.market_low_pct)}–{pct(comp.market_high_pct)}</>} secondary={usdRange} />
  );
}

function marketSection(a: PlayerComparisonData, b: PlayerComparisonData): Row[] {
  return [
    { label: 'Comp market band', a: marketBandCell(a), b: marketBandCell(b) },
    {
      label: 'Suggested target',
      a: a.compSynthesis ? <Cell primary={pct(a.compSynthesis.suggested_pct)} secondary={usd(a.compSynthesis.suggested_usd)} /> : NA,
      b: b.compSynthesis ? <Cell primary={pct(b.compSynthesis.suggested_pct)} secondary={usd(b.compSynthesis.suggested_usd)} /> : NA,
    },
    {
      label: 'Comps used',
      a: <span className="ds-tnum">{a.compSynthesis ? a.compSynthesis.n_comps : NA}</span>,
      b: <span className="ds-tnum">{b.compSynthesis ? b.compSynthesis.n_comps : NA}</span>,
    },
  ];
}

const PRODUCTION_METRICS: Array<{ label: string; compute: (f: Record<string, number>) => number | null; fmt: (v: number) => string }> = [
  { label: 'GP', compute: (f) => f.gp ?? null, fmt: (v) => v.toFixed(0) },
  { label: 'MPG', compute: (f) => (f.minutes != null && f.gp ? f.minutes / f.gp : null), fmt: (v) => v.toFixed(1) },
  { label: 'PTS', compute: (f) => f.pts_pg ?? null, fmt: (v) => v.toFixed(1) },
  { label: 'REB', compute: (f) => f.reb_pg ?? null, fmt: (v) => v.toFixed(1) },
  { label: 'AST', compute: (f) => f.ast_pg ?? null, fmt: (v) => v.toFixed(1) },
  { label: 'TS%', compute: (f) => (f.TS_PCT != null ? f.TS_PCT * 100 : null), fmt: (v) => v.toFixed(1) },
  { label: 'BPM', compute: (f) => f.BPM ?? null, fmt: (v) => signed(v, 1) },
  { label: 'NET', compute: (f) => f.NET_RATING ?? null, fmt: (v) => signed(v, 1) },
];

function productionCell(data: PlayerComparisonData, compute: (f: Record<string, number>) => number | null, fmt: (v: number) => string): ReactNode {
  const features = data.valuation?.features;
  const value = features ? compute(features) : null;
  return <span className="ds-tnum">{value != null ? fmt(value) : NA}</span>;
}

function productionSection(a: PlayerComparisonData, b: PlayerComparisonData): Row[] {
  return PRODUCTION_METRICS.map(({ label, compute, fmt }) => ({
    label,
    a: productionCell(a, compute, fmt),
    b: productionCell(b, compute, fmt),
  }));
}

interface ComparisonTableProps {
  a: PlayerComparisonData;
  b: PlayerComparisonData;
  nameA: string;
  nameB: string;
}

export function ComparisonTable({ a, b, nameA, nameB }: ComparisonTableProps) {
  // Compare the seasons each player's rows are actually anchored to, not just
  // valuation seasons — a slot falling back to its summary season can still be
  // misaligned with the other, and that must be surfaced.
  const seasonA = effectiveSeason(a);
  const seasonB = effectiveSeason(b);
  const seasonMismatch = seasonA != null && seasonB != null && seasonA !== seasonB;

  const sections: Array<{ title: string; rows: Row[] }> = [
    { title: 'Identity', rows: identitySection(a, b) },
    { title: 'Valuation', rows: valuationSection(a, b) },
    { title: 'Pay', rows: paySection(a, b) },
    { title: 'Market', rows: marketSection(a, b) },
    { title: 'Production', rows: productionSection(a, b) },
  ];

  return (
    <div className="siq-compare-table-wrap">
      {seasonMismatch && (
        <Alert tone="warning">
          {nameA}&apos;s rows are anchored to {seasonA}, while {nameB}&apos;s are anchored to {seasonB}. These rows are not season-aligned — compare with caution.
        </Alert>
      )}
      <div className="siq-compare-scroll">
        <table className="siq-compare-table">
          <thead>
            <tr>
              <th scope="col" className="siq-compare-rowlabel" />
              <th scope="col">{nameA}</th>
              <th scope="col">{nameB}</th>
            </tr>
          </thead>
          <tbody>
            {sections.map((section) => (
              <Fragment key={section.title}>
                <tr className="siq-compare-section">
                  <th scope="colgroup" colSpan={3} className="ds-eyebrow siq-compare-section__label">{section.title}</th>
                </tr>
                {section.rows.map((row) => (
                  <tr key={`${section.title}-${row.label}`}>
                    <th scope="row" className="siq-compare-rowlabel">{row.label}</th>
                    <td>{row.a}</td>
                    <td>{row.b}</td>
                  </tr>
                ))}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
