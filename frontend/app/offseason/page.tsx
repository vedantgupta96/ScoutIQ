'use client';

import type { CSSProperties } from 'react';
import { Suspense, useEffect, useMemo, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import {
  CalendarRange,
  CircleDollarSign,
  Plus,
  RotateCcw,
  Shield,
  Trash2,
  TriangleAlert,
  UserRoundPlus,
} from 'lucide-react';
import {
  buildOffseasonPlan,
  getFreeAgencyOptions,
  getTeamFaTargets,
  getTeams,
  FreeAgentEntry,
  OffseasonMoveResponse,
  OffseasonPlanRequest,
  OffseasonPlanResponse,
  TeamFaTarget,
  TeamFaTargetsResponse,
  TeamListItem,
} from '@/lib/api';
import { AssumptionFlag } from '@/components/ui/AssumptionFlag';
import { Avatar } from '@/components/ui/Avatar';
import { Badge } from '@/components/ui/Badge';
import { Card } from '@/components/ui/Card';
import { CapBar, CAP_TIER_LABEL, CapTierKey, capTierBadgeTone } from '@/components/cap/CapBar';
import { StatTile } from '@/components/ui/StatTile';
import { Surface } from '@/components/ui/Surface';
import { TeamLogo } from '@/components/ui/TeamLogo';
import { fmtM, fmtPct, signed } from '@/lib/utils';
import { teamVisual } from '@/lib/teamVisuals';

const DEFAULT_SEASON = '2026-27';
const HORIZON = 4;

type FinalYearOption = 'none' | 'player' | 'team';

interface DraftContract {
  player: TeamFaTarget;
  aavPct: number;
  years: number;
  finalYearOption: FinalYearOption;
}

function nextSeason(season: string): string {
  const start = Number(season.slice(0, 4));
  const next = start + 1;
  return `${next}-${String((next + 1) % 100).padStart(2, '0')}`;
}

const SEASONS = [
  DEFAULT_SEASON,
  nextSeason(DEFAULT_SEASON),
  nextSeason(nextSeason(DEFAULT_SEASON)),
];

function cappedValue(value: number | null | undefined): number {
  return Math.min(35, Math.max(1, Math.round((value ?? 10) * 2) / 2));
}

function moneyDelta(value: number): string {
  if (value === 0) return '$0';
  return `${value > 0 ? '+' : '−'}${fmtM(Math.abs(value))}`;
}

function moveLabel(move: OffseasonMoveResponse): string {
  if (move.kind === 're-sign') return 'Re-sign';
  if (move.kind === 'team-option-decline') return 'Decline team option';
  if (move.kind === 'player-option-opt-out') return 'Assume player opts out';
  return 'Sign';
}

function TargetRow({
  target,
  added,
  onAdd,
}: {
  target: TeamFaTarget;
  added: boolean;
  onAdd: () => void;
}) {
  const team = target.current_team ?? target.latest_stats_team;
  return (
    <div className="siq-offseason-target-row">
      <Avatar name={target.full_name} playerId={target.player_id} position={target.position} size="sm" />
      <div className="siq-offseason-target-id">
        <Link href={`/players/${target.player_id}`} className="siq-offseason-player-link">
          {target.full_name}
        </Link>
        <span>{target.position ?? '—'} · {team?.abbreviation ?? 'FA'}</span>
      </div>
      <div className="siq-offseason-target-value ds-tnum">
        <strong>{target.value_pct != null ? fmtPct(target.value_pct) : '—'}</strong>
        <span>{target.lo_pct != null && target.hi_pct != null ? `${target.lo_pct.toFixed(1)}–${target.hi_pct.toFixed(1)}%` : 'No interval'}</span>
      </div>
      <button
        type="button"
        className="siq-icon-button siq-offseason-add"
        onClick={onAdd}
        disabled={added}
        aria-label={added ? `${target.full_name} is in the plan` : `Add ${target.full_name} to plan`}
        title={added ? 'Already in plan' : 'Add to plan'}
      >
        <Plus size={16} />
      </button>
    </div>
  );
}

function OptionRow({
  player,
  selected,
  onToggle,
}: {
  player: FreeAgentEntry;
  selected: boolean;
  onToggle: () => void;
}) {
  const isTeamOption = player.fa_type === 'team-option';
  return (
    <div className="siq-offseason-option-row">
      <Avatar name={player.full_name} playerId={player.player_id} position={player.position} size="sm" />
      <div className="siq-offseason-target-id">
        <Link href={`/players/${player.player_id}`} className="siq-offseason-player-link">
          {player.full_name}
        </Link>
        <span>{isTeamOption ? 'Team option' : 'Player option'} · {player.expiring_aav_usd != null ? fmtM(player.expiring_aav_usd) : '—'}</span>
      </div>
      {player.option ? (
        <span className="siq-offseason-option-verdict">
          <Badge tone={player.option.tone} variant="outline" size="sm">{player.option.verdict}</Badge>
        </span>
      ) : null}
      <button
        type="button"
        className={selected ? 'siq-secondary-button' : 'siq-primary-button'}
        onClick={onToggle}
        aria-pressed={selected}
        style={{ padding: '6px 9px', fontSize: 12, whiteSpace: 'nowrap' }}
      >
        {selected ? <RotateCcw size={14} /> : <Trash2 size={14} />}
        {selected ? 'Restore' : isTeamOption ? 'Decline' : 'Assume opt out'}
      </button>
    </div>
  );
}

function ContractEditor({
  draft,
  result,
  onChange,
  onRemove,
}: {
  draft: DraftContract;
  result: OffseasonMoveResponse | undefined;
  onChange: (patch: Partial<Omit<DraftContract, 'player'>>) => void;
  onRemove: () => void;
}) {
  const pct = ((draft.aavPct - 1) / 34) * 100;
  return (
    <div className="siq-offseason-move">
      <div className="siq-offseason-move-head">
        <Avatar name={draft.player.full_name} playerId={draft.player.player_id} position={draft.player.position} size="sm" />
        <div className="siq-offseason-target-id">
          <Link href={`/players/${draft.player.player_id}`} className="siq-offseason-player-link">
            {draft.player.full_name}
          </Link>
          <span>{result ? moveLabel(result) : 'Proposed contract'}</span>
        </div>
        {result?.value_gap_pct != null ? (
          <span className="siq-offseason-move-verdict">
            <Badge tone={result.value_gap_pct >= 1 ? 'positive' : result.value_gap_pct <= -1 ? 'negative' : 'neutral'} size="sm">
              {signed(result.value_gap_pct)}% value gap
            </Badge>
          </span>
        ) : null}
        <button
          type="button"
          className="siq-icon-button"
          onClick={onRemove}
          aria-label={`Remove ${draft.player.full_name} from plan`}
          title="Remove from plan"
        >
          <Trash2 size={15} />
        </button>
      </div>

      <div className="siq-offseason-controls">
        <label className="siq-offseason-aav-control">
          <span>AAV <strong className="ds-tnum">{fmtPct(draft.aavPct)}</strong></span>
          <input
            className="siq-slider"
            type="range"
            min={1}
            max={35}
            step={0.5}
            value={draft.aavPct}
            onChange={(event) => onChange({ aavPct: Number(event.target.value) })}
            aria-label={`${draft.player.full_name} proposed AAV as percent of cap`}
            style={{ '--siq-slider-pct': `${pct}%` } as CSSProperties}
          />
        </label>
        <label>
          <span>Years</span>
          <select
            value={draft.years}
            onChange={(event) => onChange({ years: Number(event.target.value) })}
            aria-label={`${draft.player.full_name} contract years`}
          >
            {[1, 2, 3, 4].map((year) => <option key={year} value={year}>{year}</option>)}
          </select>
        </label>
        <label>
          <span>Final year</span>
          <select
            value={draft.finalYearOption}
            onChange={(event) => onChange({ finalYearOption: event.target.value as FinalYearOption })}
            aria-label={`${draft.player.full_name} final year structure`}
          >
            <option value="none">Guaranteed</option>
            <option value="team">Team option</option>
            <option value="player">Player option</option>
          </select>
        </label>
      </div>
    </div>
  );
}

function SeasonLedger({ plan }: { plan: OffseasonPlanResponse }) {
  return (
    <Surface variant="instrument" eyebrow="Multi-season ledger" icon={<CalendarRange size={15} />}>
      <div className="siq-offseason-ledger-head" aria-hidden="true">
        <span>Season</span><span>Baseline</span><span>Plan</span><span>Delta</span><span>Tier</span>
      </div>
      <div className="siq-offseason-ledger">
        {plan.seasons.map((season) => {
          const tier = season.tier_after as CapTierKey;
          return (
            <div className="siq-offseason-season" key={season.season}>
              <div className="siq-offseason-season-metrics">
                <div>
                  <strong className="ds-tnum">{season.season}</strong>
                  {season.is_projected_cap ? <Badge tone="neutral" variant="outline" size="sm">Projected</Badge> : null}
                </div>
                <span className="ds-tnum" data-label="Baseline">{fmtM(season.baseline_payroll_usd)}</span>
                <span className="ds-tnum" data-label="Plan"><strong>{fmtM(season.payroll_after_usd)}</strong></span>
                <span className="ds-tnum" data-label="Delta" style={{ color: season.payroll_delta_usd > 0 ? 'var(--negative-text)' : season.payroll_delta_usd < 0 ? 'var(--positive-text)' : 'var(--text-muted)' }}>
                  {moneyDelta(season.payroll_delta_usd)}
                </span>
                <span className="siq-offseason-tier" data-label="Tier">
                  <Badge tone={capTierBadgeTone(tier)} size="sm">{CAP_TIER_LABEL[tier]}</Badge>
                </span>
              </div>
              <CapBar
                value={season.payroll_after_usd}
                taxLine={season.tax_line}
                firstApron={season.first_apron}
                secondApron={season.second_apron}
                height={10}
                valueLabel="Plan"
              />
              <div className="siq-offseason-season-foot ds-tnum">
                <span>{season.roster_count_after} committed</span>
                <span style={{ color: season.room_to_cap_after >= 0 ? 'var(--positive-text)' : 'var(--warning-text)' }}>
                  {season.room_to_cap_after >= 0 ? `${fmtM(season.room_to_cap_after)} cap room` : `${fmtM(Math.abs(season.room_to_cap_after))} over cap`}
                </span>
                <span>{season.room_to_first_apron_after >= 0
                  ? `${fmtM(season.room_to_first_apron_after)} to 1st apron`
                  : `${fmtM(Math.abs(season.room_to_first_apron_after))} over 1st apron`}</span>
              </div>
            </div>
          );
        })}
      </div>
    </Surface>
  );
}

function PlannerWorkspace({ teamId, season }: { teamId: number; season: string }) {
  const [market, setMarket] = useState<TeamFaTargetsResponse | null>(null);
  const [teamOptions, setTeamOptions] = useState<FreeAgentEntry[]>([]);
  const [contracts, setContracts] = useState<DraftContract[]>([]);
  const [declines, setDeclines] = useState<number[]>([]);
  const [plan, setPlan] = useState<OffseasonPlanResponse | null>(null);
  const [marketLoading, setMarketLoading] = useState(true);
  const [planLoading, setPlanLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setMarketLoading(true);
    setError(null);
    Promise.all([
      getTeamFaTargets(teamId, { season, limit: 20 }, controller.signal),
      getFreeAgencyOptions({ season, limit: 100 }, controller.signal),
    ])
      .then(([targets, options]) => {
        setMarket(targets);
        setTeamOptions(options.items.filter((item) => item.current_team?.team_id === teamId));
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setError(reason instanceof Error ? reason.message : 'Failed to load offseason market.');
      })
      .finally(() => {
        if (!controller.signal.aborted) setMarketLoading(false);
      });
    return () => controller.abort();
  }, [season, teamId]);

  const request = useMemo<OffseasonPlanRequest>(() => ({
    team_id: teamId,
    start_season: season,
    horizon: HORIZON,
    contracts: contracts.map((draft) => {
      const hasOption = draft.finalYearOption !== 'none';
      return {
        player_id: draft.player.player_id,
        aav_pct: draft.aavPct,
        years: draft.years,
        guaranteed_years: hasOption ? draft.years - 1 : draft.years,
        player_option_years: draft.finalYearOption === 'player' ? 1 : 0,
        team_option_years: draft.finalYearOption === 'team' ? 1 : 0,
      };
    }),
    option_declines: declines.filter((playerId) => (
      !contracts.some((draft) => draft.player.player_id === playerId)
    )),
  }), [contracts, declines, season, teamId]);
  const requestKey = JSON.stringify(request);

  useEffect(() => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => {
      setPlanLoading(true);
      setError(null);
      buildOffseasonPlan(request, controller.signal)
        .then(setPlan)
        .catch((reason: unknown) => {
          if (controller.signal.aborted) return;
          setError(reason instanceof Error ? reason.message : 'Failed to price offseason plan.');
        })
        .finally(() => {
          if (!controller.signal.aborted) setPlanLoading(false);
        });
    }, contracts.length || declines.length ? 180 : 0);
    return () => {
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [requestKey]); // requestKey is the primitive snapshot that triggers repricing.

  const stagedIds = useMemo(() => new Set(contracts.map((draft) => draft.player.player_id)), [contracts]);
  const moveByPlayer = useMemo(
    () => new Map(plan?.moves.map((move) => [move.player_id, move]) ?? []),
    [plan?.moves],
  );
  const firstYear = plan?.seasons[0] ?? null;
  const visual = teamVisual(plan?.team.abbreviation ?? market?.team.abbreviation);

  function addTarget(player: TeamFaTarget) {
    setDeclines((current) => current.filter((id) => id !== player.player_id));
    setContracts((current) => current.some((draft) => draft.player.player_id === player.player_id)
      ? current
      : [...current, {
        player,
        aavPct: cappedValue(player.value_pct ?? player.expiring_cap_pct),
        years: 4,
        finalYearOption: 'none',
      }]);
  }

  function updateContract(playerId: number, patch: Partial<Omit<DraftContract, 'player'>>) {
    setContracts((current) => current.map((draft) => (
      draft.player.player_id === playerId ? { ...draft, ...patch } : draft
    )));
  }

  function toggleDecline(playerId: number, selected: boolean) {
    if (!selected) {
      setContracts((current) => current.filter((draft) => draft.player.player_id !== playerId));
    }
    setDeclines((current) => selected
      ? current.filter((id) => id !== playerId)
      : current.includes(playerId) ? current : [...current, playerId]);
  }

  function resetPlan() {
    setContracts([]);
    setDeclines([]);
  }

  return (
    <div
      className="siq-offseason-workspace"
      style={{
        '--team-primary': visual.primary,
        '--team-secondary': visual.secondary,
        '--team-wash': visual.wash,
      } as CSSProperties}
    >
      {error ? <div className="siq-offseason-error">{error}</div> : null}

      {firstYear && plan ? (
        <Surface
          variant="instrument"
          teamAccent
          eyebrow={`${season} plan`}
          icon={<Shield size={15} />}
          action={<Badge tone={capTierBadgeTone(firstYear.tier_after as CapTierKey)}>{CAP_TIER_LABEL[firstYear.tier_after as CapTierKey]}</Badge>}
        >
          <div className="siq-offseason-hero">
            <div className="siq-offseason-team">
              <TeamLogo teamId={plan.team.team_id} abbreviation={plan.team.abbreviation} name={plan.team.name} size="lg" />
              <div>
                <h1>{plan.team.name ?? plan.team.abbreviation}</h1>
                <span>{plan.moves.length} staged {plan.moves.length === 1 ? 'move' : 'moves'} · {firstYear.roster_count_after} committed players</span>
              </div>
            </div>
            <div className="siq-offseason-hero-payroll">
              <strong className={`ds-tnum${planLoading ? ' siq-offseason-updating' : ''}`}>{fmtM(firstYear.payroll_after_usd)}</strong>
              <span className="ds-tnum">{moneyDelta(firstYear.payroll_delta_usd)} vs baseline</span>
            </div>
          </div>
          <CapBar
            value={firstYear.payroll_after_usd}
            taxLine={firstYear.tax_line}
            firstApron={firstYear.first_apron}
            secondApron={firstYear.second_apron}
            height={15}
            showLabels
            valueLabel="Plan"
          />
          <div className="siq-offseason-summary-grid">
            <Card padded><StatTile label="Plan payroll" value={fmtM(firstYear.payroll_after_usd)} sub={`${fmtPct(firstYear.payroll_after_usd / firstYear.salary_cap * 100)} of cap`} size="sm" /></Card>
            <Card padded><StatTile label="Cap room" value={firstYear.room_to_cap_after >= 0 ? fmtM(firstYear.room_to_cap_after) : `−${fmtM(Math.abs(firstYear.room_to_cap_after))}`} sub={firstYear.room_to_cap_after >= 0 ? 'below salary cap' : 'over salary cap'} size="sm" /></Card>
            <Card padded><StatTile label="To first apron" value={firstYear.room_to_first_apron_after >= 0 ? fmtM(firstYear.room_to_first_apron_after) : `−${fmtM(Math.abs(firstYear.room_to_first_apron_after))}`} sub={firstYear.crosses_a_line ? `from ${CAP_TIER_LABEL[firstYear.tier_before as CapTierKey]}` : 'tier unchanged'} size="sm" /></Card>
            <Card padded><StatTile label="Committed" value={firstYear.roster_count_after} sub={`${firstYear.baseline_roster_count} baseline`} size="sm" /></Card>
          </div>
        </Surface>
      ) : (
        <div className="siq-offseason-loading">Pricing baseline…</div>
      )}

      <div className="siq-offseason-grid">
        <div className="siq-offseason-market">
          <Surface variant="instrument" eyebrow="Free-agent targets" icon={<UserRoundPlus size={15} />}
            action={<Badge tone="neutral" variant="outline" size="sm">{market?.targets.length ?? 0} ranked</Badge>}>
            {marketLoading ? <div className="siq-offseason-empty">Loading market…</div> : market?.targets.length ? (
              <div className="siq-offseason-targets">
                {market.targets.map((target) => (
                  <TargetRow key={target.player_id} target={target} added={stagedIds.has(target.player_id)} onAdd={() => addTarget(target)} />
                ))}
              </div>
            ) : <div className="siq-offseason-empty">No targets available for this class.</div>}
          </Surface>

          <Surface variant="instrument" eyebrow="Option decisions" icon={<CircleDollarSign size={15} />}
            action={<Badge tone="neutral" variant="outline" size="sm">{teamOptions.length}</Badge>}>
            {marketLoading ? <div className="siq-offseason-empty">Loading options…</div> : teamOptions.length ? (
              <div className="siq-offseason-options">
                {teamOptions.map((player) => (
                  <OptionRow
                    key={player.player_id}
                    player={player}
                    selected={declines.includes(player.player_id)}
                    onToggle={() => toggleDecline(player.player_id, declines.includes(player.player_id))}
                  />
                ))}
              </div>
            ) : <div className="siq-offseason-empty">No option decisions for this team and season.</div>}
          </Surface>
        </div>

        <div className="siq-offseason-plan-column">
          <Surface variant="instrument" eyebrow="Staged moves" icon={<CalendarRange size={15} />}
            action={(contracts.length || declines.length) ? (
              <button type="button" className="siq-icon-button" onClick={resetPlan} aria-label="Reset offseason plan" title="Reset plan"><RotateCcw size={15} /></button>
            ) : undefined}>
            {contracts.length === 0 && declines.length === 0 ? (
              <div className="siq-offseason-empty siq-offseason-empty--plan">
                <CalendarRange size={22} />
                <span>No moves staged.</span>
              </div>
            ) : (
              <div className="siq-offseason-moves">
                {contracts.map((draft) => (
                  <ContractEditor
                    key={draft.player.player_id}
                    draft={draft}
                    result={moveByPlayer.get(draft.player.player_id)}
                    onChange={(patch) => updateContract(draft.player.player_id, patch)}
                    onRemove={() => setContracts((current) => current.filter((item) => item.player.player_id !== draft.player.player_id))}
                  />
                ))}
                {declines.map((playerId) => {
                  const move = moveByPlayer.get(playerId);
                  const player = teamOptions.find((item) => item.player_id === playerId);
                  if (!player) return null;
                  return (
                    <div className="siq-offseason-decline" key={playerId}>
                      <Avatar name={player.full_name} playerId={player.player_id} position={player.position} size="sm" />
                      <div className="siq-offseason-target-id">
                        <strong>{player.full_name}</strong>
                        <span>{move ? moveLabel(move) : 'Option removal'}</span>
                      </div>
                      <span className="ds-tnum" style={{ color: 'var(--positive-text)', fontWeight: 700 }}>
                        {move ? `−${fmtM(move.removed_existing_usd)}` : '—'}
                      </span>
                      <button type="button" className="siq-icon-button" onClick={() => toggleDecline(playerId, true)} aria-label={`Restore ${player.full_name} option`} title="Restore option"><RotateCcw size={15} /></button>
                    </div>
                  );
                })}
              </div>
            )}
          </Surface>
        </div>
      </div>

      {plan ? <SeasonLedger plan={plan} /> : null}

      {plan ? (
        <AssumptionFlag title="Planning assumptions" tone="warning" icon={<TriangleAlert size={15} />}>
          {plan.caveat}
        </AssumptionFlag>
      ) : null}
    </div>
  );
}

function OffseasonContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [teams, setTeams] = useState<TeamListItem[]>([]);
  const teamParam = Number(searchParams.get('team'));
  const seasonParam = searchParams.get('season');
  const teamId = Number.isFinite(teamParam) && teamParam > 0 ? teamParam : teams[0]?.team_id ?? null;
  const season = seasonParam && SEASONS.includes(seasonParam) ? seasonParam : DEFAULT_SEASON;

  useEffect(() => {
    const controller = new AbortController();
    getTeams(controller.signal).then(setTeams).catch(() => {});
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (teamId == null) return;
    if (searchParams.get('team') === String(teamId) && searchParams.get('season') === season) return;
    router.replace(`/offseason?team=${teamId}&season=${encodeURIComponent(season)}`);
  }, [router, searchParams, season, teamId]);

  function updateRoute(nextTeam: number, nextSeason: string) {
    router.replace(`/offseason?team=${nextTeam}&season=${encodeURIComponent(nextSeason)}`);
  }

  return (
    <div className="siq-offseason-page">
      <div className="siq-offseason-toolbar">
        <span className="ds-eyebrow">Offseason plan</span>
        <select value={teamId ?? ''} onChange={(event) => updateRoute(Number(event.target.value), season)} aria-label="Select team">
          {teams.length === 0 ? <option value="">Loading teams…</option> : null}
          {teams.map((team) => <option key={team.team_id} value={team.team_id}>{team.name ?? team.abbreviation}</option>)}
        </select>
        <select value={season} onChange={(event) => teamId && updateRoute(teamId, event.target.value)} aria-label="Select offseason">
          {SEASONS.map((item) => <option key={item} value={item}>{item} offseason</option>)}
        </select>
        <Link href={`/free-agency?tab=targets&team=${teamId ?? ''}&season=${encodeURIComponent(season)}`} className="siq-secondary-button" style={{ textDecoration: 'none', marginLeft: 'auto' }}>
          Free-agency board
        </Link>
      </div>
      {teamId ? <PlannerWorkspace key={`${teamId}-${season}`} teamId={teamId} season={season} /> : <div className="siq-offseason-loading">Loading teams…</div>}
    </div>
  );
}

export default function OffseasonPage() {
  return (
    <Suspense fallback={<div className="siq-offseason-loading">Loading offseason plan…</div>}>
      <OffseasonContent />
    </Suspense>
  );
}
