"""CLI for evaluating scout-text to structured-rating extraction."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from scoutiq.llm.extract import call_anthropic_raw
from scoutiq.llm.schemas import ScoutRatingExtraction
from scoutiq.llm.scoring import score_extractions

DEFAULT_OUTPUT = Path(__file__).resolve().parent / "artifacts" / "scout_ratings_eval.json"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                rows.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSONL row: {exc}") from exc
    return rows


def load_gold(path: Path) -> list[ScoutRatingExtraction]:
    gold: list[ScoutRatingExtraction] = []
    for row in load_jsonl(path):
        try:
            gold.append(ScoutRatingExtraction.model_validate(row))
        except ValidationError as exc:
            raise ValueError(f"{path}: invalid gold row for note_id={row.get('note_id')!r}: {exc}") from exc
    return gold


def run_live_predictions(gold: list[ScoutRatingExtraction]) -> list[dict[str, Any]]:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    model = os.environ.get("SCOUTIQ_LLM_MODEL")
    if not api_key or not model:
        raise RuntimeError(
            "Live eval requires ANTHROPIC_API_KEY and SCOUTIQ_LLM_MODEL. "
            "Use --predictions for offline fixture mode."
        )
    return [
        call_anthropic_raw(row.note_id, row.player_name, row.source_text, api_key=api_key, model=model)
        for row in gold
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate ScoutIQ scout-rating extraction.")
    parser.add_argument("--gold", required=True, type=Path, help="Gold JSONL file.")
    parser.add_argument("--predictions", type=Path, help="Prediction JSONL file for offline eval.")
    parser.add_argument("--live", action="store_true", help="Run live Claude extraction instead of fixture predictions.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Report JSON path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.live and args.predictions:
        parser.error("--live and --predictions are mutually exclusive")
    if not args.live and not args.predictions:
        parser.error("provide --predictions or --live")

    try:
        gold = load_gold(args.gold)
        prediction_rows = run_live_predictions(gold) if args.live else load_jsonl(args.predictions)
        report = score_extractions(gold, prediction_rows).to_dict()
    except Exception as exc:
        print(f"scout-ratings eval failed: {exc}")
        return 2

    # Provenance travels with the artifact so consumers (the model-page API)
    # can tell a live-model eval from a fixture replay without guessing.
    report["meta"] = {
        "mode": "live" if args.live else "fixture",
        "model": os.environ.get("SCOUTIQ_LLM_MODEL") if args.live else None,
        "gold": args.gold.name,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

