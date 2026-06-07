'use client';

import { useEffect, useMemo, useState, Suspense } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { Search } from 'lucide-react';
import { getPlayerCards, PlayerCardResponse } from '@/lib/api';
import { VerdictPill } from '@/components/ui/VerdictPill';
import { Avatar } from '@/components/ui/Avatar';
import { Badge } from '@/components/ui/Badge';
import { fmtPct } from '@/lib/utils';

function RosterCard({ player }: { player: PlayerCardResponse }) {
  const [hovered, setHovered] = useState(false);
  const team = player.current_team ?? player.latest_stats_team;
  const valuation = player.valuation_status === 'ready' ? player.valuation : undefined;

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

function PlayersContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const q = searchParams.get('q') ?? '';

  const [draftQuery, setDraftQuery] = useState(q);
  const [players, setPlayers] = useState<PlayerCardResponse[]>([]);
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
    let cancelled = false;
    const controller = new AbortController();

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const list = await getPlayerCards(q || undefined, 40, controller.signal);
        if (cancelled) return;
        setPlayers(list);
        setLoading(false);
      } catch (e: unknown) {
        if (cancelled) return;
        if (e instanceof DOMException && e.name === 'AbortError') return;
        setError(e instanceof Error ? e.message : 'Failed to load players.');
        setPlayers([]);
        setLoading(false);
      }
    }

    load();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [q]);

  const sorted = useMemo(() => [...players].sort((a, b) => {
    const ag = a.valuation?.gap_pct;
    const bg = b.valuation?.gap_pct;
    if (ag == null && bg == null) return 0;
    if (ag == null) return 1;
    if (bg == null) return -1;
    return Math.abs(bg) - Math.abs(ag);
  }), [players]);

  return (
    <div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
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
