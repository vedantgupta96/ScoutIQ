'use client';

import { useEffect, useMemo, useState, type CSSProperties } from 'react';
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
} from '@/lib/api';
import { Panel } from '@/components/ui/Panel';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Select } from '@/components/ui/Select';
import { Avatar } from '@/components/ui/Avatar';
import { DecisionStrip } from '@/components/ui/DecisionStrip';
import { AssumptionFlag } from '@/components/ui/AssumptionFlag';

const SIGNAL_LABEL: Record<StrategySignal, string> = {
  gap: 'Value gap (undervaluation)',
  value: 'Model value',
  ws: 'Win Shares',
  bpm: 'Box Plus/Minus',
  vorp: 'VORP',
};

const BENCH_LABEL: Record<string, string> = {
  random: 'Random rotation player',
  chase_production: 'Chase production (top WS)',
  chase_salary: 'Chase salary (highest paid)',
};

const DEFAULT: StrategyRequest = {
  signal: 'gap', require_undervalued: true, portfolio_size: 10, horizon: 3,
  min_mpg: 20, min_gp: 40,
};

function pct(v: number, dp = 1): string {
  return `${v > 0 ? '+' : ''}${v.toFixed(dp)}%`;
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

// Cumulative realized-surplus equity curve over decision cohorts.
function EquityCurve({ result }: { result: BacktestResult }) {
  const pts = result.equity_curve;
  const W = 640, H = 220, padL = 44, padR = 12, padT = 14, padB = 26;
  const values = pts.map((p) => p.cumulative_surplus_pct);
  const min = Math.min(0, ...values), max = Math.max(0, ...values);
  const span = max - min || 1;
  const x = (i: number) => padL + (pts.length <= 1 ? 0 : (i / (pts.length - 1)) * (W - padL - padR));
  const y = (v: number) => padT + (1 - (v - min) / span) * (H - padT - padB);
  const line = pts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${x(i).toFixed(1)} ${y(p.cumulative_surplus_pct).toFixed(1)}`).join(' ');
  const zeroY = y(0);

  return (
    <svg className="siq-strat-equity-svg" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label="Cumulative realized surplus by decision season">
      <line x1={padL} y1={zeroY} x2={W - padR} y2={zeroY} stroke="var(--border-strong)" strokeDasharray="3 3" />
      <text x={padL - 6} y={zeroY + 3} textAnchor="end" fontSize="9" fill="var(--text-muted)" fontFamily="var(--font-mono)">0</text>
      <text x={padL - 6} y={y(max) + 3} textAnchor="end" fontSize="9" fill="var(--text-muted)" fontFamily="var(--font-mono)">{max.toFixed(0)}</text>
      <text x={padL - 6} y={y(min) + 3} textAnchor="end" fontSize="9" fill="var(--text-muted)" fontFamily="var(--font-mono)">{min.toFixed(0)}</text>
      <path d={`${line} L ${x(pts.length - 1)} ${zeroY} L ${x(0)} ${zeroY} Z`} fill="var(--accent)" opacity="0.08" />
      <path d={line} fill="none" stroke="var(--accent)" strokeWidth="2" />
      {pts.map((p, i) => (
        <g key={p.season}>
          <circle cx={x(i)} cy={y(p.cumulative_surplus_pct)} r="2.5" fill="var(--accent)" />
          {i % 2 === 0 && <text x={x(i)} y={H - 8} textAnchor="middle" fontSize="8" fill="var(--text-muted)" fontFamily="var(--font-mono)">{p.season.slice(2)}</text>}
        </g>
      ))}
    </svg>
  );
}

function BenchmarkBars({ result }: { result: BacktestResult }) {
  const rows = [
    { key: 'strategy', label: 'This strategy', value: result.surplus_per_slot_pct, accent: true },
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
            <strong className={`ds-tnum siq-strat-bar-val ${pos ? 'is-positive' : 'is-negative'}`}>{pct(r.value)}</strong>
          </div>
        );
      })}
    </div>
  );
}

function PickRow({ pick, onPick }: { pick: BacktestPick; onPick: () => void }) {
  return (
    <button className="siq-row siq-row--12 siq-strat-pick-row" onClick={onPick}>
      <Avatar name={pick.full_name} playerId={pick.player_id} size="sm" />
      <span className="siq-min0 siq-strat-pick-id">
        <strong>{pick.full_name}</strong>
        <small className="ds-note">{pick.decision_season} · gap {pick.signal_value >= 0 ? '+' : ''}{pick.signal_value.toFixed(1)} · held {pick.seasons_realized}y</small>
      </span>
      <Badge tone={pick.hit ? 'positive' : 'negative'} size="sm">{pick.hit ? 'hit' : 'miss'}</Badge>
      <strong className={`ds-tnum ds-right siq-strat-pick-surplus ${pick.realized_surplus_pct >= 0 ? 'is-positive' : 'is-negative'}`}>
        {pct(pick.realized_surplus_pct)}
      </strong>
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
      setError(e instanceof Error ? e.message : 'Backtest failed.');
    } finally {
      setRunning(false);
    }
  };

  const topPicks = useMemo(
    () => (result ? [...result.picks].sort((a, b) => b.realized_surplus_pct - a.realized_surplus_pct) : []),
    [result],
  );

  const alpha = result?.alpha_per_slot_pct ?? 0;

  return (
    <div className="siq-stack">
      <header className="siq-strat-heading">
        <span className="ds-eyebrow">Historical strategy backtest · 2012-13 → 2024-25 decisions</span>
        <h1>Backtesting</h1>
        <p>Define a roster-building rule, replay it across NBA history, and see whether it beat the market on realized value-for-dollar. Selection uses the model&apos;s value signal; results are graded on real production (Win Shares), so the model never grades itself.</p>
      </header>

      <Panel variant="card" padded eyebrow="Strategy" icon={<FlaskConical size={15} />}>
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
            <span className="ds-eyebrow">Rank players by</span>
            <Select value={req.signal} onChange={(e) => set('signal', e.target.value as StrategySignal)}>
              {(Object.keys(SIGNAL_LABEL) as StrategySignal[]).map((s) => (
                <option key={s} value={s}>{SIGNAL_LABEL[s]}</option>
              ))}
            </Select>
          </label>
          <Slider label="Portfolio size" value={req.portfolio_size ?? 10} onChange={(v) => set('portfolio_size', v)} min={1} max={30} />
          <Slider label="Hold (seasons)" value={req.horizon ?? 3} onChange={(v) => set('horizon', v)} min={1} max={5} />
          <Slider label="Min minutes/game" value={req.min_mpg ?? 20} onChange={(v) => set('min_mpg', v)} min={0} max={40} />
          <Slider label="Min games" value={req.min_gp ?? 40} onChange={(v) => set('min_gp', v)} min={0} max={82} />
          <Slider label="Max age" value={req.max_age ?? 45} onChange={(v) => set('max_age', v === 45 ? null : v)} min={19} max={45} />
          <Slider label="Min BPM" value={req.min_bpm ?? -15} onChange={(v) => set('min_bpm', v === -15 ? null : v)} min={-15} max={12} />
          <label className="siq-strat-field siq-strat-toggle">
            <input type="checkbox" checked={!!req.require_undervalued} onChange={(e) => set('require_undervalued', e.target.checked)} />
            <span>Undervalued only (model value &gt; pay)</span>
          </label>
        </div>

        <div className="siq-strat-run">
          <span className="ds-note">Max age 45 / Min BPM −15 mean &ldquo;no limit.&rdquo; Backtest holds each cohort {req.horizon} seasons across ~13 decision years.</span>
          <Button variant="primary" onClick={run} disabled={running}
            icon={running ? <LoaderCircle size={16} className="siq-spin" /> : <Play size={16} />}>
            {running ? 'Running…' : 'Run backtest'}
          </Button>
        </div>
      </Panel>

      {error && (
        <AssumptionFlag tone="negative" title="Backtest failed" icon={<TriangleAlert size={16} />}>{error}</AssumptionFlag>
      )}

      {result && (
        <>
          <DecisionStrip
            ariaLabel="Backtest verdict"
            lead={{
              label: 'Alpha vs random',
              value: pct(alpha),
              detail: alpha >= 0 ? 'Beat a random rotation-player portfolio, per roster slot' : 'Lost to a random rotation-player portfolio, per roster slot',
              tone: alpha > 0.5 ? 'positive' : alpha < -0.5 ? 'negative' : 'neutral',
            }}
            items={[
              { label: 'Realized surplus / slot', value: pct(result.surplus_per_slot_pct), detail: '% of cap of value beyond pay', tone: result.surplus_per_slot_pct >= 0 ? 'positive' : 'negative' },
              { label: 'Hit rate', value: `${(result.hit_rate * 100).toFixed(0)}%`, detail: `${result.n_picks} picks that beat their pay`, tone: 'neutral' },
              { label: 'Risk-adjusted', value: result.sharpe.toFixed(2), detail: 'Surplus ÷ volatility (Sharpe-like)', tone: 'confidence' },
            ]}
          />

          <div className="siq-strat-results-grid">
            <Panel variant="instrument" eyebrow="Cumulative realized surplus" icon={<TrendingUp size={15} />}
              action={<Badge tone="accent" size="sm" dot>{result.decision_seasons.length} cohorts</Badge>}>
              <EquityCurve result={result} />
              <p className="ds-note siq-strat-chart-note">Cumulative % of cap of value-for-dollar if the strategy were run every season. Down-only means it lost every cohort.</p>
            </Panel>

            <Panel variant="board" eyebrow="Vs benchmarks · per roster slot" icon={<TrendingUp size={15} />}
              action={<Badge tone="neutral" variant="outline" size="sm">% of cap</Badge>}>
              <BenchmarkBars result={result} />
              <p className="ds-note siq-strat-chart-note">Realized surplus per roster slot. The gap to &ldquo;Random&rdquo; is the honest signal — absolute levels are conservative.</p>
            </Panel>
          </div>

          <Panel variant="dossier" eyebrow="Pick ledger · best to worst" icon={<FlaskConical size={15} />} flush
            action={<Badge tone="warning" size="sm">{result.n_picks} picks</Badge>}>
            {topPicks.slice(0, 24).map((p) => (
              <PickRow key={`${p.player_id}-${p.decision_season}`} pick={p} onPick={() => router.push(`/players/${p.player_id}`)} />
            ))}
          </Panel>

          <AssumptionFlag tone="warning" title="How to read this" icon={<TriangleAlert size={16} />}>
            {result.caveat}
          </AssumptionFlag>
        </>
      )}
    </div>
  );
}
