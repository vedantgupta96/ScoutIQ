'use client';

import type { CSSProperties } from 'react';
import { useEffect, useRef, useState, Suspense } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import { Search, SlidersHorizontal, TriangleAlert } from 'lucide-react';
import {
  searchPlayers, getPlayer, simulateContract,
  PlayerSummary, SimulatorResponse, ContractYearResponse,
} from '@/lib/api';
import { Card } from '@/components/ui/Card';
import { Surface } from '@/components/ui/Surface';
import { Badge } from '@/components/ui/Badge';
import { StatTile } from '@/components/ui/StatTile';
import { VerdictPill } from '@/components/ui/VerdictPill';
import { AssumptionFlag } from '@/components/ui/AssumptionFlag';
import { Avatar } from '@/components/ui/Avatar';
import { MiniValuePayGauge } from '@/components/players/MiniValuePayGauge';
import { CapBar as SharedCapBar, CAP_TIER_LABEL, capTierBadgeTone } from '@/components/cap/CapBar';
import { capTier, fmtM, fmtPct, signed } from '@/lib/utils';
import { teamVisual } from '@/lib/teamVisuals';

// ---- Slider -------------------------------------------------------
function DSSlider({
  label, value, onChange, min, max, step, format,
}: {
  label: string; value: number; onChange: (v: number) => void;
  min: number; max: number; step: number; format: (v: number) => string;
}) {
  const pct = max === min ? 0 : ((value - min) / (max - min)) * 100;

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
        <span style={{ fontSize: 13, color: 'var(--text-secondary)', fontWeight: 500 }}>{label}</span>
        <span className="ds-tnum" style={{ fontSize: 13, color: 'var(--text-primary)', fontWeight: 600 }}>
          {format(value)}
        </span>
      </div>
      <input
        className="siq-slider"
        type="range" min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        style={{ '--siq-slider-pct': `${Math.min(100, Math.max(0, pct))}%` } as CSSProperties}
      />
    </div>
  );
}

// ---- CapBar (per contract year) -----------------------------------
function CapBar({ yr }: { yr: ContractYearResponse }) {
  const tier = capTier(yr.cap_hit_usd, yr.tax_line, yr.first_apron, yr.second_apron);
  const optionLabel = yr.is_player_option ? 'Player opt.' : yr.is_team_option ? 'Team opt.' : null;

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6, alignItems: 'center' }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span className="ds-tnum" style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
            {yr.season}
          </span>
          {optionLabel && <Badge tone="warning" size="sm">{optionLabel}</Badge>}
          {!yr.is_guaranteed && !yr.is_player_option && !yr.is_team_option && (
            <Badge tone="neutral" size="sm">Non-gtd</Badge>
          )}
          {yr.is_projected_cap && <Badge tone="neutral" variant="outline" size="sm">Projected cap</Badge>}
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <Badge tone={capTierBadgeTone(tier)} size="sm">{CAP_TIER_LABEL[tier]}</Badge>
          <span className="ds-tnum" style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
            {fmtM(yr.cap_hit_usd)} · {fmtPct(yr.cap_hit_pct)}
          </span>
        </div>
      </div>

      <SharedCapBar
        value={yr.cap_hit_usd}
        taxLine={yr.tax_line}
        firstApron={yr.first_apron}
        secondApron={yr.second_apron}
      />
    </div>
  );
}

// ---- Player search ------------------------------------------------
function PlayerSearch({ onPick }: { onPick: (p: PlayerSummary) => void }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<PlayerSummary[]>([]);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!query.trim()) { setResults([]); return; }
    const t = setTimeout(() => {
      searchPlayers(query, 8).then(setResults).catch(() => {});
    }, 250);
    return () => clearTimeout(t);
  }, [query]);

  return (
    <div style={{ position: 'relative' }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '8px 12px', background: 'var(--bg-panel)',
        border: '1px solid var(--border-default)', borderRadius: 'var(--radius-md)',
      }}>
        <Search size={15} color="var(--text-muted)" />
        <input
          type="text" placeholder="Search a player to simulate…" value={query}
          onChange={(e) => { setQuery(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          style={{ flex: 1, background: 'transparent', border: 'none', outline: 'none', fontFamily: 'var(--font-sans)', fontSize: 14, color: 'var(--text-primary)' }}
        />
      </div>
      {open && results.length > 0 && (
        <div style={{
          position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 100,
          background: 'var(--bg-panel)', border: '1px solid var(--border-default)',
          borderRadius: 'var(--radius-md)', boxShadow: 'var(--shadow-md)', marginTop: 4,
          overflow: 'hidden',
        }}>
          {results.map((p) => (
            <button key={p.player_id}
              onClick={() => { onPick(p); setQuery(''); setResults([]); setOpen(false); }}
              style={{
                display: 'flex', alignItems: 'center', gap: 10, width: '100%',
                padding: '10px 14px', background: 'transparent', border: 'none',
                borderBottom: '1px solid var(--border-subtle)', cursor: 'pointer', textAlign: 'left',
              }}>
              <Avatar name={p.full_name} size="sm" position={p.position} playerId={p.player_id} />
              <div>
                <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>{p.full_name}</div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                  {p.current_team?.abbreviation ?? p.latest_stats_team?.abbreviation ?? '—'} · {p.position}
                </div>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function numParam(value: string | null, fallback: number, min: number, max: number): number {
  if (value == null) return fallback;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(max, Math.max(min, parsed));
}

// ---- Main page ----------------------------------------------------
function SimulatorContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const initialPlayerId = searchParams.get('player') ? Number(searchParams.get('player')) : null;
  const initialAav = numParam(searchParams.get('aav'), 15, 1, 35);
  const initialYears = Math.round(numParam(searchParams.get('years'), 4, 1, 5));
  const initialStartSeason = searchParams.get('start') ?? '2025-26';

  const [player, setPlayer] = useState<PlayerSummary | null>(null);
  const [aav, setAav] = useState(initialAav);
  const [years, setYears] = useState(initialYears);
  const [guaranteed, setGuaranteed] = useState(Math.min(3, initialYears));
  const [playerOpts, setPlayerOpts] = useState(0);
  const [teamOpts, setTeamOpts] = useState(0);
  const [startSeason, setStartSeason] = useState(initialStartSeason);
  const [result, setResult] = useState<SimulatorResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestSeq = useRef(0);

  // Auto-load player from query param — fetch directly by ID, not from alphabetical list
  useEffect(() => {
    if (!initialPlayerId) return;
    getPlayer(initialPlayerId).then(setPlayer).catch(() => {});
  }, [initialPlayerId]);

  const totalOptions = playerOpts + teamOpts;
  const effectiveGuaranteed = Math.min(guaranteed, years - totalOptions);

  // Debounced live simulation. Keep the previous result on screen while the
  // latest request is running, and ignore stale responses from older slider ticks.
  useEffect(() => {
    if (!player) return;
    const controller = new AbortController();
    const seq = ++requestSeq.current;
    setLoading(true);
    setError(null);

    const timer = setTimeout(async () => {
      try {
        const res = await simulateContract({
          player_id: player.player_id,
          aav_pct: aav,
          years,
          guaranteed_years: effectiveGuaranteed,
          player_option_years: playerOpts,
          team_option_years: teamOpts,
          start_season: startSeason,
        }, controller.signal);
        if (seq === requestSeq.current) setResult(res);
      } catch (e: unknown) {
        if (controller.signal.aborted || seq !== requestSeq.current) return;
        setError(e instanceof Error ? e.message : 'Simulation failed.');
      } finally {
        if (seq === requestSeq.current) setLoading(false);
      }
    }, 300);

    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [player, aav, years, effectiveGuaranteed, playerOpts, teamOpts, startSeason]);

  const taxYears = result?.years.filter((y) => y.cap_hit_usd >= y.tax_line).length ?? 0;
  const apronYears = result?.years.filter((y) => y.cap_hit_usd >= y.first_apron).length ?? 0;
  const visual = teamVisual(player?.current_team?.abbreviation ?? null);

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 'var(--panel-gap)',
        '--team-primary': visual.primary,
        '--team-secondary': visual.secondary,
        '--team-wash': visual.wash,
      } as CSSProperties}
    >
      {/* Player select */}
      {!player && (
        <Surface variant="instrument" eyebrow="Select a player" icon={<SlidersHorizontal size={15} />}>
          <PlayerSearch onPick={(p) => { setPlayer(p); router.push(`/simulator?player=${p.player_id}`); }} />
        </Surface>
      )}

      {player && (
        <>
          {/* Player chip */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <Avatar name={player.full_name} size="md" position={player.position} playerId={player.player_id} />
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 16, fontWeight: 600, fontFamily: 'var(--font-display)', color: 'var(--text-primary)' }}>
                {player.full_name}
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                {player.position} · {player.current_team?.abbreviation ?? '—'} · proposed deal from {startSeason}
              </div>
            </div>
            <div style={{ flex: 1 }} />
            {result?.value_pct != null && (
              <Badge tone="confidence" variant="outline" size="sm">
                Model value {fmtPct(result.value_pct)}
              </Badge>
            )}
            {loading && result && (
              <Badge tone="neutral" variant="outline" size="sm" dot>
                Updating
              </Badge>
            )}
            <button
              onClick={() => { setPlayer(null); setResult(null); router.push('/simulator'); }}
              style={{ padding: '6px 12px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)', background: 'var(--bg-panel)', color: 'var(--text-secondary)', cursor: 'pointer', fontSize: 12 }}
            >
              Change player
            </button>
          </div>

          <div className="siq-simulator-grid">
            {/* Controls */}
            <Surface variant="instrument" teamAccent eyebrow="Contract terms" icon={<SlidersHorizontal size={15} />}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 22 }}>
                <DSSlider
                  label="AAV"
                  value={aav} onChange={setAav}
                  min={1} max={35} step={0.5}
                  format={(v) => `${v}% of cap`}
                />
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                    <span style={{ fontSize: 13, color: 'var(--text-secondary)', fontWeight: 500 }}>Start season</span>
                    <span className="ds-tnum" style={{ fontSize: 13, color: 'var(--text-primary)', fontWeight: 600 }}>
                      {startSeason}
                    </span>
                  </div>
                  <input
                    value={startSeason}
                    onChange={(e) => setStartSeason(e.target.value)}
                    maxLength={7}
                    style={{
                      width: '100%',
                      padding: '8px 10px',
                      border: '1px solid var(--border-default)',
                      borderRadius: 'var(--radius-md)',
                      background: 'var(--bg-panel)',
                      color: 'var(--text-primary)',
                      fontFamily: 'var(--font-mono)',
                      fontSize: 13,
                    }}
                  />
                </div>
                <DSSlider
                  label="Length"
                  value={years} onChange={(v) => { setYears(v); setGuaranteed(Math.min(guaranteed, v)); }}
                  min={1} max={5} step={1}
                  format={(v) => `${v} yr${v > 1 ? 's' : ''}`}
                />
                <DSSlider
                  label="Guaranteed years"
                  value={effectiveGuaranteed}
                  onChange={setGuaranteed}
                  min={0} max={Math.max(0, years - totalOptions)} step={1}
                  format={(v) => `${v} of ${years}`}
                />
                <DSSlider
                  label="Player option"
                  value={playerOpts}
                  onChange={(v) => setPlayerOpts(Math.min(v, years - teamOpts))}
                  min={0} max={Math.max(0, years - teamOpts)} step={1}
                  format={(v) => `${v} yr${v !== 1 ? 's' : ''}`}
                />
                <DSSlider
                  label="Team option"
                  value={teamOpts}
                  onChange={(v) => setTeamOpts(Math.min(v, years - playerOpts))}
                  min={0} max={Math.max(0, years - playerOpts)} step={1}
                  format={(v) => `${v} yr${v !== 1 ? 's' : ''}`}
                />
              </div>
            </Surface>

            {/* Results */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--panel-gap)' }}>
              {loading && !result && (
                <Card padded>
                  <div style={{ padding: 16, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
                  Running simulation…
                  </div>
                </Card>
              )}

              {error && (
                <div style={{ padding: '10px 14px', background: 'var(--negative-soft)', borderRadius: 'var(--radius-md)', color: 'var(--negative-text)', fontSize: 13 }}>
                  {error}
                </div>
              )}

              {result && (
                <>
                  {/* Summary card */}
                  <Surface variant="board" teamAccent eyebrow="Proposed deal" icon={<SlidersHorizontal size={15} />}>
                    <div style={{ display: 'flex', gap: 26, flexWrap: 'wrap', alignItems: 'flex-start' }}>
                      <StatTile
                        label="Contract AAV"
                        value={fmtM(result.proposed_aav_usd)}
                        unit={` · ${fmtPct(result.proposed_aav_pct)}`}
                        sub={`${years}-year deal`}
                        size="md"
                      />
                      {result.value_pct != null && (
                        <StatTile
                          label="Value gap"
                          value={result.value_gap_pct != null ? signed(result.value_gap_pct) + '%' : '—'}
                          sub={result.value_gap_pct != null
                            ? (result.value_gap_pct >= 0 ? 'Underpaid' : 'Overpaid')
                            : 'No valuation'
                          }
                          delta={undefined}
                          size="md"
                        />
                      )}
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                        <span className="ds-eyebrow">AAV vs. value</span>
                        <VerdictPill gapPct={result.value_gap_pct} size="md" />
                      </div>
                    </div>
                    {result.value_pct != null && (
                      <div style={{ marginTop: 16 }}>
                        <div className="ds-eyebrow" style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                          <span style={{ color: 'var(--confidence-text)' }}>model value {fmtPct(result.value_pct)}</span>
                          <span>proposed AAV {fmtPct(result.proposed_aav_pct)}</span>
                        </div>
                        <MiniValuePayGauge valuePct={result.value_pct} payPct={result.proposed_aav_pct} />
                      </div>
                    )}
                  </Surface>

                  {/* Year-by-year */}
                  <Surface
                    variant="board"
                    teamAccent
                    eyebrow="Year-by-year cap hits"
                    icon={<SlidersHorizontal size={15} />}
                    action={
                      <div style={{ display: 'flex', gap: 6 }}>
                        {taxYears > 0 && <Badge tone="warning" size="sm">{taxYears} yr over tax</Badge>}
                        {apronYears > 0 && <Badge tone="negative" size="sm" dot>{apronYears} yr in apron</Badge>}
                        {taxYears === 0 && <Badge tone="positive" size="sm" dot>Under tax</Badge>}
                      </div>
                    }
                  >
                    <p style={{ fontSize: 12, color: 'var(--text-muted)', margin: '0 0 10px', lineHeight: 1.5 }}>
                      Cap hit for this contract each season. Markers show tax line and apron thresholds.
                    </p>
                    <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', marginBottom: 16, fontSize: 11, color: 'var(--text-muted)' }}>
                      {[
                        { c: 'var(--grad-positive)', t: 'Under tax' },
                        { c: 'rgba(236,178,46,0.5)', t: 'Tax → apron' },
                        { c: 'rgba(244,98,31,0.6)', t: 'First apron' },
                        { c: 'rgba(238,71,71,0.6)', t: 'Second apron' },
                      ].map((z) => (
                        <span key={z.t} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                          <span style={{ width: 14, height: 8, borderRadius: 3, background: z.c }} />
                          {z.t}
                        </span>
                      ))}
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                      {result.years.map((yr) => <CapBar key={yr.season} yr={yr} />)}
                    </div>
                  </Surface>

                  <AssumptionFlag tone="warning" title="Simplified CBA model" icon={<TriangleAlert size={16} />}>
                    {result.disclaimer} Caps project at {(result.assumptions.cap_projection_rate * 100).toFixed(1)}%/yr.
                  </AssumptionFlag>
                </>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

export default function SimulatorPage() {
  return (
    <Suspense fallback={<div style={{ padding: 48, textAlign: 'center', color: 'var(--text-muted)' }}>Loading…</div>}>
      <SimulatorContent />
    </Suspense>
  );
}
