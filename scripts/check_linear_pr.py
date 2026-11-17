"""Validate ScoutIQ PR-to-Linear closure metadata from a GitHub event payload."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SCO = r"SCO-\d+"
PRIMARY = re.compile(rf"\b({SCO})\b")
CLOSING = re.compile(rf"(?im)^\s*Fixes\s+({SCO})\s*$")
PART = re.compile(rf"(?im)^\s*Part of\s+({SCO})\s*$")
MAGIC = re.compile(
    rf"(?is)\b(?:close|closes|closed|closing|fix|fixes|fixed|fixing|resolve|resolves|resolved|resolving|"
    rf"complete|completes|completed|completing|implement|implements|implemented|implementing|linear\s+issue)\b"
    rf"[^\n]{{0,160}}?(?:{SCO}|https?://[^\s)]*/(?:issue/)?{SCO})"
)


def validate(pr: dict) -> list[str]:
    title, body = pr.get("title", ""), pr.get("body") or ""
    primary = PRIMARY.findall(title)
    errors = []
    if len(primary) != 1:
        return ["title must contain exactly one primary SCO-N"]
    card = primary[0]
    closing = CLOSING.findall(body)
    parts = PART.findall(body)
    if len(closing) + len(parts) != 1:
        errors.append("body must contain exactly one standalone Fixes SCO-N or Part of SCO-N line")
    elif (closing or parts)[0] != card:
        errors.append("closing or partial card must match the title card")
    allowed = f"Fixes {card}"
    if MAGIC.search(title):
        errors.append("closing magic is allowed only as the exact standalone Fixes SCO-N body line on main")
    for line in body.splitlines():
        if MAGIC.search(line) and (line.strip() != allowed or pr.get("base", {}).get("ref") != "main"):
            errors.append("closing magic is allowed only as the exact standalone Fixes SCO-N body line on main")
            break
    return errors


def main(path: str) -> int:
    payload = json.loads(Path(path).read_text())
    errors = validate(payload["pull_request"])
    for error in errors:
        print(f"error: {error}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
