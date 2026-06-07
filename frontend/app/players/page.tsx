'use client';

import { useEffect, useState, useCallback, Suspense } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { PlayerSummary, searchPlayers } from '@/lib/api';
import { getValuation, ValuationResponse } from '@/lib/api';
import { VerdictPill } from '@/components/ui/VerdictPill';
import { Avatar } from '@/components/ui/Avatar';
import { Badge } from '@/components/ui/Badge';
import { fmtPct } from '@/lib/utils';

function RosterCard({ player }: { player: PlayerSummary & { valuation?: ValuationResponse } }) {
  const [hovered, setHovered] = useState(false);
  const team = player.current_team ?? player.latest_stats_team;

  return (
    <Link href={`/players/${player.player_id}`} style={{ textDecoration: 'none' }}>
      <button
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        style={{
          width: '100%',
          textAlign: 'left',
          border: `1px solid ${hovered ? 'var(--border-strong)' : 'var(--border-subtle)'}`,
          background: 'var(--bg-panel)',
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
          <Avatar name={player.full_name} size="lg" position={player.position} />
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
          {player.valuation ? (
            <>
              <VerdictPill gapPct={player.valuation.gap_pct} size="sm" />
              <div style={{ textAlign: 'right' }}>
                <div className="ds-eyebrow">value / pay</div>
                <div className="ds-tnum" style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 2 }}>
                  {fmtPct(player.valuation.value_pct)} / {player.valuation.actual_pct != null ? fmtPct(player.valuation.actual_pct) : '—'}
                </div>
              </div>
            </>
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

type PlayerWithVal = PlayerSummary & { valuation?: ValuationResponse };

function PlayersContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const q = searchParams.get('q') ?? '';

  const [players, setPlayers] = useState<PlayerWithVal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (query: string) => {
    setLoading(true);
    setError(null);
    try {
      const list = await searchPlayers(query || undefined, 40);
      setPlayers(list.map((p) => ({ ...p, valuation: undefined })));

      // Hydrate valuations in background — non-blocking
      list.forEach((p) => {
        getValuation(p.player_id).then((val) => {
          setPlayers((prev) =>
            prev.map((r) => r.player_id === p.player_id ? { ...r, valuation: val } : r)
          );
        }).catch(() => {});
      });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load players.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(q); }, [q, load]);

  const sorted = [...players].sort((a, b) => {
    const ag = a.valuation?.gap_pct;
    const bg = b.valuation?.gap_pct;
    if (ag == null && bg == null) return 0;
    if (ag == null) return 1;
    if (bg == null) return -1;
    return Math.abs(bg) - Math.abs(ag);
  });

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 16 }}>
        <span className="ds-eyebrow">Watchlist</span>
        {!loading && (
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            {players.length} players · sorted by |value − pay| gap
          </span>
        )}
        {q && (
          <Badge tone="accent" size="sm">
            Searching: {q}
            <button
              onClick={() => router.push('/players')}
              style={{ background: 'none', border: 'none', cursor: 'pointer', marginLeft: 4, color: 'inherit', padding: 0 }}
            >
              ✕
            </button>
          </Badge>
        )}
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

      {!loading && sorted.length > 0 && (
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(248px, 1fr))',
          gap: 'var(--panel-gap)',
        }}>
          {sorted.map((p) => <RosterCard key={p.player_id} player={p} />)}
        </div>
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
