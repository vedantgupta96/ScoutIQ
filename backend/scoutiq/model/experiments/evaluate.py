"""CLI: offline rolling-origin valuation backtests + promotion gates (issue #110).

Never writes production artifacts or published valuations. Default output goes to
scoutiq/model/experiments/output/.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from scoutiq.model.spec import SEED
from scoutiq.model.experiments.candidates import CANDIDATES
from scoutiq.model.experiments.report import write_reports
from scoutiq.model.experiments.runner import run_evaluation

DEFAULT_OUT_DIR = Path(__file__).resolve().parent / "output"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m scoutiq.model.experiments.evaluate",
        description="Offline rolling-origin valuation backtests and promotion gates (issue #110). "
                    "Reuses the canonical Model-trust reporting contract; never writes production "
                    "artifacts, production metrics, or published valuations. develop mode (default) "
                    "reserves the final holdout seasons so they are never used as a tuning set.")
    p.add_argument("--baseline", default="v1", choices=sorted(CANDIDATES),
                   help="baseline candidate (default: v1).")
    p.add_argument("--candidate", default=None, choices=sorted(CANDIDATES),
                   help="optional candidate to compare against the baseline.")
    p.add_argument("--min-train-seasons", type=int, default=3,
                   help="minimum training target seasons before the first validation fold.")
    p.add_argument("--seed", type=int, default=SEED, help="random seed for deterministic folds/fits.")
    p.add_argument("--mode", choices=["develop", "final"], default="develop",
                   help="develop (default) reserves the final holdout seasons; final evaluates on them.")
    p.add_argument("--out", default=str(DEFAULT_OUT_DIR), help="output directory for JSON + Markdown reports.")
    return p


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    # Deferred import so `--help` needs no database connection.
    from scoutiq.model.dataset import build_dataset

    df = build_dataset()
    result = run_evaluation(df, baseline=args.baseline, candidate=args.candidate,
                            min_train_seasons=args.min_train_seasons, seed=args.seed,
                            mode=args.mode)
    json_path, md_path = write_reports(result, Path(args.out))
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    print(f"decision: {result['decision']}")


if __name__ == "__main__":
    main()
