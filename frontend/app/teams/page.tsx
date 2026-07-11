'use client';

import { useEffect, useMemo, useState, Suspense, type CSSProperties } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { Shield, SlidersHorizontal, Users, TriangleAlert } from 'lucide-react';
import {
  getTeams,
  getTeamCapSheet,
  TeamListItem,
  TeamCapSheetResponse,
  TeamCapSheetPlayer,
} from '@/lib/api';
import { Panel } from '@/components/ui/Panel';
import { Badge } from '@/components/ui/Badge';
import { Alert } from '@/components/ui/Alert';
import { Select } from '@/components/ui/Select';
import { DecisionStrip } from '@/components/ui/DecisionStrip';
import { LoadingNote } from '@/components/ui/LoadingNote';
import { Avatar } from '@/components/ui/Avatar';
import { TeamLogo } from '@/components/ui/TeamLogo';
import { AssumptionFlag } from '@/components/ui/AssumptionFlag';
import { MiniValuePayGauge } from '@/components/players/MiniValuePayGauge';
import { CapBar, CAP_TIER_LABEL, capTierBadgeTone, CapTierKey } from '@/components/cap/CapBar';
import { fmtM, fmtPct, roundedDomainMax, signed } from '@/lib/utils';
import { teamVisual } from '@/lib/teamVisuals';

type RosterSort = 'cap' | 'gap' | 'value' | 'name';
const SORTS: Array<{ value: RosterSort; label: string }> = [
  { value: 'cap', label: 'Cap hit' },
  { value: 'gap', label: 'Value gap' },
  { value: 'value', label: 'Model value' },
  { value: 'name', label: 'Name (A–Z)' },
];

function gapColor(gap: number | null): string {
  if (gap == null) return 'var(--text-muted)';
  if (gap >= 1) return 'var(--positive-text)';
  if (gap <= -1) return 'var(--negative-text)';
  return 'var(--text-secondary)';
}

function RoomLine({ label, room }: { label: string; room: number | null }) {
  if (room == null) return null;
  const over = room < 0;
  return (
    <span className="siq-teams-room-line">
      <span className="ds-eyebrow siq-teams-room-label">{label}</span>
      <span className="ds-tnum siq-teams-room-value" style={{ color: over ? 'var(--negative-text)' : 'var(--positive-text)' }}>
        {over ? `−${fmtM(Math.abs(room))} over` : `${fmtM(room)} under`}
      </span>
    </span>
  );
}

function RosterRow({ player, gaugeDomainMaxPct }: { player: TeamCapSheetPlayer; gaugeDomainMaxPct: number }) {
  const team = player.current_team ?? player.latest_stats_team;
  return (
    <div className="siq-roster-ledger-row">
      <Link href={`/players/${player.player_id}`} className="siq-plain-link siq-min0">
        <div className="siq-row siq-row--10 siq-min0">
          <Avatar name={player.full_name} size="md" position={player.position} playerId={player.player_id} />
          <div className="siq-min0">
            <div className="siq-teams-player-name">
              {player.full_name}
            </div>
            <div className="ds-note">
              {player.position ?? '—'}{player.age != null ? ` · age ${player.age}` : ''}{team?.abbreviation ? ` · ${team.abbreviation}` : ''}
            </div>
          </div>
        </div>
      </Link>

      <div className="ds-right">
        <div className="ds-tnum siq-teams-cap-value">
          {player.cap_hit_usd != null ? fmtM(player.cap_hit_usd) : '—'}
        </div>
        <div className="ds-tnum ds-note">
          {player.salary_pct != null ? `${fmtPct(player.salary_pct)} cap` : (player.pay_source == null ? 'no cap data' : '—')}
        </div>
      </div>

      <div className="siq-roster-gauge-cell">
        {player.valuation_status === 'ready' ? (
          <MiniValuePayGauge
            valuePct={player.value_pct}
            payPct={player.salary_pct}
            showLabels
            domainMaxPct={gaugeDomainMaxPct}
          />
        ) : (
          <span className="ds-note">No model value</span>
        )}
      </div>

      <div className="ds-tnum ds-right siq-teams-gap-value" style={{ color: gapColor(player.gap_pct) }}>
        {player.gap_pct != null ? `${signed(player.gap_pct)}%` : '—'}
      </div>
    </div>
  );
}

function WarRoom({ sheet }: { sheet: TeamCapSheetResponse }) {
  const [sort, setSort] = useState<RosterSort>('cap');
  const ctx = sheet.cap_context;
  const totals = sheet.totals;
  const tier = ctx.tier as CapTierKey;
  const visual = teamVisual(sheet.team.abbreviation);

  const players = useMemo(() => {
    const rows = [...sheet.players];
    rows.sort((a, b) => {
      if (sort === 'name') return a.full_name.localeCompare(b.full_name);
      if (sort === 'gap') return (b.gap_pct ?? -Infinity) - (a.gap_pct ?? -Infinity);
      if (sort === 'value') return (b.value_pct ?? -Infinity) - (a.value_pct ?? -Infinity);
      return (b.cap_hit_usd ?? -Infinity) - (a.cap_hit_usd ?? -Infinity);
    });
    return rows;
  }, [sheet.players, sort]);

  const gaugeDomainMaxPct = useMemo(() => {
    return roundedDomainMax(sheet.players.flatMap((player) => [player.value_pct, player.salary_pct]));
  }, [sheet.players]);

  const thresholdsReady = ctx.tax_line != null && ctx.first_apron != null && ctx.second_apron != null;
  const surplusPositive = totals.surplus_usd >= 0;
  const primaryMismatch = sheet.top_overpay ?? sheet.top_bargain;

  return (
    <div
      className="siq-stack"
      style={{
        '--team-primary': visual.primary,
        '--team-secondary': visual.secondary,
        '--team-wash': visual.wash,
      } as CSSProperties}
    >
      {/* Payroll hero */}
      <Panel variant="instrument" teamAccent eyebrow="Team payroll vs cap" icon={<Shield size={15} />}
        action={
          <div className="siq-row">
            <Link href={`/offseason?team=${sheet.team.team_id}`} className="siq-plain-link">
              <Badge tone="accent" size="sm">Build plan →</Badge>
            </Link>
            <Link href={`/free-agency?tab=targets&team=${sheet.team.team_id}`} className="siq-plain-link">
              <Badge tone="neutral" variant="outline" size="sm">FA targets →</Badge>
            </Link>
            <Badge tone="confidence" variant="outline" size="sm">{sheet.season}</Badge>
          </div>
        }>
        <div className="siq-teams-hero-head">
          <div className="siq-row siq-row--12 siq-min0">
            <TeamLogo
              teamId={sheet.team.team_id}
              abbreviation={sheet.team.abbreviation}
              name={sheet.team.name}
              size="lg"
            />
            <div className="siq-row siq-row--12 siq-teams-row-wrap-fit">
              <h1 className="siq-teams-title">
                {sheet.team.name ?? sheet.team.abbreviation ?? 'Team'}
              </h1>
              <Badge tone={capTierBadgeTone(tier)} size="md">{CAP_TIER_LABEL[tier]}</Badge>
            </div>
          </div>
          <div className="ds-right">
            <div className="ds-tnum siq-teams-payroll-value">
              {fmtM(totals.total_payroll_usd)}
            </div>
            <div className="ds-tnum ds-note siq-teams-mt3">
              {totals.payroll_pct != null ? `${fmtPct(totals.payroll_pct)} of cap` : '—'}
            </div>
          </div>
        </div>

        {thresholdsReady ? (
          <>
            <CapBar
              value={totals.total_payroll_usd}
              taxLine={ctx.tax_line!}
              firstApron={ctx.first_apron!}
              secondApron={ctx.second_apron!}
              height={16}
              showLabels
              valueLabel="Payroll"
            />
            <div className="siq-teams-room-lines">
              <RoomLine label="To tax" room={ctx.room_to_tax} />
              <RoomLine label="To 1st apron" room={ctx.room_to_first_apron} />
              <RoomLine label="To 2nd apron" room={ctx.room_to_second_apron} />
            </div>
          </>
        ) : (
          <p className="ds-note ds-note--13 ds-m0">
            Cap thresholds unavailable for {sheet.season}.
          </p>
        )}
      </Panel>

      <DecisionStrip
        ariaLabel={`${sheet.team.name ?? sheet.team.abbreviation} decision status`}
        lead={{
          label: sheet.top_overpay ? 'Priority contract review' : 'Strongest value position',
          value: primaryMismatch?.full_name ?? 'No priced mismatch',
          detail: primaryMismatch?.gap_pct != null ? `${signed(primaryMismatch.gap_pct)}% of cap versus pay` : `${totals.valued_player_count} players valued`,
          tone: sheet.top_overpay ? 'negative' : sheet.top_bargain ? 'positive' : 'neutral',
        }}
        items={[
          {
            label: 'Cap constraint',
            value: CAP_TIER_LABEL[tier],
            detail: ctx.room_to_first_apron != null ? `${ctx.room_to_first_apron >= 0 ? fmtM(ctx.room_to_first_apron) + ' below' : fmtM(Math.abs(ctx.room_to_first_apron)) + ' over'} first apron` : 'Threshold unavailable',
            tone: tier === 'second-apron' || tier === 'first-apron' ? 'warning' : 'neutral',
          },
          {
            label: 'Roster value gap',
            value: `${surplusPositive ? '+' : '−'}${fmtM(Math.abs(totals.surplus_usd))}`,
            detail: totals.surplus_pct != null ? `${signed(totals.surplus_pct)}% of cap · model value minus payroll` : 'Model value minus payroll',
            tone: surplusPositive ? 'positive' : 'negative',
          },
          {
            label: 'Coverage',
            value: `${totals.valued_player_count}/${totals.roster_size} valued`,
            detail: `${totals.bargain_count} bargains · ${totals.overpay_count} overpays`,
            tone: totals.valued_player_count === totals.roster_size ? 'confidence' : 'warning',
          },
        ]}
      />

      {/* Roster board */}
      <Panel variant="card"
        className="siq-roster-ledger"
        eyebrow={`Roster · ${totals.roster_size} players`}
        icon={<Users size={15} />}
        action={
          <Select
            selectSize="sm"
            value={sort}
            onChange={(e) => setSort(e.target.value as RosterSort)}
            aria-label="Sort roster"
          >
            {SORTS.map((s) => <option key={s.value} value={s.value}>Sort: {s.label}</option>)}
          </Select>
        }
      >
        {sheet.top_bargain && sheet.top_overpay && (
          <div className="siq-teams-badge-row">
            <Badge tone="positive" variant="outline" size="sm">
              Top bargain: {sheet.top_bargain.full_name} {sheet.top_bargain.gap_pct != null ? signed(sheet.top_bargain.gap_pct) + '%' : ''}
            </Badge>
            <Badge tone="negative" variant="outline" size="sm">
              Top overpay: {sheet.top_overpay.full_name} {sheet.top_overpay.gap_pct != null ? signed(sheet.top_overpay.gap_pct) + '%' : ''}
            </Badge>
          </div>
        )}
        <div className="siq-roster-ledger-head">
          <span className="ds-eyebrow">Player</span>
          <span className="ds-eyebrow ds-right">Cap hit</span>
          <span className="ds-eyebrow">Value vs pay</span>
          <span className="ds-eyebrow ds-right">Gap</span>
        </div>
        {players.map((p) => <RosterRow key={p.player_id} player={p} gaugeDomainMaxPct={gaugeDomainMaxPct} />)}
      </Panel>

      <AssumptionFlag tone="warning" title="Simplified roster cap model" icon={<TriangleAlert size={16} />}>
        {sheet.caveat}
      </AssumptionFlag>
    </div>
  );
}

function TeamsContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const teamParam = searchParams.get('team');

  const [teams, setTeams] = useState<TeamListItem[]>([]);
  const [sheet, setSheet] = useState<TeamCapSheetResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedId = teamParam ? Number(teamParam) : null;
  const effectiveSelectedId = selectedId ?? teams[0]?.team_id ?? null;

  useEffect(() => {
    getTeams().then(setTeams).catch(() => {});
  }, []);

  // Default to the first team once the list loads if none is selected.
  useEffect(() => {
    if (selectedId == null && teams.length > 0) {
      router.replace(`/teams?team=${teams[0].team_id}`);
    }
  }, [selectedId, teams, router]);

  useEffect(() => {
    if (effectiveSelectedId == null) return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    getTeamCapSheet(effectiveSelectedId, undefined, controller.signal)
      .then((res) => { setSheet(res); setLoading(false); })
      .catch((e: unknown) => {
        if (e instanceof DOMException && e.name === 'AbortError') return;
        setError(e instanceof Error ? e.message : 'Failed to load cap sheet.');
        setSheet(null);
        setLoading(false);
      });
    return () => controller.abort();
  }, [effectiveSelectedId]);

  return (
    <div className="siq-stack">
      <div className="siq-row siq-row--12 siq-teams-row-wrap">
        <span className="ds-eyebrow">Team war room</span>
        <Select
          value={effectiveSelectedId ?? ''}
          onChange={(e) => router.replace(`/teams?team=${e.target.value}`)}
          aria-label="Select team"
          className="siq-teams-select-wide"
        >
          {teams.length === 0 && <option value="">Loading teams…</option>}
          {teams.map((t) => <option key={t.team_id} value={t.team_id}>{t.name ?? t.abbreviation}</option>)}
        </Select>
      </div>

      {error && (
        <Alert tone="negative">
          {error} — is the FastAPI server running at localhost:8000?
        </Alert>
      )}
      {loading && !sheet && <LoadingNote>Loading cap sheet…</LoadingNote>}
      {sheet && <WarRoom sheet={sheet} />}
    </div>
  );
}

export default function TeamsPage() {
  return (
    <Suspense fallback={<LoadingNote>Loading…</LoadingNote>}>
      <TeamsContent />
    </Suspense>
  );
}
