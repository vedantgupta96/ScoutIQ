"""Shared Claude extraction: scouting prose -> structured, schema-valid trait ratings.

Single code path used by BOTH the offline eval harness (eval_scout_ratings.py) and the production
backfill (etl/extract_scout_ratings.py), so the prompt and parsing never drift between them.
Uses the Anthropic Messages API directly via `requests` (no SDK dependency).
"""
from __future__ import annotations

import json
from typing import Any

import requests

from scoutiq.llm.schemas import ScoutRatingExtraction

ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
SYSTEM_PROMPT = (
    "You extract structured NBA scouting ratings. Return only valid JSON matching this shape: "
    '{"note_id":"...","player_name":"...","source_text":"...","ratings":[{"trait":"leadership",'
    '"score":1,"confidence":"low","evidence_span":"..."}]}. '
    "Allowed traits: leadership, coachability, work_ethic, athleticism, discipline, basketball_iq. "
    "Scores are integers 1-5. Evidence spans must be copied verbatim from the note."
)


def extract_json_object(text: str) -> dict[str, Any]:
    """Best-effort unwrap for responses that include surrounding prose."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("live response did not contain a JSON object")
    return json.loads(text[start:end + 1])


def call_anthropic_raw(
    note_id: str,
    player_name: str,
    source_text: str,
    *,
    api_key: str,
    model: str,
) -> dict[str, Any]:
    """Call Claude and return the raw extracted JSON object (unvalidated)."""
    payload = {
        "model": model,
        "max_tokens": 1200,
        "temperature": 0,
        "system": SYSTEM_PROMPT,
        "messages": [
            {
                "role": "user",
                "content": (
                    f"note_id: {note_id}\n"
                    f"player_name: {player_name}\n"
                    f"source_text: {source_text}\n"
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
    return extract_json_object("\n".join(text_parts))


def extract_ratings(
    note_id: str,
    player_name: str,
    source_text: str,
    *,
    api_key: str,
    model: str,
) -> ScoutRatingExtraction:
    """Call Claude and return a schema-VALIDATED extraction (raises on invalid output)."""
    raw = call_anthropic_raw(note_id, player_name, source_text, api_key=api_key, model=model)
    # The model may omit/echo these context fields — pin them to our known values before validating.
    raw["note_id"] = note_id
    raw["player_name"] = player_name
    raw["source_text"] = source_text
    return ScoutRatingExtraction.model_validate(raw)
