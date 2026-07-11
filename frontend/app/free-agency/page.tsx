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
import { Card } from '@/components/ui/Card';
import { Surface } from '@/components/ui/Surface';
import { Badge } from '@/components/ui/Badge';
import { StatTile } from '@/components/ui/StatTile';
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
    <Link href={`/players/${entry.player_id}`} style={{ textDecoration: 'none', minWidth: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
        <Avatar name={entry.full_name} size="md" position={entry.position} playerId={entry.player_id} />
        <div style={{ minWidth: 0 }}>
          <div style={{
            fontSize: 14, fontWeight: 700, color: 'var(--text-primary)',
            whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
          }}>
            {entry.full_name}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 2, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              {entry.position ?? '—'}{entry.age != null ? ` · age ${entry.age}` : ''}{team?.abbreviation ? ` · ${team.abbreviation}` : ''}
            </span>
            {extra ?? faTypeBadge(entry)}
          </div>
        </div>
      </div>
    </Link>
  );
}

function SelectBox({ value, onChange, ariaLabel, children }: {
  value: string; onChange: (v: string) => void; ariaLabel: string; children: ReactNode;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      aria-label={ariaLabel}
      style={{
        height: 34, borderRadius: 'var(--radius-md)', border: '1px solid var(--border-default)',
        background: 'var(--bg-panel)', color: 'var(--text-primary)', padding: '0 10px',
        fontFamily: 'var(--font-sans)', fontSize: 13, fontWeight: 600,
      }}
    >
      {children}
    </select>
  );
}

function ErrorNote({ message }: { message: string }) {
  return (
    <div style={{ padding: '12px 16px', borderRadius: 'var(--radius-lg)', background: 'var(--negative-soft)', color: 'var(--negative-text)', fontSize: 13 }}>
      {message} — is the FastAPI server running at localhost:8000?
    </div>
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
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--panel-gap)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span className="ds-eyebrow">Filter</span>
        {TYPE_FILTERS.map((f) => (
          <button
            key={f.value}
            onClick={() => setType(f.value)}
            aria-pressed={type === f.value}
            className="siq-enter-x"
            style={{
              height: 30, padding: '0 12px', borderRadius: 'var(--radius-pill)', cursor: 'pointer',
              border: `1px solid ${type === f.value ? 'transparent' : 'var(--border-subtle)'}`,
              background: type === f.value ? 'var(--accent-soft)' : 'transparent',
              color: type === f.value ? 'var(--accent-text)' : 'var(--text-secondary)',
              fontSize: 12, fontWeight: 600, fontFamily: 'var(--font-sans)',
            }}
          >
            {f.label}
          </button>
        ))}
        <SelectBox value={position} onChange={setPosition} ariaLabel="Filter by position">
          <option value="all">All positions</option>
          {POSITION_FILTERS.map((p) => <option key={p} value={p}>{p}</option>)}
        </SelectBox>
      </div>

      {error && <ErrorNote message={error} />}

      <Card
        className="siq-roster-ledger"
        eyebrow={data ? `${data.total} free agents · entering ${data.entering_season}` : 'Free agents'}
        icon={<Handshake size={15} />}
      >
        <div className="siq-roster-ledger-head">
          <span className="ds-eyebrow">Player</span>
          <span className="ds-eyebrow" style={{ textAlign: 'right' }}>Expiring pay</span>
          <span className="ds-eyebrow">Value vs pay</span>
          <span className="ds-eyebrow" style={{ textAlign: 'right' }}>Model value</span>
        </div>

        {loading && !data && (
          <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>Loading free agents…</div>
        )}
        {data && data.items.length === 0 && (
          <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>
            No free agents match this filter for {data.entering_season}.
          </div>
        )}

        {data?.items.map((entry) => (
          <div key={entry.player_id} className="siq-roster-ledger-row">
            <PlayerCell entry={entry} />
            <div style={{ textAlign: 'right' }}>
              <div className="ds-tnum" style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)' }}>
                {entry.expiring_aav_usd != null ? fmtM(entry.expiring_aav_usd) : '—'}
              </div>
              <div className="ds-tnum" style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                {entry.expiring_cap_pct != null ? `${fmtPct(entry.expiring_cap_pct)} cap` : '—'}
              </div>
            </div>
            <div className="siq-roster-gauge-cell">
              {entry.valuation_status === 'ready'
                ? <MiniValuePayGauge valuePct={entry.value_pct} payPct={entry.expiring_cap_pct} showLabels domainMaxPct={domainMax} />
                : <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>No model value</span>}
            </div>
            <div style={{ textAlign: 'right' }}>
              <div className="ds-tnum" style={{ fontSize: 14, fontWeight: 800, color: 'var(--text-primary)' }}>
                {entry.value_usd != null ? fmtM(entry.value_usd) : '—'}
              </div>
              <div className="ds-tnum" style={{ fontSize: 12, color: 'var(--confidence-text)' }}>
                {entry.value_pct != null ? fmtPct(entry.value_pct) : '—'}
              </div>
            </div>
          </div>
        ))}

        {data && data.total > PAGE_SIZE && (
          <Pager offset={offset} total={data.total} onPrev={() => setOffset(Math.max(0, offset - PAGE_SIZE))} onNext={() => setOffset(offset + PAGE_SIZE)} />
        )}
      </Card>

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
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--panel-gap)' }}>
      {error && <ErrorNote message={error} />}

      <Card eyebrow={data ? `${data.total} option decisions · entering ${data.entering_season}` : 'Option decisions'} icon={<Scale size={15} />}>
        {loading && !data && <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>Loading option decisions…</div>}
        {data && data.items.length === 0 && (
          <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>No player/team options for {data.entering_season}.</div>
        )}

        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
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
                    : <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>No model value</span>}
                  {o && (
                    <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 6 }}>{o.rationale}</div>
                  )}
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4 }}>
                  {o
                    ? <VerdictPill gapPct={o.gap_pct} tone={o.tone} label={o.verdict} size="md" />
                    : <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>—</span>}
                  {o && <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{o.deciding_party} decides</span>}
                </div>
              </div>
            );
          })}
        </div>

        {data && data.total > PAGE_SIZE && (
          <Pager offset={offset} total={data.total} onPrev={() => setOffset(Math.max(0, offset - PAGE_SIZE))} onNext={() => setOffset(offset + PAGE_SIZE)} />
        )}
      </Card>

      {data && <AssumptionFlag tone="warning" title="Verdicts compare model value to the option salary" icon={<TriangleAlert size={16} />}>{data.caveat}</AssumptionFlag>}
    </div>
  );
}

// ---- Targets tab --------------------------------------------------------------
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
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--panel-gap)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span className="ds-eyebrow">Team</span>
        <SelectBox value={selectedId != null ? String(selectedId) : ''} onChange={setTeam} ariaLabel="Select team">
          {teams.length === 0 && <option value="">Loading teams…</option>}
          {teams.map((t) => <option key={t.team_id} value={t.team_id}>{t.name ?? t.abbreviation}</option>)}
        </SelectBox>
        <span className="ds-eyebrow" style={{ marginLeft: 4 }}>Rank by</span>
        <SelectBox value={sort} onChange={(value) => setSort(value as 'fit' | 'value')} ariaLabel="Rank targets by">
          <option value="fit">Roster need fit</option>
          <option value="value">Model value</option>
        </SelectBox>
      </div>

      {error && <ErrorNote message={error} />}
      {loading && !data && <div style={{ padding: 48, textAlign: 'center', color: 'var(--text-muted)' }}>Loading projected room…</div>}

      {data && ctx && (
        <>
          <Surface variant="instrument" eyebrow={`Projected room · ${data.entering_season}`} icon={<Users size={15} />}
            action={
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Link href={`/offseason?team=${data.team.team_id}&season=${encodeURIComponent(data.entering_season)}`} style={{ textDecoration: 'none' }}>
                  <Badge tone="accent" size="sm">Build plan →</Badge>
                </Link>
                <Badge tone="confidence" variant="outline" size="sm">{ctx.is_projected ? 'projected' : 'actual'} cap</Badge>
              </div>
            }>
            <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', marginBottom: 16 }}>
              <h1 style={{ margin: 0, fontFamily: 'var(--font-display)', fontSize: 24, fontWeight: 700, color: 'var(--text-primary)' }}>
                {data.team.name ?? data.team.abbreviation}
              </h1>
              <div style={{ textAlign: 'right' }}>
                <div className="ds-tnum" style={{ fontSize: 26, fontWeight: 700, fontFamily: 'var(--font-display)', color: ctx.room_to_cap != null && ctx.room_to_cap < 0 ? 'var(--negative-text)' : 'var(--positive-text)', lineHeight: 1 }}>
                  {ctx.room_to_cap != null ? (ctx.room_to_cap < 0 ? `−${fmtM(Math.abs(ctx.room_to_cap))}` : fmtM(ctx.room_to_cap)) : '—'}
                </div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 3 }}>projected cap space</div>
              </div>
            </div>
            {thresholdsReady && (
              <>
                <CapBar value={ctx.committed_payroll_usd} taxLine={ctx.tax_line!} firstApron={ctx.first_apron!} secondApron={ctx.second_apron!} height={16} showLabels valueLabel="Committed" />
                <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', marginTop: 14 }}>
                  <RoomLine label="To tax" room={ctx.room_to_tax} />
                  <RoomLine label="To 1st apron" room={ctx.room_to_first_apron} />
                  <RoomLine label="To 2nd apron" room={ctx.room_to_second_apron} />
                </div>
              </>
            )}
          </Surface>

          <Surface
            variant="instrument"
            eyebrow="Projected roster needs"
            icon={<Radar size={15} />}
            action={<Badge tone="neutral" variant="outline" size="sm">vs league median</Badge>}
          >
            <RosterNeeds before={data.needs} />
          </Surface>

          <div className="siq-summary-tile-grid">
            <Card padded><StatTile label="Committed payroll" value={fmtM(ctx.committed_payroll_usd)} sub={`${data.committed_player_count} under contract`} size="sm" /></Card>
            <Card padded><StatTile label="Projected cap" value={ctx.salary_cap != null ? fmtM(ctx.salary_cap) : '—'} sub={ctx.is_projected ? '4.5% escalator' : 'from cap constants'} size="sm" /></Card>
            <Card padded><StatTile label="Targets that fit" value={data.targets.filter((t) => t.fits_room).length} sub={`of ${data.targets.length} ranked`} size="sm" /></Card>
            <Card padded><StatTile label="Top roster need" value={data.needs.needs[0]?.label ?? '—'} sub={data.needs.needs[0] ? `${data.needs.needs[0].deficit_pct.toFixed(1)}-point coverage gap` : 'No measured gap'} size="sm" /></Card>
          </div>

          <Card className="siq-roster-ledger" eyebrow={sort === 'fit' ? 'Team-fit targets' : 'Top available by model value'} icon={<Handshake size={15} />}>
            <div className="siq-roster-ledger-head">
              <span className="ds-eyebrow">Player</span>
              <span className="ds-eyebrow" style={{ textAlign: 'right' }}>Need fit</span>
              <span className="ds-eyebrow">Value vs pay</span>
              <span className="ds-eyebrow" style={{ textAlign: 'right' }}>Cap</span>
            </div>
            {data.targets.length === 0 && (
              <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>No free agents for {data.entering_season}.</div>
            )}
            {data.targets.map((entry) => (
              <div key={entry.player_id} className="siq-roster-ledger-row">
                <PlayerCell entry={entry} />
                <div style={{ textAlign: 'right' }}>
                  <div className="ds-tnum" style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)' }}>
                    {entry.fit.fit_score.toFixed(1)}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                    {entry.fit.fills[0]?.label ?? 'Depth only'}
                  </div>
                </div>
                <div className="siq-roster-gauge-cell">
                  {entry.valuation_status === 'ready'
                    ? <MiniValuePayGauge valuePct={entry.value_pct} payPct={entry.expiring_cap_pct} showLabels domainMaxPct={domainMax} />
                    : <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>No model value</span>}
                </div>
                <div style={{ textAlign: 'right' }}>
                  {entry.fits_room == null
                    ? <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>—</span>
                    : <Badge tone={entry.fits_room ? 'positive' : 'negative'} size="sm">{entry.fits_room ? 'Fits' : 'Over room'}</Badge>}
                </div>
              </div>
            ))}
          </Card>

          <AssumptionFlag tone="warning" title="Projected room is a simplified model" icon={<TriangleAlert size={16} />}>{data.caveat}</AssumptionFlag>
        </>
      )}
    </div>
  );
}

function Pager({ offset, total, onPrev, onNext }: { offset: number; total: number; onPrev: () => void; onNext: () => void }) {
  const from = offset + 1;
  const to = Math.min(offset + PAGE_SIZE, total);
  const btn = (disabled: boolean): React.CSSProperties => ({
    display: 'inline-flex', alignItems: 'center', gap: 4, height: 32, padding: '0 12px',
    borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)',
    background: 'var(--bg-panel)', color: disabled ? 'var(--text-muted)' : 'var(--text-primary)',
    fontSize: 12, fontWeight: 600, cursor: disabled ? 'default' : 'pointer',
  });
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 12, paddingTop: 12, borderTop: '1px solid var(--border-subtle)' }}>
      <span className="ds-tnum" style={{ fontSize: 12, color: 'var(--text-muted)' }}>{from}–{to} of {total}</span>
      <div style={{ display: 'flex', gap: 8 }}>
        <button onClick={onPrev} disabled={offset === 0} style={btn(offset === 0)}><ChevronLeft size={14} /> Prev</button>
        <button onClick={onNext} disabled={to >= total} style={btn(to >= total)}>Next <ChevronRight size={14} /></button>
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
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--panel-gap)' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {TABS.map(({ id, label, Icon }) => {
            const active = tab === id;
            return (
              <button
                key={id}
                onClick={() => setTab(id)}
                aria-pressed={active}
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: 6, height: 36, padding: '0 14px',
                  borderRadius: 'var(--radius-pill)', cursor: 'pointer',
                  border: `1px solid ${active ? 'transparent' : 'var(--border-subtle)'}`,
                  background: active ? 'var(--accent-soft)' : 'transparent',
                  color: active ? 'var(--accent-text)' : 'var(--text-secondary)',
                  fontSize: 13, fontWeight: 600, fontFamily: 'var(--font-sans)',
                }}
              >
                <Icon size={15} /> {label}
              </button>
            );
          })}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span className="ds-eyebrow">Class of</span>
          <SelectBox value={season} onChange={setSeason} ariaLabel="Free-agency season">
            {SEASONS.map((s) => <option key={s} value={s}>{s}</option>)}
          </SelectBox>
        </div>
      </div>

      {tab === 'board' && <BoardTab season={season} />}
      {tab === 'options' && <OptionsTab season={season} />}
      {tab === 'targets' && <TargetsTab season={season} teams={teams} />}
    </div>
  );
}

export default function FreeAgencyPage() {
  return (
    <Suspense fallback={<div style={{ padding: 48, textAlign: 'center', color: 'var(--text-muted)' }}>Loading…</div>}>
      <FreeAgencyContent />
    </Suspense>
  );
}
