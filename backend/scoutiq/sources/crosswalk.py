"""Resolve nba_api players to verified Basketball-Reference slugs.

Strategy: build the heuristic slug, fetch the page (cached), and verify the page's title name matches the
player. On mismatch, try suffixes 02/03 (collisions). Returns (slug, status) where status is one of
'verified' | 'mismatch' | 'not_found' — we keep honest provenance rather than trusting the heuristic.
"""
from __future__ import annotations

from scoutiq.sources.bbref import (
    bbref_slug,
    fetch_player_html,
    normalize_name,
    page_player_name,
)


def resolve_slug(full_name: str, max_suffix: int = 3) -> tuple[str | None, str]:
    target = normalize_name(full_name)
    last_seen: str | None = None
    for suffix in range(1, max_suffix + 1):
        slug = bbref_slug(full_name, suffix=suffix)
        if not slug:
            return None, "not_found"
        html = fetch_player_html(slug)
        if html is None:
            # No page at this suffix -> no higher suffix will exist either.
            return (last_seen or None), ("not_found" if last_seen is None else "mismatch")
        last_seen = slug
        # The <title> is "<Name> Stats, Height, Weight, ...", so the name is a prefix of it.
        page_name = normalize_name(page_player_name(html) or "")
        if page_name.startswith(target):
            return slug, "verified"
    # Pages existed but none matched the name.
    return last_seen, "mismatch"
