"""Resolve ESPN roster athletes to NBA player ids from corroborated, cached evidence.

An athlete resolves only when exactly one NBA id is proposed and at least two independent
sources agree, one of them a birth-date source (Basketball-Reference evidence or Wikidata).
A reviewed override CSV can pick among proposed ids; it can never introduce one. Anything
else stays unresolved and blocks `import_espn_snapshot`. The nba_api index and Wikidata
responses are cached under the snapshot so a run is reproducible offline.

Usage:
    python -m scoutiq.etl.resolve_espn_identity --snapshot-dir DIR --fetch-evidence
    python -m scoutiq.etl.resolve_espn_identity --snapshot-dir DIR --bbref-evidence evidence.json
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from sqlalchemy import select

from scoutiq.config import settings
from scoutiq.db import get_session
from scoutiq.etl import collect_espn_refresh
from scoutiq.models import Player
from scoutiq.sources import espn, identity_evidence

DEFAULT_OVERRIDES_PATH = settings.DATA_DIR / "espn_identity_overrides.csv"
OVERRIDE_COLUMNS = ["espn_id", "nba_id", "full_name", "reason", "reviewed_on"]
DOB_SOURCES = frozenset({"bbref_dob", "wikidata_dob"})


def load_overrides(path: Path = DEFAULT_OVERRIDES_PATH) -> list[dict]:
    with Path(path).open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != OVERRIDE_COLUMNS:
            raise ValueError(f"override CSV header must be {','.join(OVERRIDE_COLUMNS)}")
        rows = list(reader)
    overrides: list[dict] = []
    seen: set[int] = set()
    for row in rows:
        espn_id, nba_id = int(row["espn_id"]), int(row["nba_id"])
        reason = (row["reason"] or "").strip()
        if not reason:
            raise ValueError(f"override for ESPN id {espn_id} has a blank reason")
        if espn_id in seen:
            raise ValueError(f"duplicate override for ESPN id {espn_id}")
        seen.add(espn_id)
        overrides.append({"espn_id": espn_id, "nba_id": nba_id, "reason": reason})
    return overrides


def _candidates(athlete: dict, indexes: dict) -> dict[int, set[str]]:
    name, dob = espn.normalize_name(athlete["full_name"]), athlete.get("date_of_birth")
    found: dict[int, set[str]] = defaultdict(set)
    for row in indexes["bbref"].get(name, []):
        if dob and row["dob"] == dob:
            found[row["nba_id"]].add("bbref_dob")
    for player_id in indexes["stored"].get(name, []):
        found[player_id].add("stored_name")
    named = indexes["index"].get(name, [])
    active = [row for row in named if row["is_active"]]
    for row in (active if len(named) > 1 and len(active) == 1 else named):
        found[row["nba_id"]].add("nba_index_name")
    if dob:
        for row in indexes["wikidata_by_dob"].get(dob, []):
            if row["nba_id"] in found or espn.normalize_name(row["label"]) == name:
                found[row["nba_id"]].add("wikidata_dob")
    return found


def resolve_identities(
    roster: Iterable[dict],
    *,
    stored_players: Iterable[dict],
    bbref_evidence: Iterable[dict] = (),
    nba_index: Iterable[dict] = (),
    wikidata: Iterable[dict] = (),
    overrides: Iterable[dict] = (),
) -> dict:
    roster = list(roster)
    stored_names = {int(p["player_id"]): p["full_name"] for p in stored_players}
    nba_index = list(nba_index)
    index_names = {row["nba_id"]: row["full_name"] for row in nba_index}
    indexes: dict[str, Any] = {
        "bbref": defaultdict(list), "stored": defaultdict(list),
        "index": defaultdict(list), "wikidata_by_dob": defaultdict(list),
    }
    for row in bbref_evidence:
        if row.get("verified") and row.get("dob") and row.get("name"):
            indexes["bbref"][espn.normalize_name(str(row["name"]))].append(row)
    for player_id, full_name in stored_names.items():
        indexes["stored"][espn.normalize_name(full_name)].append(player_id)
    for row in nba_index:
        indexes["index"][espn.normalize_name(row["full_name"])].append(row)
    for row in wikidata:
        if row.get("dob"):
            indexes["wikidata_by_dob"][row["dob"]].append(row)
    override_by_espn = {int(o["espn_id"]): o for o in overrides}

    resolved: list[dict] = []
    unresolved: list[dict] = []

    def reject(athlete: dict, reason: str, found: dict[int, set[str]]) -> None:
        unresolved.append({
            "provider_id": athlete["provider_id"],
            "full_name": athlete["full_name"],
            "date_of_birth": athlete.get("date_of_birth"),
            "reason": reason,
            "candidates": {str(k): sorted(v) for k, v in sorted(found.items())},
        })

    for athlete in roster:
        found = _candidates(athlete, indexes)
        override = override_by_espn.get(athlete["provider_id"])
        override_reason = None
        if override is not None:
            if override["nba_id"] not in found:
                reject(athlete, "override nba_id is not proposed by any source", found)
                continue
            nba_id, basis, override_reason = override["nba_id"], "override", override["reason"]
        elif not found:
            reject(athlete, "no candidate", found)
            continue
        elif len(found) > 1:
            reject(athlete, "conflicting candidates", found)
            continue
        else:
            (nba_id, sources), = found.items()
            if not sources & DOB_SOURCES:
                reject(athlete, "no birth-date corroboration", found)
                continue
            if len(sources) < 2:
                reject(athlete, "single source", found)
                continue
            basis = "+".join(sorted(sources))
        stored = nba_id in stored_names
        resolved.append({
            "provider_id": athlete["provider_id"],
            "full_name": athlete["full_name"],
            "date_of_birth": athlete.get("date_of_birth"),
            "nba_id": nba_id,
            "basis": basis,
            "sources": sorted(found[nba_id]),
            "is_new_player": not stored,
            "player_full_name": stored_names.get(nba_id) or index_names.get(nba_id) or athlete["full_name"],
            "override_reason": override_reason,
        })

    claims: dict[int, list[dict]] = defaultdict(list)
    for row in resolved:
        claims[row["nba_id"]].append(row)
    clashing = {nba_id for nba_id, rows in claims.items() if len(rows) > 1}
    if clashing:
        kept = []
        for row in resolved:
            if row["nba_id"] in clashing:
                athlete = next(a for a in roster if a["provider_id"] == row["provider_id"])
                reject(athlete, "nba id claimed by more than one athlete", {row["nba_id"]: set(row["sources"])})
            else:
                kept.append(row)
        resolved = kept
        order = {a["provider_id"]: i for i, a in enumerate(roster)}
        unresolved.sort(key=lambda r: order[r["provider_id"]])

    by_basis: dict[str, int] = defaultdict(int)
    for row in resolved:
        by_basis[row["basis"]] += 1
    return {
        "resolved": resolved,
        "unresolved": unresolved,
        "counts": {
            "athletes": len(roster),
            "resolved": len(resolved),
            "unresolved": len(unresolved),
            "new_players": sum(1 for r in resolved if r["is_new_player"]),
            "by_basis": dict(sorted(by_basis.items())),
        },
    }


def load_stored_players() -> list[dict]:
    with get_session() as session:
        rows = session.execute(select(Player.player_id, Player.full_name)).all()
    return [{"player_id": player_id, "full_name": full_name} for player_id, full_name in rows]


def _evidence_cache(snapshot_dir: Path, *, fetch: bool) -> tuple[dict, dict]:
    directory = snapshot_dir / "identity_evidence"
    index_path, wikidata_path = directory / "nba_index.json", directory / "wikidata.json"
    if fetch and not (index_path.exists() and wikidata_path.exists()):
        session = requests.Session()
        session.headers.update({"User-Agent": collect_espn_refresh.USER_AGENT})
        if not index_path.exists():
            text, meta = identity_evidence.fetch_nba_index(session)
            collect_espn_refresh._write_json(index_path, {**meta, "text": text})
        if not wikidata_path.exists():
            payload, meta = identity_evidence.fetch_wikidata(session)
            collect_espn_refresh._write_json(wikidata_path, {**meta, "payload": payload})
    missing = [str(p) for p in (index_path, wikidata_path) if not p.exists()]
    if missing:
        raise FileNotFoundError(f"identity evidence cache is missing {missing}; rerun with --fetch-evidence")
    return collect_espn_refresh._read_json(index_path), collect_espn_refresh._read_json(wikidata_path)


def run(
    snapshot_dir: Path,
    *,
    bbref_evidence_path: Path | None = None,
    overrides_path: Path = DEFAULT_OVERRIDES_PATH,
    fetch_evidence: bool = False,
    output: Path | None = None,
) -> dict:
    snapshot_dir = Path(snapshot_dir)
    manifest = collect_espn_refresh._read_json(snapshot_dir / "manifest.json")
    roster = collect_espn_refresh._read_json(snapshot_dir / "normalized_roster.json")
    index_envelope, wikidata_envelope = _evidence_cache(snapshot_dir, fetch=fetch_evidence)
    bbref = collect_espn_refresh._read_json(Path(bbref_evidence_path)) if bbref_evidence_path else []
    result = resolve_identities(
        roster,
        stored_players=load_stored_players(),
        bbref_evidence=bbref,
        nba_index=identity_evidence.parse_nba_index(index_envelope["text"]),
        wikidata=identity_evidence.parse_wikidata(wikidata_envelope["payload"]),
        overrides=load_overrides(overrides_path),
    )
    result.update({
        "season": manifest["season"],
        "snapshot_generated_at_utc": manifest["generated_at_utc"],
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "evidence": {
            "nba_index": {k: index_envelope[k] for k in ("source_url", "fetched_at_utc")},
            "wikidata": {k: wikidata_envelope[k] for k in ("source_url", "fetched_at_utc")},
            "bbref_evidence": str(bbref_evidence_path) if bbref_evidence_path else None,
            "overrides": str(overrides_path),
        },
    })
    collect_espn_refresh._write_json(output or snapshot_dir / "identity_map.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resolve ESPN athletes to NBA player ids.")
    parser.add_argument("--snapshot-dir", required=True, type=Path)
    parser.add_argument("--bbref-evidence", type=Path, default=None, help="JSON list of verified identity rows")
    parser.add_argument("--overrides", type=Path, default=DEFAULT_OVERRIDES_PATH)
    parser.add_argument("--fetch-evidence", action="store_true", help="fetch missing evidence cache files")
    parser.add_argument("--output", type=Path, default=None, help="default: <snapshot-dir>/identity_map.json")
    args = parser.parse_args(argv)
    try:
        result = run(
            args.snapshot_dir,
            bbref_evidence_path=args.bbref_evidence,
            overrides_path=args.overrides,
            fetch_evidence=args.fetch_evidence,
            output=args.output,
        )
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result["counts"], indent=2, sort_keys=True))
    return 1 if result["unresolved"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
