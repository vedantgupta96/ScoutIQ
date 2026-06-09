'use client';

import { useEffect, useState, use, type CSSProperties, type ReactNode } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import {
  ArrowLeft,
  Scale,
  Activity,
  BarChart3,
  SlidersHorizontal,
  Info,
  ClipboardCheck,
  FileText,
  Users,
  Target,
  DollarSign,
  GitCompare,
} from 'lucide-react';
import {
  getPlayerContract,
  getPlayerScoutRatings,
  getSimilarPlayers,
  getValuation,
  PlayerContractResponse,
  PlayerContractYear,
  PlayerScoutRatingsResponse,
  PlayerScoutTraitRating,
  SimilarPlayerResult,
  SimilarPlayersMode,
  SimilarPlayersResponse,
  ValuationResponse,
  teamLogoUrl,
} from '@/lib/api';
import { Card } from '@/components/ui/Card';
import { Surface } from '@/components/ui/Surface';
import { Badge } from '@/components/ui/Badge';
import { StatTile } from '@/components/ui/StatTile';
import { VerdictPill } from '@/components/ui/VerdictPill';
import { AssumptionFlag } from '@/components/ui/AssumptionFlag';
import { Avatar } from '@/components/ui/Avatar';
import { TeamLogo } from '@/components/ui/TeamLogo';
import { ValueGauge } from '@/components/players/ValueGauge';
import { MiniValuePayGauge } from '@/components/players/MiniValuePayGauge';
import { PlayerCutout } from '@/components/players/PlayerCutout';
import { fmtM, fmtPct, signed } from '@/lib/utils';
import { teamVisual } from '@/lib/teamVisuals';

function StatRow({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'baseline', justifyContent: 'space-between',
      padding: '8px 0', borderBottom: '1px solid var(--border-subtle)',
    }}>
      <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>{label}</span>
      <span className="ds-tnum" style={{
        fontSize: 14, fontWeight: 600,
        color: warn ? 'var(--warning-text)' : 'var(--text-primary)',
      }}>
        {value}
      </span>
    </div>
  );
}

// Feature metadata: label + how to format the raw value from the API.
// Keys match the actual column names in features.py (some are uppercase NBA_ADV keys).
const FEATURE_META: Record<string, { label: string; fmt: (v: number) => string }> = {
  // Base
  age:        { label: 'Age',              fmt: (v) => v.toFixed(0) },
  gp:         { label: 'Games played',     fmt: (v) => v.toFixed(0) },
  minutes:    { label: 'Season minutes',   fmt: (v) => Math.round(v).toLocaleString() },
  // Per-game box (API returns _pg suffix)
  pts_pg:     { label: 'Points / game',    fmt: (v) => v.toFixed(1) },
  reb_pg:     { label: 'Rebounds / game',  fmt: (v) => v.toFixed(1) },
  ast_pg:     { label: 'Assists / game',   fmt: (v) => v.toFixed(1) },
  stl_pg:     { label: 'Steals / game',    fmt: (v) => v.toFixed(1) },
  blk_pg:     { label: 'Blocks / game',    fmt: (v) => v.toFixed(1) },
  tov_pg:     { label: 'Turnovers / game', fmt: (v) => v.toFixed(1) },
  fg3m_pg:    { label: '3PM / game',       fmt: (v) => v.toFixed(1) },
  // NBA.com Advanced (uppercase keys from API)
  TS_PCT:     { label: 'True shooting',    fmt: (v) => (v * 100).toFixed(1) + '%' },
  EFG_PCT:    { label: 'eFG%',             fmt: (v) => (v * 100).toFixed(1) + '%' },
  USG_PCT:    { label: 'Usage rate',       fmt: (v) => (v * 100).toFixed(1) + '%' },
  PIE:        { label: 'PIE',              fmt: (v) => (v * 100).toFixed(1) + '%' },
  OFF_RATING: { label: 'Off. rating',      fmt: (v) => v.toFixed(1) },
  DEF_RATING: { label: 'Def. rating',      fmt: (v) => v.toFixed(1) },
  NET_RATING: { label: 'Net rating',       fmt: (v) => (v >= 0 ? '+' : '') + v.toFixed(1) },
  AST_PCT:    { label: 'Ast. %',           fmt: (v) => (v * 100).toFixed(1) + '%' },
  OREB_PCT:   { label: 'OReb. %',          fmt: (v) => (v * 100).toFixed(1) + '%' },
  DREB_PCT:   { label: 'DReb. %',          fmt: (v) => (v * 100).toFixed(1) + '%' },
  REB_PCT:    { label: 'Reb. %',           fmt: (v) => (v * 100).toFixed(1) + '%' },
  TM_TOV_PCT: { label: 'Team TOV %',       fmt: (v) => (v * 100).toFixed(1) + '%' },
  PACE:       { label: 'Pace',             fmt: (v) => v.toFixed(1) },
  // BBRef advanced (uppercase)
  BPM:        { label: 'BPM',              fmt: (v) => (v >= 0 ? '+' : '') + v.toFixed(1) },
  OBPM:       { label: 'Off. BPM',         fmt: (v) => (v >= 0 ? '+' : '') + v.toFixed(1) },
  DBPM:       { label: 'Def. BPM',         fmt: (v) => (v >= 0 ? '+' : '') + v.toFixed(1) },
  VORP:       { label: 'VORP',             fmt: (v) => v.toFixed(1) },
  WS:         { label: 'Win Shares',       fmt: (v) => v.toFixed(1) },
  WS48:       { label: 'WS / 48',          fmt: (v) => v.toFixed(3) },
  PER:        { label: 'PER',              fmt: (v) => v.toFixed(1) },
};

function formatFeatureValue(key: string, value: number): { label: string; formatted: string } {
  const meta = FEATURE_META[key];
  if (meta) return { label: meta.label, formatted: meta.fmt(value) };
  return { label: key.replace(/_/g, ' '), formatted: value.toFixed(2) };
}

function traitLabel(trait: string): string {
  if (trait === 'basketball_iq') return 'Basketball IQ';
  return trait
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function ScoutTraitRow({ trait }: { trait: PlayerScoutTraitRating }) {
  const score = Math.min(5, Math.max(0, trait.average_score));
  const width = `${score / 5 * 100}%`;
  // Quality tone for the score readout: low (red) → mid (amber) → high (green).
  const scoreColor = score < 2.5 ? 'var(--negative-text)' : score < 3.75 ? 'var(--warning-text)' : 'var(--positive-text)';
  const topEvidence = trait.evidence[0];
  return (
    <div style={{ padding: '9px 0', borderBottom: '1px solid var(--border-subtle)' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>{traitLabel(trait.trait)}</span>
        <span className="ds-tnum" style={{ fontSize: 13, fontWeight: 700, color: scoreColor }}>
          {trait.average_score.toFixed(1)}/5
        </span>
      </div>
      {/* Full-width quality gradient; a dim overlay masks the unreached portion
          so the visible fill edge sits at the true score color. */}
      <div style={{
        position: 'relative', height: 8, marginTop: 7, borderRadius: 'var(--radius-pill)',
        background: 'var(--grad-quality)', overflow: 'hidden',
        boxShadow: 'inset 0 1px 2px rgba(16,24,40,0.06)',
      }}>
        <div style={{ position: 'absolute', top: 0, bottom: 0, left: width, right: 0, background: 'var(--bg-inset)' }} />
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 6, minWidth: 0 }}>
        <Badge tone={trait.confidence_mix.high > 0 ? 'confidence' : 'neutral'} size="sm">
          {trait.report_count} report{trait.report_count === 1 ? '' : 's'}
        </Badge>
        {topEvidence && (
          <span style={{ fontSize: 11, color: 'var(--text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            &quot;{topEvidence}&quot;
          </span>
        )}
      </div>
    </div>
  );
}

function ScoutRatingsCard({ ratings, error }: { ratings: PlayerScoutRatingsResponse | null; error: string | null }) {
  return (
    <Surface
      variant="dossier"
      teamAccent
      eyebrow="Scout ratings"
      icon={<ClipboardCheck size={15} />}
      action={<Badge tone="warning" variant="outline" size="sm">synthetic fixture</Badge>}
    >
      {error ? (
        <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: 0, lineHeight: 1.5 }}>
          Scout-rating fixture unavailable: {error}
        </p>
      ) : ratings == null ? (
        <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: 0 }}>Loading scout ratings…</p>
      ) : ratings.report_count === 0 ? (
        <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: 0, lineHeight: 1.5 }}>
          No synthetic scout-report fixture exists for this player yet.
        </p>
      ) : (
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
            <span style={{ fontSize: 22, fontWeight: 800, color: 'var(--text-primary)', lineHeight: 1 }}>
              {ratings.report_count}
            </span>
            <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
              synthetic report{ratings.report_count === 1 ? '' : 's'} aggregated
            </span>
          </div>
          {ratings.traits.map((trait) => <ScoutTraitRow key={trait.trait} trait={trait} />)}
          <p style={{ fontSize: 11, color: 'var(--text-muted)', margin: '10px 0 0', lineHeight: 1.5 }}>
            {ratings.caveat}
          </p>
        </>
      )}
    </Surface>
  );
}

function ContractYearRow({ year }: { year: PlayerContractYear }) {
  const optionLabel = year.is_player_option ? 'Player opt.' : year.is_team_option ? 'Team opt.' : null;
  const gap = year.value_gap_pct;
  const gapColor = gap == null
    ? 'var(--text-muted)'
    : gap >= 0 ? 'var(--positive-text)' : 'var(--negative-text)';
  const barFill = gap == null
    ? 'var(--border-strong)'
    : gap >= 0 ? 'var(--grad-positive)' : 'var(--grad-negative)';

  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: '76px minmax(0, 1fr) auto',
      gap: 10,
      alignItems: 'center',
      padding: '10px 0',
      borderBottom: '1px solid var(--border-subtle)',
    }}>
      <span className="ds-tnum" style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)' }}>
        {year.season}
      </span>
      <div style={{ minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 7, flexWrap: 'wrap' }}>
          <span className="ds-tnum" style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)' }}>
            {year.cap_hit_usd != null ? fmtM(year.cap_hit_usd) : '—'}
          </span>
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            {year.cap_hit_pct != null ? fmtPct(year.cap_hit_pct) + ' of cap' : 'cap % unavailable'}
          </span>
          {optionLabel && <Badge tone="warning" variant="outline" size="sm">{optionLabel}</Badge>}
          {!year.is_guaranteed && !optionLabel && <Badge tone="neutral" variant="outline" size="sm">Non-gtd</Badge>}
        </div>
        {year.value_pct != null && (
          <div style={{ marginTop: 4, fontSize: 11, color: 'var(--text-muted)' }}>
            Model value {fmtPct(year.value_pct)} of cap
          </div>
        )}
        {year.cap_hit_pct != null && (
          <div style={{
            position: 'relative', height: 5, marginTop: 7, borderRadius: 'var(--radius-pill)',
            background: 'var(--bg-inset)', overflow: 'hidden',
          }}>
            <div style={{
              width: `${Math.min(100, Math.max(0, year.cap_hit_pct / 35 * 100))}%`,
              height: '100%', background: barFill,
            }} />
          </div>
        )}
      </div>
      <span className="ds-tnum" style={{ fontSize: 13, fontWeight: 700, color: gapColor, textAlign: 'right' }}>
        {gap != null ? `${signed(gap)}%` : '—'}
      </span>
    </div>
  );
}

function ContractCard({
  contract,
  error,
  onSimulateExtension,
}: {
  contract: PlayerContractResponse | null;
  error: string | null;
  onSimulateExtension: () => void;
}) {
  if (error) {
    return null;
  }

  return (
    <Surface
      variant="board"
      teamAccent
      eyebrow="Current contract"
      icon={<FileText size={15} />}
      action={contract ? <Badge tone="neutral" variant="outline" size="sm">{contract.source}</Badge> : undefined}
    >
      {contract == null ? (
        <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: 0 }}>Loading contract…</p>
      ) : (
        <>
          <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', marginBottom: 6 }}>
            <StatTile
              label="Total value"
              value={contract.total_value != null ? fmtM(contract.total_value) : '—'}
              sub={`${contract.years} year${contract.years === 1 ? '' : 's'} from ${contract.season_start}`}
              size="sm"
            />
            <StatTile
              label="Next extension"
              value={contract.extension_start_season ?? '—'}
              sub="First season after listed deal"
              size="sm"
            />
          </div>
          <div>
            {contract.years_detail.map((year) => <ContractYearRow key={year.season} year={year} />)}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 12, flexWrap: 'wrap' }}>
            <button onClick={onSimulateExtension} className="siq-primary-button" disabled={!contract.extension_start_season}>
              <SlidersHorizontal size={15} />
              Simulate extension
            </button>
            <p style={{ fontSize: 11, color: 'var(--text-muted)', margin: 0, lineHeight: 1.5, flex: '1 1 220px' }}>
              {contract.caveat}
            </p>
          </div>
        </>
      )}
    </Surface>
  );
}

const SIMILAR_MODE_LABELS: Record<SimilarPlayersMode, string> = {
  twins: 'Twins',
  contract_comps: 'Contract comps',
  replacements: 'Replacements',
};

function SimilarPlayerRow({ result }: { result: SimilarPlayerResult }) {
  const gap = result.gap_pct;
  const gapColor = gap == null
    ? 'var(--text-muted)'
    : gap >= 0 ? 'var(--positive-text)' : 'var(--negative-text)';
  const simHref = `/simulator?player=${result.player.player_id}&aav=${Math.max(1, Math.min(35, result.value_pct ?? 15))}`;

  return (
    <div className="siq-similar-dossier-row">
      <PlayerCutout playerId={result.player.player_id} name={result.player.full_name} variant="card" />
      <Link href={`/players/${result.player.player_id}`} style={{ textDecoration: 'none', minWidth: 0 }}>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', minWidth: 0 }}>
          <Avatar name={result.player.full_name} size="md" position={result.player.position} playerId={result.player.player_id} />
          <div style={{ minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 7, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)' }}>
                {result.player.full_name}
              </span>
              <Badge tone="neutral" variant="outline" size="sm">
                {result.player.position ?? '—'}
              </Badge>
            </div>
            <div style={{ marginTop: 3, fontSize: 11, color: 'var(--text-muted)' }}>
              {result.player.current_team?.abbreviation ?? result.player.latest_stats_team?.abbreviation ?? '—'}
              {result.age != null ? ` · age ${result.age.toFixed(0)}` : ''}
            </div>
          </div>
        </div>
        {result.explanation_tags.length > 0 && (
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
            {result.explanation_tags.map((tag) => (
              <Badge key={tag} tone={tag.includes('cheaper') || tag.includes('surplus') ? 'positive' : 'neutral'} variant="outline" size="sm">
                {tag}
              </Badge>
            ))}
          </div>
        )}
      </Link>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 5 }}>
        <span className="ds-tnum" style={{ fontSize: 14, fontWeight: 800, color: 'var(--accent-text)' }}>
          {result.similarity_score.toFixed(1)}
        </span>
        <span className="ds-eyebrow">match strength</span>
        <div style={{ width: 124, height: 6, borderRadius: 'var(--radius-pill)', background: 'var(--bg-inset)', overflow: 'hidden' }}>
          <div style={{
            width: `${Math.min(100, Math.max(0, result.similarity_score)).toFixed(1)}%`,
            height: '100%', background: 'var(--grad-confidence)', boxShadow: 'var(--glow-confidence)',
          }} />
        </div>
        <div style={{ width: 124, marginTop: 3 }}>
          <MiniValuePayGauge valuePct={result.value_pct} payPct={result.salary_pct} />
        </div>
        <div style={{ textAlign: 'right', fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.5 }}>
          <div>Value {result.value_pct != null ? fmtPct(result.value_pct) : '—'}</div>
          <div>Pay {result.salary_pct != null ? fmtPct(result.salary_pct) : '—'}</div>
          <div style={{ color: gapColor }}>Gap {gap != null ? `${signed(gap)}%` : '—'}</div>
        </div>
        <Link
          href={simHref}
          className="siq-secondary-button"
          style={{ padding: '5px 8px', fontSize: 11, textDecoration: 'none' }}
        >
          <SlidersHorizontal size={13} />
          Sim
        </Link>
      </div>
    </div>
  );
}

function SimilarPlayersCard({
  market,
  error,
  mode,
  onModeChange,
}: {
  market: SimilarPlayersResponse | null;
  error: string | null;
  mode: SimilarPlayersMode;
  onModeChange: (mode: SimilarPlayersMode) => void;
}) {
  return (
    <Surface
      variant="board"
      teamAccent
      eyebrow="Similar player market"
      icon={<Users size={15} />}
      action={market ? <Badge tone="confidence" variant="outline" size="sm">{market.season}</Badge> : undefined}
    >
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
        {(Object.keys(SIMILAR_MODE_LABELS) as SimilarPlayersMode[]).map((key) => (
          <button
            key={key}
            onClick={() => onModeChange(key)}
            className={key === mode ? 'siq-primary-button' : 'siq-secondary-button'}
            style={{ padding: '6px 10px', fontSize: 12, width: 'auto' }}
          >
            {SIMILAR_MODE_LABELS[key]}
          </button>
        ))}
      </div>

      {error ? (
        <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: 0, lineHeight: 1.5 }}>
          Similar-player market unavailable: {error}
        </p>
      ) : market == null ? (
        <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: 0 }}>Loading similar players…</p>
      ) : market.results.length === 0 ? (
        <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: 0, lineHeight: 1.5 }}>
          No qualified matches found for this mode.
        </p>
      ) : (
        <>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 2 }}>
            {market.basis.slice(0, 5).map((basis) => (
              <Badge key={basis} tone="neutral" variant="outline" size="sm">{basis}</Badge>
            ))}
          </div>
          {market.results.slice(0, 6).map((result) => (
            <SimilarPlayerRow key={result.player.player_id} result={result} />
          ))}
          <p style={{ fontSize: 11, color: 'var(--text-muted)', margin: '10px 0 0', lineHeight: 1.5 }}>
            {market.caveat}
          </p>
        </>
      )}
    </Surface>
  );
}

type WorkspaceTab = 'brief' | 'market' | 'contract' | 'scout' | 'model';

const WORKSPACE_TABS: { key: WorkspaceTab; label: string; icon: ReactNode }[] = [
  { key: 'brief', label: 'Front-office read', icon: <Target size={14} /> },
  { key: 'market', label: 'Similar market', icon: <Users size={14} /> },
  { key: 'contract', label: 'Contract', icon: <FileText size={14} /> },
  { key: 'scout', label: 'Scout', icon: <ClipboardCheck size={14} /> },
  { key: 'model', label: 'Model', icon: <BarChart3 size={14} /> },
];

function RiskLine({ label, value, tone = 'neutral' }: { label: string; value: string; tone?: 'positive' | 'negative' | 'neutral' }) {
  const color = tone === 'positive'
    ? 'var(--positive-text)'
    : tone === 'negative' ? 'var(--negative-text)' : 'var(--text-primary)';
  return (
    <div className="siq-risk-line">
      <span>{label}</span>
      <strong className="ds-tnum" style={{ color }}>{value}</strong>
    </div>
  );
}

function MetricPlate({
  label,
  value,
  sub,
  tone = 'neutral',
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: 'positive' | 'negative' | 'neutral';
}) {
  const accent = tone === 'positive'
    ? 'var(--positive-text)'
    : tone === 'negative' ? 'var(--negative-text)' : undefined;
  return (
    <div
      className="siq-metric-plate"
      style={accent ? ({ '--plate-accent': accent } as CSSProperties) : undefined}
    >
      <span className="ds-eyebrow siq-metric-plate__label">{label}</span>
      <span className="siq-metric-plate__value">{value}</span>
      {sub && <span className="siq-metric-plate__sub">{sub}</span>}
    </div>
  );
}

function DecisionHero({
  val,
  valueUsd,
  actualUsd,
  contract,
  extensionHref,
  onSimulate,
}: {
  val: ValuationResponse;
  valueUsd: number;
  actualUsd: number | null;
  contract: PlayerContractResponse | null;
  extensionHref: string;
  onSimulate: () => void;
}) {
  return (
    <section className="siq-decision-hero">
      {val.current_team && (
        <div className="siq-decision-logo-bg" aria-hidden="true">
          <img
            src={teamLogoUrl(val.current_team.team_id)}
            alt=""
            onError={(e) => { e.currentTarget.style.display = 'none'; }}
          />
        </div>
      )}
      <div className="siq-decision-identity">
        <Avatar name={val.player_name} size="xl" position={val.position} playerId={val.player_id} />
        <div style={{ minWidth: 0 }}>
          <div className="siq-decision-kicker">
            <Badge tone="neutral" size="sm">{val.season}</Badge>
            {val.current_team && (
              <TeamLogo
                teamId={val.current_team.team_id}
                abbreviation={val.current_team.abbreviation}
                name={val.current_team.name}
                size="sm"
              />
            )}
            <span>{val.current_team?.name ?? 'Team unavailable'}</span>
          </div>
          <h1>{val.player_name}</h1>
          <div className="siq-decision-subline">
            <span>{val.position ?? 'Position unavailable'}</span>
            <span>Value case workspace</span>
          </div>
        </div>
      </div>

      <div className="siq-decision-snapshot">
        <StatTile
          label="Model value"
          value={fmtM(valueUsd)}
          unit={fmtPct(val.value_pct)}
          sub={`80% range ${fmtPct(val.lo_pct)} to ${fmtPct(val.hi_pct)}`}
          size="sm"
        />
        <StatTile
          label="Current pay"
          value={actualUsd != null ? fmtM(actualUsd) : '—'}
          unit={val.actual_pct != null ? fmtPct(val.actual_pct) : undefined}
          sub={`${val.season} cap hit`}
          size="sm"
        />
        <StatTile
          label="Extension window"
          value={contract?.extension_start_season ?? '—'}
          sub={contract ? `${contract.years} listed years` : 'Contract data loading'}
          size="sm"
        />
      </div>

      <div className="siq-decision-actions">
        <VerdictPill gapPct={val.gap_pct} label={val.verdict_label} tone={val.verdict_tone} size="lg" />
        <button onClick={onSimulate} className="siq-primary-button">
          <SlidersHorizontal size={15} />
          Run simulation
        </button>
        <Link href={extensionHref} className="siq-secondary-button" style={{ textDecoration: 'none' }}>
          <DollarSign size={15} />
          Price deal
        </Link>
      </div>
    </section>
  );
}

function WorkspaceTabs({
  active,
  onChange,
}: {
  active: WorkspaceTab;
  onChange: (tab: WorkspaceTab) => void;
}) {
  return (
    <div className="siq-workspace-tabs">
      {WORKSPACE_TABS.map((tab) => (
        <button
          key={tab.key}
          onClick={() => onChange(tab.key)}
          className={active === tab.key ? 'is-active' : undefined}
        >
          {tab.icon}
          {tab.label}
        </button>
      ))}
    </div>
  );
}

function FrontOfficeRead({
  val,
  valueUsd,
  actualUsd,
  contract,
  similarMarket,
  scoutRatings,
}: {
  val: ValuationResponse;
  valueUsd: number;
  actualUsd: number | null;
  contract: PlayerContractResponse | null;
  similarMarket: SimilarPlayersResponse | null;
  scoutRatings: PlayerScoutRatingsResponse | null;
}) {
  const topMatch = similarMarket?.results[0];
  const gapTone = val.gap_pct == null ? 'neutral' : val.gap_pct >= 0 ? 'positive' : 'negative';
  const scoutTop = scoutRatings?.traits[0];
  const marketGaugeDomainMaxPct = Math.max(
    10,
    Math.ceil((Math.max(
      val.value_pct ?? 0,
      val.actual_pct ?? 0,
      topMatch?.value_pct ?? 0,
      topMatch?.salary_pct ?? 0,
    ) * 1.15) / 5) * 5,
  );

  return (
    <div className="siq-read-grid">
      <Surface variant="instrument" teamAccent eyebrow="Decision brief" icon={<Target size={15} />}>
        <div className="siq-brief-copy">
          <p>
            Production prices {val.player_name} at <strong>{fmtPct(val.value_pct)}</strong> of the cap
            {val.actual_pct != null ? <> against a <strong>{fmtPct(val.actual_pct)}</strong> current hit</> : null}.
          </p>
          <p>
            The current case reads as <strong>{val.gap_pct != null ? `${signed(val.gap_pct)}% of cap` : 'incomplete'}</strong>
            {topMatch ? <> with <strong>{topMatch.player.full_name}</strong> as the closest visible market comp.</> : <> while the market set loads.</>}
          </p>
          {val.caveat && (
            <p>
              <strong>{val.verdict_label}:</strong> {val.caveat}
            </p>
          )}
        </div>
        <div className="siq-gauge-well">
          <div className="siq-gauge-well__caption">
            <span className="ds-eyebrow">Production-implied value</span>
            <Badge tone="confidence" variant="outline" size="sm">
              80% range {fmtPct(val.lo_pct)}–{fmtPct(val.hi_pct)}
            </Badge>
          </div>
          <ValueGauge
            valuePct={val.value_pct}
            loPct={val.lo_pct}
            hiPct={val.hi_pct}
            actualPct={val.actual_pct}
          />
        </div>
        <div className="siq-metric-plates">
          <MetricPlate label="Value $" value={fmtM(valueUsd)} sub={`${fmtPct(val.value_pct)} of cap`} tone="positive" />
          <MetricPlate
            label="Pay $"
            value={actualUsd != null ? fmtM(actualUsd) : '—'}
            sub={val.actual_pct != null ? `${fmtPct(val.actual_pct)} of cap` : `${val.season} cap hit`}
            tone={val.gap_pct != null && val.gap_pct < 0 ? 'negative' : 'neutral'}
          />
          <MetricPlate
            label="Gap to pay"
            value={val.gap_pct != null ? `${signed(val.gap_pct)}%` : '—'}
            sub="value − pay"
            tone={gapTone}
          />
          <MetricPlate
            label="Extension"
            value={contract?.extension_start_season ?? '—'}
            sub={contract ? `${contract.years} listed yrs` : 'loading'}
          />
        </div>
      </Surface>

      <Surface variant="board" teamAccent eyebrow="Market signal" icon={<GitCompare size={15} />}>
        {topMatch ? (
          <div className="siq-market-signal">
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
              <Avatar name={topMatch.player.full_name} size="md" position={topMatch.player.position} playerId={topMatch.player.player_id} />
              <div style={{ minWidth: 0 }}>
                <Link href={`/players/${topMatch.player.player_id}`} style={{ textDecoration: 'none', fontWeight: 800, color: 'var(--text-primary)' }}>
                  {topMatch.player.full_name}
                </Link>
                <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                  {topMatch.player.current_team?.abbreviation ?? '—'} · {topMatch.similarity_score.toFixed(1)} match
                </div>
              </div>
            </div>
            <div className="siq-market-chip-row">
              {topMatch.explanation_tags.slice(0, 4).map((tag) => (
                <Badge key={tag} tone="neutral" variant="outline" size="sm">{tag}</Badge>
              ))}
            </div>
            <MiniValuePayGauge
              valuePct={topMatch.value_pct}
              payPct={topMatch.salary_pct}
              showLabels
              domainMaxPct={marketGaugeDomainMaxPct}
            />
            <RiskLine label="Comp value" value={topMatch.value_pct != null ? fmtPct(topMatch.value_pct) : '—'} />
            <RiskLine label="Comp pay" value={topMatch.salary_pct != null ? fmtPct(topMatch.salary_pct) : '—'} />
            <RiskLine label="Comp gap" value={topMatch.gap_pct != null ? `${signed(topMatch.gap_pct)}%` : '—'} tone={topMatch.gap_pct != null && topMatch.gap_pct >= 0 ? 'positive' : 'negative'} />
          </div>
        ) : (
          <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: 0 }}>Loading market signal…</p>
        )}
      </Surface>

      <Surface variant="dossier" teamAccent eyebrow="Confidence notes" icon={<Info size={15} />}>
        <div className="siq-confidence-bracket">
          <div className="siq-confidence-stack">
            <RiskLine label="Model interval" value={`${fmtPct(val.lo_pct)} to ${fmtPct(val.hi_pct)}`} />
            <RiskLine label="Scout fixture" value={scoutRatings ? `${scoutRatings.report_count} reports` : 'Loading'} />
            <RiskLine label="Top trait" value={scoutTop ? `${traitLabel(scoutTop.trait)} ${scoutTop.average_score.toFixed(1)}/5` : '—'} />
          </div>
        </div>
        <p style={{ fontSize: 12, color: 'var(--text-muted)', margin: '12px 0 0', lineHeight: 1.5 }}>
          Use the tabs to move from the executive read into the market, contract structure, scout context, and raw model inputs.
        </p>
      </Surface>
    </div>
  );
}

function ActionRail({
  val,
  contract,
  similarMarket,
  extensionHref,
  activeTab,
  onTab,
  onSimulate,
}: {
  val: ValuationResponse;
  contract: PlayerContractResponse | null;
  similarMarket: SimilarPlayersResponse | null;
  extensionHref: string;
  activeTab: WorkspaceTab;
  onTab: (tab: WorkspaceTab) => void;
  onSimulate: () => void;
}) {
  const topMatch = similarMarket?.results[0];
  return (
    <aside className="siq-action-rail">
      <Card eyebrow="Action rail" icon={<SlidersHorizontal size={15} />}>
        <div className="siq-action-stack">
          <button onClick={onSimulate} className="siq-primary-button">
            <SlidersHorizontal size={15} />
            Simulate extension
          </button>
          <Link href={extensionHref} className="siq-secondary-button" style={{ textDecoration: 'none' }}>
            <DollarSign size={15} />
            Open contract pricer
          </Link>
          <button onClick={() => onTab('market')} className="siq-secondary-button">
            <Users size={15} />
            Review comps
          </button>
          <button onClick={() => onTab('model')} className="siq-secondary-button">
            <BarChart3 size={15} />
            Inspect model inputs
          </button>
        </div>
      </Card>

      <Surface variant="dossier" teamAccent eyebrow="Case file" icon={<FileText size={15} />}>
        <RiskLine label="Active view" value={WORKSPACE_TABS.find((tab) => tab.key === activeTab)?.label ?? '—'} />
        <RiskLine label="Value gap" value={val.gap_pct != null ? `${signed(val.gap_pct)}%` : '—'} tone={val.gap_pct != null && val.gap_pct >= 0 ? 'positive' : 'negative'} />
        <RiskLine label="Top comp" value={topMatch?.player.full_name ?? 'Loading'} />
        <RiskLine label="Extension window" value={contract?.extension_start_season ?? '—'} />
      </Surface>
    </aside>
  );
}

export default function PlayerPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const playerId = Number(id);
  const router = useRouter();

  const [val, setVal] = useState<ValuationResponse | null>(null);
  const [contract, setContract] = useState<PlayerContractResponse | null>(null);
  const [contractError, setContractError] = useState<string | null>(null);
  const [similarMode, setSimilarMode] = useState<SimilarPlayersMode>('twins');
  const [similarMarket, setSimilarMarket] = useState<SimilarPlayersResponse | null>(null);
  const [similarError, setSimilarError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<WorkspaceTab>('brief');
  const [scoutRatings, setScoutRatings] = useState<PlayerScoutRatingsResponse | null>(null);
  const [scoutError, setScoutError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    getValuation(playerId)
      .then(setVal)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Failed to load valuation.'))
      .finally(() => setLoading(false));

    setContract(null);
    setContractError(null);
    getPlayerContract(playerId)
      .then(setContract)
      .catch((e: unknown) => setContractError(e instanceof Error ? e.message : 'Failed to load contract.'));

    setScoutRatings(null);
    setScoutError(null);
    getPlayerScoutRatings(playerId)
      .then(setScoutRatings)
      .catch((e: unknown) => setScoutError(e instanceof Error ? e.message : 'Failed to load scout ratings.'));
  }, [playerId]);

  useEffect(() => {
    const controller = new AbortController();
    setSimilarMarket(null);
    setSimilarError(null);
    getSimilarPlayers(playerId, { mode: similarMode, limit: 8 }, controller.signal)
      .then(setSimilarMarket)
      .catch((e: unknown) => {
        if (!controller.signal.aborted) {
          setSimilarError(e instanceof Error ? e.message : 'Failed to load similar players.');
        }
      });
    return () => controller.abort();
  }, [playerId, similarMode]);

  if (loading) {
    return <div style={{ padding: 48, textAlign: 'center', color: 'var(--text-muted)' }}>Loading…</div>;
  }

  if (error || !val) {
    return (
      <div>
        <Link href="/players" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, marginBottom: 16, textDecoration: 'none', fontSize: 13, color: 'var(--text-secondary)' }}>
          <ArrowLeft size={15} /> All players
        </Link>
        <div style={{ padding: '12px 16px', borderRadius: 'var(--radius-lg)', background: 'var(--negative-soft)', color: 'var(--negative-text)', fontSize: 13 }}>
          {error ?? 'Player not found.'}
        </div>
      </div>
    );
  }

  const capM = val.salary_cap ?? 140_588_000;
  const valueUsd = val.value_usd ?? Math.round(val.value_pct / 100 * capM);
  const actualUsd = val.actual_usd;

  // Feature entries — raw stat values from the model input
  const featureEntries = val.features
    ? Object.entries(val.features).slice(0, 8)
    : [];
  const extensionAav = Math.max(1, Math.min(35, Number(val.value_pct.toFixed(1))));
  const extensionHref = contract?.extension_start_season
    ? `/simulator?player=${playerId}&start=${encodeURIComponent(contract.extension_start_season)}&aav=${extensionAav}&years=4`
    : `/simulator?player=${playerId}&aav=${extensionAav}`;
  const visual = teamVisual(val.current_team?.abbreviation);

  const modelInputs = (
    <div className="siq-read-grid">
      <Surface
        variant="instrument"
        teamAccent
        eyebrow="Production-implied value"
        icon={<Scale size={15} />}
        action={<Badge tone="confidence" variant="outline" size="sm">80% interval</Badge>}
      >
        <div style={{ display: 'flex', gap: 28, flexWrap: 'wrap', marginBottom: 16 }}>
          <StatTile
            label="Model value"
            value={fmtM(valueUsd)}
            unit={` · ${fmtPct(val.value_pct)}`}
            delta={val.gap_pct != null ? signed(val.gap_pct) + '%' : undefined}
            deltaDir={val.gap_pct != null ? (val.gap_pct >= 0 ? 'up' : 'down') : undefined}
            sub={`80% CI: ${fmtPct(val.lo_pct)}–${fmtPct(val.hi_pct)} of cap`}
            size="md"
          />
          {actualUsd && (
            <StatTile
              label="Actual pay"
              value={fmtM(actualUsd)}
              unit={val.actual_pct != null ? ` · ${fmtPct(val.actual_pct)}` : undefined}
              sub={`${val.season} cap hit`}
              size="md"
            />
          )}
        </div>
        <div className="siq-gauge-well">
          <div className="siq-gauge-well__caption">
            <span className="ds-eyebrow">Value vs pay on the cap</span>
            <Badge tone="confidence" variant="outline" size="sm">
              80% range {fmtPct(val.lo_pct)}–{fmtPct(val.hi_pct)}
            </Badge>
          </div>
          <ValueGauge
            valuePct={val.value_pct}
            loPct={val.lo_pct}
            hiPct={val.hi_pct}
            actualPct={val.actual_pct}
          />
        </div>
      </Surface>

      <Surface variant="board" teamAccent eyebrow="Model inputs" icon={<Activity size={15} />}>
        {featureEntries.length > 0 ? (
          <>
            {featureEntries.map(([key, value]) => {
              const { label, formatted } = formatFeatureValue(key, value);
              return <StatRow key={key} label={label} value={formatted} />;
            })}
            <p style={{ fontSize: 11, color: 'var(--text-muted)', margin: '10px 0 0', lineHeight: 1.5 }}>
              Raw feature values fed to the model for this season.
            </p>
          </>
        ) : (
          <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: 0 }}>
            Feature data not available for this player-season.
          </p>
        )}
      </Surface>

      <Surface variant="dossier" teamAccent eyebrow="Model info" icon={<BarChart3 size={15} />}>
        <StatRow label="Model version" value={val.model_version ?? '—'} />
        <StatRow label="Season" value={val.season} />
        <StatRow label="Value" value={`${fmtPct(val.value_pct)} of cap`} />
        <StatRow label="80% interval" value={`${fmtPct(val.lo_pct)} – ${fmtPct(val.hi_pct)}`} />
        <StatRow label="Verdict" value={val.verdict_label} warn={val.verdict_tone === 'warning'} />
        {val.gap_pct != null && (
          <StatRow
            label="Gap to pay"
            value={`${signed(val.gap_pct)}%`}
          />
        )}
        {val.caution_flags.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, paddingTop: 10 }}>
            {val.caution_flags.slice(0, 4).map((flag) => (
              <Badge key={flag} tone="warning" variant="outline" size="sm">{flag}</Badge>
            ))}
          </div>
        )}
      </Surface>

      <AssumptionFlag
        tone={val.verdict_tone === 'warning' ? 'warning' : 'confidence'}
        title={val.verdict_tone === 'warning' ? 'Model caution' : 'Calibrated honesty'}
        icon={<Info size={16} />}
      >
        {val.caveat ?? (
          'This is a production-implied valuation, not a market-value estimate. It does not account for injury risk, defensive impact beyond box-score proxies, or gravity effects. Check the Model & backtest view for full performance metrics.'
        )}
      </AssumptionFlag>
    </div>
  );

  return (
    <div
      className="siq-decision-page"
      style={{
        '--team-primary': visual.primary,
        '--team-secondary': visual.secondary,
        '--team-wash': visual.wash,
      } as CSSProperties}
    >
      <Link href="/players" className="siq-back-link">
        <ArrowLeft size={15} /> All players
      </Link>

      <DecisionHero
        val={val}
        valueUsd={valueUsd}
        actualUsd={actualUsd}
        contract={contract}
        extensionHref={extensionHref}
        onSimulate={() => router.push(extensionHref)}
      />

      <div className="siq-workspace-layout">
        <main className="siq-workspace-main">
          <WorkspaceTabs active={activeTab} onChange={setActiveTab} />

          <div className="siq-workspace-panel">
            {activeTab === 'brief' && (
              <FrontOfficeRead
                val={val}
                valueUsd={valueUsd}
                actualUsd={actualUsd}
                contract={contract}
                similarMarket={similarMarket}
                scoutRatings={scoutRatings}
              />
            )}

            {activeTab === 'market' && (
              <SimilarPlayersCard
                market={similarMarket}
                error={similarError}
                mode={similarMode}
                onModeChange={setSimilarMode}
              />
            )}

            {activeTab === 'contract' && (
              <ContractCard
                contract={contract}
                error={contractError}
                onSimulateExtension={() => router.push(extensionHref)}
              />
            )}

            {activeTab === 'scout' && (
              <div className="siq-read-grid">
                <ScoutRatingsCard ratings={scoutRatings} error={scoutError} />
                <Card eyebrow="How to read this" icon={<Info size={15} />}>
                  <p style={{ font: '14px/1.6 var(--font-sans)', color: 'var(--text-primary)', margin: 0 }}>
                    Scout ratings are fixture-backed qualitative context for the portfolio demo. Treat them as
                    a separate lens from the deterministic model and cap math.
                  </p>
                </Card>
              </div>
            )}

            {activeTab === 'model' && modelInputs}
          </div>
        </main>

        <ActionRail
          val={val}
          contract={contract}
          similarMarket={similarMarket}
          extensionHref={extensionHref}
          activeTab={activeTab}
          onTab={setActiveTab}
          onSimulate={() => router.push(extensionHref)}
        />
      </div>
    </div>
  );
}
