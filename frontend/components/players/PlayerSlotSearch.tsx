'use client';

import { useEffect, useState } from 'react';
import { Search } from 'lucide-react';
import { searchPlayers, PlayerSummary } from '@/lib/api';
import { Avatar } from '@/components/ui/Avatar';

interface PlayerSlotSearchProps {
  slotLabel: string;
  excludePlayerId?: number | null;
  onPick: (player: PlayerSummary) => void;
}

export function PlayerSlotSearch({ slotLabel, excludePlayerId, onPick }: PlayerSlotSearchProps) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<PlayerSummary[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // True once a search has actually resolved for the current query. Without this,
  // the zero-result state is unreachable (nothing to show → menu stays hidden), and
  // showing it eagerly would flash "No players found." during the debounce window.
  const [searched, setSearched] = useState(false);

  useEffect(() => {
    const trimmed = query.trim();
    if (!trimmed) {
      setResults([]);
      setLoading(false);
      setError(null);
      setSearched(false);
      return;
    }
    // Drop results from the previous query immediately. Keeping them through the
    // debounce window left stale players selectable under a query they no longer
    // match (e.g. picking "Aaron Gordon" while the box reads a non-matching term).
    setResults([]);
    setSearched(false);
    const controller = new AbortController();
    const t = setTimeout(() => {
      setLoading(true);
      setError(null);
      searchPlayers(trimmed, 8, controller.signal)
        .then((r) => {
          setResults(r);
          setSearched(true);
        })
        .catch((e: unknown) => {
          if (controller.signal.aborted) return;
          setResults([]);
          setError(e instanceof Error ? e.message : 'Player search failed.');
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }, 250);
    return () => {
      clearTimeout(t);
      controller.abort();
    };
  }, [query]);

  const filteredResults = results.filter((p) => p.player_id !== excludePlayerId);
  const showMenu = open && query.trim().length > 0 && (loading || error || searched || filteredResults.length > 0);

  return (
    <div className="siq-compare-search">
      <div className="siq-row siq-compare-search-field">
        <Search size={15} color="var(--text-muted)" />
        <input
          type="text"
          placeholder={`Search a player for ${slotLabel}…`}
          value={query}
          aria-label={`Search a player for ${slotLabel}`}
          onChange={(e) => { setQuery(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          className="siq-compare-search-input"
        />
      </div>
      {showMenu && (
        <div className="siq-compare-search-menu" role="listbox" aria-label={`${slotLabel} search results`}>
          {loading ? (
            <div className="ds-note ds-note--13 siq-compare-search-status">Searching…</div>
          ) : error ? (
            <div className="ds-note ds-note--13 siq-compare-search-status siq-compare-search-status--error">
              {error}
            </div>
          ) : filteredResults.length === 0 ? (
            <div className="ds-note ds-note--13 siq-compare-search-status">No players found.</div>
          ) : (
            filteredResults.map((p) => (
              <button
                key={p.player_id}
                type="button"
                role="option"
                aria-selected={false}
                className="siq-row siq-row--10 siq-compare-search-result"
                onClick={() => { onPick(p); setQuery(''); setResults([]); setOpen(false); }}
              >
                <Avatar name={p.full_name} size="sm" position={p.position} playerId={p.player_id} />
                <div>
                  <div className="siq-compare-search-result-name">{p.full_name}</div>
                  <div className="ds-note">
                    {p.current_team?.abbreviation ?? p.latest_stats_team?.abbreviation ?? '—'} · {p.position ?? '—'}
                  </div>
                </div>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
