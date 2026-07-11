'use client';

import type { CSSProperties, ReactNode } from 'react';
import { useEffect, useMemo, useRef, useState, Suspense } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { Search, SlidersHorizontal, TriangleAlert, Scale, BarChart3, ArrowRight, ArrowUpRight } from 'lucide-react';
import {
  searchPlayers, getPlayer, simulateContract, getPlayerWatchlist,
  PlayerSummary, PlayerCardResponse, SimulatorResponse, ContractYearResponse,
} from '@/lib/api';
import { Panel } from '@/components/ui/Panel';
import { Badge } from '@/components/ui/Badge';
import { Button, ButtonLink } from '@/components/ui/Button';
import { StatTile } from '@/components/ui/StatTile';
import { VerdictPill } from '@/components/ui/VerdictPill';
import { AssumptionFlag } from '@/components/ui/AssumptionFlag';
import { Avatar } from '@/components/ui/Avatar';
import { MiniValuePayGauge } from '@/components/players/MiniValuePayGauge';
import { fmtM, fmtPct, gapLabel, gapTone, signed } from '@/lib/utils';
import { teamVisual } from '@/lib/teamVisuals';

// ---- Slider -------------------------------------------------------
function DSSlider({
  label, value, onChange, min, max, step, format, verdict = false,
}: {
  label: string; value: number; onChange: (v: number) => void;
  min: number; max: number; step: number; format: (v: number) => string;
  /** The control that decides the verdict: its thumb halo speaks --sim-verdict. */
  verdict?: boolean;
}) {
  // Defend against an out-of-range value (e.g. the available range shrank): the
  // thumb, the fill, and the readout must always agree.
  const clamped = Math.max(min, Math.min(max, value));
  const disabled = max <= min;
  const pct = max === min ? 0 : ((clamped - min) / (max - min)) * 100;

  // Whole-step controls with few stops get detent dots — countable instrument
  // stops under the track. Positions are corrected for thumb radius (9px) so
  // each dot sits exactly under the thumb center at that stop.
  const detents = !disabled && step >= 1 && (max - min) / step <= 8
    ? Array.from({ length: Math.round((max - min) / step) + 1 }, (_, idx) => min + idx * step)
    : null;

  return (
    <div className="siq-control-slab" style={{ opacity: disabled ? 0.6 : 1 }}>
      <div className="siq-sim-control-label-row">
        <span className="siq-sim-control-label">{label}</span>
        <span className="ds-tnum siq-sim-control-value">
          {format(clamped)}
        </span>
      </div>
      <input
        className={verdict ? 'siq-slider siq-slider--verdict' : 'siq-slider'}
        type="range" min={min} max={max} step={step} value={clamped}
        aria-label={label}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
        style={{
          '--siq-slider-pct': `${Math.min(100, Math.max(0, pct))}%`,
          cursor: disabled ? 'not-allowed' : 'pointer',
        } as CSSProperties}
      />
      {detents && (
        <div className="siq-slider-detents" aria-hidden="true">
          {detents.map((d) => {
            const frac = (d - min) / (max - min);
            return (
              <span
                key={d}
                className={
                  'siq-slider-detent' +
                  (d <= clamped ? ' siq-slider-detent--passed' : '') +
                  (d === clamped ? ' siq-slider-detent--at' : '')
                }
                style={{ left: `calc(${frac * 100}% + ${9 - frac * 18}px)` }}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}

// ---- Max-salary tiers — the thresholds that actually bind one contract -----
// A single player's cap hit never approaches the *team* tax/apron lines, so
// reading it against them is meaningless (always "under tax"). What binds an
// individual is the max-salary scale: 25% of the cap (≤6 yrs service), 30%
// (7–9 yrs), 35% (10+ yrs). We grade the deal's cap share against those.
function maxTierInfo(pct: number): { label: string; tone: 'positive' | 'warning' | 'negative'; fill: string } {
  if (pct >= 35) return { label: 'Supermax tier',  tone: 'negative', fill: 'var(--grad-negative)' };
  if (pct >= 30) return { label: '30% max tier',   tone: 'warning',  fill: 'linear-gradient(90deg, var(--amber-500), var(--orange-500))' };
  if (pct >= 25) return { label: '25% max tier',   tone: 'warning',  fill: 'linear-gradient(90deg, var(--amber-500), var(--amber-600))' };
  return { label: 'Below max', tone: 'positive', fill: 'linear-gradient(90deg, var(--teal-500), var(--green-500))' };
}

const SHARE_SCALE_MAX = 38; // % of cap the share bar spans
const MAX_TIERS = [25, 30, 35];

// The deal's cap share read against the individual max-salary tiers.
function CapShareBar({ sharePct }: { sharePct: number }) {
  const place = (v: number) => Math.min(100, Math.max(0, (v / SHARE_SCALE_MAX) * 100));
  const fillW = place(sharePct);
  const info = maxTierInfo(sharePct);
  return (
    <div className="siq-sim-share">
      <div className="siq-sim-share__rail">
        <div className="siq-sim-share__track">
          <div className="siq-sim-share__fill" style={{ width: `${fillW}%`, background: info.fill }} />
        </div>
        {MAX_TIERS.map((t) => (
          <span key={t} className="siq-sim-share__tier" style={{ left: `${place(t)}%` }} aria-hidden="true" />
        ))}
        <span className="siq-sim-share__dot" style={{ left: `${fillW}%`, background: info.fill }} aria-hidden="true" />
      </div>
      <div className="siq-sim-share__ticks" aria-hidden="true">
        {MAX_TIERS.map((t) => (
          <span key={t} className="siq-sim-share__tick" style={{ left: `${place(t)}%` }}>{t}%</span>
        ))}
      </div>
    </div>
  );
}

// ---- One contract year in the structure ledger --------------------
function YearRow({ yr }: { yr: ContractYearResponse }) {
  const optionLabel = yr.is_player_option ? 'Player opt.' : yr.is_team_option ? 'Team opt.' : null;
  const nonGtd = !yr.is_guaranteed && !yr.is_player_option && !yr.is_team_option;
  return (
    <div className="siq-sim-year-row">
      <span className="ds-tnum siq-sim-year-row__season">{yr.season}</span>
      <span className="siq-sim-year-row__flags">
        {optionLabel && <Badge tone="warning" size="sm">{optionLabel}</Badge>}
        {nonGtd && <Badge tone="neutral" size="sm">Non-gtd</Badge>}
        {yr.is_projected_cap && <Badge tone="neutral" variant="outline" size="sm">Projected cap</Badge>}
      </span>
      <span className="ds-tnum siq-sim-year-row__usd">{fmtM(yr.cap_hit_usd)}</span>
      <span className="ds-tnum siq-sim-year-row__pct">{fmtPct(yr.cap_hit_pct)}</span>
    </div>
  );
}

// ---- Player search ------------------------------------------------
function PlayerSearch({ onPick }: { onPick: (p: PlayerSummary) => void }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<PlayerSummary[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const trimmed = query.trim();
    if (!trimmed) {
      setResults([]);
      setLoading(false);
      setError(null);
      return;
    }
    const controller = new AbortController();
    const t = setTimeout(() => {
      setLoading(true);
      setError(null);
      searchPlayers(trimmed, 8, controller.signal)
        .then(setResults)
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

  const showMenu = open && query.trim().length > 0 && (loading || error || results.length > 0);

  return (
    <div className="siq-sim-search">
      <div className="siq-row siq-sim-search-field">
        <Search size={15} color="var(--text-muted)" />
        <input
          type="text" placeholder="Search a player to simulate…" value={query}
          aria-label="Search players to simulate"
          onChange={(e) => { setQuery(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          className="siq-sim-search-input"
        />
      </div>
      {showMenu && (
        <div className="siq-sim-search-menu">
          {loading ? (
            <div className="ds-note ds-note--13 siq-sim-search-status">Searching…</div>
          ) : error ? (
            <div className="ds-note ds-note--13 siq-sim-search-status siq-sim-search-status--error">
              {error}
            </div>
          ) : results.length === 0 ? (
            <div className="ds-note ds-note--13 siq-sim-search-status">No players found.</div>
          ) : (
            results.map((p) => (
              <button key={p.player_id}
                className="siq-row siq-row--10 siq-sim-search-result"
                onClick={() => { onPick(p); setQuery(''); setResults([]); setOpen(false); }}
              >
                <Avatar name={p.full_name} size="sm" position={p.position} playerId={p.player_id} />
                <div>
                  <div className="siq-sim-search-result-name">{p.full_name}</div>
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

// ---- Empty-state building blocks ----------------------------------
const VERDICT_COLOR: Record<string, string> = {
  positive: 'var(--positive-text)',
  negative: 'var(--negative-text)',
  neutral: 'var(--text-secondary)',
  warning: 'var(--warning-text)',
};

// One-click starter pulled from the live mismatch board — the players most
// worth re-pricing, so the user can launch a scenario without typing cold.
function QuickPick({ p, onPick }: { p: PlayerCardResponse; onPick: (p: PlayerSummary) => void }) {
  const v = p.valuation_status === 'ready' ? p.valuation : null;
  const gap = v?.gap_pct ?? null;
  const tone = v?.verdict_tone ?? 'neutral';
  const team = p.current_team ?? p.latest_stats_team;
  return (
    <button type="button" className="siq-sim-quick" onClick={() => onPick(p)}>
      <Avatar name={p.full_name} size="sm" position={p.position} playerId={p.player_id} />
      <span className="siq-sim-quick__id">
        <span className="siq-sim-quick__name">{p.full_name}</span>
        <span className="siq-sim-quick__meta">{team?.abbreviation ?? '—'} · {p.position ?? '—'}</span>
      </span>
      {gap != null && (
        <span className="ds-tnum siq-sim-quick__gap" style={{ color: VERDICT_COLOR[tone] }}>
          {signed(gap)}%
        </span>
      )}
    </button>
  );
}

// "What you'll get" — previews the three payoffs the simulator produces so the
// empty page sells the feature instead of just demanding a search.
function FeatureCard({ icon, accent, title, body }: { icon: ReactNode; accent: string; title: string; body: string }) {
  return (
    <div className="siq-panel siq-sim-feature">
      <span
        className="siq-sim-feature__icon"
        style={{ color: accent, background: `color-mix(in srgb, ${accent} 12%, transparent)` }}
      >
        {icon}
      </span>
      <span className="siq-sim-feature__title">{title}</span>
      <span className="siq-sim-feature__body">{body}</span>
    </div>
  );
}

const clampInt = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, Math.round(v)));

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
  const [quickPicks, setQuickPicks] = useState<PlayerCardResponse[]>([]);
  const requestSeq = useRef(0);

  const pick = (p: PlayerSummary) => {
    setPlayer(p);
    router.push(`/simulator?player=${p.player_id}`);
  };

  // Auto-load player from query param — fetch directly by ID, not from alphabetical list
  useEffect(() => {
    if (!initialPlayerId) return;
    getPlayer(initialPlayerId).then(setPlayer).catch(() => {});
  }, [initialPlayerId]);

  // Starter suggestions for the empty state: the biggest live value/pay
  // mismatches — the players most worth running a what-if extension on.
  useEffect(() => {
    if (player) return;
    const controller = new AbortController();
    getPlayerWatchlist({ bucket: 'all', sort: 'mismatch', qualifiedOnly: true, limit: 6 }, controller.signal)
      .then((r) => setQuickPicks(r.items))
      .catch(() => {});
    return () => controller.abort();
  }, [player]);

  const totalOptions = playerOpts + teamOpts;
  const effectiveGuaranteed = clampInt(guaranteed, 0, Math.max(0, years - totalOptions));

  // Contract invariant: guaranteed + player options + team options ≤ years, all
  // ≥ 0. Every control re-derives the others so the deal can never go incoherent
  // (the old handlers let options outlive a shortened deal → negative guaranteed
  // and out-of-range sliders).
  const setLength = (v: number) => {
    const y = clampInt(v, 1, 5);
    const po = Math.min(playerOpts, y);
    const to = Math.min(teamOpts, y - po);
    setYears(y);
    setPlayerOpts(po);
    setTeamOpts(to);
    setGuaranteed(clampInt(guaranteed, 0, y - po - to));
  };

  const setPlayerOption = (v: number) => {
    const po = clampInt(v, 0, years - teamOpts);
    setPlayerOpts(po);
    setGuaranteed(clampInt(guaranteed, 0, years - po - teamOpts));
  };

  const setTeamOption = (v: number) => {
    const to = clampInt(v, 0, years - playerOpts);
    setTeamOpts(to);
    setGuaranteed(clampInt(guaranteed, 0, years - playerOpts - to));
  };

  const setGuaranteedYears = (v: number) => {
    setGuaranteed(clampInt(v, 0, years - totalOptions));
  };

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
    }, 140);

    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [player, aav, years, effectiveGuaranteed, playerOpts, teamOpts, startSeason]);

  // Optimistic display: the AAV slider is the most-dragged control, but the
  // network round-trip makes the readouts feel laggy. The model value is
  // independent of the proposed AAV, and every cap hit scales linearly with it,
  // so we can re-price the last server result against the live AAV instantly and
  // let the debounced response reconcile (it matches, so there's no visible snap).
  const displayResult = useMemo(() => {
    if (!result) return null;
    const base = result.proposed_aav_pct;
    if (!base || Math.abs(base - aav) < 1e-6) return result;
    const scale = aav / base;
    return {
      ...result,
      proposed_aav_pct: aav,
      proposed_aav_usd: result.proposed_aav_usd * scale,
      value_gap_pct: result.value_pct != null ? result.value_pct - aav : result.value_gap_pct,
      years: result.years.map((y) => ({
        ...y,
        cap_hit_usd: y.cap_hit_usd * scale,
        cap_hit_pct: y.cap_hit_pct * scale,
      })),
    };
  }, [result, aav]);

  const totalValue = displayResult?.years.reduce((sum, y) => sum + (y.cap_hit_usd ?? 0), 0) ?? 0;
  const tierInfo = maxTierInfo(displayResult?.proposed_aav_pct ?? 0);
  const visual = teamVisual(player?.current_team?.abbreviation ?? null);

  // The live verdict, made felt: the AAV thumb halo, the verdict pill, and the
  // value-gap readout all ride this one hue. Green = bargain, red = overpay,
  // teal = priced at model value (calibration, not a verdict), brand orange
  // while there's no reading yet.
  const simGap = displayResult?.value_gap_pct ?? null;
  const simTone = gapTone(simGap);
  const simVerdictColor =
    simGap == null ? 'var(--accent)'
    : simTone === 'positive' ? 'var(--positive)'
    : simTone === 'negative' ? 'var(--negative)'
    : 'var(--confidence)';

  return (
    <div
      className="siq-stack"
      style={{
        '--team-primary': visual.primary,
        '--team-secondary': visual.secondary,
        '--team-wash': visual.wash,
        '--sim-verdict': simVerdictColor,
      } as CSSProperties}
    >
      <h1 className="siq-sr-only">Cap simulator</h1>
      {/* First-run cockpit: explain the signature feature, give a prominent
          picker, and offer one-click starters so the page is never a dead end. */}
      {!player && (
        <div className="siq-sim-intro">
          <Panel
            variant="instrument"
            eyebrow="What-if contract & cap simulator"
            icon={<SlidersHorizontal size={15} />}
            className="siq-sim-intro-panel"
          >
            <div className="siq-sim-intro__hero">
              <h2 className="siq-sim-intro__title">Model a contract before you offer it.</h2>
              <p className="siq-sim-intro__lede">
                Set the terms — AAV, length, guarantees, and options — and ScoutIQ projects the cap hit,
                luxury tax, and apron exposure for every season, then grades the deal against the player&apos;s
                model value.
              </p>

              <div className="siq-sim-intro__search">
                <PlayerSearch onPick={pick} />
              </div>

              {quickPicks.length > 0 && (
                <div className="siq-sim-intro__quick">
                  <span className="ds-eyebrow">Jump in with a live mismatch</span>
                  <div className="siq-sim-quick-row">
                    {quickPicks.map((p) => <QuickPick key={p.player_id} p={p} onPick={pick} />)}
                  </div>
                </div>
              )}
            </div>
          </Panel>

          <div className="siq-sim-intro__features">
            <FeatureCard
              icon={<Scale size={17} />}
              accent="var(--confidence)"
              title="Value gap"
              body="See instantly whether the deal is a bargain or an overpay versus the player's model value."
            />
            <FeatureCard
              icon={<BarChart3 size={17} />}
              accent="var(--accent)"
              title="Year-by-year cap"
              body="Every season's cap hit laid out as a ladder you can read at a glance."
            />
            <FeatureCard
              icon={<TriangleAlert size={17} />}
              accent="var(--warning)"
              title="Tax & apron exposure"
              body="Flags the seasons a deal crosses the luxury tax line and both aprons."
            />
          </div>

          <p className="siq-sim-intro__hint">
            <ArrowRight size={13} /> Start from a player&apos;s contract page to auto-fill a realistic extension.
          </p>
        </div>
      )}

      {player && (
        <>
          {/* Player chip — the identity links through to the full profile, with
              an explicit "View profile" action so the simulator isn't a dead end. */}
          <div className="siq-row siq-row--12 siq-sim-player-bar">
            <Link
              href={`/players/${player.player_id}`}
              className="siq-sim-player-link siq-row siq-row--12 siq-min0 siq-plain-link siq-sim-player-link--layout"
            >
              <Avatar name={player.full_name} size="md" position={player.position} playerId={player.player_id} />
              <div className="siq-min0">
                <div className="siq-sim-player-name siq-sim-player-name--selected">
                  {player.full_name}
                </div>
                <div className="ds-note">
                  {player.position} · {player.current_team?.abbreviation ?? '—'} · proposed deal from {startSeason}
                </div>
              </div>
            </Link>
            <div className="siq-sim-player-spacer" />
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
            <ButtonLink href={`/players/${player.player_id}`} icon={<ArrowUpRight size={15} />}>
              View profile
            </ButtonLink>
            <Button onClick={() => { setPlayer(null); setResult(null); router.push('/simulator'); }}>
              Change player
            </Button>
          </div>

          <div className="siq-simulator-grid">
            {/* Controls */}
            <Panel variant="instrument" teamAccent eyebrow="Contract terms" icon={<SlidersHorizontal size={15} />}>
              <div className="siq-simulator-controls">
                <DSSlider
                  label="AAV"
                  value={aav} onChange={setAav}
                  min={1} max={35} step={0.5}
                  format={(v) => `${v}% of cap`}
                  verdict
                />
                <div className="siq-control-slab">
                  <div className="siq-sim-control-label-row">
                    <span className="siq-sim-control-label">Start season</span>
                    <span className="ds-tnum siq-sim-control-value">
                      {startSeason}
                    </span>
                  </div>
                  <input
                    value={startSeason}
                    onChange={(e) => setStartSeason(e.target.value)}
                    maxLength={7}
                    aria-label="Start season"
                    className="siq-sim-start-season-input"
                  />
                </div>
                <DSSlider
                  label="Length"
                  value={years} onChange={setLength}
                  min={1} max={5} step={1}
                  format={(v) => `${v} yr${v > 1 ? 's' : ''}`}
                />
                <DSSlider
                  label="Guaranteed years"
                  value={effectiveGuaranteed}
                  onChange={setGuaranteedYears}
                  min={0} max={Math.max(0, years - totalOptions)} step={1}
                  format={(v) => `${v} of ${years}`}
                />
                <DSSlider
                  label="Player option"
                  value={playerOpts}
                  onChange={setPlayerOption}
                  min={0} max={Math.max(0, years - teamOpts)} step={1}
                  format={(v) => `${v} yr${v !== 1 ? 's' : ''}`}
                />
                <DSSlider
                  label="Team option"
                  value={teamOpts}
                  onChange={setTeamOption}
                  min={0} max={Math.max(0, years - playerOpts)} step={1}
                  format={(v) => `${v} yr${v !== 1 ? 's' : ''}`}
                />
              </div>
            </Panel>

            {/* Results */}
            <div className="siq-stack">
              {loading && !result && (
                <Panel variant="card" padded className="siq-sim-loading-card">
                  <div className="siq-sim-loading-head">
                    <span className="ds-eyebrow">Running simulation</span>
                    <span className="siq-loading-dot" />
                  </div>
                  <div className="siq-sim-loading-grid" aria-hidden="true">
                    <span />
                    <span />
                    <span />
                  </div>
                  <div className="siq-sim-loading-bars" aria-hidden="true">
                    <span />
                    <span />
                    <span />
                  </div>
                </Panel>
              )}

              {error && (
                <div className="ds-note ds-note--13 siq-sim-error">
                  {error}
                </div>
              )}

              {displayResult && (
                <>
                  {/* Summary card */}
                  <Panel variant="board" teamAccent eyebrow="Proposed deal" icon={<SlidersHorizontal size={15} />}>
                    <div className="siq-sim-summary-grid">
                      <StatTile
                        label="Contract AAV"
                        value={fmtM(displayResult.proposed_aav_usd)}
                        unit={` · ${fmtPct(displayResult.proposed_aav_pct)}`}
                        sub={`${displayResult.years.length}-yr · ${fmtM(totalValue)} total`}
                        size="md"
                        live
                      />
                      {displayResult.value_pct != null && (
                        <StatTile
                          label="Value gap"
                          value={displayResult.value_gap_pct != null ? signed(displayResult.value_gap_pct) + '%' : '—'}
                          sub={displayResult.value_gap_pct != null ? gapLabel(displayResult.value_gap_pct) : 'No valuation'}
                          valueTone={simTone}
                          delta={undefined}
                          size="md"
                          live
                        />
                      )}
                      <div className="siq-sim-verdict-column">
                        <span className="ds-eyebrow">AAV vs. value</span>
                        {/* Keyed by tone: crossing a verdict threshold remounts
                            the wrapper, replaying the one-shot pulse. */}
                        <span key={simTone} className="siq-verdict-flip">
                          <VerdictPill gapPct={displayResult.value_gap_pct} size="md" />
                        </span>
                      </div>
                    </div>
                    {displayResult.value_pct != null && (
                      <div className="siq-sim-gauge">
                        <div className="ds-eyebrow siq-sim-gauge-header">
                          <span className="siq-sim-gauge-value">model value {fmtPct(displayResult.value_pct)}</span>
                          <span>proposed AAV {fmtPct(displayResult.proposed_aav_pct)}</span>
                        </div>
                        <MiniValuePayGauge valuePct={displayResult.value_pct} payPct={displayResult.proposed_aav_pct} />
                      </div>
                    )}
                  </Panel>

                  {/* Cap share & structure — read against the individual
                      max-salary tiers (a single deal never nears the team tax line),
                      plus the year-by-year dollar escalation and guarantee structure. */}
                  <Panel
                    variant="board"
                    teamAccent
                    eyebrow="Cap share & structure"
                    icon={<SlidersHorizontal size={15} />}
                    action={<Badge tone={tierInfo.tone} size="sm">{tierInfo.label}</Badge>}
                  >
                    <p className="ds-note siq-sim-share-copy">
                      This deal commits {fmtPct(displayResult.proposed_aav_pct)} of the cap. A single contract never
                      nears the team tax line, so it&apos;s read against the max-salary tiers that actually bind one player.
                    </p>

                    <CapShareBar sharePct={displayResult.proposed_aav_pct} />
                    <p className="siq-sim-tier-copy">
                      Max-salary tiers — 25% (≤6 yrs service) · 30% (7–9 yrs) · 35% (10+ yrs)
                    </p>

                    <div className="siq-sim-year-stack">
                      <div className="siq-sim-year-row siq-sim-year-row--head">
                        <span className="siq-sim-year-row__season">Season</span>
                        <span className="siq-sim-year-row__flags" />
                        <span className="siq-sim-year-row__usd">Cap hit</span>
                        <span className="siq-sim-year-row__pct">Share</span>
                      </div>
                      {displayResult.years.map((yr) => <YearRow key={yr.season} yr={yr} />)}
                    </div>
                  </Panel>

                  <AssumptionFlag tone="warning" title="Simplified CBA model" icon={<TriangleAlert size={16} />}>
                    {displayResult.disclaimer} Caps project at {(displayResult.assumptions.cap_projection_rate * 100).toFixed(1)}%/yr.
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
    <Suspense fallback={<div className="siq-sim-suspense-fallback">Loading…</div>}>
      <SimulatorContent />
    </Suspense>
  );
}
