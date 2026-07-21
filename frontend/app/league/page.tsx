'use client';

import { useMemo, useState } from 'react';
import { Globe, TriangleAlert } from 'lucide-react';
import { getLeagueCapLandscape, LeagueCapResponse, LeagueTeamRow, CapTier } from '@/lib/api';
import { Panel } from '@/components/ui/Panel';
import { Badge } from '@/components/ui/Badge';
import { Alert } from '@/components/ui/Alert';
import { DecisionStrip } from '@/components/ui/DecisionStrip';
import { LoadingNote } from '@/components/ui/LoadingNote';
import { AssumptionFlag } from '@/components/ui/AssumptionFlag';
import { CAP_TIER_LABEL, tierTone } from '@/lib/present';
import { fmtM, fmtPct } from '@/lib/utils';
import { useApi } from '@/lib/useApi';

type SortKey = 'payroll' | 'room_to_first_apron' | 'surplus' | 'expiring';
type SortDir = 'asc' | 'desc';

const COLUMNS: Array<{ key: SortKey; label: string }> = [
  { key: 'payroll', label: 'Payroll' },
  { key: 'room_to_first_apron', label: 'Room to 1st apron' },
  { key: 'surplus', label: 'Surplus' },
  { key: 'expiring', label: 'Expiring' },
];

function sortValue(row: LeagueTeamRow, key: SortKey): number {
  if (key === 'payroll') return row.total_payroll_usd;
  if (key === 'room_to_first_apron') return row.room_to_first_apron_usd ?? -Infinity;
  if (key === 'surplus') return row.surplus_usd;
  return row.expiring_usd;
}

function SignedMoney({ value }: { value: number | null }) {
  if (value == null) return <span className="ds-note">—</span>;
  const negative = value < 0;
  return (
    <span
      className="ds-tnum"
      style={{ color: negative ? 'var(--negative-text)' : 'var(--positive-text)' }}
    >
      {value < 0 ? `−${fmtM(Math.abs(value))}` : `+${fmtM(value)}`}
    </span>
  );
}

function LeagueTable({ teams }: { teams: LeagueTeamRow[] }) {
  const [sortKey, setSortKey] = useState<SortKey>('payroll');
  const [sortDir, setSortDir] = useState<SortDir>('desc');

  const sorted = useMemo(() => {
    const rows = [...teams];
    rows.sort((a, b) => {
      const diff = sortValue(a, sortKey) - sortValue(b, sortKey);
      return sortDir === 'asc' ? diff : -diff;
    });
    return rows;
  }, [teams, sortKey, sortDir]);

  const onSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
  };

  const ariaSort = (key: SortKey): 'ascending' | 'descending' | 'none' => {
    if (key !== sortKey) return 'none';
    return sortDir === 'asc' ? 'ascending' : 'descending';
  };

  return (
    <div className="siq-league-table-wrap">
      <table className="siq-league-table">
        <thead>
          <tr>
            <th scope="col">Team</th>
            <th scope="col">Tier</th>
            {COLUMNS.map((col) => (
              <th scope="col" key={col.key} aria-sort={ariaSort(col.key)}>
                <button type="button" className="siq-league-sort-btn" onClick={() => onSort(col.key)}>
                  {col.label}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => (
            <tr key={row.team.team_id}>
              <td>{row.team.name ?? row.team.abbreviation ?? '—'}</td>
              <td>
                <Badge tone={tierTone(row.tier)} size="sm">{CAP_TIER_LABEL[row.tier]}</Badge>
              </td>
              <td className="ds-tnum">
                {fmtM(row.total_payroll_usd)}
                <span className="ds-note"> {row.payroll_pct != null ? `· ${fmtPct(row.payroll_pct)}` : ''}</span>
              </td>
              <td><SignedMoney value={row.room_to_first_apron_usd} /></td>
              <td><SignedMoney value={row.surplus_usd} /></td>
              <td className="ds-tnum">{fmtM(row.expiring_usd)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LeagueContent({ data }: { data: LeagueCapResponse }) {
  const ctx = data.context;
  const tiers = Object.keys(data.tier_counts) as CapTier[];

  return (
    <div className="siq-stack">
      <Panel
        variant="instrument"
        eyebrow={`League cap landscape · ${ctx.season}`}
        icon={<Globe size={15} />}
      >
        <p className="ds-note ds-note--13 ds-m0">
          Cap {ctx.salary_cap != null ? fmtM(ctx.salary_cap) : '—'} · Tax {ctx.tax_line != null ? fmtM(ctx.tax_line) : '—'} ·
          {' '}1st apron {ctx.first_apron != null ? fmtM(ctx.first_apron) : '—'} · 2nd apron {ctx.second_apron != null ? fmtM(ctx.second_apron) : '—'}
        </p>
      </Panel>

      <DecisionStrip
        ariaLabel="League cap distribution"
        lead={{
          label: 'Teams with cap room',
          value: data.teams_with_cap_room,
          detail: `of ${data.team_count} teams`,
          tone: data.teams_with_cap_room > 0 ? 'positive' : 'neutral',
        }}
        items={[
          ...tiers.map((tier) => ({
            label: CAP_TIER_LABEL[tier],
            value: data.tier_counts[tier],
            tone: tierTone(tier) as 'positive' | 'negative' | 'neutral' | 'warning',
          })),
          {
            label: 'League expiring',
            value: fmtM(data.league_expiring_usd),
            detail: 'money with no contract next season',
            tone: 'neutral',
          },
        ]}
      />

      <Panel variant="card" eyebrow={`Teams · ${data.team_count}`}>
        <LeagueTable teams={data.teams} />
      </Panel>

      <AssumptionFlag tone="warning" title="Simplified league cap model" icon={<TriangleAlert size={16} />}>
        {data.caveat}
      </AssumptionFlag>
    </div>
  );
}

export default function LeaguePage() {
  const { data, loading, error } = useApi<LeagueCapResponse>(
    (signal) => getLeagueCapLandscape(undefined, signal),
    [],
    { fallback: 'Failed to load league cap landscape.' },
  );

  return (
    <>
      {error && (
        <Alert tone="negative">
          {error} — is the FastAPI server running at localhost:8000?
        </Alert>
      )}
      {loading && !data && <LoadingNote>Loading league cap landscape…</LoadingNote>}
      {data && <LeagueContent data={data} />}
    </>
  );
}
