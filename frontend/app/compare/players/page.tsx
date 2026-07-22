'use client';

import { useCallback, useEffect, useState, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { ArrowLeftRight, GitCompare, X } from 'lucide-react';
import { PlayerSummary } from '@/lib/api';
import { PlayerComparisonData, loadPlayerComparison } from '@/lib/playerComparisonApi';
import { Panel } from '@/components/ui/Panel';
import { IconButton } from '@/components/ui/IconButton';
import { Button } from '@/components/ui/Button';
import { EmptyState } from '@/components/ui/EmptyState';
import { LoadingNote } from '@/components/ui/LoadingNote';
import { Alert } from '@/components/ui/Alert';
import { Avatar } from '@/components/ui/Avatar';
import { PlayerSlotSearch } from '@/components/players/PlayerSlotSearch';
import { ComparisonTable } from '@/components/players/ComparisonTable';

type SlotKey = 'a' | 'b';

interface SlotState {
  playerId: number | null;
  data: PlayerComparisonData | null;
  loading: boolean;
  error: string | null;
}

const EMPTY_SLOT: SlotState = { playerId: null, data: null, loading: false, error: null };

function parseSlotId(value: string | null): number | null {
  if (!value) return null;
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? n : null;
}

function slotName(slot: SlotState): string {
  // Summary is the model-independent identity source, so it is consulted before
  // falling back to a bare id — a valuation failure must not blank the header.
  if (slot.data?.summary?.full_name) return slot.data.summary.full_name;
  if (slot.data?.valuation?.player_name) return slot.data.valuation.player_name;
  if (slot.data?.contract?.player_name) return slot.data.contract.player_name;
  if (slot.playerId != null) return `Player #${slot.playerId}`;
  return 'Player';
}

/** Every *core* source (identity, valuation, contract) failed, leaving nothing
 *  factual to show — so an error is surfaced instead of a table of "Not
 *  available" rows. Comp synthesis is deliberately excluded: it is legitimately
 *  null for players with too few paid comps, so its absence is not a failure. */
function slotCoreUnavailable(slot: SlotState): boolean {
  const d = slot.data;
  if (!d) return false;
  return !d.summary && !d.valuation && !d.contract;
}

function slotErrorMessage(slot: SlotState): string | null {
  const d = slot.data;
  if (!d) return null;
  return d.summaryError ?? d.valuationError ?? d.contractError ?? 'Player data is unavailable.';
}

function useComparisonSlot(playerId: number | null): SlotState {
  const [state, setState] = useState<SlotState>(EMPTY_SLOT);

  useEffect(() => {
    if (playerId == null) {
      setState(EMPTY_SLOT);
      return;
    }
    const controller = new AbortController();
    setState({ playerId, data: null, loading: true, error: null });
    loadPlayerComparison(playerId, controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return;
        setState({ playerId, data, loading: false, error: null });
      })
      .catch((e: unknown) => {
        if (controller.signal.aborted) return;
        setState({
          playerId,
          data: null,
          loading: false,
          error: e instanceof Error ? e.message : 'Failed to load player comparison data.',
        });
      });
    return () => controller.abort();
  }, [playerId]);

  return state;
}

function SlotPanel({
  label,
  slot,
  otherId,
  onPick,
  onClear,
}: {
  label: string;
  slot: SlotState;
  otherId: number | null;
  onPick: (player: PlayerSummary) => void;
  onClear: () => void;
}) {
  return (
    <Panel variant="card" eyebrow={label} icon={<GitCompare size={15} />}>
      {slot.playerId == null ? (
        <PlayerSlotSearch slotLabel={label} excludePlayerId={otherId} onPick={onPick} />
      ) : (
        <div className="siq-compare-slot-filled">
          <div className="siq-row siq-row--10 siq-min0">
            <Avatar
              name={slotName(slot)}
              size="md"
              position={slot.data?.valuation?.position ?? slot.data?.summary?.position}
              playerId={slot.playerId}
            />
            <div className="siq-min0">
              <div className="siq-compare-slot-name">{slotName(slot)}</div>
              <div className="ds-note">
                {slot.loading
                  ? 'Loading…'
                  : slot.data?.valuation?.current_team?.abbreviation
                    ?? slot.data?.summary?.current_team?.abbreviation
                    ?? slot.data?.summary?.latest_stats_team?.abbreviation
                    ?? 'Not available'}
              </div>
            </div>
          </div>
          <IconButton label={`Clear ${label}`} onClick={onClear}>
            <X size={15} />
          </IconButton>
        </div>
      )}
      {slot.error && <Alert tone="negative">{slot.error}</Alert>}
      {/* Surfaced per slot so a single bad player still reports its error, even
          while the other slot is empty and the main area shows the neutral prompt. */}
      {!slot.error && slotCoreUnavailable(slot) && (
        <Alert tone="negative">{slotErrorMessage(slot)}</Alert>
      )}
    </Panel>
  );
}

function ComparePlayersContent() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const idA = parseSlotId(searchParams.get('a'));
  const idB = parseSlotId(searchParams.get('b'));

  const slotA = useComparisonSlot(idA);
  const slotB = useComparisonSlot(idB);

  // Picking, clearing and swapping are user actions, so each pushes a history
  // entry — Back walks through previous comparison states instead of jumping
  // straight out of the workspace.
  const writeSlots = useCallback((nextA: number | null, nextB: number | null) => {
    const next = new URLSearchParams(searchParams.toString());
    if (nextA != null) next.set('a', String(nextA)); else next.delete('a');
    if (nextB != null) next.set('b', String(nextB)); else next.delete('b');
    router.push(`/compare/players${next.toString() ? `?${next.toString()}` : ''}`);
  }, [router, searchParams]);

  const pickA = (p: PlayerSummary) => writeSlots(p.player_id, idB);
  const pickB = (p: PlayerSummary) => writeSlots(idA, p.player_id);
  const clearA = () => writeSlots(null, idB);
  const clearB = () => writeSlots(idA, null);
  const swap = () => writeSlots(idB, idA);

  const bothFilled = idA != null && idB != null;

  return (
    <div className="siq-stack">
      <div className="siq-compare-header">
        <h1 className="siq-compare-title">
          <GitCompare size={18} /> Player comparison
        </h1>
        {bothFilled && (
          <Button size="sm" icon={<ArrowLeftRight size={14} />} onClick={swap}>
            Swap
          </Button>
        )}
      </div>

      <div className="siq-compare-slots">
        <SlotPanel label="Player A" slot={slotA} otherId={idB} onPick={pickA} onClear={clearA} />
        <SlotPanel label="Player B" slot={slotB} otherId={idA} onPick={pickB} onClear={clearB} />
      </div>

      {!bothFilled ? (
        <Panel variant="plain">
          <EmptyState
            title="Pick two players to compare."
            description="Search and select a player for each slot above to see a side-by-side valuation, pay, market, and production breakdown."
            icon={<GitCompare size={22} />}
          />
        </Panel>
      ) : slotA.loading || slotB.loading ? (
        <LoadingNote>Loading comparison…</LoadingNote>
      ) : slotA.error || slotB.error ? (
        <Alert tone="negative">{slotA.error ?? slotB.error}</Alert>
      ) : slotCoreUnavailable(slotA) || slotCoreUnavailable(slotB) ? (
        // loadPlayerComparison settles rather than throwing, so slot.error never
        // fires for a bad id. Each failing slot already reports its own reason in
        // its panel, so this only explains the absent table without repeating it.
        <Panel variant="plain">
          <EmptyState
            title="Comparison unavailable."
            description="One or both players could not be loaded. See the error on the affected slot above."
            icon={<GitCompare size={22} />}
          />
        </Panel>
      ) : slotA.data && slotB.data ? (
        <ComparisonTable a={slotA.data} b={slotB.data} nameA={slotName(slotA)} nameB={slotName(slotB)} />
      ) : null}
    </div>
  );
}

export default function ComparePlayersPage() {
  return (
    <Suspense fallback={<LoadingNote>Loading…</LoadingNote>}>
      <ComparePlayersContent />
    </Suspense>
  );
}
