import { Fragment, type ReactNode } from 'react';
import { PlayerContractYear } from '@/lib/api';
import { PlayerComparisonData } from '@/lib/playerComparisonApi';
import { VerdictPill } from '@/components/ui/VerdictPill';
import { Badge } from '@/components/ui/Badge';
import { Alert } from '@/components/ui/Alert';
import { fmtM, fmtPct, signed } from '@/lib/utils';

const DASH = '—';

function pct(value: number | null | undefined, decimals = 1): string {
  return value != null ? fmtPct(value, decimals) : DASH;
}

function usd(value: number | null | undefined): string {
  return value != null ? fmtM(value) : DASH;
}

function signedPct(value: number | null | undefined, decimals = 1): string {
  return value != null ? `${signed(value, decimals)}%` : DASH;
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

function playerIdentityCells(data: PlayerComparisonData) {
  const val = data.valuation;
  const age = val?.features?.age;
  return {
    team: val?.current_team?.name ?? val?.current_team?.abbreviation ?? DASH,
    position: val?.position ?? DASH,
    age: age != null ? age.toFixed(0) : DASH,
    season: val?.season ?? DASH,
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
  if (!val) return DASH;
  return <VerdictPill gapPct={val.gap_pct} label={val.verdict_label} tone={val.verdict_tone} size="sm" />;
}

function cautionFlagsCell(data: PlayerComparisonData): ReactNode {
  const val = data.valuation;
  if (!val) return DASH;
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
    { label: 'Caveat', a: <span className="ds-note">{a.valuation?.caveat ?? DASH}</span>, b: <span className="ds-note">{b.valuation?.caveat ?? DASH}</span> },
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
  if (years.length === 0) return DASH;
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

function paySection(a: PlayerComparisonData, b: PlayerComparisonData): Row[] {
  const missingA = !a.contract && a.contractError;
  const missingB = !b.contract && b.contractError;
  // Either slot's valuation season identifies "now"; they are the same season
  // unless the mismatch notice is showing, and null only if both valuations failed.
  const currentSeason = a.valuation?.season ?? b.valuation?.season ?? null;
  return [
    {
      label: 'Current cap hit',
      a: <Cell primary={pct(a.valuation?.actual_pct)} secondary={usd(a.valuation?.actual_usd)} />,
      b: <Cell primary={pct(b.valuation?.actual_pct)} secondary={usd(b.valuation?.actual_usd)} />,
    },
    {
      label: 'Future contract years',
      a: missingA ? <span className="ds-note">Not available — {a.contractError}</span> : futureYearsCell(a, currentSeason),
      b: missingB ? <span className="ds-note">Not available — {b.contractError}</span> : futureYearsCell(b, currentSeason),
    },
  ];
}

function marketBandCell(data: PlayerComparisonData): ReactNode {
  const comp = data.compSynthesis;
  if (!comp) return <span className="ds-note">{data.marketError ? `Not available — ${data.marketError}` : 'No comp synthesis available.'}</span>;
  return <span className="ds-tnum">{pct(comp.market_low_pct)}–{pct(comp.market_high_pct)}</span>;
}

function marketSection(a: PlayerComparisonData, b: PlayerComparisonData): Row[] {
  return [
    { label: 'Comp market band', a: marketBandCell(a), b: marketBandCell(b) },
    {
      label: 'Suggested target',
      a: a.compSynthesis ? <Cell primary={pct(a.compSynthesis.suggested_pct)} secondary={usd(a.compSynthesis.suggested_usd)} /> : DASH,
      b: b.compSynthesis ? <Cell primary={pct(b.compSynthesis.suggested_pct)} secondary={usd(b.compSynthesis.suggested_usd)} /> : DASH,
    },
    {
      label: 'Comps used',
      a: <span className="ds-tnum">{a.compSynthesis ? a.compSynthesis.n_comps : DASH}</span>,
      b: <span className="ds-tnum">{b.compSynthesis ? b.compSynthesis.n_comps : DASH}</span>,
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
  return <span className="ds-tnum">{value != null ? fmt(value) : DASH}</span>;
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
  const seasonA = a.valuation?.season ?? null;
  const seasonB = b.valuation?.season ?? null;
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
          {nameA}&apos;s valuation is for {seasonA}, while {nameB}&apos;s is for {seasonB}. These rows are not season-aligned — compare with caution.
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
