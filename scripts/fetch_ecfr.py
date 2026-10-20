"""Tier 1: fetch 8 CFR 214.2 from the eCFR API into data/raw/ecfr/.

The API's smallest unit is a section, so the whole of 214.2 is saved untouched;
extracting paragraph (f) is the chunker's job. The issue date defaults to the
one recorded in the manifest, so a rerun reproduces the same file; pass
--issue-date to fetch another version. Re-running overwrites the file and the
tier 1 manifest entry.

Usage: uv run python scripts/fetch_ecfr.py [--issue-date YYYY-MM-DD]
"""

import argparse
import json

import httpx

from corpus import MANIFEST, RAW_DIR, make_client, manifest_entry, update_manifest

API = "https://www.ecfr.gov/api/versioner/v1"
TITLE = 8
HIERARCHY = {"chapter": "I", "subchapter": "B", "part": "214", "section": "214.2"}
OUT = RAW_DIR / "ecfr" / "8-cfr-214.2.xml"
# Only paragraph (f) gets ingested, so the source id names (f), not the whole section.
SOURCE_ID = "ecfr-214.2f"


def recorded_issue_date() -> str | None:
    if not MANIFEST.exists():
        return None
    return json.loads(MANIFEST.read_text()).get("ecfr_issue_date")


def latest_issue_date(client: httpx.Client) -> str:
    titles = client.get(f"{API}/titles.json").raise_for_status().json()["titles"]
    return next(t["latest_issue_date"] for t in titles if t["number"] == TITLE)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch 8 CFR 214.2 from the eCFR versioner API.")
    parser.add_argument(
        "--issue-date",
        help="eCFR issue date, YYYY-MM-DD (default: the manifest's ecfr_issue_date; "
        "the latest issue date if there is no manifest yet)",
    )
    args = parser.parse_args()

    with make_client() as client:
        issue_date = args.issue_date or recorded_issue_date() or latest_issue_date(client)
        # eCFR answers 406 to uncompressed requests; httpx sends Accept-Encoding: gzip by default.
        resp = client.get(f"{API}/full/{issue_date}/title-{TITLE}.xml", params=HIERARCHY)
        resp.raise_for_status()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(resp.content)
    update_manifest(1, [manifest_entry(SOURCE_ID, 1, resp, OUT)], ecfr_issue_date=issue_date)
    print(f"issue date {issue_date}: {len(resp.content):,} bytes -> {OUT.relative_to(RAW_DIR)}")


if __name__ == "__main__":
    main()
