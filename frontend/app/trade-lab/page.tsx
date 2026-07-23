'use client';

import {
  useDeferredValue,
  useEffect,
  useMemo,
  useState,
  type Dispatch,
  type SetStateAction,
} from 'react';
import {
  ArrowLeftRight,
  Check,
  ChevronDown,
  Info,
  LoaderCircle,
  Plus,
  Search,
  Trash2,
  TriangleAlert,
} from 'lucide-react';
import {
  analyzeTrade,
  getTeamPicks,
  getTeams,
  getTradeWorkspace,
  type CapTier,
  type ContractYearStatus,
  type SurplusPlayerDetail,
  type SurplusScenario,
  type TeamListItem,
  type TradePickAsset,
  type TradeResponse,
  type TradeTeamAnalysis,
  type TradeTeamState,
  type TradeTeamWorkspace,
  type TradeWorkspacePlayer,
} from '@/lib/api';
import { BalanceMeter, GradeChip } from '@/components/trade/BalanceMeter';
import { CapBar } from '@/components/cap/CapBar';
import { Alert } from '@/components/ui/Alert';
import { Avatar } from '@/components/ui/Avatar';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Dialog } from '@/components/ui/Dialog';
import { EmptyState } from '@/components/ui/EmptyState';
import { LoadingNote } from '@/components/ui/LoadingNote';
import { Panel } from '@/components/ui/Panel';
import { Select } from '@/components/ui/Select';
import { TeamLogo } from '@/components/ui/TeamLogo';
import { CAP_TIER_LABEL, TIER_RANK, fmtSignedM, tierIcon, tierTone } from '@/lib/present';
import { fmtM, signed } from '@/lib/utils';

const SEASON = '2026-27';

function capTransition(before: CapTier, after: CapTier): string {
  if (before === after) return `Remains ${CAP_TIER_LABEL[after].toLowerCase()}`;
  if (TIER_RANK[after] < TIER_RANK[before]) return `Moves to ${CAP_TIER_LABEL[after].toLowerCase()}`;
  return `Crosses into ${CAP_TIER_LABEL[after].toLowerCase()}`;
}

const TEAM_STATE_LABEL: Record<TradeTeamState, string> = {
  contending: 'Contending',
  neutral: 'Neutral',
  rebuilding: 'Rebuilding',
};

function useTeamPicks(teamId: number | null, teamState: TradeTeamState) {
  const [picks, setPicks] = useState<TradePickAsset[]>([]);

  useEffect(() => {
    if (!teamId) {
      setPicks([]);
      return;
    }
    const controller = new AbortController();
    getTeamPicks(teamId, teamState, controller.signal)
      .then((response) => setPicks(response.picks))
      .catch(() => { if (!controller.signal.aborted) setPicks([]); });
    return () => controller.abort();
  }, [teamId, teamState]);

  return picks;
}

interface PickSectionProps {
  picks: TradePickAsset[];
  selected: number[];
  teamState: TradeTeamState;
  onToggle: (pickId: number) => void;
  onTeamState: (state: TradeTeamState) => void;
}

function PickSection({ picks, selected, teamState, onToggle, onTeamState }: PickSectionProps) {
  const selectedSet = new Set(selected);
  const firsts = picks.filter((pick) => pick.round === 1);
  const seconds = picks.filter((pick) => pick.round === 2);

  return (
    <details className="siq-trade-details">
      <summary className="ds-tnum">
        Draft picks · {selected.length} selected
      </summary>
      <label className="siq-trade-team-select" style={{ display: 'flex', gap: 8, alignItems: 'center', margin: '8px 0' }}>
        <span className="ds-eyebrow">Team state</span>
        <Select value={teamState} onChange={(event) => onTeamState(event.target.value as TradeTeamState)}>
          {(Object.keys(TEAM_STATE_LABEL) as TradeTeamState[]).map((state) => (
            <option key={state} value={state}>{TEAM_STATE_LABEL[state]}</option>
          ))}
        </Select>
      </label>
      {[firsts, seconds].map((group, index) => group.length ? (
        <div className="siq-trade-selected-list" key={index === 0 ? 'firsts' : 'seconds'}>
          {group.map((pick) => (
            <label className="siq-trade-selected-row" key={pick.pick_id} style={{ cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={selectedSet.has(pick.pick_id)}
                onChange={() => onToggle(pick.pick_id)}
                aria-label={`Include ${pick.label}`}
              />
              <span className="siq-trade-player-id" title={pick.notes ?? undefined}>
                <strong>{pick.label}</strong>
                <small>
                  exp. #{pick.expected_pick}
                  {pick.source === 'default-ownership' ? ' · assumed own pick'
                    : pick.source === 'spotrac-conditional' ? ' · conditional terms' : ''}
                </small>
              </span>
              <strong className="ds-tnum">{pick.value_usd != null ? fmtM(pick.value_usd) : '—'}</strong>
            </label>
          ))}
        </div>
      ) : null)}
      <p className="ds-note">
        Pick values use an approximate rookie-deal surplus curve under the selected team state; ownership marked
        &ldquo;assumed&rdquo; is default self-ownership, not verified trade data.
      </p>
    </details>
  );
}

interface PlayerPickerProps {
  workspace: TradeTeamWorkspace | null;
  open: boolean;
  selected: number[];
  onClose: () => void;
  onConfirm: (ids: number[]) => void;
}

function PlayerPicker({ workspace, open, selected, onClose, onConfirm }: PlayerPickerProps) {
  const [draft, setDraft] = useState<number[]>(selected);
  const [query, setQuery] = useState('');
  const deferredQuery = useDeferredValue(query);

  useEffect(() => {
    if (open) {
      setDraft(selected);
      setQuery('');
    }
  }, [open, selected]);

  const draftSet = useMemo(() => new Set(draft), [draft]);
  const filtered = useMemo(() => {
    const normalized = deferredQuery.trim().toLowerCase();
    if (!normalized) return workspace?.players ?? [];
    return (workspace?.players ?? []).filter((player) =>
      `${player.full_name} ${player.position ?? ''}`.toLowerCase().includes(normalized),
    );
  }, [deferredQuery, workspace]);
  const selectedSalary = useMemo(() => (workspace?.players ?? []).reduce(
    (total, player) => total + (draftSet.has(player.player_id) ? player.cap_hit_usd ?? 0 : 0),
    0,
  ), [draftSet, workspace]);

  const toggle = (player: TradeWorkspacePlayer) => {
    if (!player.cap_hit_usd || player.cap_hit_usd <= 0) return;
    setDraft((current) => current.includes(player.player_id)
      ? current.filter((id) => id !== player.player_id)
      : [...current, player.player_id]);
  };

  return (
    <Dialog
      open={open && workspace != null}
      title={`Add players from ${workspace?.team.name ?? workspace?.team.abbreviation ?? 'team'}`}
      onClose={onClose}
      footer={(
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" onClick={() => { onConfirm(draft); onClose(); }}>
            Add {draft.length} {draft.length === 1 ? 'player' : 'players'} · {fmtM(selectedSalary)}
          </Button>
        </>
      )}
    >
      <p className="siq-dialog__intro">
        Select the {SEASON} salaries this team would send. Changes apply only when you confirm.
      </p>
      <label className="siq-trade-player-search">
        <Search size={16} aria-hidden="true" />
        <span className="siq-sr-only">Search roster</span>
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search by player or position"
          autoFocus
        />
      </label>
      <div className="siq-trade-picker-summary ds-tnum">
        <span>{filtered.length} rostered players</span>
        <strong>{draft.length} selected · {fmtM(selectedSalary)}</strong>
      </div>
      <div className="siq-trade-picker-list">
        {filtered.map((player) => {
          const isSelected = draftSet.has(player.player_id);
          const unavailable = !player.cap_hit_usd || player.cap_hit_usd <= 0;
          return (
            <label
              key={player.player_id}
              className={`siq-trade-picker-row${isSelected ? ' is-selected' : ''}${unavailable ? ' is-disabled' : ''}`}
              title={unavailable ? `No positive ${SEASON} cap hit is available` : undefined}
            >
              <input
                type="checkbox"
                checked={isSelected}
                disabled={unavailable}
                onChange={() => toggle(player)}
              />
              <Avatar name={player.full_name} playerId={player.player_id} position={player.position} size="sm" />
              <span className="siq-trade-player-id">
                <strong>{player.full_name}</strong>
                <small>{player.position ?? 'Position unavailable'}</small>
              </span>
              <span className="siq-trade-player-money ds-tnum">
                <strong>{player.cap_hit_usd ? fmtM(player.cap_hit_usd) : 'Salary unavailable'}</strong>
                <small>{player.salary_pct != null ? `${player.salary_pct.toFixed(1)}% of cap` : 'Cannot add'}</small>
              </span>
            </label>
          );
        })}
        {filtered.length === 0 ? <EmptyState title="No roster matches that search." /> : null}
      </div>
    </Dialog>
  );
}

interface TeamPackageProps {
  side: 'A' | 'B';
  teams: TeamListItem[];
  selectedTeam: number | null;
  disabledTeam: number | null;
  workspace: TradeTeamWorkspace | null;
  loading: boolean;
  selected: number[];
  onTeam: (id: number | null) => void;
  onAdd: () => void;
  onRemove: (id: number) => void;
  pickSection?: React.ReactNode;
}

function TeamPackage({
  side,
  teams,
  selectedTeam,
  disabledTeam,
  workspace,
  loading,
  selected,
  onTeam,
  onAdd,
  onRemove,
  pickSection,
}: TeamPackageProps) {
  const selectedSet = useMemo(() => new Set(selected), [selected]);
  const players = useMemo(
    () => (workspace?.players ?? []).filter((player) => selectedSet.has(player.player_id)),
    [selectedSet, workspace],
  );
  const outgoing = players.reduce((total, player) => total + (player.cap_hit_usd ?? 0), 0);

  return (
    <Panel
      variant="instrument"
      eyebrow={`Team ${side}`}
      action={workspace ? <Badge tone={tierTone(workspace.tier_before)}>{CAP_TIER_LABEL[workspace.tier_before]}</Badge> : undefined}
      className="siq-trade-package-panel"
    >
      <div className="siq-trade-team-head">
        {workspace ? (
          <TeamLogo
            teamId={workspace.team.team_id}
            abbreviation={workspace.team.abbreviation}
            name={workspace.team.name}
            size="lg"
          />
        ) : <span className="siq-trade-team-placeholder" aria-hidden="true">{side}</span>}
        <label className="siq-trade-team-select">
          <span className="siq-sr-only">Select Team {side}</span>
          <Select
            value={selectedTeam ?? ''}
            onChange={(event) => onTeam(event.target.value ? Number(event.target.value) : null)}
          >
            <option value="">Select a team</option>
            {teams.map((team) => (
              <option key={team.team_id} value={team.team_id} disabled={team.team_id === disabledTeam}>
                {team.name}
              </option>
            ))}
          </Select>
        </label>
      </div>

      {loading ? <LoadingNote>Loading {SEASON} roster and salaries…</LoadingNote> : null}
      {workspace && !loading ? (
        <>
          <div className="siq-trade-team-baseline ds-tnum">
            <span>Baseline payroll<strong>{fmtM(workspace.payroll_before_usd)}</strong></span>
            <span>Roster<strong>{workspace.roster_count}</strong></span>
            <span>Season<strong>{SEASON}{workspace.is_projected_cap ? ' projected' : ''}</strong></span>
          </div>
          <div className="siq-trade-package-head">
            <div>
              <span className="ds-eyebrow">Outgoing package</span>
              <strong className="ds-tnum">{players.length} {players.length === 1 ? 'player' : 'players'} · {fmtM(outgoing)}</strong>
            </div>
            <Button size="sm" variant="secondary" icon={<Plus size={15} />} onClick={onAdd}>Add player</Button>
          </div>
          {players.length ? (
            <div className="siq-trade-selected-list">
              {players.map((player) => (
                <div className="siq-trade-selected-row" key={player.player_id}>
                  <Avatar name={player.full_name} playerId={player.player_id} position={player.position} size="sm" />
                  <span className="siq-trade-player-id">
                    <strong>{player.full_name}</strong>
                    <small>{player.position ?? '—'}</small>
                  </span>
                  <strong className="ds-tnum">{fmtM(player.cap_hit_usd ?? 0)}</strong>
                  <button type="button" onClick={() => onRemove(player.player_id)} aria-label={`Remove ${player.full_name}`}>
                    <Trash2 size={16} />
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <div className="siq-trade-package-empty">
              <span>No players added.</span>
              <small>Open the roster to build this team&apos;s outgoing package.</small>
            </div>
          )}
          {pickSection}
        </>
      ) : null}
      {!selectedTeam && !loading ? <EmptyState title="Select a team to begin." description="Its Add player action will appear here." /> : null}
    </Panel>
  );
}

type FlagTone = 'positive' | 'negative' | 'warning' | 'neutral';

function FlagChip({ label, value, tone, title }: { label: string; value: string; tone: FlagTone; title?: string }) {
  return (
    <span className={`siq-flag-chip siq-flag-chip--${tone}`} title={title}>
      <span className="siq-flag-chip__k ds-eyebrow">{label}</span>
      <span className="siq-flag-chip__v">{value}</span>
    </span>
  );
}

const YEAR_STATUS_LABEL: Record<ContractYearStatus, string> = {
  guaranteed: 'Guaranteed',
  player_option: 'Player option',
  team_option: 'Team option',
  non_guaranteed: 'Non-guaranteed',
};

export function pctText(value: number | null, signedValue = false): string {
  if (value == null) return '—';
  return `${signedValue ? signed(value, 1) : value.toFixed(1)}%`;
}

export function surplusSignClass(value: number | null | undefined): string {
  if (value == null || value === 0) return '';
  return value > 0 ? 'is-positive' : 'is-negative';
}

// The auditable year-by-year math behind one player's contract-surplus number: every
// input (cap hit, modeled value %, raw surplus %, team-state discount) and the discounted
// dollar result, so the visible rows sum to the displayed total under the chosen scenario.
export function SurplusBreakdown({ detail }: { detail: SurplusPlayerDetail }) {
  return (
    <div className="siq-surplus-breakdown">
      <div className="siq-surplus-table-wrap">
        <table className="siq-surplus-table ds-tnum">
          <thead>
            <tr>
              <th className="siq-surplus-th-season">Season</th>
              <th>Cap hit</th>
              <th title="Modeled value as a % of the cap, held flat across remaining years">Value</th>
              <th title="Raw surplus %: modeled value % minus cap-hit %">Surplus</th>
              <th title="Team-state time discount factor applied to this year">Disc</th>
              <th>Surplus $</th>
            </tr>
          </thead>
          <tbody>
            {detail.years.map((year) => (
              <tr key={year.season} className={year.committed ? undefined : 'is-uncertain'}>
                <td className="siq-surplus-td-season">
                  <span>{year.season}</span>
                  <span className={`siq-year-status siq-year-status--${year.committed ? 'committed' : 'uncertain'}`}>
                    {YEAR_STATUS_LABEL[year.status]}
                  </span>
                </td>
                <td>
                  {fmtM(year.cap_hit_usd)}
                  <small>{pctText(year.cap_hit_pct)} of cap</small>
                </td>
                <td>{pctText(year.value_pct)}</td>
                <td className={surplusSignClass(year.surplus_pct)}>{pctText(year.surplus_pct, true)}</td>
                <td>{year.discount_factor.toFixed(2)}</td>
                <td className={surplusSignClass(year.discounted_surplus_usd)}>
                  {year.discounted_surplus_usd != null ? fmtSignedM(year.discounted_surplus_usd) : '—'}
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td colSpan={5}>{detail.scenario === 'committed' ? 'Committed years total' : 'All listed years total'}</td>
              <td className={surplusSignClass(detail.total_surplus_usd)}>{fmtSignedM(detail.total_surplus_usd)}</td>
            </tr>
          </tfoot>
        </table>
      </div>
      {detail.has_uncertain_years ? (
        <p className="ds-note">
          Committed only <strong>{fmtSignedM(detail.total_surplus_committed_usd)}</strong> · all listed years{' '}
          <strong>{fmtSignedM(detail.total_surplus_all_usd)}</strong>. Option and non-guaranteed years are
          excluded from the committed total, not silently counted as guaranteed.
        </p>
      ) : null}
    </div>
  );
}

// One side's outgoing package (players + picks) with salary and modeled contract surplus,
// from the sending team's own team-state lens. Each player row expands to the auditable
// year-by-year breakdown. Half of the fused Exchange.
function ExchangeSide({ analysis, toAbbr }: { analysis: TradeTeamAnalysis; toAbbr: string }) {
  const abbr = analysis.team.abbreviation ?? analysis.team.name;
  const players = analysis.selected_outgoing;
  const picks = analysis.picks_outgoing;
  const detail = analysis.assets.players_detail;
  const salaryOut = players.reduce((total, p) => total + (p.cap_hit_usd ?? 0), 0);
  const surplusOut = analysis.assets.player_surplus_sent_usd + analysis.assets.picks_sent_usd;

  return (
    <div className="siq-exchange-side">
      <header className="siq-exchange-side__head">
        <TeamLogo teamId={analysis.team.team_id} abbreviation={analysis.team.abbreviation} name={analysis.team.name} size="sm" />
        <span className="siq-exchange-side__title">
          <strong>{abbr} sends</strong>
          <small>to {toAbbr}</small>
        </span>
      </header>
      <ul className="siq-exchange-list">
        {players.map((p) => {
          const s = detail[String(p.player_id)];
          return (
            <li className="siq-exchange-row" key={p.player_id}>
              <details className="siq-surplus-toggle">
                <summary className="siq-surplus-summary">
                  <Avatar name={p.full_name} playerId={p.player_id} position={p.position} size="sm" />
                  <span className="siq-trade-player-id">
                    <strong>{p.full_name}</strong>
                    <small>{p.position ?? '—'}</small>
                  </span>
                  <span className="siq-exchange-row__num ds-tnum">
                    <strong>{fmtM(p.cap_hit_usd ?? 0)}</strong>
                    <small className={surplusSignClass(s?.total_surplus_usd)}>
                      {s ? `${fmtSignedM(s.total_surplus_usd)} surplus` : 'surplus n/a'}
                      {s?.has_uncertain_years ? <span className="siq-surplus-flag" title="Has option / non-guaranteed years">*</span> : null}
                    </small>
                  </span>
                  <ChevronDown className="siq-surplus-chevron" size={15} aria-hidden="true" />
                </summary>
                {s ? (
                  <SurplusBreakdown detail={s} />
                ) : (
                  <p className="ds-note">No modeled contract surplus for this player (value unavailable or no loaded contract).</p>
                )}
              </details>
            </li>
          );
        })}
        {picks.map((pick) => (
          <li className="siq-exchange-row siq-exchange-row--pick" key={`pick-${pick.pick_id}`}>
            <span className="siq-exchange-pick" aria-hidden="true">◆</span>
            <span className="siq-trade-player-id">
              <strong>{pick.label}</strong>
              <small>exp. #{pick.expected_pick}</small>
            </span>
            <span className="siq-exchange-row__num ds-tnum">
              <strong>{pick.value_usd != null ? fmtM(pick.value_usd) : '—'}</strong>
              <small>pick value</small>
            </span>
          </li>
        ))}
        {players.length === 0 && picks.length === 0 ? (
          <li className="siq-exchange-empty">Nothing outgoing on this side.</li>
        ) : null}
      </ul>
      <footer className="siq-exchange-side__foot ds-tnum">
        <span>{players.length} {players.length === 1 ? 'player' : 'players'}{picks.length ? ` · ${picks.length} ${picks.length === 1 ? 'pick' : 'picks'}` : ''}</span>
        <span>
          {fmtM(salaryOut)} out
          <strong className={surplusOut >= 0 ? 'is-positive' : 'is-negative'} title="Total modeled contract surplus + pick value leaving this side.">
            {' · '}{fmtSignedM(surplusOut)} surplus
          </strong>
        </span>
      </footer>
    </div>
  );
}

const SCENARIO_LABEL: Record<SurplusScenario, string> = {
  committed: 'Committed years',
  all: 'All listed years',
};

// The fused deal: both outgoing packages in one read. The scenario toggle governs which
// contract years feed every surplus number below (and the balance meter above).
function TradeExchange({
  result,
  scenario,
  onScenario,
  busy,
}: {
  result: TradeResponse;
  scenario: SurplusScenario;
  onScenario: (scenario: SurplusScenario) => void;
  busy: boolean;
}) {
  const a = result.team_a.team.abbreviation ?? 'A';
  const b = result.team_b.team.abbreviation ?? 'B';
  return (
    <section className="siq-exchange">
      <header className="siq-exchange__head">
        <span className="ds-eyebrow">The exchange</span>
        <small>What each side gives up — salary and modeled contract surplus. Tap a player for the year-by-year math.</small>
        <div className="siq-scenario-toggle" role="group" aria-label="Contract-year scenario">
          {(Object.keys(SCENARIO_LABEL) as SurplusScenario[]).map((key) => (
            <button
              key={key}
              type="button"
              className={`siq-scenario-btn${scenario === key ? ' is-active' : ''}`}
              aria-pressed={scenario === key}
              disabled={busy}
              onClick={() => onScenario(key)}
              title={key === 'committed'
                ? 'Count only fully guaranteed years (options excluded).'
                : 'Count every listed year, including options and non-guaranteed years (upside/downside).'}
            >
              {SCENARIO_LABEL[key]}
            </button>
          ))}
        </div>
      </header>
      <p className="siq-exchange__legend ds-note">
        <Info size={13} aria-hidden="true" />
        <span>
          <strong>Contract surplus</strong> is modeled value minus salary owed over a player&apos;s remaining years, from
          each team&apos;s own team-state lens. Positive means the model values the player above their salary; negative
          means the salary owed exceeds modeled value. It is not total trade-market value.
        </span>
      </p>
      <div className="siq-exchange__grid">
        <ExchangeSide analysis={result.team_a} toAbbr={b} />
        <div className="siq-exchange__swap" aria-hidden="true"><ArrowLeftRight size={18} /></div>
        <ExchangeSide analysis={result.team_b} toAbbr={a} />
      </div>
    </section>
  );
}

// Per-team consequences only — cap trajectory, quick legality flags, fit shift —
// with the CBA math tucked into an on-demand drawer. The value/pick inventory
// lives in the Exchange above; this panel answers "what does it do to this team".
function Impact({ analysis }: { analysis: TradeTeamAnalysis }) {
  const cap = analysis.cap_context;
  const sm = analysis.salary_match;
  const pl = analysis.pick_legality;
  const rl = analysis.roster_legality;
  const abbr = analysis.team.abbreviation ?? analysis.team.name;
  const hasPicks = analysis.picks_outgoing.length > 0 || analysis.picks_incoming.length > 0;
  const coverage = analysis.value.sent_coverage + analysis.value.received_coverage;
  const selected = analysis.value.sent_selected + analysis.value.received_selected;

  const salaryTone: FlagTone = sm.status === 'pass' ? 'positive' : sm.status === 'fail' ? 'negative' : 'warning';
  const stepienTone: FlagTone = !pl ? 'neutral'
    : pl.status === 'pass' || pl.status === 'not-applicable' ? 'positive'
    : pl.status === 'fail' ? 'negative' : 'warning';

  return (
    <section className={`siq-trade-impact siq-trade-impact--${analysis.tier_after}`}>
      <header className="siq-trade-impact-head">
        <div>
          <span className="ds-eyebrow">{abbr} cap trajectory</span>
          <h3>{capTransition(analysis.tier_before, analysis.tier_after)}</h3>
        </div>
        <Badge tone={tierTone(analysis.tier_after)} icon={tierIcon(analysis.tier_after)}>
          {CAP_TIER_LABEL[analysis.tier_after]}
        </Badge>
      </header>
      <div className="siq-trade-payroll-shift ds-tnum">
        <span>Before<strong>{fmtM(analysis.payroll_before_usd)}</strong></span>
        <ArrowLeftRight size={18} aria-hidden="true" />
        <span>After<strong>{fmtM(analysis.payroll_after_usd)}</strong></span>
      </div>
      <CapBar
        value={analysis.payroll_after_usd}
        taxLine={cap.tax_line}
        firstApron={cap.first_apron}
        secondApron={cap.second_apron}
        showLabels
        valueLabel="After"
      />
      <div className="siq-trade-flags">
        <FlagChip
          label="Salary match"
          value={sm.status === 'pass' ? 'Works' : sm.status === 'fail' ? 'Over limit' : sm.status === 'incomplete' ? '—' : 'Review'}
          tone={salaryTone}
          title="CBA salary matching: the incoming salary must fit an allowed band set by the outgoing salary and this team's cap tier."
        />
        {hasPicks && pl ? (
          <FlagChip
            label="Stepien"
            value={pl.status === 'not-applicable' ? 'n/a' : pl.status === 'pass' ? 'OK' : pl.status === 'fail' ? 'Fails' : 'Review'}
            tone={stepienTone}
            title="Stepien rule: a team can't trade away first-round picks in consecutive future drafts."
          />
        ) : null}
        <FlagChip
          label="Roster"
          value={rl.status === 'pass' ? `~${rl.standard_after} standard` : 'Review'}
          tone={rl.status === 'pass' ? 'neutral' : 'warning'}
          title="Standard-contract count after the trade (two-way players excluded). Max 15, min 14; counts are approximate."
        />
      </div>
      {analysis.fit_changes.length ? (
        <div className="siq-trade-fit">
          <span className="ds-eyebrow">Roster fit shift</span>
          {analysis.fit_changes.slice(0, 2).map((change) => (
            <p className="ds-note ds-tnum" key={change.key}>
              {change.label}: <strong className={change.delta_pct >= 0 ? 'is-positive' : 'is-negative'}>{signed(change.delta_pct)} pts</strong>
              <small> ({change.before_pct.toFixed(0)}% → {change.after_pct.toFixed(0)}%)</small>
            </p>
          ))}
        </div>
      ) : null}
      <details className="siq-trade-details">
        <summary>The math · salary, picks, roster</summary>
        <div className="siq-trade-secondary-grid ds-tnum">
          <span title="Total salary this team sends out.">Outgoing<strong>{fmtM(analysis.outgoing_salary_usd)}</strong></span>
          <span title="Total salary this team takes back.">Incoming<strong>{fmtM(analysis.incoming_salary_usd)}</strong></span>
          <span title="The most salary this team may take back under the matched rule.">Allowed back<strong>{fmtM(sm.allowed_incoming)}</strong></span>
          <span title="Headroom under the allowed incoming; negative means over by that much.">Margin<strong className={sm.margin >= 0 ? 'is-positive' : 'is-negative'}>{fmtSignedM(sm.margin)}</strong></span>
        </div>
        {sm.reasons.map((reason) => <p className="ds-note" key={reason}>{reason}</p>)}
        {pl?.reasons.map((reason) => <p className="ds-note" key={reason}>{reason}</p>)}
        {rl.reasons.map((reason) => <p className="ds-note" key={reason}>{reason}</p>)}
        <div className="siq-trade-secondary-grid ds-tnum">
          <span title="Standard contracts before → after; two-way players excluded from the count.">
            Standard roster<strong>{rl.standard_before} → ~{rl.standard_after}</strong><small>{rl.two_way_count} two-way excluded</small>
          </span>
          <span title="How many of the players involved on this side the model could value.">
            Model coverage<strong>{coverage}/{selected || 0}</strong><small>players valued · fit {analysis.fit_after.confidence}</small>
          </span>
        </div>
      </details>
    </section>
  );
}

const LEGALITY_WORD: Record<string, string> = {
  'modeled-compliant': 'Works',
  'modeled-noncompliant': 'Blocked',
  'needs-review': 'Needs review',
  'incomplete': 'Incomplete',
};

export function TradeVerdictBar({ result, stale }: { result: TradeResponse; stale: boolean }) {
  const { balance } = result;
  const status = result.overall_status;
  const tone = status === 'modeled-compliant' ? 'positive'
    : status === 'modeled-noncompliant' ? 'negative' : 'warning';
  const a = result.team_a.team.abbreviation ?? 'A';
  const b = result.team_b.team.abbreviation ?? 'B';
  const label = balance.fairness_label.replace('Team A', a).replace('Team B', b);
  const cap = result.cap_reference;

  return (
    <section className={`siq-trade-verdict-bar siq-trade-verdict-bar--${status}`}>
      <div className="siq-trade-verdict-legality" data-tone={tone}>
        <div className="siq-trade-verdict-stamp">
          <span className="ds-eyebrow">Trade verdict · salary &amp; legality</span>
          <div className="siq-trade-verdict-stamp-row">
            <Badge tone={tone} icon={tone === 'positive' ? <Check size={14} /> : <TriangleAlert size={14} />}>
              {LEGALITY_WORD[status] ?? 'Review'}
            </Badge>
            {stale ? <Badge tone="warning" icon={<TriangleAlert size={13} />}>Prior result</Badge> : null}
          </div>
        </div>
        <h2>{result.overall_label}</h2>
        <p>{result.summary}</p>
        {result.review_reasons.length ? (
          <ul className="siq-trade-review-reasons">
            {result.review_reasons.map((reason) => (
              <li key={reason}><TriangleAlert size={13} aria-hidden="true" /><span>{reason}</span></li>
            ))}
          </ul>
        ) : null}
        <p className="siq-trade-cap-ref ds-note">
          Priced against the {cap.season}{cap.is_projected ? ' projected' : ''} cap of {fmtM(cap.salary_cap_usd)}.
          Salary matching, contract surplus, and roster legality are independent checks.
        </p>
      </div>
      <div className="siq-trade-verdict-balance">
        <span className="ds-eyebrow">Value balance</span>
        <BalanceMeter
          fairnessPct={balance.fairness_pct}
          tier={balance.fairness_tier}
          label={label}
          netUsd={balance.net_usd}
          leftAbbr={a}
          rightAbbr={b}
          lowConfidence={balance.low_confidence}
        />
        <div className="siq-trade-grades">
          <GradeChip grade={balance.team_a_grade} teamAbbr={a} lowConfidence={balance.low_confidence} />
          <GradeChip grade={balance.team_b_grade} teamAbbr={b} lowConfidence={balance.low_confidence} />
        </div>
      </div>
    </section>
  );
}

function useTradeWorkspace(
  teamId: number | null,
  setError: Dispatch<SetStateAction<string | null>>,
) {
  const [workspace, setWorkspace] = useState<TradeTeamWorkspace | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!teamId) {
      setWorkspace(null);
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    getTradeWorkspace(teamId, SEASON, controller.signal)
      .then(setWorkspace)
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Team roster could not be loaded.');
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [setError, teamId]);

  return { workspace, loading };
}

export default function TradeLabPage() {
  const [teams, setTeams] = useState<TeamListItem[]>([]);
  const [teamA, setTeamA] = useState<number | null>(null);
  const [teamB, setTeamB] = useState<number | null>(null);
  const [teamASends, setTeamASends] = useState<number[]>([]);
  const [teamBSends, setTeamBSends] = useState<number[]>([]);
  const [teamASendsPicks, setTeamASendsPicks] = useState<number[]>([]);
  const [teamBSendsPicks, setTeamBSendsPicks] = useState<number[]>([]);
  const [teamAState, setTeamAState] = useState<TradeTeamState>('neutral');
  const [teamBState, setTeamBState] = useState<TradeTeamState>('neutral');
  const [surplusScenario, setSurplusScenario] = useState<SurplusScenario>('committed');
  const [picker, setPicker] = useState<'a' | 'b' | null>(null);
  const [result, setResult] = useState<TradeResponse | null>(null);
  const [analyzedKey, setAnalyzedKey] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [teamsRetry, setTeamsRetry] = useState(0);
  const teamAWorkspace = useTradeWorkspace(teamA, setError);
  const teamBWorkspace = useTradeWorkspace(teamB, setError);
  const teamAPicks = useTeamPicks(teamA, teamAState);
  const teamBPicks = useTeamPicks(teamB, teamBState);

  useEffect(() => {
    const controller = new AbortController();
    getTeams(controller.signal).then(setTeams).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Teams could not be loaded.');
    });
    return () => controller.abort();
  }, [teamsRetry]);

  const buildKey = (scenario: SurplusScenario) => [
    teamA, teamB, teamASends.join(','), teamBSends.join(','),
    teamASendsPicks.join(','), teamBSendsPicks.join(','), teamAState, teamBState, scenario,
  ].join(':');
  const currentKey = buildKey(surplusScenario);
  const stale = result != null && analyzedKey !== currentKey;
  const canAnalyze = Boolean(
    teamA && teamB && teamA !== teamB
    && teamASends.length > 0 && teamBSends.length > 0
    && !teamAWorkspace.loading && !teamBWorkspace.loading,
  );

  const runAnalysis = async (scenario: SurplusScenario = surplusScenario) => {
    if (!teamA || !teamB || !canAnalyze) return;
    const requestKey = buildKey(scenario);
    setAnalyzing(true);
    setError(null);
    try {
      const next = await analyzeTrade({
        season: SEASON,
        team_a_id: teamA,
        team_b_id: teamB,
        team_a_sends: teamASends,
        team_b_sends: teamBSends,
        team_a_sends_picks: teamASendsPicks,
        team_b_sends_picks: teamBSendsPicks,
        team_a_state: teamAState,
        team_b_state: teamBState,
        surplus_scenario: scenario,
      });
      setResult(next);
      setAnalyzedKey(requestKey);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : 'Trade analysis failed.');
    } finally {
      setAnalyzing(false);
    }
  };

  // Flipping the scenario re-prices surplus immediately when a result already exists,
  // rather than leaving it stale behind an Analyze click (it only changes surplus math).
  const changeScenario = (scenario: SurplusScenario) => {
    if (scenario === surplusScenario) return;
    setSurplusScenario(scenario);
    if (result && canAnalyze && !analyzing) runAnalysis(scenario);
  };

  const chooseTeamA = (id: number | null) => {
    setTeamA(id);
    setTeamASends([]);
    setTeamASendsPicks([]);
    setResult(null);
    setAnalyzedKey(null);
  };
  const chooseTeamB = (id: number | null) => {
    setTeamB(id);
    setTeamBSends([]);
    setTeamBSendsPicks([]);
    setResult(null);
    setAnalyzedKey(null);
  };
  const togglePick = (side: 'a' | 'b') => (pickId: number) => {
    const setter = side === 'a' ? setTeamASendsPicks : setTeamBSendsPicks;
    setter((current) => current.includes(pickId)
      ? current.filter((id) => id !== pickId)
      : [...current, pickId]);
  };

  return (
    <div className="siq-trade-page">
      <header className="siq-trade-heading">
        <span className="ds-eyebrow">Manual two-team workspace · {SEASON} projected</span>
        <h1>Trade lab</h1>
        <p>Select two teams, build each outgoing package, then run a modeled salary and cap check.</p>
      </header>

      {error ? (
        <Alert tone="negative" title="Trade lab unavailable">
          {error} <Button size="sm" variant="secondary" onClick={() => setTeamsRetry((value) => value + 1)}>Retry teams</Button>
        </Alert>
      ) : null}

      <div className="siq-trade-board">
        <TeamPackage
          side="A"
          teams={teams}
          selectedTeam={teamA}
          disabledTeam={teamB}
          workspace={teamAWorkspace.workspace}
          loading={teamAWorkspace.loading}
          selected={teamASends}
          onTeam={chooseTeamA}
          onAdd={() => setPicker('a')}
          onRemove={(id) => setTeamASends((current) => current.filter((playerId) => playerId !== id))}
          pickSection={teamA ? (
            <PickSection
              picks={teamAPicks}
              selected={teamASendsPicks}
              teamState={teamAState}
              onToggle={togglePick('a')}
              onTeamState={setTeamAState}
            />
          ) : null}
        />
        <div className="siq-trade-exchange" aria-label={`${teamASends.length} players from Team A and ${teamBSends.length} from Team B`}>
          <ArrowLeftRight size={20} />
          <span>{teamASends.length} A · {teamBSends.length} B</span>
        </div>
        <TeamPackage
          side="B"
          teams={teams}
          selectedTeam={teamB}
          disabledTeam={teamA}
          workspace={teamBWorkspace.workspace}
          loading={teamBWorkspace.loading}
          selected={teamBSends}
          onTeam={chooseTeamB}
          onAdd={() => setPicker('b')}
          onRemove={(id) => setTeamBSends((current) => current.filter((playerId) => playerId !== id))}
          pickSection={teamB ? (
            <PickSection
              picks={teamBPicks}
              selected={teamBSendsPicks}
              teamState={teamBState}
              onToggle={togglePick('b')}
              onTeamState={setTeamBState}
            />
          ) : null}
        />
      </div>

      <div className="siq-trade-action-bar" aria-live="polite">
        <div>
          <strong>{canAnalyze ? 'Packages ready for analysis' : 'Add at least one player from each team'}</strong>
          <span>{stale ? 'Changes not analyzed. Run the model again to refresh the result.' : 'Analysis runs only when you choose—roster edits stay local.'}</span>
        </div>
        {stale ? <Badge tone="warning" icon={<TriangleAlert size={14} />}>Changes not analyzed</Badge> : null}
        <Button
          variant="primary"
          icon={analyzing ? <LoaderCircle size={16} className="siq-spin" /> : <ArrowLeftRight size={16} />}
          disabled={!canAnalyze || analyzing}
          onClick={() => runAnalysis()}
        >
          {analyzing ? 'Analyzing trade…' : stale ? 'Analyze changes' : 'Analyze trade'}
        </Button>
      </div>

      {result ? (
        <section className={`siq-trade-results${stale ? ' is-stale' : ''}`} aria-busy={analyzing}>
          <TradeVerdictBar result={result} stale={stale} />
          <TradeExchange result={result} scenario={surplusScenario} onScenario={changeScenario} busy={analyzing} />
          <div className="siq-trade-impacts">
            <Impact analysis={result.team_a} />
            <Impact analysis={result.team_b} />
          </div>
          <details className="siq-trade-assumptions">
            <summary>Model assumptions and exclusions</summary>
            <p>{result.assumptions.join(' ')}</p>
            <p><strong>Not modeled:</strong> {result.not_modeled.join('; ')}.</p>
          </details>
        </section>
      ) : null}

      <PlayerPicker
        workspace={teamAWorkspace.workspace}
        open={picker === 'a'}
        selected={teamASends}
        onClose={() => setPicker(null)}
        onConfirm={setTeamASends}
      />
      <PlayerPicker
        workspace={teamBWorkspace.workspace}
        open={picker === 'b'}
        selected={teamBSends}
        onClose={() => setPicker(null)}
        onConfirm={setTeamBSends}
      />
    </div>
  );
}
