"""CLI for evaluating scout-text to structured-rating extraction."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import requests
from pydantic import ValidationError

from scoutiq.llm.schemas import ScoutRatingExtraction
from scoutiq.llm.scoring import score_extractions

DEFAULT_OUTPUT = Path(__file__).resolve().parent / "artifacts" / "scout_ratings_eval.json"
ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
SYSTEM_PROMPT = (
    "You extract structured NBA scouting ratings. Return only valid JSON matching this shape: "
    '{"note_id":"...","player_name":"...","source_text":"...","ratings":[{"trait":"leadership",'
    '"score":1,"confidence":"low","evidence_span":"..."}]}. '
    "Allowed traits: leadership, coachability, work_ethic, athleticism, discipline, basketball_iq. "
    "Scores are integers 1-5. Evidence spans must be copied verbatim from the note."
)


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


def _extract_json_object(text: str) -> dict[str, Any]:
    """Best-effort unwrap for live responses that include surrounding prose."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("live response did not contain a JSON object")
    return json.loads(text[start:end + 1])


def _live_extract_one(gold_row: ScoutRatingExtraction, api_key: str, model: str) -> dict[str, Any]:
    payload = {
        "model": model,
        "max_tokens": 1200,
        "temperature": 0,
        "system": SYSTEM_PROMPT,
        "messages": [
            {
                "role": "user",
                "content": (
                    f"note_id: {gold_row.note_id}\n"
                    f"player_name: {gold_row.player_name}\n"
                    f"source_text: {gold_row.source_text}\n"
                ),
            }
        ],
    }
    response = requests.post(
        ANTHROPIC_MESSAGES_URL,
        headers={
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
        json=payload,
        timeout=45,
    )
    response.raise_for_status()
    body = response.json()
    text_parts = [
        part.get("text", "")
        for part in body.get("content", [])
        if part.get("type") == "text"
    ]
    return _extract_json_object("\n".join(text_parts))


def run_live_predictions(gold: list[ScoutRatingExtraction]) -> list[dict[str, Any]]:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    model = os.environ.get("SCOUTIQ_LLM_MODEL")
    if not api_key or not model:
        raise RuntimeError(
            "Live eval requires ANTHROPIC_API_KEY and SCOUTIQ_LLM_MODEL. "
            "Use --predictions for offline fixture mode."
        )
    return [_live_extract_one(row, api_key, model) for row in gold]


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

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

