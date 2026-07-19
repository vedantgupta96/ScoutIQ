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
  type TeamListItem,
  type TradePickAsset,
  type TradeResponse,
  type TradeTeamAnalysis,
  type TradeTeamState,
  type TradeTeamWorkspace,
  type TradeWorkspacePlayer,
} from '@/lib/api';
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
              <span className="siq-trade-player-id">
                <strong>{pick.label}</strong>
                <small>exp. #{pick.expected_pick}{pick.source === 'default-ownership' ? ' · assumed own pick' : ''}</small>
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

function Impact({ analysis }: { analysis: TradeTeamAnalysis }) {
  const tone = analysis.salary_match.status === 'pass'
    ? 'positive'
    : analysis.salary_match.status === 'fail' ? 'negative' : 'warning';
  const hasValue = analysis.value.sent_coverage + analysis.value.received_coverage > 0;
  const cap = analysis.cap_context;

  return (
    <section className={`siq-trade-impact siq-trade-impact--${analysis.tier_after}`}>
      <header className="siq-trade-impact-head">
        <div>
          <span className="ds-eyebrow">{analysis.team.abbreviation} cap pressure</span>
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
      <div className="siq-trade-match">
        <div className="siq-trade-match-head">
          <span className="ds-eyebrow">Salary matching</span>
          <Badge tone={tone}>{analysis.salary_match.rule_label}</Badge>
        </div>
        <div className="siq-trade-match-grid ds-tnum">
          <span>Outgoing<strong>{fmtM(analysis.outgoing_salary_usd)}</strong></span>
          <span>Incoming<strong>{fmtM(analysis.incoming_salary_usd)}</strong></span>
          <span>Allowed incoming<strong>{fmtM(analysis.salary_match.allowed_incoming)}</strong></span>
          <span>Rule margin<strong className={analysis.salary_match.margin >= 0 ? 'is-positive' : 'is-negative'}>{fmtSignedM(analysis.salary_match.margin)}</strong></span>
        </div>
        {analysis.salary_match.reasons.map((reason) => <p className="ds-note" key={reason}>{reason}</p>)}
      </div>
      {(analysis.picks_outgoing.length > 0 || analysis.picks_incoming.length > 0) ? (
        <div className="siq-trade-match">
          <div className="siq-trade-match-head">
            <span className="ds-eyebrow">Draft picks · {TEAM_STATE_LABEL[analysis.team_state]} lens</span>
            {analysis.pick_legality ? (
              <Badge tone={
                analysis.pick_legality.status === 'pass' || analysis.pick_legality.status === 'not-applicable'
                  ? 'positive'
                  : analysis.pick_legality.status === 'fail' ? 'negative' : 'warning'
              }>
                {analysis.pick_legality.status === 'not-applicable' ? 'Stepien n/a' : `Stepien ${analysis.pick_legality.status}`}
              </Badge>
            ) : null}
          </div>
          <div className="siq-trade-match-grid ds-tnum">
            <span>Picks out<strong>{analysis.picks_outgoing.length ? `${analysis.picks_outgoing.length} · ${fmtM(analysis.assets.picks_sent_usd)}` : '—'}</strong></span>
            <span>Picks in<strong>{analysis.picks_incoming.length ? `${analysis.picks_incoming.length} · ${fmtM(analysis.assets.picks_received_usd)}` : '—'}</strong></span>
            <span>Net assets<strong className={analysis.assets.net_usd >= 0 ? 'is-positive' : 'is-negative'}>{fmtSignedM(analysis.assets.net_usd)}</strong></span>
            <span>Player surplus<strong>{fmtSignedM(analysis.assets.player_surplus_received_usd - analysis.assets.player_surplus_sent_usd)}</strong></span>
          </div>
          {[...analysis.picks_outgoing.map((pick) => `Out: ${pick.label}`),
            ...analysis.picks_incoming.map((pick) => `In: ${pick.label}`)].map((line) => (
            <p className="ds-note" key={line}>{line}</p>
          ))}
          {analysis.pick_legality?.reasons.map((reason) => <p className="ds-note" key={reason}>{reason}</p>)}
        </div>
      ) : null}
      <details className="siq-trade-details">
        <summary>Model value and roster fit</summary>
        <div className="siq-trade-secondary-grid ds-tnum">
          <span>Modeled value<strong>{hasValue ? `${fmtM(analysis.value.sent_usd)} sent / ${fmtM(analysis.value.received_usd)} received` : 'Unavailable'}</strong><small>{analysis.value.sent_coverage}/{analysis.value.sent_selected} sent · {analysis.value.received_coverage}/{analysis.value.received_selected} received valued</small></span>
          <span>Value change<strong>{hasValue ? fmtSignedM(analysis.value.delta_usd) : '—'}</strong></span>
          <span>Roster count<strong>{analysis.roster_count_before} → {analysis.roster_count_after}</strong></span>
          <span>Fit confidence<strong>{analysis.fit_after.confidence}</strong></span>
        </div>
        {analysis.fit_changes.map((change) => (
          <p className="ds-note ds-tnum" key={change.key}>
            {change.label}: {change.before_pct.toFixed(1)}% → {change.after_pct.toFixed(1)}% ({signed(change.delta_pct)} pts)
          </p>
        ))}
      </details>
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

  const currentKey = [
    teamA, teamB, teamASends.join(','), teamBSends.join(','),
    teamASendsPicks.join(','), teamBSendsPicks.join(','), teamAState, teamBState,
  ].join(':');
  const stale = result != null && analyzedKey !== currentKey;
  const canAnalyze = Boolean(
    teamA && teamB && teamA !== teamB
    && teamASends.length > 0 && teamBSends.length > 0
    && !teamAWorkspace.loading && !teamBWorkspace.loading,
  );

  const runAnalysis = async () => {
    if (!teamA || !teamB || !canAnalyze) return;
    const requestKey = currentKey;
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
      });
      setResult(next);
      setAnalyzedKey(requestKey);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : 'Trade analysis failed.');
    } finally {
      setAnalyzing(false);
    }
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
          onClick={runAnalysis}
        >
          {analyzing ? 'Analyzing trade…' : stale ? 'Analyze changes' : 'Analyze trade'}
        </Button>
      </div>

      {result ? (
        <section className={`siq-trade-results${stale ? ' is-stale' : ''}`} aria-busy={analyzing}>
          <header className={`siq-trade-verdict siq-trade-verdict--${result.overall_status}`}>
            <div>
              <span className="ds-eyebrow">Modeled salary verdict</span>
              <h2>{result.overall_label}</h2>
              <p>{result.summary}</p>
            </div>
            <Badge
              tone={result.overall_status === 'modeled-compliant' ? 'positive' : result.overall_status === 'modeled-noncompliant' ? 'negative' : 'warning'}
              icon={result.overall_status === 'modeled-compliant' ? <Check size={14} /> : <TriangleAlert size={14} />}
            >
              {stale ? 'Prior result' : 'Current result'}
            </Badge>
          </header>
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
