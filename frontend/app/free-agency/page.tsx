'use client';

import { useEffect, useMemo, useState, Suspense, type ReactNode } from 'react';
import { useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { Handshake, Users, Scale, TriangleAlert, ChevronLeft, ChevronRight, Radar } from 'lucide-react';
import {
  getFreeAgencyBoard,
  getFreeAgencyOptions,
  getTeamFaTargets,
  getTeams,
  FreeAgentEntry,
  FreeAgencyBoardResponse,
  FreeAgencyOptionsResponse,
  TeamFaTargetsResponse,
  TeamListItem,
  FaType,
} from '@/lib/api';
import { Panel } from '@/components/ui/Panel';
import { Badge } from '@/components/ui/Badge';
import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { Select } from '@/components/ui/Select';
import { Field } from '@/components/ui/Field';
import { SegmentedControl } from '@/components/ui/SegmentedControl';
import { EmptyState } from '@/components/ui/EmptyState';
import { LoadingNote } from '@/components/ui/LoadingNote';
import { DecisionStrip } from '@/components/ui/DecisionStrip';
import { Avatar } from '@/components/ui/Avatar';
import { AssumptionFlag } from '@/components/ui/AssumptionFlag';
import { VerdictPill } from '@/components/ui/VerdictPill';
import { MiniValuePayGauge } from '@/components/players/MiniValuePayGauge';
import { CapBar } from '@/components/cap/CapBar';
import { RosterNeeds } from '@/components/teams/RosterNeeds';
import { fmtM, fmtPct, roundedDomainMax } from '@/lib/utils';

type TabId = 'board' | 'options' | 'targets';
const TABS: Array<{ id: TabId; label: string; Icon: typeof Handshake }> = [
  { id: 'board', label: 'Board', Icon: Handshake },
  { id: 'options', label: 'Options', Icon: Scale },
  { id: 'targets', label: 'Team targets', Icon: Users },
];

const SEASONS = ['2026-27', '2027-28', '2028-29', '2029-30'];
const PAGE_SIZE = 25;

const TYPE_FILTERS: Array<{ value: FaType | 'all'; label: string }> = [
  { value: 'all', label: 'All' },
  { value: 'expiring', label: 'Expiring' },
  { value: 'player-option', label: 'Player options' },
  { value: 'team-option', label: 'Team options' },
];

const POSITION_FILTERS = ['PG', 'SG', 'SF', 'PF', 'C'] as const;

function isTabId(value: string | null): value is TabId {
  return TABS.some((tab) => tab.id === value);
}

function writeFreeAgencyUrl(searchParams: { toString: () => string }, key: string, value: string) {
  const next = new URLSearchParams(searchParams.toString());
  next.set(key, value);
  window.history.replaceState(null, '', `/free-agency?${next.toString()}`);
}

// ---- shared bits --------------------------------------------------------------
function faTypeBadge(entry: { fa_type: FaType; rfa_estimate: boolean }): ReactNode {
  if (entry.fa_type === 'player-option') return <Badge tone="warning" size="sm">Player option</Badge>;
  if (entry.fa_type === 'team-option') return <Badge tone="confidence" size="sm">Team option</Badge>;
  return <Badge tone="neutral" size="sm">{entry.rfa_estimate ? 'RFA (est.)' : 'UFA'}</Badge>;
}

function PlayerCell({ entry, extra }: { entry: FreeAgentEntry; extra?: ReactNode }) {
  const team = entry.current_team ?? entry.latest_stats_team;
  return (
    <Link href={`/players/${entry.player_id}`} className="siq-plain-link siq-min0">
      <div className="siq-row siq-row--10 siq-min0">
        <Avatar name={entry.full_name} size="md" position={entry.position} playerId={entry.player_id} />
        <div className="siq-min0">
          <div className="siq-fa-player-name">
            {entry.full_name}
          </div>
          <div className="siq-fa-player-meta-row">
            <span className="ds-note">
              {entry.position ?? '—'}{entry.age != null ? ` · age ${entry.age}` : ''}{team?.abbreviation ? ` · ${team.abbreviation}` : ''}
            </span>
            {extra ?? faTypeBadge(entry)}
          </div>
        </div>
      </div>
    </Link>
  );
}

function ErrorNote({ message }: { message: string }) {
  return (
    <Alert tone="negative">
      {message} — is the FastAPI server running at localhost:8000?
    </Alert>
  );
}

// ---- Board tab ----------------------------------------------------------------
function BoardTab({ season }: { season: string }) {
  const [type, setType] = useState<FaType | 'all'>('all');
  const [position, setPosition] = useState('all');
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<FreeAgencyBoardResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { setOffset(0); }, [season, type, position]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    getFreeAgencyBoard({
      season,
      type: type === 'all' ? undefined : type,
      position: position === 'all' ? undefined : position,
      limit: PAGE_SIZE,
      offset,
    }, controller.signal)
      .then((res) => { setData(res); setLoading(false); })
      .catch((e: unknown) => {
        if (e instanceof DOMException && e.name === 'AbortError') return;
        setError(e instanceof Error ? e.message : 'Failed to load the free-agency board.');
        setData(null);
        setLoading(false);
      });
    return () => controller.abort();
  }, [season, type, position, offset]);

  const domainMax = useMemo(
    () => roundedDomainMax((data?.items ?? []).flatMap((e) => [e.value_pct, e.expiring_cap_pct])),
    [data],
  );

  return (
    <div className="siq-stack">
      <div className="siq-row siq-fa-flex-wrap">
        <span className="ds-eyebrow">Filter</span>
        <SegmentedControl
          options={TYPE_FILTERS}
          value={type}
          onChange={setType}
          ariaLabel="Filter by contract type"
        />
        <Select selectSize="sm" value={position} onChange={(e) => setPosition(e.target.value)} aria-label="Filter by position">
          <option value="all">All positions</option>
          {POSITION_FILTERS.map((p) => <option key={p} value={p}>{p}</option>)}
        </Select>
      </div>

      {error && <ErrorNote message={error} />}

      <Panel variant="card"
        className="siq-roster-ledger"
        eyebrow={data ? `${data.total} free agents · entering ${data.entering_season}` : 'Free agents'}
        icon={<Handshake size={15} />}
      >
        <div className="siq-roster-ledger-head">
          <span className="ds-eyebrow">Player</span>
          <span className="ds-eyebrow ds-right">Expiring pay</span>
          <span className="ds-eyebrow">Value vs pay</span>
          <span className="ds-eyebrow ds-right">Model value</span>
        </div>

        {loading && !data && <LoadingNote>Loading free agents…</LoadingNote>}
        {data && data.items.length === 0 && (
          <EmptyState title={`No free agents match this filter for ${data.entering_season}.`} />
        )}

        {data?.items.map((entry) => (
          <div key={entry.player_id} className="siq-roster-ledger-row">
            <PlayerCell entry={entry} />
            <div className="ds-right">
              <div className="ds-tnum siq-fa-value-primary">
                {entry.expiring_aav_usd != null ? fmtM(entry.expiring_aav_usd) : '—'}
              </div>
              <div className="ds-tnum ds-note">
                {entry.expiring_cap_pct != null ? `${fmtPct(entry.expiring_cap_pct)} cap` : '—'}
              </div>
            </div>
            <div className="siq-roster-gauge-cell">
              {entry.valuation_status === 'ready'
                ? <MiniValuePayGauge valuePct={entry.value_pct} payPct={entry.expiring_cap_pct} showLabels domainMaxPct={domainMax} />
                : <span className="ds-note">No model value</span>}
            </div>
            <div className="ds-right">
              <div className="ds-tnum siq-fa-value-strong">
                {entry.value_usd != null ? fmtM(entry.value_usd) : '—'}
              </div>
              <div className="ds-tnum siq-fa-note-confidence">
                {entry.value_pct != null ? fmtPct(entry.value_pct) : '—'}
              </div>
            </div>
          </div>
        ))}

        {data && data.total > PAGE_SIZE && (
          <Pager offset={offset} total={data.total} onPrev={() => setOffset(Math.max(0, offset - PAGE_SIZE))} onNext={() => setOffset(offset + PAGE_SIZE)} />
        )}
      </Panel>

      {data && <AssumptionFlag tone="warning" title="Derived free-agency status" icon={<TriangleAlert size={16} />}>{data.caveat}</AssumptionFlag>}
    </div>
  );
}

// ---- Options tab --------------------------------------------------------------
function OptionsTab({ season }: { season: string }) {
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<FreeAgencyOptionsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { setOffset(0); }, [season]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    getFreeAgencyOptions({ season, limit: PAGE_SIZE, offset }, controller.signal)
      .then((res) => { setData(res); setLoading(false); })
      .catch((e: unknown) => {
        if (e instanceof DOMException && e.name === 'AbortError') return;
        setError(e instanceof Error ? e.message : 'Failed to load option decisions.');
        setData(null);
        setLoading(false);
      });
    return () => controller.abort();
  }, [season, offset]);

  const domainMax = useMemo(
    () => roundedDomainMax((data?.items ?? []).flatMap((e) => [e.value_pct, e.option?.option_cap_pct ?? null])),
    [data],
  );

  return (
    <div className="siq-stack">
      {error && <ErrorNote message={error} />}

      <Panel variant="card" eyebrow={data ? `${data.total} option decisions · entering ${data.entering_season}` : 'Option decisions'} icon={<Scale size={15} />}>
        {loading && !data && <LoadingNote>Loading option decisions…</LoadingNote>}
        {data && data.items.length === 0 && (
          <EmptyState title={`No player/team options for ${data.entering_season}.`} />
        )}

        <div className="siq-fa-option-list">
          {data?.items.map((entry) => {
            const o = entry.option;
            return (
              <div key={entry.player_id} className="siq-fa-option-row">
                <PlayerCell
                  entry={entry}
                  extra={<Badge tone={entry.fa_type === 'player-option' ? 'warning' : 'confidence'} size="sm">
                    {entry.expiring_season} {entry.fa_type === 'player-option' ? 'player option' : 'team option'}
                  </Badge>}
                />
                <div className="siq-fa-option-gauge">
                  {entry.valuation_status === 'ready'
                    ? <MiniValuePayGauge valuePct={entry.value_pct} payPct={o?.option_cap_pct ?? null} showLabels domainMaxPct={domainMax} />
                    : <span className="ds-note">No model value</span>}
                  {o && (
                    <div className="ds-note siq-fa-mt6">{o.rationale}</div>
                  )}
                </div>
                <div className="siq-fa-verdict-col">
                  {o
                    ? <VerdictPill gapPct={o.gap_pct} tone={o.tone} label={o.verdict} size="md" />
                    : <span className="ds-note">—</span>}
                  {o && <span className="siq-fa-note-sm">{o.deciding_party} decides</span>}
                </div>
              </div>
            );
          })}
        </div>

        {data && data.total > PAGE_SIZE && (
          <Pager offset={offset} total={data.total} onPrev={() => setOffset(Math.max(0, offset - PAGE_SIZE))} onNext={() => setOffset(offset + PAGE_SIZE)} />
        )}
      </Panel>

      {data && <AssumptionFlag tone="warning" title="Verdicts compare model value to the option salary" icon={<TriangleAlert size={16} />}>{data.caveat}</AssumptionFlag>}
    </div>
  );
}

// ---- Targets tab --------------------------------------------------------------
function RoomLine({ label, room }: { label: string; room: number | null }) {
  if (room == null) return null;
  const over = room < 0;
  return (
    <span className="siq-fa-room-line">
      <span className="ds-eyebrow siq-fa-eyebrow-tight">{label}</span>
      <span className="ds-tnum siq-fa-room-value" style={{ color: over ? 'var(--negative-text)' : 'var(--positive-text)' }}>
        {over ? `−${fmtM(Math.abs(room))} over` : `${fmtM(room)} under`}
      </span>
    </span>
  );
}

function TargetsTab({ season, teams }: { season: string; teams: TeamListItem[] }) {
  const searchParams = useSearchParams();
  const teamParam = searchParams.get('team');
  const parsedTeamId = teamParam ? Number(teamParam) : null;
  const selectedFromUrl = parsedTeamId != null && Number.isFinite(parsedTeamId)
    ? parsedTeamId
    : (teams[0]?.team_id ?? null);
  const [selectedId, setSelectedId] = useState<number | null>(selectedFromUrl);
  const [sort, setSort] = useState<'fit' | 'value'>('fit');

  const [data, setData] = useState<TeamFaTargetsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { setSelectedId(selectedFromUrl); }, [selectedFromUrl]);

  useEffect(() => {
    if (selectedId == null) return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    getTeamFaTargets(selectedId, { season, sort }, controller.signal)
      .then((res) => { setData(res); setLoading(false); })
      .catch((e: unknown) => {
        if (e instanceof DOMException && e.name === 'AbortError') return;
        setError(e instanceof Error ? e.message : 'Failed to load team targets.');
        setData(null);
        setLoading(false);
      });
    return () => controller.abort();
  }, [selectedId, season, sort]);

  const setTeam = (id: string) => {
    setSelectedId(Number(id));
    writeFreeAgencyUrl(searchParams, 'team', id);
  };

  const ctx = data?.cap_context;
  const thresholdsReady = !!ctx && ctx.tax_line != null && ctx.first_apron != null && ctx.second_apron != null;
  const domainMax = useMemo(
    () => roundedDomainMax((data?.targets ?? []).flatMap((e) => [e.value_pct, e.expiring_cap_pct])),
    [data],
  );

  return (
    <div className="siq-stack">
      <div className="siq-row siq-row--12 siq-fa-flex-wrap">
        <Field label="Team" htmlFor="fa-team-select" inline>
          <Select id="fa-team-select" value={selectedId != null ? String(selectedId) : ''} onChange={(e) => setTeam(e.target.value)}>
            {teams.length === 0 && <option value="">Loading teams…</option>}
            {teams.map((t) => <option key={t.team_id} value={t.team_id}>{t.name ?? t.abbreviation}</option>)}
          </Select>
        </Field>
        <Field label="Rank by" htmlFor="fa-rank-select" inline>
          <Select id="fa-rank-select" value={sort} onChange={(e) => setSort(e.target.value as 'fit' | 'value')}>
            <option value="fit">Roster need fit</option>
            <option value="value">Model value</option>
          </Select>
        </Field>
      </div>

      {error && <ErrorNote message={error} />}
      {loading && !data && <LoadingNote>Loading projected room…</LoadingNote>}

      {data && ctx && (
        <>
          <Panel variant="instrument" eyebrow={`Projected room · ${data.entering_season}`} icon={<Users size={15} />}
            action={
              <div className="siq-row">
                <Link href={`/offseason?team=${data.team.team_id}&season=${encodeURIComponent(data.entering_season)}`} className="siq-plain-link">
                  <Badge tone="accent" size="sm">Build plan →</Badge>
                </Link>
                <Badge tone="confidence" variant="outline" size="sm">{ctx.is_projected ? 'projected' : 'actual'} cap</Badge>
              </div>
            }>
            <div className="siq-fa-hero-row">
              <h1 className="siq-fa-hero-title">
                {data.team.name ?? data.team.abbreviation}
              </h1>
              <div className="ds-right">
                <div className="ds-tnum siq-fa-hero-value" style={{ color: ctx.room_to_cap != null && ctx.room_to_cap < 0 ? 'var(--negative-text)' : 'var(--positive-text)' }}>
                  {ctx.room_to_cap != null ? (ctx.room_to_cap < 0 ? `−${fmtM(Math.abs(ctx.room_to_cap))}` : fmtM(ctx.room_to_cap)) : '—'}
                </div>
                <div className="ds-note siq-fa-mt3">projected cap space</div>
              </div>
            </div>
            {thresholdsReady && (
              <>
                <CapBar value={ctx.committed_payroll_usd} taxLine={ctx.tax_line!} firstApron={ctx.first_apron!} secondApron={ctx.second_apron!} height={16} showLabels valueLabel="Committed" />
                <div className="siq-fa-room-lines">
                  <RoomLine label="To tax" room={ctx.room_to_tax} />
                  <RoomLine label="To 1st apron" room={ctx.room_to_first_apron} />
                  <RoomLine label="To 2nd apron" room={ctx.room_to_second_apron} />
                </div>
              </>
            )}
          </Panel>

          <Panel
            variant="instrument"
            eyebrow="Projected roster needs"
            icon={<Radar size={15} />}
            action={<Badge tone="neutral" variant="outline" size="sm">vs league median</Badge>}
          >
            <RosterNeeds before={data.needs} />
          </Panel>

          <DecisionStrip
            ariaLabel={`${data.team.name ?? data.team.abbreviation} free-agency decision status`}
            lead={{
              label: sort === 'fit' ? 'Best roster target' : 'Highest model value',
              value: data.targets[0]?.full_name ?? 'No eligible target',
              detail: data.targets[0] ? `${data.targets[0].fit.fit_score.toFixed(1)} fit · ${data.targets[0].fit.fills[0]?.label ?? 'depth'}` : `No free agents for ${data.entering_season}`,
              tone: data.targets[0]?.fits_room === false ? 'warning' : 'positive',
            }}
            items={[
              {
                label: 'Primary roster need',
                value: data.needs.needs[0]?.label ?? 'No measured gap',
                detail: data.needs.needs[0] ? `${data.needs.needs[0].deficit_pct.toFixed(1)}-point deficit versus league median` : 'Projected roster clears measured needs',
                tone: data.needs.needs[0] ? 'warning' : 'positive',
              },
              {
                label: 'Cap feasibility',
                value: `${data.targets.filter((target) => target.fits_room).length}/${data.targets.length} fit`,
                detail: ctx.room_to_cap != null ? `${ctx.room_to_cap >= 0 ? fmtM(ctx.room_to_cap) + ' room' : fmtM(Math.abs(ctx.room_to_cap)) + ' over cap'}` : 'Room unavailable',
                tone: data.targets.some((target) => target.fits_room) ? 'positive' : 'negative',
              },
              {
                label: 'Value uncertainty',
                value: data.targets[0]?.value_pct != null ? fmtPct(data.targets[0].value_pct) : 'Not priced',
                detail: data.targets[0]?.lo_pct != null && data.targets[0]?.hi_pct != null ? `${data.targets[0].lo_pct.toFixed(1)}–${data.targets[0].hi_pct.toFixed(1)}% of cap interval` : `${data.targets.length} targets ranked`,
                tone: 'confidence',
              },
            ]}
          />

          <Panel variant="card" className="siq-roster-ledger" eyebrow={sort === 'fit' ? 'Team-fit targets' : 'Top available by model value'} icon={<Handshake size={15} />}>
            <div className="siq-roster-ledger-head">
              <span className="ds-eyebrow">Player</span>
              <span className="ds-eyebrow ds-right">Need fit</span>
              <span className="ds-eyebrow">Value vs pay</span>
              <span className="ds-eyebrow ds-right">Cap</span>
            </div>
            {data.targets.length === 0 && (
              <div className="siq-fa-empty-cell">No free agents for {data.entering_season}.</div>
            )}
            {data.targets.map((entry) => (
              <div key={entry.player_id} className="siq-roster-ledger-row">
                <PlayerCell entry={entry} />
                <div className="ds-right">
                  <div className="ds-tnum siq-fa-value-primary">
                    {entry.fit.fit_score.toFixed(1)}
                  </div>
                  <div className="siq-fa-note-sm-mt2">
                    {entry.fit.fills[0]?.label ?? 'Depth only'}
                  </div>
                </div>
                <div className="siq-roster-gauge-cell">
                  {entry.valuation_status === 'ready'
                    ? <MiniValuePayGauge valuePct={entry.value_pct} payPct={entry.expiring_cap_pct} showLabels domainMaxPct={domainMax} />
                    : <span className="ds-note">No model value</span>}
                </div>
                <div className="ds-right">
                  {entry.fits_room == null
                    ? <span className="ds-note">—</span>
                    : <Badge tone={entry.fits_room ? 'positive' : 'negative'} size="sm">{entry.fits_room ? 'Fits' : 'Over room'}</Badge>}
                </div>
              </div>
            ))}
          </Panel>

          <AssumptionFlag tone="warning" title="Projected room is a simplified model" icon={<TriangleAlert size={16} />}>{data.caveat}</AssumptionFlag>
        </>
      )}
    </div>
  );
}

function Pager({ offset, total, onPrev, onNext }: { offset: number; total: number; onPrev: () => void; onNext: () => void }) {
  const from = offset + 1;
  const to = Math.min(offset + PAGE_SIZE, total);
  return (
    <div className="siq-fa-pager">
      <span className="ds-tnum ds-note">{from}–{to} of {total}</span>
      <div className="siq-fa-btn-row">
        <Button size="sm" icon={<ChevronLeft size={14} />} onClick={onPrev} disabled={offset === 0}>Prev</Button>
        <Button size="sm" onClick={onNext} disabled={to >= total}>Next <ChevronRight size={14} /></Button>
      </div>
    </div>
  );
}

// ---- Page shell ---------------------------------------------------------------
function FreeAgencyContent() {
  const searchParams = useSearchParams();
  const tabParam = searchParams.get('tab');
  const tabFromUrl: TabId = isTabId(tabParam) ? tabParam : 'board';
  const seasonParam = searchParams.get('season');
  const seasonFromUrl = seasonParam && SEASONS.includes(seasonParam) ? seasonParam : SEASONS[0];
  const [tab, setTabState] = useState<TabId>(tabFromUrl);
  const [season, setSeasonState] = useState(seasonFromUrl);
  const [teams, setTeams] = useState<TeamListItem[]>([]);

  useEffect(() => { getTeams().then(setTeams).catch(() => {}); }, []);
  useEffect(() => { setTabState(tabFromUrl); }, [tabFromUrl]);
  useEffect(() => { setSeasonState(seasonFromUrl); }, [seasonFromUrl]);

  const setTab = (id: TabId) => {
    setTabState(id);
    writeFreeAgencyUrl(searchParams, 'tab', id);
  };

  const setSeason = (value: string) => {
    setSeasonState(value);
    writeFreeAgencyUrl(searchParams, 'season', value);
  };

  return (
    <div className="siq-stack">
      <div className="siq-row siq-row--12 siq-fa-justify-wrap">
        <SegmentedControl
          options={TABS.map(({ id, label, Icon }) => ({ value: id, label, icon: <Icon size={15} /> }))}
          value={tab}
          onChange={setTab}
          ariaLabel="Free-agency view"
        />
        <Field label="Class of" htmlFor="fa-class-select" inline>
          <Select id="fa-class-select" value={season} onChange={(e) => setSeason(e.target.value)}>
            {SEASONS.map((s) => <option key={s} value={s}>{s}</option>)}
          </Select>
        </Field>
      </div>

      {tab === 'board' && <BoardTab season={season} />}
      {tab === 'options' && <OptionsTab season={season} />}
      {tab === 'targets' && <TargetsTab season={season} teams={teams} />}
    </div>
  );
}

export default function FreeAgencyPage() {
  return (
    <Suspense fallback={<LoadingNote>Loading…</LoadingNote>}>
      <FreeAgencyContent />
    </Suspense>
  );
}
