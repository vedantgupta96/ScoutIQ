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
import { Card } from '@/components/ui/Card';
import { Surface } from '@/components/ui/Surface';
import { Badge } from '@/components/ui/Badge';
import { StatTile } from '@/components/ui/StatTile';
import { Avatar } from '@/components/ui/Avatar';
import { TeamLogo } from '@/components/ui/TeamLogo';
import { AssumptionFlag } from '@/components/ui/AssumptionFlag';
import { MiniValuePayGauge } from '@/components/players/MiniValuePayGauge';
import { CapBar, CAP_TIER_LABEL, capTierBadgeTone, CapTierKey } from '@/components/cap/CapBar';
import { fmtM, fmtPct, signed } from '@/lib/utils';
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
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12 }}>
      <span className="ds-eyebrow" style={{ letterSpacing: '0.06em' }}>{label}</span>
      <span className="ds-tnum" style={{ fontWeight: 700, color: over ? 'var(--negative-text)' : 'var(--positive-text)' }}>
        {over ? `−${fmtM(Math.abs(room))} over` : `${fmtM(room)} under`}
      </span>
    </span>
  );
}

function RosterRow({ player, gaugeDomainMaxPct }: { player: TeamCapSheetPlayer; gaugeDomainMaxPct: number }) {
  const team = player.current_team ?? player.latest_stats_team;
  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: 'minmax(0, 1.5fr) 120px minmax(120px, 1fr) 92px',
      gap: 12,
      alignItems: 'center',
      padding: '11px 0',
      borderBottom: '1px solid var(--border-subtle)',
    }}>
      <Link href={`/players/${player.player_id}`} style={{ textDecoration: 'none', minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
          <Avatar name={player.full_name} size="md" position={player.position} playerId={player.player_id} />
          <div style={{ minWidth: 0 }}>
            <div style={{
              fontSize: 14, fontWeight: 700, color: 'var(--text-primary)',
              whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
            }}>
              {player.full_name}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
              {player.position ?? '—'}{player.age != null ? ` · age ${player.age}` : ''}{team?.abbreviation ? ` · ${team.abbreviation}` : ''}
            </div>
          </div>
        </div>
      </Link>

      <div style={{ textAlign: 'right' }}>
        <div className="ds-tnum" style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)' }}>
          {player.cap_hit_usd != null ? fmtM(player.cap_hit_usd) : '—'}
        </div>
        <div className="ds-tnum" style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          {player.salary_pct != null ? `${fmtPct(player.salary_pct)} cap` : (player.pay_source == null ? 'no cap data' : '—')}
        </div>
      </div>

      <div>
        {player.valuation_status === 'ready' ? (
          <MiniValuePayGauge
            valuePct={player.value_pct}
            payPct={player.salary_pct}
            showLabels
            domainMaxPct={gaugeDomainMaxPct}
          />
        ) : (
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>No model value</span>
        )}
      </div>

      <div className="ds-tnum" style={{ textAlign: 'right', fontSize: 14, fontWeight: 700, color: gapColor(player.gap_pct) }}>
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
    const maxPct = sheet.players.reduce((max, player) => {
      return Math.max(max, player.value_pct ?? 0, player.salary_pct ?? 0);
    }, 0);
    return Math.max(10, Math.ceil((maxPct * 1.15) / 5) * 5);
  }, [sheet.players]);

  const thresholdsReady = ctx.tax_line != null && ctx.first_apron != null && ctx.second_apron != null;

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 'var(--panel-gap)',
        '--team-primary': visual.primary,
        '--team-secondary': visual.secondary,
        '--team-wash': visual.wash,
      } as CSSProperties}
    >
      {/* Payroll hero */}
      <Surface variant="instrument" teamAccent eyebrow="Team payroll vs cap" icon={<Shield size={15} />}
        action={<Badge tone="confidence" variant="outline" size="sm">{sheet.season}</Badge>}>
        <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', marginBottom: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 0 }}>
            <TeamLogo
              teamId={sheet.team.team_id}
              abbreviation={sheet.team.abbreviation}
              name={sheet.team.name}
              size="lg"
            />
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', minWidth: 0 }}>
              <h1 style={{ margin: 0, fontFamily: 'var(--font-display)', fontSize: 26, fontWeight: 700, color: 'var(--text-primary)' }}>
                {sheet.team.name ?? sheet.team.abbreviation ?? 'Team'}
              </h1>
              <Badge tone={capTierBadgeTone(tier)} size="md">{CAP_TIER_LABEL[tier]}</Badge>
            </div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div className="ds-tnum" style={{ fontSize: 28, fontWeight: 700, fontFamily: 'var(--font-display)', color: 'var(--text-primary)', lineHeight: 1 }}>
              {fmtM(totals.total_payroll_usd)}
            </div>
            <div className="ds-tnum" style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 3 }}>
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
            <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', marginTop: 14 }}>
              <RoomLine label="To tax" room={ctx.room_to_tax} />
              <RoomLine label="To 1st apron" room={ctx.room_to_first_apron} />
              <RoomLine label="To 2nd apron" room={ctx.room_to_second_apron} />
            </div>
          </>
        ) : (
          <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: 0 }}>
            Cap thresholds unavailable for {sheet.season}.
          </p>
        )}
      </Surface>

      {/* Summary tiles */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 'var(--panel-gap)' }}>
        <Card padded><StatTile label="Total payroll" value={fmtM(totals.total_payroll_usd)} unit={totals.payroll_pct != null ? `· ${fmtPct(totals.payroll_pct)}` : undefined} sub={`${totals.payroll_player_count} of ${totals.roster_size} on the books`} size="sm" /></Card>
        <Card padded><StatTile label="Model value" value={fmtM(totals.total_value_usd)} sub={`${totals.valued_player_count} valued`} size="sm" /></Card>
        <Card padded><StatTile label="Surplus value" value={`${totals.surplus_usd >= 0 ? '+' : '−'}${fmtM(Math.abs(totals.surplus_usd))}`} unit={totals.surplus_pct != null ? `· ${signed(totals.surplus_pct)}%` : undefined} delta={totals.surplus_usd >= 0 ? 'value over pay' : 'pay over value'} deltaDir={totals.surplus_usd >= 0 ? 'up' : 'down'} sub="model value − payroll" size="sm" /></Card>
        <Card padded><StatTile label="Bargains" value={totals.bargain_count} sub="value ≥ pay +1%" size="sm" /></Card>
        <Card padded><StatTile label="Overpays" value={totals.overpay_count} sub="pay ≥ value +1%" size="sm" /></Card>
      </div>

      {/* Roster board */}
      <Card
        eyebrow={`Roster · ${totals.roster_size} players`}
        icon={<Users size={15} />}
        action={
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value as RosterSort)}
            aria-label="Sort roster"
            style={{
              height: 32, borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)',
              background: 'var(--bg-panel)', color: 'var(--text-primary)', padding: '0 10px',
              fontFamily: 'var(--font-sans)', fontSize: 12, fontWeight: 600,
            }}
          >
            {SORTS.map((s) => <option key={s.value} value={s.value}>Sort: {s.label}</option>)}
          </select>
        }
      >
        {sheet.top_bargain && sheet.top_overpay && (
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 10 }}>
            <Badge tone="positive" variant="outline" size="sm">
              Top bargain: {sheet.top_bargain.full_name} {sheet.top_bargain.gap_pct != null ? signed(sheet.top_bargain.gap_pct) + '%' : ''}
            </Badge>
            <Badge tone="negative" variant="outline" size="sm">
              Top overpay: {sheet.top_overpay.full_name} {sheet.top_overpay.gap_pct != null ? signed(sheet.top_overpay.gap_pct) + '%' : ''}
            </Badge>
          </div>
        )}
        <div style={{
          display: 'grid', gridTemplateColumns: 'minmax(0, 1.5fr) 120px minmax(120px, 1fr) 92px',
          gap: 12, paddingBottom: 8, borderBottom: '1px solid var(--border-default)',
        }}>
          <span className="ds-eyebrow">Player</span>
          <span className="ds-eyebrow" style={{ textAlign: 'right' }}>Cap hit</span>
          <span className="ds-eyebrow">Value vs pay</span>
          <span className="ds-eyebrow" style={{ textAlign: 'right' }}>Gap</span>
        </div>
        {players.map((p) => <RosterRow key={p.player_id} player={p} gaugeDomainMaxPct={gaugeDomainMaxPct} />)}
      </Card>

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
    if (selectedId == null) return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    getTeamCapSheet(selectedId, undefined, controller.signal)
      .then((res) => { setSheet(res); setLoading(false); })
      .catch((e: unknown) => {
        if (e instanceof DOMException && e.name === 'AbortError') return;
        setError(e instanceof Error ? e.message : 'Failed to load cap sheet.');
        setSheet(null);
        setLoading(false);
      });
    return () => controller.abort();
  }, [selectedId]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--panel-gap)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <span className="ds-eyebrow">Team war room</span>
        <select
          value={selectedId ?? ''}
          onChange={(e) => router.replace(`/teams?team=${e.target.value}`)}
          aria-label="Select team"
          style={{
            height: 36, borderRadius: 'var(--radius-md)', border: '1px solid var(--border-default)',
            background: 'var(--bg-panel)', color: 'var(--text-primary)', padding: '0 12px',
            fontFamily: 'var(--font-sans)', fontSize: 14, fontWeight: 600, minWidth: 220,
          }}
        >
          {teams.length === 0 && <option value="">Loading teams…</option>}
          {teams.map((t) => <option key={t.team_id} value={t.team_id}>{t.name ?? t.abbreviation}</option>)}
        </select>
      </div>

      {error && (
        <div style={{ padding: '12px 16px', borderRadius: 'var(--radius-lg)', background: 'var(--negative-soft)', color: 'var(--negative-text)', fontSize: 13 }}>
          {error} — is the FastAPI server running at localhost:8000?
        </div>
      )}
      {loading && !sheet && (
        <div style={{ padding: 48, textAlign: 'center', color: 'var(--text-muted)' }}>Loading cap sheet…</div>
      )}
      {sheet && <WarRoom sheet={sheet} />}
    </div>
  );
}

export default function TeamsPage() {
  return (
    <Suspense fallback={<div style={{ padding: 48, textAlign: 'center', color: 'var(--text-muted)' }}>Loading…</div>}>
      <TeamsContent />
    </Suspense>
  );
}
