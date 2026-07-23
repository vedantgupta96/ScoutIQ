'use client';

import { Suspense, useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { ListChecks, Target, TrendingDown, TrendingUp, TriangleAlert } from 'lucide-react';
import {
  BacktestResponse,
  PlayerCardResponse,
  PlayerValuationCautionsResponse,
  PlayerWatchlistResponse,
  TeamListItem,
  getBacktest,
  getPlayerValuationCautions,
  getPlayerWatchlist,
  getTeams,
} from '@/lib/api';
import { DecisionQueueResponse, QueueItem, getDecisionQueue } from '@/lib/decisionQueueApi';
import { Avatar } from '@/components/ui/Avatar';
import { Badge } from '@/components/ui/Badge';
import { Panel } from '@/components/ui/Panel';
import { Skeleton } from '@/components/ui/Skeleton';
import { Select } from '@/components/ui/Select';
import { Alert } from '@/components/ui/Alert';
import { EmptyState } from '@/components/ui/EmptyState';
import { LoadingNote } from '@/components/ui/LoadingNote';
import { fmtM, fmtPct, signed } from '@/lib/utils';
import { useApi } from '@/lib/useApi';

const TEAM_STORAGE_KEY = 'siq-home-team-id';

function gapText(gap: number): string {
  return `${signed(gap)}%`;
}

function MoverRow({ player, rank }: { player: PlayerCardResponse; rank: number }) {
  const v = player.valuation;
  if (!v || v.gap_pct == null) return null;
  const tone = v.gap_pct >= 0 ? 'var(--positive-text)' : 'var(--negative-text)';
  const team = player.current_team ?? player.latest_stats_team;
  return (
    <Link href={`/players/${player.player_id}`} className="siq-home-mover">
      <span className="siq-home-mover__rank ds-tnum">{rank}</span>
      <Avatar name={player.full_name} size="sm" position={player.position} playerId={player.player_id} />
      <span className="siq-home-mover__id">
        <span className="siq-home-mover__name">{player.full_name}</span>
        <span className="siq-home-mover__team">{team?.abbreviation ?? '—'} · {player.position ?? '—'}</span>
      </span>
      <span className="siq-home-mover__gap ds-tnum" style={{ color: tone }}>{gapText(v.gap_pct)}</span>
    </Link>
  );
}

function MoverSkeletons() {
  return (
    <div role="status" aria-label="Loading movers">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="siq-home-mover" aria-hidden="true">
          <Skeleton width={16} height={12} />
          <Skeleton width={28} height={28} round />
          <span className="siq-home-mover__id"><Skeleton height={12} width="70%" /></span>
          <Skeleton width={44} height={14} />
        </div>
      ))}
    </div>
  );
}

const PRIORITY_BADGE: Record<QueueItem['priority'], { label: string; tone: 'warning' | 'neutral'; variant: 'solid' | 'outline' }> = {
  high: { label: 'High', tone: 'warning', variant: 'solid' },
  medium: { label: 'Medium', tone: 'neutral', variant: 'solid' },
  low: { label: 'Low', tone: 'neutral', variant: 'outline' },
};

function QueueItemRow({ item }: { item: QueueItem }) {
  const badge = PRIORITY_BADGE[item.priority];
  const hasFigures = item.value_pct != null || item.pay_pct != null || item.gap_pct != null
    || item.value_usd != null || item.pay_usd != null;
  return (
    <Link href={item.destination} className="siq-queue-item">
      <div className="siq-queue-item__head">
        <Badge tone={badge.tone} variant={badge.variant} size="sm">{badge.label}</Badge>
        <span className="siq-queue-item__title">{item.title}</span>
      </div>
      <p className="siq-queue-item__detail">{item.detail}</p>
      {item.priority_reason !== item.detail && (
        <p className="siq-queue-item__reason">{item.priority_reason}</p>
      )}
      {hasFigures && (
        <div className="siq-queue-item__figures ds-tnum">
          {item.value_pct != null && <span>Value {fmtPct(item.value_pct)}</span>}
          {item.pay_pct != null && <span>Pay {fmtPct(item.pay_pct)}</span>}
          {item.gap_pct != null && <span>Gap {gapText(item.gap_pct)}</span>}
          {item.value_usd != null && <span className="siq-queue-item__usd">{fmtM(item.value_usd)} value</span>}
          {item.pay_usd != null && <span className="siq-queue-item__usd">{fmtM(item.pay_usd)} pay</span>}
        </div>
      )}
      {item.caution && (
        <p className="siq-queue-item__caution"><TriangleAlert size={12} aria-hidden="true" />{item.caution}</p>
      )}
    </Link>
  );
}

function DecisionQueuePanel({ teamId }: { teamId: number }) {
  const { data, loading, error } = useApi<DecisionQueueResponse>(
    (signal) => getDecisionQueue(teamId, undefined, signal),
    [teamId],
    { fallback: 'Failed to load the decision queue.' },
  );

  if (error) {
    return <Alert tone="negative">{error} — is the FastAPI server running?</Alert>;
  }
  if (loading && !data) {
    return <LoadingNote>Loading the decision queue…</LoadingNote>;
  }
  if (!data) return null;

  const actionable = data.items.filter((item) => item.type !== 'cap_tier');

  return (
    <>
      <p className="siq-queue-meta">{data.team_name ?? 'Team'} · {data.season} data</p>
      {actionable.length === 0 && (
        <EmptyState
          title="No pending option, extension, or expiring-contract decisions."
          description="The cap-tier standing below still reflects this roster."
        />
      )}
      <div className="siq-queue-list">
        {data.items.map((item) => <QueueItemRow key={item.id} item={item} />)}
      </div>
      <p className="siq-home-caution-note">{data.caveat}</p>
    </>
  );
}

function readStoredTeamId(): number | null {
  if (typeof window === 'undefined') return null;
  const raw = window.localStorage.getItem(TEAM_STORAGE_KEY);
  const parsed = raw ? Number(raw) : NaN;
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function HomeContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const teamParam = searchParams.get('team');
  const selectedId = teamParam ? Number(teamParam) : null;

  const [teams, setTeams] = useState<TeamListItem[]>([]);
  const [cautions, setCautions] = useState<PlayerValuationCautionsResponse | null>(null);
  const [backtest, setBacktest] = useState<BacktestResponse | null>(null);

  useEffect(() => { getTeams().then(setTeams).catch(() => {}); }, []);

  useEffect(() => {
    if (selectedId != null) {
      if (typeof window !== 'undefined') window.localStorage.setItem(TEAM_STORAGE_KEY, String(selectedId));
      return;
    }
    if (teams.length === 0) return;
    const stored = readStoredTeamId();
    const fallback = stored != null && teams.some((t) => t.team_id === stored) ? stored : teams[0].team_id;
    router.replace(`/?team=${fallback}`);
  }, [selectedId, teams, router]);

  const { data: board, error } = useApi<[PlayerWatchlistResponse, PlayerWatchlistResponse]>(
    (signal) => Promise.all([
      getPlayerWatchlist({ bucket: 'underpaid', limit: 5 }, signal),
      getPlayerWatchlist({ bucket: 'overpaid', limit: 5 }, signal),
    ]),
    [],
    { fallback: 'Failed to load the board.' },
  );
  const underpaid = board ? board[0].items : null;
  const overpaid = board ? board[1].items : null;

  useEffect(() => {
    const controller = new AbortController();
    getPlayerValuationCautions({ limit: 4 }, controller.signal).then(setCautions).catch(() => {});
    getBacktest().then(setBacktest).catch(() => {});
    return () => controller.abort();
  }, []);

  const metrics = backtest?.metrics;

  return (
    <div className="siq-home">
      <Panel
        variant="card"
        className="siq-home-queue"
        eyebrow="Decision queue"
        icon={<ListChecks size={15} />}
        action={
          <Select
            selectSize="sm"
            value={selectedId ?? ''}
            onChange={(e) => router.replace(`/?team=${e.target.value}`)}
            aria-label="Select team"
          >
            {teams.length === 0 && <option value="">Loading teams…</option>}
            {teams.map((t) => <option key={t.team_id} value={t.team_id}>{t.name ?? t.abbreviation}</option>)}
          </Select>
        }
      >
        {selectedId != null ? <DecisionQueuePanel teamId={selectedId} /> : <LoadingNote>Loading teams…</LoadingNote>}
      </Panel>

      <Panel eyebrow="Model, on the record" icon={<Target size={15} />} className="siq-home-calibration">
        {metrics ? (
          <div className="siq-home-cal__body">
            <p className="siq-home-cal__note">
              Valuations are production-implied, with intervals we backtest in public.
            </p>
            <dl className="siq-home-cal__stats ds-tnum">
              <div><dt>R²</dt><dd>{metrics.r2.toFixed(2)}</dd></div>
              <div><dt>MAE</dt><dd>{metrics.mae_pct_of_cap.toFixed(1)}% cap</dd></div>
              <div><dt>80% interval held</dt><dd>{(metrics.interval_80_coverage * 100).toFixed(1)}%</dd></div>
            </dl>
            <Link href="/model" className="siq-home-cal__link">See the backtest →</Link>
          </div>
        ) : (
          <Skeleton height={56} />
        )}
      </Panel>

      <Panel variant="card" eyebrow="Best value" icon={<TrendingUp size={15} />} headingLevel="h2">
        {error && <Alert tone="negative">{error} — is the FastAPI server running?</Alert>}
        {underpaid ? underpaid.map((p, i) => <MoverRow key={p.player_id} player={p} rank={i + 1} />) : <MoverSkeletons />}
        <Link href="/players?bucket=underpaid" className="siq-home-more">Full underpaid board →</Link>
      </Panel>

      <Panel variant="card" eyebrow="Most overpaid" icon={<TrendingDown size={15} />} headingLevel="h2">
        {overpaid ? overpaid.map((p, i) => <MoverRow key={p.player_id} player={p} rank={i + 1} />) : <MoverSkeletons />}
        <Link href="/players?bucket=overpaid" className="siq-home-more">Full overpaid board →</Link>
      </Panel>

      <Panel variant="card" eyebrow="Trust flags" icon={<TriangleAlert size={15} />} headingLevel="h2">
        {cautions && cautions.items.length > 0 ? (
          <>
            {cautions.items.map((p) => (
              <Link key={p.player_id} href={`/players/${p.player_id}`} className="siq-home-mover">
                <Avatar name={p.full_name} size="sm" position={p.position} playerId={p.player_id} />
                <span className="siq-home-mover__id">
                  <span className="siq-home-mover__name">{p.full_name}</span>
                  <span className="siq-home-mover__team">{p.valuation?.caution_flags[0] ?? 'Flagged'}</span>
                </span>
                <span className="siq-home-mover__gap ds-tnum siq-home-mover__gap--warning">
                  {p.valuation?.gap_pct != null ? gapText(p.valuation.gap_pct) : '—'}
                </span>
              </Link>
            ))}
            <p className="siq-home-caution-note">Cheap production with weak impact signals — bargains we do not fully trust.</p>
          </>
        ) : (
          <MoverSkeletons />
        )}
      </Panel>
    </div>
  );
}

export default function Home() {
  return (
    <Suspense fallback={<LoadingNote>Loading…</LoadingNote>}>
      <HomeContent />
    </Suspense>
  );
}
