'use client';

import { useEffect, useState, Suspense } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { Search } from 'lucide-react';
import {
  getPlayerWatchlist,
  PlayerCardResponse,
  PlayerCardStats,
  PlayerWatchlistResponse,
  WatchlistBucket,
  WatchlistSort,
} from '@/lib/api';
import { Avatar } from '@/components/ui/Avatar';
import { Badge } from '@/components/ui/Badge';
import { Alert } from '@/components/ui/Alert';
import { Button } from '@/components/ui/Button';
import { EmptyState } from '@/components/ui/EmptyState';
import { LoadingNote } from '@/components/ui/LoadingNote';
import { Select } from '@/components/ui/Select';
import { SegmentedControl } from '@/components/ui/SegmentedControl';
import { Skeleton } from '@/components/ui/Skeleton';
import { Tone, classifyGap, toneColor, toneText } from '@/lib/present';
import { fmtM, fmtPct, signed } from '@/lib/utils';
import { useApi } from '@/lib/useApi';

function CountUpPct({
  value, decimals = 1, withSign = false, style, className,
}: { value: number; decimals?: number; withSign?: boolean; style?: React.CSSProperties; className?: string }) {
  return (
    <span className={className ? `ds-tnum ${className}` : 'ds-tnum'} style={style}>
      {withSign ? signed(value, decimals) : value.toFixed(decimals)}%
    </span>
  );
}

// The signature ScoutIQ read: production-implied value with its 80% interval
// (teal band + value marker) against the actual pay marker. Distance between
// the pay marker and the band is the bargain/overpay story.
function ValuePayGauge({
  value, lo, hi, pay, tone,
}: { value: number; lo: number; hi: number; pay: number | null; tone: Tone }) {
  const domainMax = Math.max(hi, value, pay ?? 0) * 1.12 || 6;
  const pct = (x: number) => Math.max(0, Math.min(100, (x / domainMax) * 100));
  const bandLeft = pct(lo);
  const bandWidth = Math.max(pct(hi) - bandLeft, 1.5);
  const valuePos = pct(value);
  const payPos = pay != null ? pct(pay) : null;
  const payColor = toneColor(tone);

  return (
    <div className="siq-players-gauge-wrap">
      {/* markers float above the track so they read past the rounded ends */}
      <div className="siq-players-gauge-dot--value" style={{ left: `calc(${valuePos}% - 3px)` }} />
      {payPos != null && (
        <div className="siq-players-gauge-dot--pay" style={{ left: `calc(${payPos}% - 3px)`, background: payColor }} />
      )}
      <div className="siq-players-gauge-track">
        <div
          className="siq-players-gauge-band"
          style={{ left: `${bandLeft}%`, width: `${bandWidth}%` }}
        />
        <div className="siq-players-gauge-line--value" style={{ left: `calc(${valuePos}% - 1px)` }} />
        {payPos != null && (
          <div className="siq-players-gauge-line--pay" style={{ left: `calc(${payPos}% - 1px)`, background: payColor }} />
        )}
      </div>
    </div>
  );
}

function MetricCell({
  label, dotColor, pct, usd, align = 'left',
}: { label: string; dotColor: string; pct: number | null; usd: number | null; align?: 'left' | 'right' }) {
  return (
    <div style={{ textAlign: align }}>
      <div className="ds-eyebrow siq-players-metric-label" style={{ justifyContent: align === 'right' ? 'flex-end' : 'flex-start' }}>
        <span className="siq-players-metric-dot" style={{ background: dotColor }} />
        {label}
      </div>
      <div className="ds-tnum siq-players-metric-value">
        {pct != null ? fmtPct(pct) : '—'}
      </div>
      <div className="ds-tnum ds-note siq-players-metric-usd">
        {usd != null ? fmtM(usd) : '—'}
      </div>
    </div>
  );
}

// Maps the display label to the percentile key sent by the API.
const STAT_PCTL_KEY: Record<string, string> = {
  gp: 'gp', mpg: 'mpg', pts: 'pts_pg', reb: 'reb_pg', ast: 'ast_pg', bpm: 'bpm',
};

function setBoardStatHover(el: HTMLElement, stat: string | null) {
  const board = el.closest('.siq-pressure-board');
  if (!board) return;
  if (stat) board.setAttribute('data-stat-hover', stat);
  else board.removeAttribute('data-stat-hover');
}

function CardStatLine({ stats }: { stats: PlayerCardStats }) {
  const items: Array<{ value: string; label: string }> = [];
  if (stats.gp != null) items.push({ value: String(stats.gp), label: 'gp' });
  if (stats.mpg != null) items.push({ value: stats.mpg.toFixed(1), label: 'mpg' });
  if (stats.pts_pg != null) items.push({ value: stats.pts_pg.toFixed(1), label: 'pts' });
  if (stats.reb_pg != null) items.push({ value: stats.reb_pg.toFixed(1), label: 'reb' });
  if (stats.ast_pg != null) items.push({ value: stats.ast_pg.toFixed(1), label: 'ast' });
  if (stats.bpm != null) items.push({ value: `${stats.bpm > 0 ? '+' : ''}${stats.bpm.toFixed(1)}`, label: 'bpm' });
  if (items.length === 0) return null;

  return (
    <div className="siq-statline siq-statline--card">
      {items.map(({ value, label }) => {
        const pctl = stats.pctl?.[STAT_PCTL_KEY[label]];
        return (
          <span
            key={label}
            className="siq-statline__cell"
            data-stat={label}
            title={pctl != null ? `League percentile: ${pctl}` : undefined}
            onPointerEnter={(e) => setBoardStatHover(e.currentTarget, label)}
            onPointerLeave={(e) => setBoardStatHover(e.currentTarget, null)}
          >
            <span className="siq-statline__value ds-tnum">{value}</span>
            {pctl != null && (
              <span className="siq-statline__pctl" aria-hidden="true">
                <span style={{ width: `${pctl}%` }} />
              </span>
            )}
            <span className="siq-statline__label">{label}</span>
          </span>
        );
      })}
    </div>
  );
}

function RosterCard({ player, index }: { player: PlayerCardResponse; index: number }) {
  const team = player.current_team ?? player.latest_stats_team;
  const valuation = player.valuation_status === 'ready' ? player.valuation : undefined;
  const gap = valuation?.gap_pct ?? null;
  const tone: Tone = valuation?.verdict_tone ?? classifyGap(gap).tone;
  const accent = gap == null ? 'var(--border-strong)' : toneColor(tone);
  const valueUsd = valuation?.salary_cap != null
    ? (valuation.value_pct / 100) * valuation.salary_cap
    : null;

  return (
    <Link
      href={`/players/${player.player_id}`}
      className="siq-case-card siq-row-enter"
      style={{ '--case-accent': accent, '--row-i': Math.min(index, 8) } as React.CSSProperties}
    >
        <div className="siq-case-card__head">
          <Avatar name={player.full_name} size="lg" position={player.position} playerId={player.player_id} />
          <div className="siq-min0">
            <div className="siq-players-card-name">
              {player.full_name}
            </div>
            <div className="ds-note siq-players-card-meta">
              {team?.abbreviation ?? '—'} · {player.position ?? '—'} · {player.latest_season ?? '—'}
            </div>
          </div>
        </div>

        {valuation ? (
          <>
            {/* Verdict + hero gap */}
            <div className="siq-case-card__verdict">
              <span className="siq-players-verdict-label" style={{ color: toneText(tone) }}>
                {valuation.verdict_label ?? classifyGap(gap).label}
              </span>
              {gap != null && (
                <CountUpPct
                  value={gap}
                  withSign
                  className="siq-players-verdict-gap"
                  style={{ color: toneColor(tone) }}
                />
              )}
            </div>

            <ValuePayGauge
              value={valuation.value_pct}
              lo={valuation.lo_pct}
              hi={valuation.hi_pct}
              pay={valuation.actual_pct}
              tone={tone}
            />

            <div className="siq-case-card__metrics">
              <MetricCell label="value" dotColor="var(--confidence)" pct={valuation.value_pct} usd={valueUsd} />
              <MetricCell label="pay" dotColor={toneColor(tone)} pct={valuation.actual_pct} usd={valuation.actual_usd} align="right" />
            </div>

            {valuation.stats && <CardStatLine stats={valuation.stats} />}
          </>
        ) : player.valuation_status === 'unavailable' ? (
          <div className="ds-note siq-players-card-empty">
            No valuation data
          </div>
        ) : (
          <div className="ds-note siq-players-card-empty">
            Loading valuation…
          </div>
        )}
    </Link>
  );
}

const PAGE_SIZE = 24;
const BUCKETS: Array<{ value: WatchlistBucket; label: string }> = [
  { value: 'all', label: 'All mismatches' },
  { value: 'underpaid', label: 'Underpaid' },
  { value: 'overpaid', label: 'Overpaid' },
];
const POSITIONS = ['', 'PG', 'SG', 'SF', 'PF', 'C'];
const SORTS: Array<{ value: WatchlistSort; label: string }> = [
  { value: 'mismatch', label: 'Largest mismatch' },
  { value: 'gap', label: 'Signed gap' },
  { value: 'value', label: 'Highest value' },
  { value: 'pay', label: 'Highest pay' },
  { value: 'name', label: 'Name (A–Z)' },
];

function PlayersContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const q = searchParams.get('q') ?? '';

  const [draftQuery, setDraftQuery] = useState(q);
  const bucketParam = searchParams.get('bucket');
  const [bucket, setBucket] = useState<WatchlistBucket>(
    bucketParam === 'underpaid' || bucketParam === 'overpaid' ? bucketParam : 'all',
  );
  const [sort, setSort] = useState<WatchlistSort>('mismatch');
  const [position, setPosition] = useState('');
  const [qualifiedOnly, setQualifiedOnly] = useState(true);
  const [offset, setOffset] = useState(0);

  useEffect(() => {
    setDraftQuery(q);
  }, [q]);

  useEffect(() => {
    if (draftQuery === q) return;
    const t = setTimeout(() => {
      const trimmed = draftQuery.trim();
      router.replace(trimmed ? `/players?q=${encodeURIComponent(trimmed)}` : '/players');
    }, 250);
    return () => clearTimeout(t);
  }, [draftQuery, q, router]);

  useEffect(() => {
    setOffset(0);
  }, [q, bucket, sort, position, qualifiedOnly]);

  const { data: watchlist, loading, error } = useApi<PlayerWatchlistResponse>(
    (signal) => getPlayerWatchlist({
      query: q || undefined,
      bucket,
      sort,
      position: position || undefined,
      qualifiedOnly,
      limit: PAGE_SIZE,
      offset,
    }, signal),
    [q, bucket, sort, position, qualifiedOnly, offset],
    { fallback: 'Failed to load players.' },
  );

  const players = watchlist?.items ?? [];
  const total = watchlist?.total ?? 0;
  const pageStart = total === 0 ? 0 : offset + 1;
  const pageEnd = Math.min(offset + PAGE_SIZE, total);
  const canPageBack = offset > 0;
  const canPageForward = offset + PAGE_SIZE < total;

  return (
    <div>
      <div className="siq-watchlist-command">
        <div className="siq-players-title-row">
          <h1 className="siq-players-title">
            Contract watchlist
          </h1>
          {!loading && (
            <span className="ds-note">
              {total} players · largest value/pay mismatches{watchlist?.season ? ` · ${watchlist.season}` : ''}
            </span>
          )}
          {q && (
            <Badge tone="accent" size="sm">
              Searching: {q}
              <button
                type="button"
                aria-label="Clear player search"
                onClick={() => { setDraftQuery(''); router.push('/players'); }}
                className="siq-players-search-clear"
              >
                x
              </button>
            </Badge>
          )}
        </div>

        <div className="siq-players-search-bar">
          <Search size={15} color="var(--text-muted)" />
          <input
            type="text"
            value={draftQuery}
            onChange={(e) => setDraftQuery(e.target.value)}
            placeholder="Search by first name, last name, or both..."
            aria-label="Search watchlist players"
            className="siq-players-search-input"
          />
        </div>

        <div className="siq-row siq-row--10 siq-players-filter-row">
          <SegmentedControl
            options={BUCKETS}
            value={bucket}
            onChange={setBucket}
            ariaLabel="Filter by mismatch type"
          />

          <Select
            selectSize="sm"
            value={position}
            onChange={(e) => setPosition(e.target.value)}
            aria-label="Filter by position"
          >
            {POSITIONS.map((p) => (
              <option key={p || 'all'} value={p}>{p || 'All positions'}</option>
            ))}
          </Select>

          <Select
            selectSize="sm"
            value={sort}
            onChange={(e) => setSort(e.target.value as WatchlistSort)}
            aria-label="Sort players"
          >
            {SORTS.map((s) => (
              <option key={s.value} value={s.value}>Sort: {s.label}</option>
            ))}
          </Select>

          <label className="siq-check">
            <input
              type="checkbox"
              checked={qualifiedOnly}
              onChange={(e) => setQualifiedOnly(e.target.checked)}
            />
            Qualified only
          </label>
        </div>
      </div>

      {loading && (
        <div role="status" aria-label="Loading players">
          <div className="siq-pressure-board" aria-hidden="true">
            {Array.from({ length: 8 }).map((_, i) => (
              <div
                key={i}
                className="siq-case-card siq-case-skel"
                style={{ ['--i' as string]: Math.min(i, 11) }}
              >
                <div className="siq-case-skel__head">
                  <Skeleton className="siq-case-skel__avatar" />
                  <span className="siq-players-skel-meta">
                    <Skeleton height={13} width="62%" />
                    <Skeleton height={10} width="38%" />
                  </span>
                </div>
                <Skeleton height={24} width="46%" />
                <Skeleton height={12} />
                <div className="siq-players-skel-metrics">
                  <Skeleton height={32} />
                  <Skeleton height={32} />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {error && (
        <Alert tone="negative">
          {error} — is the FastAPI server running at localhost:8000?
        </Alert>
      )}

      {!loading && !error && players.length === 0 && (
        <EmptyState
          title={q ? `No players match "${q}".` : 'No players found.'}
          description={q ? 'Try a shorter name or clear the search.' : undefined}
        />
      )}

      {!loading && players.length > 0 && (
        <>
          <div className="siq-players-legend-row">
            <span className="siq-players-legend-item">
              <span className="siq-players-legend-swatch--band" />
              Production-implied value · 80% interval
            </span>
            <span className="siq-players-legend-item">
              <span className="siq-players-legend-swatch--dot" />
              Actual pay
            </span>
            <span>Value excludes current salary on purpose — this is worth, not what is on the books.</span>
          </div>

          <div className="siq-pressure-board">
            {players.map((p, i) => <RosterCard key={p.player_id} player={p} index={i} />)}
          </div>

          <div className="siq-players-pagination-row">
            <span className="ds-note">
              Showing {pageStart}-{pageEnd} of {total}
            </span>
            <div className="siq-pagination siq-players-pagination-buttons">
              <Button size="sm" disabled={!canPageBack} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
                Previous
              </Button>
              <Button
                size="sm"
                variant={canPageForward ? 'primary' : 'secondary'}
                disabled={!canPageForward}
                onClick={() => setOffset(offset + PAGE_SIZE)}
              >
                Next
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

export default function PlayersPage() {
  return (
    <Suspense fallback={<LoadingNote>Loading…</LoadingNote>}>
      <PlayersContent />
    </Suspense>
  );
}
