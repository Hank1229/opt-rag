"""Shared helpers for the corpus fetch scripts: HTTP client, raw file paths, manifest.

The manifest (data/raw/manifest.json) is a single JSON file shaped like:
    {"ecfr_issue_date": "...", "entries": [{"tier": 1, "url": "...", ...}, ...]}
Each fetch script owns one tier and only ever rewrites that tier's entries.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"
MANIFEST = RAW_DIR / "manifest.json"


def make_client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": "opt-rag-corpus-fetcher/0.1"},
        follow_redirects=True,
        timeout=60,
    )


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def manifest_entry(tier: int, resp: httpx.Response, path: Path, **extra) -> dict:
    """One manifest record for a raw file written from `resp`."""
    # resp.url is where we ended up after redirects; history[0] is what we asked for.
    requested_url = resp.history[0].url if resp.history else resp.url
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "tier": tier,
        "url": str(requested_url),
        "final_url": str(resp.url),
        "path": path.relative_to(RAW_DIR).as_posix(),
        "fetched_at": fetched_at,
        "bytes": len(resp.content),
        "raw_sha256": sha256(resp.content),
        **extra,
    }


def update_manifest(tier: int, entries: list[dict], **top_level) -> None:
    """Replace every entry of `tier`, keeping the other tier's entries untouched."""
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}

    # pop (not get) so "entries" is re-added last and stays below the top-level fields.
    old_entries = manifest.pop("entries", [])
    other_tier_entries = [e for e in old_entries if e["tier"] != tier]

    manifest.update(top_level)
    manifest["entries"] = sorted(
        other_tier_entries + entries,
        key=lambda e: (e["tier"], e["path"]),
    )
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
