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
import { Select } from '@/components/ui/Select';
import { SegmentedControl } from '@/components/ui/SegmentedControl';
import { Skeleton } from '@/components/ui/Skeleton';
import { fmtM, fmtPct, gapLabel, gapTone, signed } from '@/lib/utils';

type GapTone = 'positive' | 'negative' | 'neutral' | 'warning';

const TONE_COLOR: Record<GapTone, string> = {
  positive: 'var(--positive)',
  negative: 'var(--negative)',
  neutral: 'var(--text-secondary)',
  warning: 'var(--warning)',
};
const TONE_TEXT: Record<GapTone, string> = {
  positive: 'var(--positive-text)',
  negative: 'var(--negative-text)',
  neutral: 'var(--text-secondary)',
  warning: 'var(--warning-text)',
};

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
}: { value: number; lo: number; hi: number; pay: number | null; tone: GapTone }) {
  const domainMax = Math.max(hi, value, pay ?? 0) * 1.12 || 6;
  const pct = (x: number) => Math.max(0, Math.min(100, (x / domainMax) * 100));
  const bandLeft = pct(lo);
  const bandWidth = Math.max(pct(hi) - bandLeft, 1.5);
  const valuePos = pct(value);
  const payPos = pay != null ? pct(pay) : null;
  const payColor = TONE_COLOR[tone];

  return (
    <div style={{ position: 'relative', paddingTop: 7 }}>
      {/* markers float above the track so they read past the rounded ends */}
      <div style={{
        position: 'absolute', top: 0, left: `calc(${valuePos}% - 3px)`,
        width: 6, height: 6, borderRadius: '50%', background: 'var(--confidence)',
        border: '1px solid var(--bg-panel)',
      }} />
      {payPos != null && (
        <div style={{
          position: 'absolute', top: 0, left: `calc(${payPos}% - 3px)`,
          width: 6, height: 6, borderRadius: '50%', background: payColor,
          border: '1px solid var(--bg-panel)',
        }} />
      )}
      <div style={{
        position: 'relative', height: 11, borderRadius: 'var(--radius-pill)',
        background: 'var(--bg-inset)', border: '1px solid var(--border-subtle)',
        overflow: 'hidden',
      }}>
        <div
          style={{
            position: 'absolute', top: 0, bottom: 0, left: `${bandLeft}%`,
            width: `${bandWidth}%`,
            background: 'var(--confidence-soft)',
            borderLeft: '1.5px solid var(--confidence)',
            borderRight: '1.5px solid var(--confidence)',
          }}
        />
        <div style={{
          position: 'absolute', top: 0, bottom: 0, left: `calc(${valuePos}% - 1px)`,
          width: 2, background: 'var(--confidence)',
        }} />
        {payPos != null && (
          <div style={{
            position: 'absolute', top: 0, bottom: 0, left: `calc(${payPos}% - 1px)`,
            width: 2, background: payColor,
          }} />
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
      <div className="ds-eyebrow" style={{
        display: 'flex', alignItems: 'center', gap: 5,
        justifyContent: align === 'right' ? 'flex-end' : 'flex-start',
      }}>
        <span style={{ width: 6, height: 6, borderRadius: '50%', background: dotColor }} />
        {label}
      </div>
      <div className="ds-tnum" style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)', marginTop: 3 }}>
        {pct != null ? fmtPct(pct) : '—'}
      </div>
      <div className="ds-tnum" style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 1 }}>
        {usd != null ? fmtM(usd) : '—'}
      </div>
    </div>
  );
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
      {items.map(({ value, label }) => (
        <span key={label} className="siq-statline__cell">
          <span className="siq-statline__value ds-tnum">{value}</span>
          <span className="siq-statline__label">{label}</span>
        </span>
      ))}
    </div>
  );
}

function RosterCard({ player }: { player: PlayerCardResponse }) {
  const team = player.current_team ?? player.latest_stats_team;
  const valuation = player.valuation_status === 'ready' ? player.valuation : undefined;
  const gap = valuation?.gap_pct ?? null;
  const tone: GapTone = valuation?.verdict_tone ?? gapTone(gap);
  const accent = gap == null ? 'var(--border-strong)' : TONE_COLOR[tone];
  const valueUsd = valuation?.salary_cap != null
    ? (valuation.value_pct / 100) * valuation.salary_cap
    : null;

  return (
    <Link
      href={`/players/${player.player_id}`}
      className="siq-case-card"
      style={{ '--case-accent': accent } as React.CSSProperties}
    >
        <div className="siq-case-card__head">
          <Avatar name={player.full_name} size="lg" position={player.position} playerId={player.player_id} />
          <div style={{ minWidth: 0 }}>
            <div style={{
              fontSize: 15, fontWeight: 600, fontFamily: 'var(--font-display)',
              color: 'var(--text-primary)', whiteSpace: 'nowrap',
              overflow: 'hidden', textOverflow: 'ellipsis',
            }}>
              {player.full_name}
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
              {team?.abbreviation ?? '—'} · {player.position ?? '—'} · {player.latest_season ?? '—'}
            </div>
          </div>
        </div>

        {valuation ? (
          <>
            {/* Verdict + hero gap */}
            <div className="siq-case-card__verdict">
              <span style={{ fontSize: 12, fontWeight: 600, color: TONE_TEXT[tone] }}>
                {valuation.verdict_label ?? gapLabel(gap)}
              </span>
              {gap != null && (
                <CountUpPct
                  value={gap}
                  withSign
                  style={{
                    fontSize: 24, fontWeight: 700, lineHeight: 1,
                    fontFamily: 'var(--font-display)', color: TONE_COLOR[tone],
                  }}
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
              <MetricCell label="pay" dotColor={TONE_COLOR[tone]} pct={valuation.actual_pct} usd={valuation.actual_usd} align="right" />
            </div>

            {valuation.stats && <CardStatLine stats={valuation.stats} />}
          </>
        ) : player.valuation_status === 'unavailable' ? (
          <div style={{
            paddingTop: 12, borderTop: '1px solid var(--border-subtle)',
            fontSize: 12, color: 'var(--text-muted)',
          }}>
            No valuation data
          </div>
        ) : (
          <div style={{
            paddingTop: 12, borderTop: '1px solid var(--border-subtle)',
            fontSize: 12, color: 'var(--text-muted)',
          }}>
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
  const [watchlist, setWatchlist] = useState<PlayerWatchlistResponse | null>(null);
  const [bucket, setBucket] = useState<WatchlistBucket>('all');
  const [sort, setSort] = useState<WatchlistSort>('mismatch');
  const [position, setPosition] = useState('');
  const [qualifiedOnly, setQualifiedOnly] = useState(true);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const response = await getPlayerWatchlist({
          query: q || undefined,
          bucket,
          sort,
          position: position || undefined,
          qualifiedOnly,
          limit: PAGE_SIZE,
          offset,
        }, controller.signal);
        if (cancelled) return;
        setWatchlist(response);
        setLoading(false);
      } catch (e: unknown) {
        if (cancelled) return;
        if (e instanceof DOMException && e.name === 'AbortError') return;
        setError(e instanceof Error ? e.message : 'Failed to load players.');
        setWatchlist(null);
        setLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [q, bucket, sort, position, qualifiedOnly, offset]);

  const players = watchlist?.items ?? [];
  const total = watchlist?.total ?? 0;
  const pageStart = total === 0 ? 0 : offset + 1;
  const pageEnd = Math.min(offset + PAGE_SIZE, total);
  const canPageBack = offset > 0;
  const canPageForward = offset + PAGE_SIZE < total;

  return (
    <div>
      <div className="siq-watchlist-command">
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
          <h1 style={{
            margin: 0,
            fontFamily: 'var(--font-display)',
            fontSize: 24,
            fontWeight: 700,
            lineHeight: 1,
            color: 'var(--text-primary)',
          }}>
            Contract watchlist
          </h1>
          {!loading && (
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
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
                style={{ background: 'none', border: 'none', cursor: 'pointer', marginLeft: 4, color: 'inherit', padding: 0 }}
              >
                x
              </button>
            </Badge>
          )}
        </div>

        <div style={{
          display: 'flex', alignItems: 'center', gap: 8,
          padding: '9px 12px', background: 'var(--bg-panel)',
          border: '1px solid var(--border-default)', borderRadius: 'var(--radius-md)',
          maxWidth: 520,
        }}>
          <Search size={15} color="var(--text-muted)" />
          <input
            type="text"
            value={draftQuery}
            onChange={(e) => setDraftQuery(e.target.value)}
            placeholder="Search by first name, last name, or both..."
            aria-label="Search watchlist players"
            style={{
              flex: 1,
              minWidth: 0,
              background: 'transparent',
              border: 'none',
              outline: 'none',
              fontFamily: 'var(--font-sans)',
              fontSize: 14,
              color: 'var(--text-primary)',
            }}
          />
        </div>

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center' }}>
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
                  <span style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 7 }}>
                    <Skeleton height={13} width="62%" />
                    <Skeleton height={10} width="38%" />
                  </span>
                </div>
                <Skeleton height={24} width="46%" />
                <Skeleton height={12} />
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginTop: 'auto' }}>
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
          <div style={{
            display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap',
            marginBottom: 12, fontSize: 12, color: 'var(--text-muted)',
          }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <span style={{ width: 16, height: 9, borderRadius: 3, background: 'var(--confidence-soft)', border: '1.5px solid var(--confidence)' }} />
              Production-implied value · 80% interval
            </span>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--text-secondary)' }} />
              Actual pay
            </span>
            <span>Value excludes current salary on purpose — this is worth, not what is on the books.</span>
          </div>

          <div className="siq-pressure-board">
            {players.map((p) => <RosterCard key={p.player_id} player={p} />)}
          </div>

          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 12,
            marginTop: 18,
            flexWrap: 'wrap',
          }}>
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              Showing {pageStart}-{pageEnd} of {total}
            </span>
            <div className="siq-pagination" style={{ display: 'flex', gap: 8 }}>
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
    <Suspense fallback={<div style={{ padding: 48, textAlign: 'center', color: 'var(--text-muted)' }}>Loading…</div>}>
      <PlayersContent />
    </Suspense>
  );
}
