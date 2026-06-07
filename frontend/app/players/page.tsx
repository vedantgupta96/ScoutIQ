'use client';

import { useEffect, useState, Suspense } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { Search } from 'lucide-react';
import {
  getPlayerWatchlist,
  PlayerCardResponse,
  PlayerWatchlistResponse,
  WatchlistBucket,
} from '@/lib/api';
import { VerdictPill } from '@/components/ui/VerdictPill';
import { Avatar } from '@/components/ui/Avatar';
import { Badge } from '@/components/ui/Badge';
import { fmtPct } from '@/lib/utils';

function RosterCard({ player }: { player: PlayerCardResponse }) {
  const [hovered, setHovered] = useState(false);
  const team = player.current_team ?? player.latest_stats_team;
  const valuation = player.valuation_status === 'ready' ? player.valuation : undefined;
  const gap = valuation?.gap_pct ?? null;
  const accent = gap == null
    ? 'var(--border-subtle)'
    : gap >= 0 ? 'var(--positive)' : 'var(--negative)';

  return (
    <Link href={`/players/${player.player_id}`} style={{ textDecoration: 'none' }}>
      <button
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        style={{
          width: '100%',
          textAlign: 'left',
          border: `1px solid ${hovered ? 'var(--border-strong)' : 'var(--border-subtle)'}`,
          background: `linear-gradient(180deg, ${accent} 0 3px, var(--bg-panel) 3px)`,
          borderRadius: 'var(--radius-lg)',
          padding: 16,
          cursor: 'pointer',
          display: 'flex',
          flexDirection: 'column',
          gap: 14,
          boxShadow: hovered ? 'var(--shadow-md)' : 'var(--shadow-card)',
          transition: 'border-color var(--duration-fast) var(--ease-out), box-shadow var(--duration-fast) var(--ease-out)',
        }}
      >
        {/* Header row */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
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

        {/* Value row */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
          {valuation ? (
            <>
              <VerdictPill gapPct={valuation.gap_pct} size="sm" />
              <div style={{ textAlign: 'right' }}>
                <div className="ds-eyebrow">value / pay</div>
                <div className="ds-tnum" style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 2 }}>
                  {fmtPct(valuation.value_pct)} / {valuation.actual_pct != null ? fmtPct(valuation.actual_pct) : '—'}
                </div>
              </div>
            </>
          ) : player.valuation_status === 'unavailable' ? (
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              No valuation data
            </div>
          ) : (
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Loading valuation…</div>
          )}
        </div>
      </button>
    </Link>
  );
}

function EmptyState({ query }: { query: string }) {
  return (
    <div style={{ padding: 48, textAlign: 'center', color: 'var(--text-muted)', fontSize: 14 }}>
      {query ? `No players match "${query}".` : 'No players found.'}
    </div>
  );
}

const PAGE_SIZE = 24;
const BUCKETS: Array<{ value: WatchlistBucket; label: string }> = [
  { value: 'all', label: 'All mismatches' },
  { value: 'underpaid', label: 'Underpaid' },
  { value: 'overpaid', label: 'Overpaid' },
];
const POSITIONS = ['', 'PG', 'SG', 'SF', 'PF', 'C'];

function PlayersContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const q = searchParams.get('q') ?? '';

  const [draftQuery, setDraftQuery] = useState(q);
  const [watchlist, setWatchlist] = useState<PlayerWatchlistResponse | null>(null);
  const [bucket, setBucket] = useState<WatchlistBucket>('all');
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
  }, [q, bucket, position, qualifiedOnly]);

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
  }, [q, bucket, position, qualifiedOnly, offset]);

  const players = watchlist?.items ?? [];
  const total = watchlist?.total ?? 0;
  const pageStart = total === 0 ? 0 : offset + 1;
  const pageEnd = Math.min(offset + PAGE_SIZE, total);
  const canPageBack = offset > 0;
  const canPageForward = offset + PAGE_SIZE < total;

  return (
    <div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
          <span className="ds-eyebrow">Contract Watchlist</span>
          {!loading && (
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              {total} players · largest value/pay mismatches{watchlist?.season ? ` · ${watchlist.season}` : ''}
            </span>
          )}
          {q && (
            <Badge tone="accent" size="sm">
              Searching: {q}
              <button
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
          <div style={{
            display: 'inline-flex',
            padding: 3,
            gap: 3,
            border: '1px solid var(--border-subtle)',
            borderRadius: 'var(--radius-md)',
            background: 'var(--bg-panel)',
          }}>
            {BUCKETS.map((b) => {
              const active = bucket === b.value;
              return (
                <button
                  key={b.value}
                  onClick={() => setBucket(b.value)}
                  style={{
                    border: 'none',
                    borderRadius: 'calc(var(--radius-md) - 3px)',
                    padding: '7px 10px',
                    background: active ? 'var(--accent-soft)' : 'transparent',
                    color: active ? 'var(--accent-text)' : 'var(--text-secondary)',
                    fontSize: 12,
                    fontWeight: 700,
                    cursor: 'pointer',
                  }}
                >
                  {b.label}
                </button>
              );
            })}
          </div>

          <select
            value={position}
            onChange={(e) => setPosition(e.target.value)}
            style={{
              height: 34,
              borderRadius: 'var(--radius-md)',
              border: '1px solid var(--border-subtle)',
              background: 'var(--bg-panel)',
              color: 'var(--text-primary)',
              padding: '0 10px',
              fontFamily: 'var(--font-sans)',
              fontSize: 12,
              fontWeight: 600,
            }}
          >
            {POSITIONS.map((p) => (
              <option key={p || 'all'} value={p}>{p || 'All positions'}</option>
            ))}
          </select>

          <label style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 7,
            height: 34,
            padding: '0 10px',
            border: '1px solid var(--border-subtle)',
            borderRadius: 'var(--radius-md)',
            background: 'var(--bg-panel)',
            color: 'var(--text-secondary)',
            fontSize: 12,
            fontWeight: 600,
          }}>
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
        <div style={{ padding: 48, textAlign: 'center', color: 'var(--text-muted)' }}>Loading…</div>
      )}

      {error && (
        <div style={{
          padding: '12px 16px', borderRadius: 'var(--radius-lg)',
          background: 'var(--negative-soft)', color: 'var(--negative-text)',
          border: '1px solid var(--red-500)30', fontSize: 13, marginBottom: 16,
        }}>
          {error} — is the FastAPI server running at localhost:8000?
        </div>
      )}

      {!loading && !error && players.length === 0 && <EmptyState query={q} />}

      {!loading && players.length > 0 && (
        <>
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(248px, 1fr))',
            gap: 'var(--panel-gap)',
          }}>
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
            <div style={{ display: 'flex', gap: 8 }}>
              <button
                disabled={!canPageBack}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                style={{
                  padding: '8px 12px',
                  borderRadius: 'var(--radius-md)',
                  border: '1px solid var(--border-subtle)',
                  background: 'var(--bg-panel)',
                  color: canPageBack ? 'var(--text-primary)' : 'var(--text-muted)',
                  cursor: canPageBack ? 'pointer' : 'not-allowed',
                  fontSize: 12,
                  fontWeight: 700,
                }}
              >
                Previous
              </button>
              <button
                disabled={!canPageForward}
                onClick={() => setOffset(offset + PAGE_SIZE)}
                style={{
                  padding: '8px 12px',
                  borderRadius: 'var(--radius-md)',
                  border: '1px solid var(--border-subtle)',
                  background: canPageForward ? 'var(--accent)' : 'var(--bg-panel)',
                  color: canPageForward ? 'var(--text-on-accent)' : 'var(--text-muted)',
                  cursor: canPageForward ? 'pointer' : 'not-allowed',
                  fontSize: 12,
                  fontWeight: 700,
                }}
              >
                Next
              </button>
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
