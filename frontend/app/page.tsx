'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { ArrowUpRight, Target, TrendingDown, TrendingUp, TriangleAlert } from 'lucide-react';
import {
  BacktestResponse,
  PlayerCardResponse,
  PlayerValuationCautionsResponse,
  getBacktest,
  getPlayerValuationCautions,
  getPlayerWatchlist,
} from '@/lib/api';
import { Avatar } from '@/components/ui/Avatar';
import { Badge } from '@/components/ui/Badge';
import { ButtonLink } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { Skeleton } from '@/components/ui/Skeleton';
import { Surface } from '@/components/ui/Surface';
import { fmtPct, signed } from '@/lib/utils';

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

export default function Home() {
  const [underpaid, setUnderpaid] = useState<PlayerCardResponse[] | null>(null);
  const [overpaid, setOverpaid] = useState<PlayerCardResponse[] | null>(null);
  const [cautions, setCautions] = useState<PlayerValuationCautionsResponse | null>(null);
  const [backtest, setBacktest] = useState<BacktestResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      getPlayerWatchlist({ bucket: 'underpaid', limit: 5 }, controller.signal),
      getPlayerWatchlist({ bucket: 'overpaid', limit: 5 }, controller.signal),
    ])
      .then(([under, over]) => { setUnderpaid(under.items); setOverpaid(over.items); })
      .catch((e) => { if (e?.name !== 'AbortError') setError(String(e?.message ?? e)); });
    getPlayerValuationCautions({ limit: 4 }, controller.signal).then(setCautions).catch(() => {});
    getBacktest().then(setBacktest).catch(() => {});
    return () => controller.abort();
  }, []);

  // The sharpest mismatch on the board leads the page.
  const hero = [...(underpaid?.slice(0, 1) ?? []), ...(overpaid?.slice(0, 1) ?? [])]
    .filter((p) => p.valuation?.gap_pct != null)
    .sort((a, b) => Math.abs(b.valuation!.gap_pct!) - Math.abs(a.valuation!.gap_pct!))[0];
  const heroVal = hero?.valuation ?? null;
  const heroTeam = hero ? (hero.current_team ?? hero.latest_stats_team) : null;
  const metrics = backtest?.metrics;

  return (
    <div className="siq-home">
      <section className="siq-home-hero" aria-label="Sharpest mismatch on the board">
        {hero && heroVal && heroVal.gap_pct != null ? (
          <>
            <span className="ds-eyebrow">Sharpest mismatch · {heroVal.season}</span>
            <div className="siq-home-hero__row">
              <Avatar name={hero.full_name} size="lg" position={hero.position} playerId={hero.player_id} />
              <div className="siq-home-hero__id">
                <Link href={`/players/${hero.player_id}`} className="siq-home-hero__name">{hero.full_name}</Link>
                <span className="siq-home-hero__team">
                  {heroTeam?.name ?? '—'} · {hero.position ?? '—'} · worth {fmtPct(heroVal.value_pct)} of cap,
                  paid {heroVal.actual_pct != null ? fmtPct(heroVal.actual_pct) : '—'}
                </span>
              </div>
            </div>
            <div
              className={`siq-home-hero__gap ds-tnum siq-verdict-beat siq-verdict-beat--${heroVal.gap_pct >= 0 ? 'positive' : 'negative'}`}
            >
              {gapText(heroVal.gap_pct)}
            </div>
            <div className="siq-home-hero__foot">
              <Badge tone={heroVal.verdict_tone} size="md">{heroVal.verdict_label}</Badge>
              <ButtonLink href={`/players/${hero.player_id}`} size="sm" icon={<ArrowUpRight size={14} />}>
                Open the case
              </ButtonLink>
            </div>
          </>
        ) : error ? (
          <span className="siq-home-hero__loading">{error} — is the FastAPI server running?</span>
        ) : (
          <div role="status" aria-label="Loading the board">
            <Skeleton height={12} width={180} />
            <div style={{ height: 14 }} />
            <Skeleton height={44} width={220} />
          </div>
        )}
      </section>

      <Surface eyebrow="Model, on the record" icon={<Target size={15} />} className="siq-home-calibration">
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
      </Surface>

      <Card eyebrow="Best value" icon={<TrendingUp size={15} />} headingLevel="h2">
        {underpaid ? underpaid.map((p, i) => <MoverRow key={p.player_id} player={p} rank={i + 1} />) : <MoverSkeletons />}
        <Link href="/players?bucket=underpaid" className="siq-home-more">Full underpaid board →</Link>
      </Card>

      <Card eyebrow="Most overpaid" icon={<TrendingDown size={15} />} headingLevel="h2">
        {overpaid ? overpaid.map((p, i) => <MoverRow key={p.player_id} player={p} rank={i + 1} />) : <MoverSkeletons />}
        <Link href="/players?bucket=overpaid" className="siq-home-more">Full overpaid board →</Link>
      </Card>

      <Card eyebrow="Trust flags" icon={<TriangleAlert size={15} />} headingLevel="h2">
        {cautions && cautions.items.length > 0 ? (
          <>
            {cautions.items.map((p) => (
              <Link key={p.player_id} href={`/players/${p.player_id}`} className="siq-home-mover">
                <Avatar name={p.full_name} size="sm" position={p.position} playerId={p.player_id} />
                <span className="siq-home-mover__id">
                  <span className="siq-home-mover__name">{p.full_name}</span>
                  <span className="siq-home-mover__team">{p.valuation?.caution_flags[0] ?? 'Flagged'}</span>
                </span>
                <span className="siq-home-mover__gap ds-tnum" style={{ color: 'var(--warning-text)' }}>
                  {p.valuation?.gap_pct != null ? gapText(p.valuation.gap_pct) : '—'}
                </span>
              </Link>
            ))}
            <p className="siq-home-caution-note">Cheap production with weak impact signals — bargains we do not fully trust.</p>
          </>
        ) : (
          <MoverSkeletons />
        )}
      </Card>
    </div>
  );
}
