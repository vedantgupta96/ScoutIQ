'use client';

import { useEffect, useMemo, useState, type CSSProperties } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { FlaskConical, Play, TrendingUp, TriangleAlert, LoaderCircle } from 'lucide-react';
import {
  getStrategyPresets,
  runBacktest,
  type StrategyPreset,
  type StrategyRequest,
  type StrategySignal,
  type BacktestResult,
  type BacktestPick,
  type CurrentTarget,
} from '@/lib/api';
import { Panel } from '@/components/ui/Panel';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Select } from '@/components/ui/Select';
import { Avatar } from '@/components/ui/Avatar';
import { DecisionStrip } from '@/components/ui/DecisionStrip';
import { AssumptionFlag } from '@/components/ui/AssumptionFlag';
import { fmtM } from '@/lib/utils';

// Rank options — basketball-native names, not model jargon.
const SIGNAL_LABEL: Record<StrategySignal, string> = {
  gap: 'Best bargains (value vs pay)',
  value: 'Highest model value',
  ws: 'Most production (Win Shares)',
  bpm: 'Box Plus/Minus',
  vorp: 'VORP',
};

// Benchmarks framed as rival GM approaches.
const BENCH_LABEL: Record<string, string> = {
  random: 'Signing at random',
  chase_production: 'Signing the biggest names',
  chase_salary: 'Paying the most',
};

const DEFAULT: StrategyRequest = {
  signal: 'gap', require_undervalued: true, portfolio_size: 10, horizon: 3,
  min_mpg: 20, min_gp: 40,
};

// Cap-% → today's dollars, the unit a GM actually thinks in.
function usd(pct: number, cap: number | null): number | null {
  return cap == null ? null : (pct / 100) * cap;
}
function signedM(dollars: number): string {
  return `${dollars >= 0 ? '+' : '−'}${fmtM(Math.abs(dollars))}`;
}
function money(pct: number, cap: number | null): string {
  const d = usd(pct, cap);
  return d == null ? `${pct > 0 ? '+' : ''}${pct.toFixed(1)}%` : signedM(d);
}
// Unsigned magnitude, for "beat by X" phrasing.
function absMoney(pct: number, cap: number | null): string {
  const d = usd(Math.abs(pct), cap);
  return d == null ? `${Math.abs(pct).toFixed(1)}%` : fmtM(d);
}

// One plain-English line that reconciles "beat random" (relative) with the absolute
// value per signing — the two numbers that look contradictory on their own.
function verdictLine(result: BacktestResult, cap: number | null): { text: string; tone: 'confidence' | 'neutral' | 'negative' } {
  const a = result.alpha_per_slot_pct;   // vs random, % of cap per signing
  const s = result.surplus_per_slot_pct; // absolute value per signing
  const beat = a > 0.3, lost = a < -0.3, positive = s >= 0;
  // With only ~13 offseasons the edge can be noise — say so.
  const sure = result.edge_conclusive
    ? ' The edge holds up statistically.'
    : ' But with only 13 offseasons the edge isn’t statistically clear — treat it as suggestive, not proven.';
  if (beat && positive)
    return { tone: 'confidence', text: `Strong rule: it beat signing at random by ${absMoney(a, cap)} per signing and returned positive value overall (${money(s, cap)} per signing).${sure}` };
  if (beat && !positive)
    return { tone: 'neutral', text: `It beat signing at random by ${absMoney(a, cap)} per signing — but even this rule lost value overall (${money(s, cap)} per signing). A few gems don't offset the many players whose pay outgrows their production over the years you hold them.${sure}` };
  if (lost)
    return { tone: 'negative', text: `It lost to signing at random by ${absMoney(a, cap)} per signing — this rule did worse than picking names at random.` };
  return { tone: 'neutral', text: `Roughly a coin-flip vs signing at random (${money(a, cap)} per signing). No real edge either way.` };
}

function Slider({ label, value, onChange, min, max, step = 1, suffix = '' }: {
  label: string; value: number; onChange: (v: number) => void; min: number; max: number; step?: number; suffix?: string;
}) {
  const p = max === min ? 0 : ((value - min) / (max - min)) * 100;
  return (
    <label className="siq-strat-field">
      <span className="ds-eyebrow">{label}</span>
      <span className="siq-strat-slider-row">
        <input
          className="siq-slider" type="range" min={min} max={max} step={step} value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          style={{ '--siq-slider-pct': `${Math.min(100, Math.max(0, p))}%` } as CSSProperties}
        />
        <strong className="ds-tnum siq-strat-slider-val">{value}{suffix}</strong>
      </span>
    </label>
  );
}

// How each offseason's signing class panned out 3 seasons later (per class, not cumulative).
function ClassChart({ result }: { result: BacktestResult }) {
  const cap = result.reference_cap_usd;
  const pts = result.equity_curve.map((p) => ({ season: p.season, value: usd(p.cohort_surplus_pct, cap) ?? p.cohort_surplus_pct }));
  const W = 640, H = 220, padL = 52, padR = 12, padT = 14, padB = 26;
  const values = pts.map((p) => p.value);
  const min = Math.min(0, ...values), max = Math.max(0, ...values);
  const span = max - min || 1;
  const x = (i: number) => padL + (pts.length <= 1 ? 0 : (i / (pts.length - 1)) * (W - padL - padR));
  const y = (v: number) => padT + (1 - (v - min) / span) * (H - padT - padB);
  const zeroY = y(0);
  const axis = (v: number) => (cap == null ? `${v.toFixed(0)}%` : fmtM(v));

  return (
    <svg className="siq-strat-equity-svg" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label="Value produced by each offseason signing class">
      <line x1={padL} y1={zeroY} x2={W - padR} y2={zeroY} stroke="var(--border-strong)" strokeDasharray="3 3" />
      <text x={padL - 6} y={y(max) + 3} textAnchor="end" fontSize="9" fill="var(--text-muted)" fontFamily="var(--font-mono)">{axis(max)}</text>
      <text x={padL - 6} y={zeroY + 3} textAnchor="end" fontSize="9" fill="var(--text-muted)" fontFamily="var(--font-mono)">0</text>
      <text x={padL - 6} y={y(min) + 3} textAnchor="end" fontSize="9" fill="var(--text-muted)" fontFamily="var(--font-mono)">{axis(min)}</text>
      {pts.map((p, i) => {
        const pos = p.value >= 0;
        const bw = Math.max(6, (W - padL - padR) / pts.length - 8);
        const top = pos ? y(p.value) : zeroY;
        const h = Math.abs(y(p.value) - zeroY);
        return (
          <g key={p.season}>
            <rect x={x(i) - bw / 2} y={top} width={bw} height={Math.max(1, h)} rx="2"
              fill={pos ? 'var(--positive)' : 'var(--negative)'} opacity="0.85" />
            {i % 2 === 0 && <text x={x(i)} y={H - 8} textAnchor="middle" fontSize="8" fill="var(--text-muted)" fontFamily="var(--font-mono)">{p.season.slice(2)}</text>}
          </g>
        );
      })}
    </svg>
  );
}

function BenchmarkBars({ result }: { result: BacktestResult }) {
  const cap = result.reference_cap_usd;
  const rows = [
    { key: 'strategy', label: 'Your rule', value: result.surplus_per_slot_pct, accent: true },
    ...Object.entries(result.benchmarks).map(([k, b]) => ({ key: k, label: BENCH_LABEL[k] ?? k, value: b.surplus_per_slot_pct, accent: false })),
  ];
  const maxAbs = Math.max(1, ...rows.map((r) => Math.abs(r.value)));
  return (
    <div className="siq-strat-bars">
      {rows.map((r) => {
        const w = (Math.abs(r.value) / maxAbs) * 50;
        const pos = r.value >= 0;
        return (
          <div className="siq-strat-bar-row" key={r.key}>
            <span className="siq-strat-bar-label">{r.label}</span>
            <span className="siq-strat-bar-track">
              <span
                className={`siq-strat-bar-fill${r.accent ? ' is-accent' : ''}${pos ? ' is-pos' : ' is-neg'}`}
                style={{ width: `${w}%`, [pos ? 'left' : 'right']: '50%' } as CSSProperties}
              />
              <span className="siq-strat-bar-mid" />
            </span>
            <strong className={`ds-tnum siq-strat-bar-val ${pos ? 'is-positive' : 'is-negative'}`}>{money(r.value, cap)}</strong>
          </div>
        );
      })}
    </div>
  );
}

function PickRow({ pick, cap, onPick }: { pick: BacktestPick; cap: number | null; onPick: () => void }) {
  return (
    <button className="siq-row siq-row--12 siq-strat-pick-row" onClick={onPick}>
      <Avatar name={pick.full_name} playerId={pick.player_id} size="sm" />
      <span className="siq-min0 siq-strat-pick-id">
        <strong>{pick.full_name}</strong>
        <small className="ds-note">{pick.decision_season} · bargain {pick.signal_value >= 0 ? '+' : ''}{pick.signal_value.toFixed(1)} · kept {pick.seasons_realized}y</small>
      </span>
      <Badge tone={pick.hit ? 'positive' : 'negative'} size="sm">{pick.hit ? 'win' : 'bust'}</Badge>
      <strong className={`ds-tnum ds-right siq-strat-pick-surplus ${pick.realized_surplus_pct >= 0 ? 'is-positive' : 'is-negative'}`}>
        {money(pick.realized_surplus_pct, cap)}
      </strong>
    </button>
  );
}

// Forward-looking: a player this rule would sign in the current offseason (no grade yet).
function TargetRow({ target, cap, onPick }: { target: CurrentTarget; cap: number | null; onPick: () => void }) {
  const gap = target.gap_pct;
  return (
    <button className="siq-row siq-row--12 siq-strat-pick-row" onClick={onPick}>
      <Avatar name={target.full_name} playerId={target.player_id} size="sm" />
      <span className="siq-min0 siq-strat-pick-id">
        <strong>{target.full_name}</strong>
        <small className="ds-note">
          {target.age != null ? `age ${target.age}` : '—'}{target.position ? ` · ${target.position}` : ''}
          {gap != null ? ` · bargain ${gap >= 0 ? '+' : ''}${gap.toFixed(1)}` : ''}
        </small>
      </span>
      <span className="ds-tnum ds-right siq-strat-target-vals">
        <strong>{target.value_pct != null ? money(target.value_pct, cap).replace('+', '') : '—'}</strong>
        <small className="ds-note">value vs {target.actual_pct != null ? money(target.actual_pct, cap).replace('+', '') : '—'} pay</small>
      </span>
    </button>
  );
}

export default function StrategyPage() {
  const router = useRouter();
  const [presets, setPresets] = useState<StrategyPreset[]>([]);
  const [req, setReq] = useState<StrategyRequest>(DEFAULT);
  const [activePreset, setActivePreset] = useState<string | null>('value');
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const c = new AbortController();
    getStrategyPresets(c.signal).then((r) => setPresets(r.presets)).catch(() => {});
    return () => c.abort();
  }, []);

  const set = <K extends keyof StrategyRequest>(k: K, v: StrategyRequest[K]) => {
    setReq((cur) => ({ ...cur, [k]: v }));
    setActivePreset(null);
  };

  const applyPreset = (p: StrategyPreset) => {
    setReq({ ...DEFAULT, ...p.spec });
    setActivePreset(p.id);
  };

  const run = async () => {
    setRunning(true);
    setError(null);
    try {
      setResult(await runBacktest(req));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The test could not run.');
    } finally {
      setRunning(false);
    }
  };

  const topPicks = useMemo(
    () => (result ? [...result.picks].sort((a, b) => b.realized_surplus_pct - a.realized_surplus_pct) : []),
    [result],
  );

  const cap = result?.reference_cap_usd ?? null;
  const alpha = result?.alpha_per_slot_pct ?? 0;
  const best = topPicks[0];
  const wins = result ? result.picks.filter((p) => p.hit).length : 0;
  const busts = result ? result.n_picks - wins : 0;
  const winners = topPicks.filter((p) => p.realized_surplus_pct > 0).slice(0, 10);
  const bustList = topPicks.filter((p) => p.realized_surplus_pct <= 0).slice(-10).reverse();
  const verdict = result ? verdictLine(result, cap) : null;

  return (
    <div className="siq-stack">
      <header className="siq-strat-heading">
        <span className="ds-eyebrow">Test a signing philosophy across 13 NBA offseasons</span>
        <h1>Backtesting</h1>
        <p>Pick a rule for which players to sign, replay it across every offseason since 2012-13, and see whether it built more value than a GM signing at random. The model picks the players; real on-court production (Win Shares) grades them — so the model never grades its own picks.</p>
        <Link href="/data" className="siq-provenance-link">Data provenance →</Link>
      </header>

      <Panel variant="card" padded eyebrow="Signing rule" icon={<FlaskConical size={15} />}>
        <div className="siq-strat-presets">
          {presets.map((p) => (
            <button
              key={p.id}
              className={`siq-strat-preset${activePreset === p.id ? ' is-active' : ''}`}
              onClick={() => applyPreset(p)}
              title={p.description}
            >
              {p.name}
            </button>
          ))}
        </div>

        <div className="siq-strat-builder">
          <label className="siq-strat-field">
            <span className="ds-eyebrow">Target players by</span>
            <Select value={req.signal} onChange={(e) => set('signal', e.target.value as StrategySignal)}>
              {(Object.keys(SIGNAL_LABEL) as StrategySignal[]).map((s) => (
                <option key={s} value={s}>{SIGNAL_LABEL[s]}</option>
              ))}
            </Select>
          </label>
          <Slider label="Signings per offseason" value={req.portfolio_size ?? 10} onChange={(v) => set('portfolio_size', v)} min={1} max={30} />
          <Slider label="Seasons you keep them" value={req.horizon ?? 3} onChange={(v) => set('horizon', v)} min={1} max={5} />
          <Slider label="Min minutes/game" value={req.min_mpg ?? 20} onChange={(v) => set('min_mpg', v)} min={0} max={40} />
          <Slider label="Min games played" value={req.min_gp ?? 40} onChange={(v) => set('min_gp', v)} min={0} max={82} />
          <Slider label="Max age" value={req.max_age ?? 45} onChange={(v) => set('max_age', v === 45 ? null : v)} min={19} max={45} />
          <Slider label="Min BPM" value={req.min_bpm ?? -15} onChange={(v) => set('min_bpm', v === -15 ? null : v)} min={-15} max={12} />
          <label className="siq-strat-field siq-strat-toggle">
            <input type="checkbox" checked={!!req.require_undervalued} onChange={(e) => set('require_undervalued', e.target.checked)} />
            <span>Bargains only (model value above pay)</span>
          </label>
        </div>

        <div className="siq-strat-run">
          <span className="ds-note">Max age 45 / Min BPM −15 mean &ldquo;no limit.&rdquo; Each offseason&apos;s signings are kept {req.horizon} seasons, tested across 13 offseasons.</span>
          <Button variant="primary" onClick={run} disabled={running}
            icon={running ? <LoaderCircle size={16} className="siq-spin" /> : <Play size={16} />}>
            {running ? 'Testing…' : 'Run the test'}
          </Button>
        </div>
      </Panel>

      {error && (
        <AssumptionFlag tone="negative" title="The test could not run" icon={<TriangleAlert size={16} />}>{error}</AssumptionFlag>
      )}

      {result && verdict && (
        <>
          <div className={`siq-strat-verdict siq-strat-verdict--${verdict.tone}`}>
            <span className="siq-strat-verdict-icon">{verdict.tone === 'confidence' ? <TrendingUp size={18} /> : <TriangleAlert size={18} />}</span>
            <p>{verdict.text}</p>
          </div>

          <DecisionStrip
            ariaLabel="Backtest verdict"
            lead={{
              label: 'Edge over signing at random',
              value: money(alpha, cap),
              detail: `80% range ${money(result.alpha_lo_pct, cap)} to ${money(result.alpha_hi_pct, cap)} · ${result.edge_conclusive ? 'a clear edge' : 'not conclusive'}`,
              tone: alpha > 0.3 ? 'positive' : alpha < -0.3 ? 'negative' : 'neutral',
            }}
            items={[
              { label: 'Value per signing', value: money(result.surplus_per_slot_pct, cap), detail: 'On-court value beyond pay (today’s cap)', tone: result.surplus_per_slot_pct >= 0 ? 'positive' : 'negative' },
              { label: 'Signings that paid off', value: `${wins} of ${result.n_picks}`, detail: `${busts} busts · ${(result.hit_rate * 100).toFixed(0)}% out-produced their pay`, tone: 'neutral' },
              { label: 'Best signing', value: best ? money(best.realized_surplus_pct, cap) : '—', detail: best ? best.full_name : 'No signings', tone: 'confidence' },
            ]}
          />

          <div className="siq-strat-results-grid">
            <Panel variant="instrument" eyebrow="Value by offseason class" icon={<TrendingUp size={15} />}
              action={<Badge tone="accent" size="sm" dot>{result.decision_seasons.length} offseasons</Badge>}>
              <ClassChart result={result} />
              <p className="ds-note siq-strat-chart-note">Each bar is one offseason&apos;s signings, graded 3 seasons later. Green = the class produced more than it was paid; red = it cost more than it returned.</p>
            </Panel>

            <Panel variant="board" eyebrow="Vs other ways to sign" icon={<TrendingUp size={15} />}
              action={<Badge tone="neutral" variant="outline" size="sm">per signing</Badge>}>
              <BenchmarkBars result={result} />
              <p className="ds-note siq-strat-chart-note">Value per signing under each approach. The gap to &ldquo;Signing at random&rdquo; is what matters — the raw figures run low on purpose.</p>
            </Panel>
          </div>

          {result.current_targets.length > 0 && (
            <Panel variant="dossier" eyebrow={`What this rule would sign now · ${result.current_season ?? ''}`} icon={<Play size={15} />} flush
              action={<Badge tone="accent" size="sm" dot>{result.current_targets.length} targets</Badge>}>
              <div className="siq-strat-ledger-head">Today’s players your rule targets — no grade yet, this is the forward call</div>
              {result.current_targets.map((t) => (
                <TargetRow key={t.player_id} target={t} cap={cap} onPick={() => router.push(`/players/${t.player_id}`)} />
              ))}
              <p className="ds-note siq-strat-targets-note">Cross-check these against contract status in <a className="siq-strat-inline-link" href="/free-agency">Free agency</a> — the backtest says the philosophy travels; these are who it points to right now.</p>
            </Panel>
          )}

          <Panel variant="dossier" eyebrow="Best signings & biggest busts" icon={<FlaskConical size={15} />} flush
            action={<Badge tone="neutral" size="sm">{wins} wins · {busts} busts of {result.n_picks}</Badge>}>
            <div className="siq-strat-ledger-head siq-strat-ledger-head--win">Top signings this rule made</div>
            {winners.map((p) => (
              <PickRow key={`w-${p.player_id}-${p.decision_season}`} pick={p} cap={cap} onPick={() => router.push(`/players/${p.player_id}`)} />
            ))}
            {bustList.length > 0 && (
              <>
                <div className="siq-strat-ledger-head siq-strat-ledger-head--bust">Biggest busts this rule made</div>
                {bustList.map((p) => (
                  <PickRow key={`b-${p.player_id}-${p.decision_season}`} pick={p} cap={cap} onPick={() => router.push(`/players/${p.player_id}`)} />
                ))}
              </>
            )}
          </Panel>

          <AssumptionFlag tone="warning" title="How to read this" icon={<TriangleAlert size={16} />}>
            {result.caveat}
          </AssumptionFlag>
        </>
      )}
    </div>
  );
}
